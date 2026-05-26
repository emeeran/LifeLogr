"""Re-export all models for Alembic discovery and easy imports."""

from app.models.backup import BackupConfig, BackupSnapshot
from app.models.digest import Digest
from app.models.embedding import EntryEmbedding
from app.models.entry import Entry
from app.models.media import Media
from app.models.ocr_result import OCRResult
from app.models.plugin import Plugin, PluginHook
from app.models.prompt import DailyPrompt
from app.models.recording import VoiceRecording
from app.models.reflection_prompt import EntryPrompt
from app.models.reminder import Reminder
from app.models.revision import EntryRevision
from app.models.sentiment import EntrySentiment
from app.models.sync import SyncQueue, SyncStatus
from app.models.tag import EntryTag, Tag
from app.models.template import Template
from app.models.video_note import VideoNote

__all__ = [
    "BackupConfig",
    "BackupSnapshot",
    "DailyPrompt",
    "Digest",
    "Entry",
    "EntryEmbedding",
    "EntryPrompt",
    "EntryRevision",
    "EntrySentiment",
    "EntryTag",
    "Media",
    "OCRResult",
    "Plugin",
    "PluginHook",
    "Reminder",
    "SyncQueue",
    "SyncStatus",
    "Tag",
    "Template",
    "VideoNote",
    "VoiceRecording",
]
