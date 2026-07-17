# 📔 Open-Format Data Management & Obsidian-Vault Separation

An architectural proposal for **LifeLogr (LifeLogr)** to separate text entries and media attachments into a highly portable, standard directory tree, shifting the database's role from the primary "source of truth" to a "high-performance search/render cache."

---

## ⚡ 1. The Strategy: "Open-Format Folder" Storage (Compress)

Currently, text entries are locked in a SQLite relational database (`.db`), while media files are stored on disk. By evolving this into a **100% open, local-first folder structure**, we achieve seamless interoperability with third-party tools like Obsidian, simplify backups, and guarantee future-proof durability.

### Architectural Paradigm Shift

```
                  ┌────────────────────────────────────────────────────────┐
                  │              LifeLogr Application Directory           │
                  └──────────────────────────┬─────────────────────────────┘
                                             │
             ┌───────────────────────────────┴───────────────────────────────┐
             ▼                                                               ▼
   [📂 Primary Source of Truth]                                    [⚡ Fast Index Cache]
   - Human-Readable Directory Tree                                - SQLite (WAL Mode)
   - Daily Entry `.md` Markdown Files                              - Reconstructed instantly
   - YAML metadata (tags, mood, location)                         - Powers calendar grids,
   - Standard `/attachments/` subdirectories                      - timeline, FTS5 searches
```

---

## 📊 2. Comparative Analysis (Compile)

Below is a comparison of the current database-centric storage model versus the proposed **Separated Open-Format Folder** architecture:

| Architectural Aspect | Current Database-Centric Model | Proposed Separated Open-Format Model |
| :--- | :--- | :--- |
| **Source of Truth** | SQLite relational database file (`.db`) | Plain-text Markdown files (`.md`) + media files on disk |
| **Media Location** | Relational `media` rows pointing to local files | Standard `/attachments` folders linked via relative markdown links |
| **Text Portability** | Locked in SQLite (requires database exporter to read) | 100% portable. Openable in any text editor, VS Code, or Obsidian |
| **Vault Compatibility** | Zero direct integration | **100% Obsidian-ready**. The journal folder *is* an Obsidian vault |
| **Sync & Backups** | High friction (syncing changing binary SQLite WAL pools) | Flawless (syncs light text diffs via Git, Syncthing, or Dropbox) |
| **Resilience & Corruption** | Database file corruption results in total data loss | DB deletion has 0 impact; rebuilt dynamically by re-scanning folders |
| **Search Speed** | SQL FTS5 matching on SQLite rows | SQL FTS5 matching on cached SQLite index (highly optimized) |

---

## 🛠️ 3. Implementation Details: Schema & Directory Tree (Consolidate)

### 3.1 Proposed Directory Structure

Your daily notes are organized hierarchically by year and month. This makes chronological folder scanning extremely fast:

```
diary_vault/
├── journal/
│   └── 2026/
│       └── 05/
│           ├── 2026-05-28.md
│           └── 2026-05-29.md
└── attachments/
    └── 2026-05-29/
        ├── photo_sunset.webp
        └── voice_note.mp3
```

### 3.2 The Markdown + YAML Frontmatter Structure
Each daily entry is a standard markdown file containing structured YAML frontmatter at the top. This allows the journal text to remain readable while carrying advanced metadata:

```markdown
---
date: 2026-05-29
title: "Explored Data Architecture"
mood: "Inspired"
tags:
  - architecture/database
  - core/refinement
location: "Bangalore, India"
latitude: 12.9716
longitude: 77.5946
is_encrypted: false
attachments:
  - filename: "photo_sunset.webp"
    size: 245100
    type: "image/webp"
  - filename: "voice_note.mp3"
    size: 1048576
    type: "audio/mp3"
---

Today, I explored the scope for improving and enhancing the local data management layer. 

I proposed separating the raw text journals and media files entirely into physical folders, making the LifeLogr journal directory 100% interoperable with Obsidian.

![Sunset Over the City](../../attachments/2026-05-29/photo_sunset.webp)

Here is the voice recording explaining the system details:
<audio controls src="../../attachments/2026-05-29/voice_note.mp3"></audio>
```

---

## 💾 4. Code-First Synchronization Mechanics

In this decoupled model, the FastAPI server functions as a "watcher/indexer." On server startup or entry saves, it syncs the folder structure to the SQLite database.

### 4.1 Schema Definition for Caching Metadata

```python
# app/models/entry_cache.py
from datetime import date, datetime
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class EntryCache(Base):
    """High-speed index representing the physical Markdown entry."""
    __tablename__ = "entry_cache"

    entry_date: Mapped[date] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(nullable=True)
    mood: Mapped[str | None] = mapped_column(nullable=True)
    location_name: Mapped[str | None] = mapped_column(nullable=True)
    file_hash: Mapped[str] = mapped_column(nullable=False) # For fast change detection
    last_synced_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
```

### 4.2 Decoupled Save Pipeline

When the user edits an entry in the frontend, the FastAPI service writes directly to disk first, then updates the cache asynchronously:

```python
# app/services/storage_service.py
import yaml
from pathlib import Path
from app.schemas.entry import EntrySaveRequest

class OpenFormatStorageService:
    def __init__(self, vault_path: Path):
        self.vault_path = vault_path

    async def save_entry(self, data: EntrySaveRequest) -> Path:
        # 1. Build directory path: journal/YYYY/MM/YYYY-MM-DD.md
        year_str = data.date.strftime("%Y")
        month_str = data.date.strftime("%m")
        file_name = f"{data.date.strftime('%Y-%m-%d')}.md"
        target_dir = self.vault_path / "journal" / year_str / month_str
        target_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = target_dir / file_name

        # 2. Compile Frontmatter Metadata
        metadata = {
            "date": str(data.date),
            "title": data.title,
            "mood": data.mood,
            "tags": data.tags,
            "location": data.location_name,
            "latitude": data.latitude,
            "longitude": data.longitude,
        }

        # 3. Assemble full markdown string
        frontmatter_block = yaml.dump(metadata, sort_keys=False)
        full_content = f"---\n{frontmatter_block}---\n\n{data.body}"

        # 4. Write text physically to disk
        file_path.write_text(full_content, encoding="utf-8")
        
        # 5. Queue asynchronous cache-invalidation re-index
        await self.trigger_reindex_for_date(data.date, file_path)
        
        return file_path
```

---

## 🚀 5. Synthesis & Major Enhancements

By separating the text database storage from media storage and committing to a physical Markdown format, you achieve:
1. **0% Lock-in:** You can open your journal vault in Obsidian, VS Code, or Logseq immediately.
2. **Perfect Incremental Backups:** Git or Syncthing can version-control your journal with minute-level precision, saving only 50-byte text patches rather than shipping a full 10MB SQLite database on every typo correction.
3. **Hardware Efficiency:** SQLite database overhead drops to zero. All CRUD writes are standard file-system writes.
