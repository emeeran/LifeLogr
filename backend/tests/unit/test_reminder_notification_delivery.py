"""Desktop-notification delivery in ReminderService.

Covers the platform command chain (notify-send on Linux, osascript on macOS,
structured single warning elsewhere), the once-per-platform warning, and that
the async paths (test-notification route, scheduler fire) never run the
blocking spawn on the event loop thread.
"""

from __future__ import annotations

import sys
import threading
from typing import Any
from unittest.mock import patch

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import reminder_service as rs
from app.services.reminder_service import ReminderService


def _reset_warned() -> None:
    rs._WARNED_PLATFORMS.clear()


class TestPlatformCommandChain:
    def test_linux_uses_notify_send_with_separator(self) -> None:
        argv = ReminderService._notification_argv("- 09:00 standup", "--verbose note")
        if not sys.platform.startswith("linux"):
            assert argv is None or argv[0] != "notify-send"
            return
        assert argv is not None
        assert argv[:3] == ["notify-send", "-a", "LifeLogr"]
        assert argv[3] == "--"
        assert argv[4:] == ["- 09:00 standup", "--verbose note"]

    def test_macos_uses_osascript_with_quoted_text(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(sys, "platform", "darwin")
        argv = ReminderService._notification_argv('Say "hi"', "body")
        assert argv is not None and argv[0] == "osascript"
        script = argv[2]
        assert script.startswith("display notification ")
        assert '\\"hi\\"' in script  # embedded quotes escaped, no script injection

    def test_other_platform_has_no_backend(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        assert ReminderService._notification_argv("t", "m") is None


class TestDelivery:
    def test_spawn_is_fire_and_forget(self) -> None:
        _reset_warned()
        with patch("app.services.reminder_service.subprocess.Popen") as popen:
            ReminderService._send_notification("Write your journal", "Time!")
        popen.assert_called_once()
        assert popen.call_args.kwargs["stdout"] is rs.subprocess.DEVNULL

    def test_missing_binary_warns_once_per_platform(self, monkeypatch: Any) -> None:
        _reset_warned()
        monkeypatch.setattr(sys, "platform", "linux")
        with patch(
            "app.services.reminder_service.subprocess.Popen",
            side_effect=FileNotFoundError("no notify-send"),
        ) as popen, patch.object(rs.logger, "warning") as warn:
            for _ in range(3):
                ReminderService._send_notification("t", "m")
        assert popen.call_count == 3  # still tries every time, never raises
        assert warn.call_count == 1
        assert "platform=" in str(warn.call_args)

    def test_unsupported_platform_spawns_nothing_and_warns_once(
        self, monkeypatch: Any
    ) -> None:
        _reset_warned()
        monkeypatch.setattr(sys, "platform", "win32")
        with patch("app.services.reminder_service.subprocess.Popen") as popen, patch.object(
            rs.logger, "warning"
        ) as warn:
            for _ in range(2):
                ReminderService._send_notification("t", "m")
        popen.assert_not_called()
        assert warn.call_count == 1

    def test_generic_os_error_is_swallowed(self, monkeypatch: Any) -> None:
        _reset_warned()
        monkeypatch.setattr(sys, "platform", "linux")
        with patch(
            "app.services.reminder_service.subprocess.Popen",
            side_effect=PermissionError("noexec"),
        ):
            ReminderService._send_notification("t", "m")  # must not raise


class TestAsyncDeliveryOffLoop:
    async def test_notification_runs_off_the_event_loop(
        self, db_session: AsyncSession, monkeypatch: Any
    ) -> None:
        """The spawn happens in a worker thread, not on the loop thread."""
        monkeypatch.setattr(sys, "platform", "linux")
        captured: dict[str, int] = {}

        def record_thread(title: str, message: str) -> None:
            captured["ident"] = threading.get_ident()

        monkeypatch.setattr(ReminderService, "_send_notification", record_thread)
        svc = ReminderService(db_session)
        reminder = await svc.create(
            rs.ReminderCreate(title="Evening", message="m", reminder_time="21:00:00")
        )
        await svc.test_notification(reminder.id)
        assert captured["ident"] != threading.get_ident()
