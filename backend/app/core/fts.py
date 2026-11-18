"""Shared FTS5 (SQLite full-text search) helpers.

Two concerns live here:

1. ``sanitize_fts_query`` — turning free-form user input into a safe FTS5
   ``MATCH`` expression.
2. The **index contract** between a base table and its ``<table>_fts`` shadow:
   the backfill SQL and the seven sync triggers. Defining the DDL once here
   means the boot-time installer (``core.database._setup_fts``) and the test
   fixtures (``tests/conftest.py``) build byte-identical triggers, so the
   integration suite exercises the same trigger-maintained index production
   uses.
"""

from __future__ import annotations

# Base tables that have a maintained FTS5 shadow index (``<table>_fts``).
FTS_BASE_TABLES: tuple[str, ...] = ("entries", "notes")

# Trigger name prefix per base table (singular, matching the historical names
# ``fts_entry_ai`` / ``fts_note_ai`` — renaming would orphan old triggers).
_TRIGGER_PREFIX = {"entries": "fts_entry", "notes": "fts_note"}

# The trigger set: insert / update / hard delete / soft delete / restore /
# encrypt / decrypt. Both tables install exactly this set.
_TRIGGER_SUFFIXES: tuple[str, ...] = (
    "ai",
    "au",
    "ad",
    "soft_del",
    "restore",
    "encrypt",
    "decrypt",
)


def sanitize_fts_query(query: str) -> str:
    """Build a safe FTS5 ``MATCH`` expression from free-form user input.

    FTS5's MATCH parser treats tokens like ``OR``, ``*``, ``-`` and ``(`` as
    operators, so passing raw user input either throws a syntax error or matches
    something unintended. We split on whitespace and wrap each token in
    double-quotes — a quoted token is a literal phrase — so any input becomes a
    conjunction of literal term searches. Empty input yields ``""``, which FTS5
    treats as match-nothing (callers fall back to ILIKE on zero rows).

    A literal double-quote inside a token is doubled (``"`` → ``""``) per the
    FTS5 string-quoting rule, so a token containing a quote can't prematurely
    close the phrase.
    """
    tokens = [tok.replace('"', '""') for tok in query.split() if tok.strip()]
    return " ".join(f'"{tok}"' for tok in tokens)


def _fts_table(base: str) -> str:
    return f"{base}_fts"


def fts_populate_sql(base: str) -> str:
    """``INSERT … SELECT`` that backfills ``<base>_fts`` from ``<base>``.

    Only live plaintext rows are indexed: soft-deleted rows are hidden from
    search and encrypted rows hold ciphertext in ``body``.
    """
    t = base
    return f"""
        INSERT INTO {_fts_table(t)}(rowid, title, body)
        SELECT {t}.id, COALESCE({t}.title, ''), {t}.body
        FROM {t}
        WHERE {t}.is_deleted = 0 AND {t}.is_encrypted = 0
    """


def fts_trigger_names(base: str) -> tuple[str, ...]:
    """Names of every sync trigger for ``base`` (used for idempotent DROPs)."""
    prefix = _TRIGGER_PREFIX[base]
    return tuple(f"{prefix}_{suffix}" for suffix in _TRIGGER_SUFFIXES)


def fts_trigger_ddl(base: str) -> tuple[str, ...]:
    """The ``CREATE TRIGGER`` statements that keep ``<base>_fts`` in sync.

    Same conventions for both tables:

    * INSERT/UPDATE only index live (``is_deleted = 0``) plaintext
      (``is_encrypted = 0``) rows — ciphertext must never enter the index.
    * UPDATE does ``DELETE``-by-rowid then ``INSERT`` rather than the FTS5
      ``'delete'`` command, which throws "SQL logic error" in the bundled
      SQLite/pysqlite3 build and would fail every row update.
    """
    t = base
    fts = _fts_table(t)
    return (
        f"""
        CREATE TRIGGER {_TRIGGER_PREFIX[t]}_ai AFTER INSERT ON {t}
        WHEN NEW.is_deleted = 0 AND NEW.is_encrypted = 0
        BEGIN
            INSERT INTO {fts}(rowid, title, body)
            VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
        END
    """,
        # Remove+reinsert (not UPDATE) so this is correct even when the row was
        # previously removed from FTS (e.g. after a soft delete followed by
        # content edits) — a plain UPDATE would be a no-op. Only re-indexes
        # plaintext→plaintext edits of non-encrypted rows; encryption /
        # decryption transitions are handled by the dedicated triggers below.
        f"""
        CREATE TRIGGER {_TRIGGER_PREFIX[t]}_au AFTER UPDATE ON {t}
        WHEN NEW.is_deleted = 0 AND OLD.is_deleted = 0
           AND NEW.is_encrypted = 0 AND OLD.is_encrypted = 0
        BEGIN
            DELETE FROM {fts} WHERE rowid = NEW.id;
            INSERT INTO {fts}(rowid, title, body)
            VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
        END
    """,
        f"""
        CREATE TRIGGER {_TRIGGER_PREFIX[t]}_ad AFTER DELETE ON {t}
        BEGIN
            DELETE FROM {fts} WHERE rowid = OLD.id;
        END
    """,
        # Soft delete: remove from the index (0 → 1).
        f"""
        CREATE TRIGGER {_TRIGGER_PREFIX[t]}_soft_del AFTER UPDATE ON {t}
        WHEN NEW.is_deleted = 1 AND OLD.is_deleted = 0
        BEGIN
            DELETE FROM {fts} WHERE rowid = NEW.id;
        END
    """,
        # Restore: re-index the row (1 → 0). Skips encrypted rows — their body
        # column holds ciphertext, not searchable text.
        f"""
        CREATE TRIGGER {_TRIGGER_PREFIX[t]}_restore AFTER UPDATE ON {t}
        WHEN NEW.is_deleted = 0 AND OLD.is_deleted = 1 AND NEW.is_encrypted = 0
        BEGIN
            INSERT INTO {fts}(rowid, title, body)
            VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
        END
    """,
        # Encryption toggle. Encrypted rows must never live in the index: on
        # encrypt, drop the now-stale plaintext row.
        f"""
        CREATE TRIGGER {_TRIGGER_PREFIX[t]}_encrypt AFTER UPDATE ON {t}
        WHEN NEW.is_encrypted = 1 AND OLD.is_encrypted = 0
        BEGIN
            DELETE FROM {fts} WHERE rowid = NEW.id;
        END
    """,
        # On decrypt, re-index the restored plaintext body.
        f"""
        CREATE TRIGGER {_TRIGGER_PREFIX[t]}_decrypt AFTER UPDATE ON {t}
        WHEN NEW.is_encrypted = 0 AND OLD.is_encrypted = 1 AND NEW.is_deleted = 0
        BEGIN
            DELETE FROM {fts} WHERE rowid = NEW.id;
            INSERT INTO {fts}(rowid, title, body)
            VALUES (NEW.id, COALESCE(NEW.title, ''), NEW.body);
        END
    """,
    )
