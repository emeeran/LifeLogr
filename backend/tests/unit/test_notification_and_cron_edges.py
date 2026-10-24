"""Small edge cases: desktop notification argv, and cron forms the catch-up
math must refuse to guess at.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from app.core.cron_utils import last_scheduled_occurrence
from app.services.reminder_service import ReminderService


class TestNotificationArgv:
    def test_double_dash_precedes_the_text(self) -> None:
        """A title/message starting with '-' must not be read as an option.

        ``notify-send -a LifeLogr "- 09:00 standup" ...`` used to make
        notify-send treat the leading dash as a flag and swallow the text.
        """
        captured: dict[str, list[str]] = {}

        def fake_popen(argv: list[str], **kwargs: object) -> None:
            captured["argv"] = argv  # never actually spawn anything
            return None

        with patch(
            "app.services.reminder_service.subprocess.Popen", side_effect=fake_popen
        ):
            ReminderService._send_notification("- 09:00 standup", "--verbose note")

        argv = captured["argv"]
        assert argv[0] == "notify-send"
        assert "--" in argv
        # Everything after `--` is positional text, whatever it starts with.
        text = argv[argv.index("--") + 1 :]
        assert text == ["- 09:00 standup", "--verbose note"]

    def test_app_flag_comes_before_the_separator(self) -> None:
        captured: dict[str, list[str]] = {}

        def fake_popen(argv: list[str], **kwargs: object) -> None:
            captured["argv"] = argv  # never actually spawn anything
            return None

        with patch(
            "app.services.reminder_service.subprocess.Popen", side_effect=fake_popen
        ):
            ReminderService._send_notification("Write your journal", "Time!")

        assert captured["argv"][:3] == ["notify-send", "-a", "LifeLogr"]
        assert captured["argv"][3] == "--"

    def test_missing_binary_is_not_fatal(self) -> None:
        with patch(
            "app.services.reminder_service.subprocess.Popen",
            side_effect=FileNotFoundError("no notify-send"),
        ):
            ReminderService._send_notification("Write your journal", "Time!")


class TestCronUnsupportedForms:
    """Step/range cron fields must not be read as "matches every day".

    The backup catch-up uses this to decide whether a scheduled run was missed;
    treating ``*/2`` or ``1-5`` as always-matching made it fire on days the job
    never runs.
    """

    NOW = datetime(2026, 7, 7, 10, 0)  # a Tuesday

    def test_step_in_hour_returns_none(self) -> None:
        assert last_scheduled_occurrence("0 */6 * * *", self.NOW) is None

    def test_range_in_day_of_week_returns_none(self) -> None:
        assert last_scheduled_occurrence("0 2 * * 1-5", self.NOW) is None

    def test_step_in_day_of_month_returns_none(self) -> None:
        assert last_scheduled_occurrence("0 2 */2 * *", self.NOW) is None

    def test_step_in_month_returns_none(self) -> None:
        assert last_scheduled_occurrence("0 2 * */3 *", self.NOW) is None

    def test_named_and_numeric_lists_still_work(self) -> None:
        # Tuesday (numeric 1 and name "tue" both supported).
        assert last_scheduled_occurrence("0 2 * * 1", self.NOW) == datetime(2026, 7, 7, 2, 0)
        assert last_scheduled_occurrence("0 2 * * tue", self.NOW) == datetime(2026, 7, 7, 2, 0)
        assert last_scheduled_occurrence("0 2 * * mon,fri", self.NOW) == datetime(
            2026, 7, 6, 2, 0
        )

    def test_last_day_of_month_still_works(self) -> None:
        assert last_scheduled_occurrence("0 23 L * *", datetime(2026, 1, 31, 23, 30)) == datetime(
            2026, 1, 31, 23, 0
        )

    def test_monthly_day_and_month_still_work(self) -> None:
        assert last_scheduled_occurrence("0 2 1 7 *", self.NOW) == datetime(2026, 7, 1, 2, 0)

    def test_garbage_still_returns_none(self) -> None:
        assert last_scheduled_occurrence("not a cron", self.NOW) is None
        assert last_scheduled_occurrence("0 2 * *", self.NOW) is None
