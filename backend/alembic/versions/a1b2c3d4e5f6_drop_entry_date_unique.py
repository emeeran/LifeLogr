"""drop_entry_date_unique

Revision ID: a1b2c3d4e5f6
Revises: f047afab5e35
Create Date: 2026-05-16 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from alembic.operations import ops
from alembic.operations.base import Operations


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f047afab5e35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires table rebuild to drop UNIQUE constraint
    bind = op.get_bind()

    # Get current table columns
    from sqlalchemy import inspect
    insp = inspect(bind)
    columns = insp.get_columns('entries')

    # Create new table without unique constraint on entry_date
    op.execute("""
        CREATE TABLE _entries_new (
            id INTEGER NOT NULL PRIMARY KEY,
            entry_date DATE NOT NULL,
            title VARCHAR(255),
            body VARCHAR NOT NULL,
            mood VARCHAR(50),
            is_deleted BOOLEAN NOT NULL,
            deleted_at DATETIME,
            is_encrypted BOOLEAN NOT NULL,
            encrypted_at DATETIME,
            latitude FLOAT,
            longitude FLOAT,
            location_name VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
    """)
    op.execute("""
        INSERT INTO _entries_new SELECT * FROM entries
    """)
    op.execute("DROP TABLE entries")
    op.execute("ALTER TABLE _entries_new RENAME TO entries")


def downgrade() -> None:
    # Recreate with unique constraint
    op.execute("""
        CREATE TABLE _entries_new (
            id INTEGER NOT NULL PRIMARY KEY,
            entry_date DATE NOT NULL UNIQUE,
            title VARCHAR(255),
            body VARCHAR NOT NULL,
            mood VARCHAR(50),
            is_deleted BOOLEAN NOT NULL,
            deleted_at DATETIME,
            is_encrypted BOOLEAN NOT NULL,
            encrypted_at DATETIME,
            latitude FLOAT,
            longitude FLOAT,
            location_name VARCHAR(255),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
        )
    """)
    op.execute("""
        INSERT INTO _entries_new SELECT * FROM entries
    """)
    op.execute("DROP TABLE entries")
    op.execute("ALTER TABLE _entries_new RENAME TO entries")
