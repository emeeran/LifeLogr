"""Provider streaming + parsing behaviour.

Covers the pieces of the cloud layer that move whole backup archives around:
  * every provider can stream a download straight to disk (a multi-gigabyte
    archive must never be buffered in RAM);
  * WebDAV listings are parsed as XML, not scraped out of response text — the
    old substring scan returned raw XML fragments nobody could use;
  * a large first-time Google Drive upload streams via a resumable session
    instead of building the whole multipart body in memory.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest
import respx

from app.services.cloud_sync_service import (
    BoxProvider,
    DropboxProvider,
    GoogleDriveProvider,
    LocalFileProvider,
    NextcloudProvider,
    OneDriveProvider,
    _dav_root_path,
    _multistatus_paths,
    parse_sync_path,
)


def _propfind(paths: list[str], host_root: str = "") -> bytes:
    """A WebDAV 207 multistatus body listing *paths* under *host_root*."""
    root = ET.Element("{DAV:}multistatus")
    for path in paths:
        response = ET.SubElement(root, "{DAV:}response")
        href = ET.SubElement(response, "{DAV:}href")
        href.text = f"{host_root}{path}"
    return ET.tostring(root, xml_declaration=True, encoding="utf-8")


class TestMultistatusParsing:
    def test_returns_clean_root_relative_names(self) -> None:
        body = _propfind(
            ["lifelogr-backup-1.tar.gz", "lifelogr-backup-2.tar.gz", "notes.txt"],
            host_root="/remote.php/dav/files/alex/",
        )
        parsed = _multistatus_paths(
            body, _dav_root_path("https://cloud.example.com", "alex"), "lifelogr-backup-"
        )
        assert parsed == ["lifelogr-backup-1.tar.gz", "lifelogr-backup-2.tar.gz"]

    def test_keeps_subpath_hrefs_intact_for_sync_ops(self) -> None:
        """Sync-op listings must survive as paths parse_sync_path understands."""
        body = _propfind(
            ["lifelogr/entry/7/update.json", "lifelogr-backup-2026.tar.gz"],
            host_root="/remote.php/dav/files/alex/",
        )
        parsed = _multistatus_paths(
            body, _dav_root_path("https://cloud.example.com", "alex"), "lifelogr/"
        )
        assert parsed == ["lifelogr/entry/7/update.json"]
        assert parse_sync_path(parsed[0]) == ("entry", 7, "update")

    def test_url_encoded_and_absolute_hrefs_are_decoded(self) -> None:
        body = _propfind(
            ["life%20logr-backup%20a.tar.gz"],
            host_root="/remote.php/dav/files/al%20ex/",
        ).decode()
        # Same body, but hrefs are absolute URLs (some servers do this).
        body = body.replace("<DAV:href>/", "<DAV:href>https://cloud.example.com/")
        parsed = _multistatus_paths(
            body.encode(), _dav_root_path("https://cloud.example.com", "al ex"), "life"
        )
        assert parsed == ["life logr-backup a.tar.gz"]

    def test_unparseable_body_yields_no_files(self) -> None:
        assert _multistatus_paths(b"<not-xml", "/x/", "p") == []

    def test_skips_the_root_collection_itself(self) -> None:
        body = _propfind(
            [""], host_root="/remote.php/dav/files/alex/"
        )  # the collection's own href
        assert (
            _multistatus_paths(
                body, _dav_root_path("https://cloud.example.com", "alex"), "lifelogr"
            )
            == []
        )


class TestNextcloudProvider:
    @respx.mock
    async def test_list_files_parses_the_multistatus_body(self) -> None:
        provider = NextcloudProvider(
            base_url="https://cloud.example.com", username="alex", password="pw"
        )
        respx.request("PROPFIND", "https://cloud.example.com/remote.php/dav/files/alex/").mock(
            return_value=httpx.Response(
                207,
                content=_propfind(
                    [
                        "lifelogr-backup-20260101-000000.tar.gz",
                        "lifelogr/entry/1/create.json",
                        "unrelated.txt",
                    ],
                    host_root="/remote.php/dav/files/alex/",
                ),
                headers={"Content-Type": "application/xml; charset=utf-8"},
            )
        )

        backups = await provider.list_files("lifelogr-backup-")

        assert backups == ["lifelogr-backup-20260101-000000.tar.gz"]
        # The returned names are directly usable for a download/delete.
        respx.get("https://cloud.example.com/remote.php/dav/files/alex/lifelogr-backup-20260101-000000.tar.gz").mock(
            return_value=httpx.Response(200, content=b"archive")
        )
        assert await provider.download(backups[0]) == b"archive"
        await provider.close()

    @respx.mock
    async def test_non_multistatus_response_lists_nothing(self) -> None:
        provider = NextcloudProvider(
            base_url="https://cloud.example.com", username="alex", password="pw"
        )
        respx.request("PROPFIND", "https://cloud.example.com/remote.php/dav/files/alex/").mock(
            return_value=httpx.Response(404, text="nope")
        )
        assert await provider.list_files("lifelogr-backup-") == []
        await provider.close()

    @respx.mock
    async def test_upload_file_streams_the_body(self, tmp_path: Path) -> None:
        """A local archive is streamed up — and AsyncClient accepts the body.

        A blocking file handle as ``content`` makes httpx's AsyncClient raise
        "Attempted to send an sync request with an AsyncClient instance", which
        used to fail every cloud backup upload.
        """
        provider = NextcloudProvider(
            base_url="https://cloud.example.com", username="alex", password="pw"
        )
        archive = tmp_path / "lifelogr-backup-1.tar.gz"
        archive.write_bytes(b"a" * (2 * 1024 * 1024 + 5))
        route = respx.put(
            "https://cloud.example.com/remote.php/dav/files/alex/lifelogr-backup-1.tar.gz"
        ).mock(return_value=httpx.Response(201))

        await provider.upload_file("lifelogr-backup-1.tar.gz", str(archive))

        assert route.called
        await provider.close()

    @respx.mock
    async def test_download_to_file_streams_to_disk(self, tmp_path: Path) -> None:
        provider = NextcloudProvider(
            base_url="https://cloud.example.com", username="alex", password="pw"
        )
        route = respx.get(
            "https://cloud.example.com/remote.php/dav/files/alex/lifelogr-backup-big.tar.gz"
        ).mock(
            return_value=httpx.Response(200, content=b"x" * (3 * 1024 * 1024 + 17))
        )
        dest = tmp_path / "out.tar.gz"

        await provider.download_to_file("lifelogr-backup-big.tar.gz", str(dest))

        assert dest.read_bytes() == b"x" * (3 * 1024 * 1024 + 17)
        assert route.called
        await provider.close()

    @respx.mock
    async def test_download_to_file_propagates_http_errors(self, tmp_path: Path) -> None:
        provider = NextcloudProvider(
            base_url="https://cloud.example.com", username="alex", password="pw"
        )
        respx.get("https://cloud.example.com/remote.php/dav/files/alex/missing.tar.gz").mock(
            return_value=httpx.Response(404)
        )

        with pytest.raises(httpx.HTTPStatusError):
            await provider.download_to_file("missing.tar.gz", str(tmp_path / "out"))
        await provider.close()


class TestLocalFileProvider:
    async def test_download_to_file_copies_bytes(self, tmp_path: Path) -> None:
        provider = LocalFileProvider(base_dir=str(tmp_path))
        (tmp_path / "lifelogr-backup-1.tar.gz").write_bytes(b"archive-bytes")
        dest = tmp_path / "copy.tar.gz"

        assert await provider.download_to_file("lifelogr-backup-1.tar.gz", str(dest)) == (
            "lifelogr-backup-1.tar.gz"
        )
        assert dest.read_bytes() == b"archive-bytes"

    async def test_download_to_file_rejects_traversal(self, tmp_path: Path) -> None:
        provider = LocalFileProvider(base_dir=str(tmp_path))
        with pytest.raises(ValueError, match="escapes"):
            await provider.download_to_file("../../etc/passwd", str(tmp_path / "out"))


def _creds() -> dict[str, str]:
    return {
        "client_id": "cid",
        "client_secret": "csec",
        "refresh_token": "rt",
        "access_token": "tok",
        "token_expiry": str(0),  # force a refresh on first use
    }


class TestGoogleDriveStreaming:
    @respx.mock
    async def test_large_first_upload_is_resumable_and_streamed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A big first-time upload goes via a resumable session, streamed."""
        import app.services.cloud_sync_service as mod

        monkeypatch.setattr(mod, "_RESUMABLE_UPLOAD_MIN_BYTES", 16)
        provider = GoogleDriveProvider(_creds())
        provider._folder_id = "folder-id"
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        )
        # No file with this name yet — the upload is a create.
        respx.get(url__startswith="https://www.googleapis.com/drive/v3/files?").mock(
            return_value=httpx.Response(200, json={"files": []})
        )
        archive = tmp_path / "lifelogr-backup-big.tar.gz"
        archive.write_bytes(b"z" * 4096)

        metadata = respx.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"
        ).mock(return_value=httpx.Response(200, headers={"Location": "https://upload/x?token=1"}))
        upload = respx.put("https://upload/x?token=1").mock(
            return_value=httpx.Response(200, json={"id": "new"})
        )

        await provider.upload_file("lifelogr-backup-big.tar.gz", str(archive))

        assert metadata.called
        assert upload.called
        sent = upload.calls[0].request.content
        assert isinstance(sent, bytes) and sent == b"z" * 4096
        await provider.close()

    @respx.mock
    async def test_small_first_upload_stays_multipart(self, tmp_path: Path) -> None:
        provider = GoogleDriveProvider(_creds())
        provider._folder_id = "folder-id"
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        )
        # No file with this name yet — the upload is a create.
        respx.get(url__startswith="https://www.googleapis.com/drive/v3/files?").mock(
            return_value=httpx.Response(200, json={"files": []})
        )
        archive = tmp_path / "lifelogr-backup-small.tar.gz"
        archive.write_bytes(b"small")

        multipart = respx.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
        ).mock(return_value=httpx.Response(200, json={"id": "new"}))
        respx.post(
            "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable"
        ).mock(return_value=httpx.Response(500))

        await provider.upload_file("lifelogr-backup-small.tar.gz", str(archive))
        assert multipart.called
        await provider.close()

    @respx.mock
    async def test_download_to_file_streams_the_archive(self, tmp_path: Path) -> None:
        provider = GoogleDriveProvider(_creds())
        provider._folder_id = "folder-id"
        respx.get(url__startswith="https://www.googleapis.com/drive/v3/files?").mock(
            return_value=httpx.Response(200, json={"files": [{"id": "file-1"}]})
        )
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=httpx.Response(
                200, json={"access_token": "fresh", "expires_in": 3600}
            )
        )
        respx.get("https://www.googleapis.com/drive/v3/files/file-1?alt=media").mock(
            return_value=httpx.Response(200, content=b"archive-bytes")
        )
        dest = tmp_path / "out.tar.gz"

        await provider.download_to_file("lifelogr-backup-1.tar.gz", str(dest))

        assert dest.read_bytes() == b"archive-bytes"
        await provider.close()


class TestOtherProvidersStreamToDisk:
    @respx.mock
    async def test_onedrive(self, tmp_path: Path) -> None:
        provider = OneDriveProvider(_creds())
        respx.post(OneDriveProvider.TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        )
        respx.get(f"{OneDriveProvider.GRAPH}:lifelogr-backup-1.tar.gz:/content").mock(
            return_value=httpx.Response(200, content=b"od-bytes")
        )
        dest = tmp_path / "out"

        await provider.download_to_file("lifelogr-backup-1.tar.gz", str(dest))
        assert dest.read_bytes() == b"od-bytes"
        await provider.close()

    @respx.mock
    async def test_dropbox(self, tmp_path: Path) -> None:
        provider = DropboxProvider(_creds())
        respx.post(DropboxProvider.TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        )
        respx.post(f"{DropboxProvider.CONTENT}/files/download").mock(
            return_value=httpx.Response(200, content=b"db-bytes")
        )
        dest = tmp_path / "out"

        await provider.download_to_file("lifelogr-backup-1.tar.gz", str(dest))
        assert dest.read_bytes() == b"db-bytes"
        await provider.close()

    @respx.mock
    async def test_box(self, tmp_path: Path) -> None:
        provider = BoxProvider(_creds())
        provider._folder_id = "folder-id"
        respx.post(BoxProvider.TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        )
        respx.get("https://api.box.com/2.0/folders/folder-id/items").mock(
            return_value=httpx.Response(
                200,
                json={"entries": [{"type": "file", "id": "file-9", "name": "backup.tar.gz"}]},
            )
        )
        respx.get("https://api.box.com/2.0/files/file-9/content").mock(
            return_value=httpx.Response(200, content=b"box-bytes")
        )
        dest = tmp_path / "out"

        await provider.download_to_file("backup.tar.gz", str(dest))
        assert dest.read_bytes() == b"box-bytes"
        await provider.close()
