"""Central model imports so every ORM class registers in ``Base.metadata``.

Without this, models that are only imported lazily inside service functions
(e.g. ``EntrySentiment``, ``EntryPrompt`` via ``enrichment_service``) never
register at startup — so ``Base.metadata.create_all`` would skip their tables
on a fresh DB, and schema introspection would mis-flag them as "unexpected".
Importing this package (e.g. from ``init_db``) guarantees the full set is
registered before ``create_all`` / integrity checks run.
"""

from app.models.ai_provider import AIProvider
from app.models.backup import BackupConfig, BackupSchedule, BackupSnapshot
from app.models.embedding import EntryEmbedding
from app.models.entry import Entry
from app.models.media import Media
from app.models.note import Note, NoteFolder, NotePage, NoteTag
from app.models.note_media import NoteMedia
from app.models.prompt import DailyPrompt
from app.models.recording import VoiceRecording
from app.models.reflection_prompt import EntryPrompt
from app.models.reminder import Reminder
from app.models.sentiment import EntrySentiment
from app.models.sync import SyncQueue, SyncStatus
from app.models.tag import EntryTag, Tag
from app.models.template import Template
from app.models.video_note import VideoNote

__all__ = [
    "AIProvider",
    "BackupConfig",
    "BackupSchedule",
    "BackupSnapshot",
    "DailyPrompt",
    "Entry",
    "EntryEmbedding",
    "EntryPrompt",
    "EntrySentiment",
    "EntryTag",
    "Media",
    "Note",
    "NoteFolder",
    "NoteMedia",
    "NotePage",
    "NoteTag",
    "Reminder",
    "SyncQueue",
    "SyncStatus",
    "Tag",
    "Template",
    "VideoNote",
    "VoiceRecording",
]
