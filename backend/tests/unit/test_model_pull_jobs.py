"""Model-pull job API (POST/GET/DELETE /api/v1/ai/pull-model).

The subprocess is stubbed at ``app.routers.ai._spawn_pull`` so the tests cover
the registry lifecycle — start, progress parsing, completion, failure, cancel,
unknown id — without an Ollama install or network.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import status

from app.routers import ai as ai_router


class _FakeStdout:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    async def read(self, size: int = -1) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""


class _FakeProc:
    """Stand-in for asyncio.subprocess.Process with canned output."""

    def __init__(
        self,
        chunks: list[bytes] | None = None,
        returncode: int = 0,
        stderr: bytes = b"",
    ) -> None:
        self.stdout = _FakeStdout(chunks or [])
        self.stderr = _FakeStdout([stderr])
        self.returncode: int | None = None
        self._exit_code = returncode
        self.terminated = False

    async def wait(self) -> int:
        self.returncode = self._exit_code
        return self._exit_code

    def terminate(self) -> None:
        self.terminated = True
        self._exit_code = -15
        self.returncode = -15
        self.stdout._chunks = []  # closing the pipe ends the read loop


def _install(proc: _FakeProc, monkeypatch: Any) -> None:
    async def fake_spawn(model: str) -> _FakeProc:
        return proc

    monkeypatch.setattr(ai_router, "_spawn_pull", fake_spawn)


async def _settled_status(client: httpx.AsyncClient, job_id: str) -> httpx.Response:
    """Poll until the job leaves 'pulling' (the worker runs on the same loop)."""
    for _ in range(200):
        r = await client.get(f"/api/v1/ai/pull-model/{job_id}")
        assert r.status_code == 200
        if r.json()["status"] != "pulling":
            return r
        await asyncio.sleep(0)
    return r


class TestStart:
    async def test_start_returns_job_id_and_pulls(
        self, client: httpx.AsyncClient, monkeypatch: Any
    ) -> None:
        proc = _FakeProc(chunks=[b"pulling manifest\n", b"50% downloading\n"], returncode=0)
        _install(proc, monkeypatch)
        r = await client.post("/api/v1/ai/pull-model", params={"model": "nomic-embed-text"})
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "pulling" and body["model"] == "nomic-embed-text"
        assert body["job_id"]

        data = (await _settled_status(client, body["job_id"])).json()
        assert data["status"] == "complete"
        # The last streamed percent was 50, but a pull that exited 0 is done —
        # the terminal state must read 100, not the last mid-flight update.
        assert data["progress_percent"] == 100.0
        assert "downloading" in (data["message"] or "")
        assert data["finished_at"] is not None

    async def test_invalid_model_name_is_rejected(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/api/v1/ai/pull-model", params={"model": "x; rm -rf /"})
        assert r.status_code == 400


class TestFailure:
    async def test_nonzero_exit_surfaces_stderr(
        self, client: httpx.AsyncClient, monkeypatch: Any
    ) -> None:
        _install(_FakeProc(returncode=1, stderr=b"pull model manifest: file not found"), monkeypatch)
        r = await client.post("/api/v1/ai/pull-model", params={"model": "nope:latest"})
        job_id = r.json()["job_id"]
        data = (await _settled_status(client, job_id)).json()
        assert data["status"] == "failed"
        assert "manifest" in data["error"]
        assert data["progress_percent"] != 100.0

    async def test_spawn_error_marks_job_failed(
        self, client: httpx.AsyncClient, monkeypatch: Any
    ) -> None:
        async def boom(model: str) -> _FakeProc:
            raise FileNotFoundError("ollama not installed")

        monkeypatch.setattr(ai_router, "_spawn_pull", boom)
        r = await client.post("/api/v1/ai/pull-model", params={"model": "llama3"})
        data = (await _settled_status(client, r.json()["job_id"])).json()
        assert data["status"] == "failed"
        assert "ollama not installed" in data["error"]


class TestCancel:
    async def test_cancel_terminates_and_marks_failed(
        self, client: httpx.AsyncClient, monkeypatch: Any
    ) -> None:
        # A pull that never finishes on its own.
        started = asyncio.Event()

        class _SlowProc(_FakeProc):
            async def wait(self) -> int:
                await started.wait()
                return 0

        proc = _SlowProc(chunks=[b"10%\n"])
        _install(proc, monkeypatch)
        r = await client.post("/api/v1/ai/pull-model", params={"model": "big-model"})
        job_id = r.json()["job_id"]

        # Let the worker start and read its first chunk.
        for _ in range(20):
            await asyncio.sleep(0)
        c = await client.delete(f"/api/v1/ai/pull-model/{job_id}")
        started.set()
        assert c.status_code == 200
        body = c.json()
        assert body["status"] == "failed"
        assert body["error"] == "Pull cancelled"
        assert proc.terminated is True

        # Terminal state survives further polling.
        assert (await client.get(f"/api/v1/ai/pull-model/{job_id}")).json()["status"] == "failed"

    async def test_cancel_finished_job_is_a_noop(
        self, client: httpx.AsyncClient, monkeypatch: Any
    ) -> None:
        proc = _FakeProc(chunks=[b"100%\n"], returncode=0)
        _install(proc, monkeypatch)
        job_id = (
            await client.post("/api/v1/ai/pull-model", params={"model": "m"})
        ).json()["job_id"]
        await _settled_status(client, job_id)
        c = await client.delete(f"/api/v1/ai/pull-model/{job_id}")
        assert c.json()["status"] == "complete"


class TestUnknownJob:
    async def test_get_unknown_job_404(self, client: httpx.AsyncClient) -> None:
        assert (
            await client.get("/api/v1/ai/pull-model/not-a-job")
        ).status_code == status.HTTP_404_NOT_FOUND

    async def test_cancel_unknown_job_404(self, client: httpx.AsyncClient) -> None:
        assert (
            await client.delete("/api/v1/ai/pull-model/not-a-job")
        ).status_code == status.HTTP_404_NOT_FOUND


class TestRegistryHygiene:
    async def test_registry_is_pruned_and_capped(self, monkeypatch: Any) -> None:
        now = ai_router.datetime.now(tz=ai_router.timezone.utc)
        old = now - ai_router.timedelta(seconds=ai_router._PULL_JOB_TTL_SECONDS + 10)
        for i in range(ai_router._PULL_JOBS_MAX + 5):
            ai_router._PULL_JOBS[f"old{i}"] = {
                "model": "m",
                "status": "complete",
                "started_at": old,
                "finished_at": old,
            }
        ai_router._prune_pull_jobs(now)
        assert len(ai_router._PULL_JOBS) <= ai_router._PULL_JOBS_MAX
        ai_router._PULL_JOBS.clear()
