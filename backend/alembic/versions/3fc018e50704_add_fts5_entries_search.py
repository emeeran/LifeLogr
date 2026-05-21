"""add_fts5_entries_search

Revision ID: 3fc018e50704
Revises: 01472f00acb3
Create Date: 2026-05-11 09:07:19.264552

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3fc018e50704'
down_revision: Union[str, Sequence[str], None] = '01472f00acb3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
        USING fts5(title, body, content=entries, content_rowid=id);
    """)

    # Populate FTS from existing entries
    op.execute("""
        INSERT INTO entries_fts(rowid, title, body)
        SELECT id, title, body FROM entries WHERE is_deleted = 0;
    """)

    # Sync triggers
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS fts_entry_ai AFTER INSERT ON entries
        BEGIN
            INSERT INTO entries_fts(rowid, title, body)
            VALUES (NEW.id, NEW.title, NEW.body);
        END;
    """)
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS fts_entry_au AFTER UPDATE ON entries
        BEGIN
            UPDATE entries_fts SET title = NEW.title, body = NEW.body
            WHERE rowid = NEW.id;
        END;
    """)
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS fts_entry_ad AFTER DELETE ON entries
        BEGIN
            INSERT INTO entries_fts(entries_fts, rowid, title, body)
            VALUES ('delete', OLD.id, OLD.title, OLD.body);
        END;
    """)
    op.execute("""
        CREATE TRIGGER IF NOT EXISTS fts_entry_soft_del AFTER UPDATE ON entries
        WHEN NEW.is_deleted = 1 AND OLD.is_deleted = 0
        BEGIN
            INSERT INTO entries_fts(entries_fts, rowid, title, body)
            VALUES ('delete', NEW.id, NEW.title, NEW.body);
        END;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS fts_entry_soft_del")
    op.execute("DROP TRIGGER IF EXISTS fts_entry_ad")
    op.execute("DROP TRIGGER IF EXISTS fts_entry_au")
    op.execute("DROP TRIGGER IF EXISTS fts_entry_ai")
    op.execute("DROP TABLE IF EXISTS entries_fts")
