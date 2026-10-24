"""FTS5 index integrity — query sanitising, trigger maintenance, boot gating.

The conftest fixture installs the *real* sync triggers (shared DDL from
``app.core.fts``), so these tests exercise the trigger-maintained index that
production serves, not the ILIKE fallback.
"""

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fts import sanitize_fts_query


class TestSanitizeFtsQuery:
    """FTS5 MATCH injection — operator characters must stay literal."""

    def test_empty_is_match_nothing(self):
        assert sanitize_fts_query("") == ""
        assert sanitize_fts_query("   ") == ""

    def test_plain_word_is_quoted(self):
        assert sanitize_fts_query("hello") == '"hello"'

    def test_multiple_words_conjoin(self):
        assert sanitize_fts_query("hello world") == '"hello" "world"'

    def test_or_operator_is_literal(self):
        # Bare OR would be a boolean operator — quoting forces a literal term.
        assert sanitize_fts_query("a OR b") == '"a" "OR" "b"'

    def test_star_wildcard_is_literal(self):
        assert sanitize_fts_query("pyth*") == '"pyth*"'

    def test_quote_cannot_escape_the_phrase(self):
        # A doubled quote stays inside the token, so the expression stays a
        # single well-formed phrase instead of terminating early.
        assert sanitize_fts_query('a"b') == '"a""b"'

    def test_parens_and_colon_are_literal(self):
        assert sanitize_fts_query("(a)") == '"(a)"'
        assert sanitize_fts_query("title:foo") == '"title:foo"'

    def test_caret_and_nearest_are_literal(self):
        assert sanitize_fts_query("^x NEAR y") == '"^x" "NEAR" "y"'

    async def test_sanitised_query_is_accepted_by_fts5(self, db_session: AsyncSession):
        """The whole point: every weird input must parse, not throw."""
        from app.models.entry import Entry

        db_session.add(Entry(entry_date=date(2026, 1, 1), title="Python tips", body="decorator"))
        await db_session.commit()

        for raw in (
            "python",
            "python OR",
            '"python',
            "(python",
            "pyth*",
            "title:python",
            "NEAR",
            "a b AND (c) OR NOT",
            "'",
            "–",
        ):
            rows = (
                await db_session.execute(
                    text("SELECT rowid FROM entries_fts WHERE entries_fts MATCH :q"),
                    {"q": sanitize_fts_query(raw)},
                )
            ).fetchall()
            assert isinstance(rows, list)  # never raises


class TestTriggerMaintainedIndex:
    """Insert/update/delete keep ``entries_fts`` aligned without a rebuild."""

    async def _fts_ids(self, db_session: AsyncSession) -> set[int]:
        rows = await db_session.execute(text("SELECT rowid FROM entries_fts"))
        return {int(r[0]) for r in rows.fetchall()}

    async def test_insert_and_update_are_indexed(self, db_session: AsyncSession):
        from app.models.entry import Entry

        entry = Entry(entry_date=date(2026, 1, 1), title="alpha", body="first words")
        db_session.add(entry)
        await db_session.commit()
        assert await self._fts_ids(db_session) == {entry.id}

        entry.body = "second words entirely"
        await db_session.commit()
        hit = (
            await db_session.execute(
                text("SELECT rowid FROM entries_fts WHERE entries_fts MATCH :q"),
                {"q": '"entirely"'},
            )
        ).fetchall()
        assert [int(r[0]) for r in hit] == [entry.id]
        stale = (
            await db_session.execute(
                text("SELECT rowid FROM entries_fts WHERE entries_fts MATCH :q"),
                {"q": '"first"'},
            )
        ).fetchall()
        assert stale == []

    async def test_soft_delete_then_restore(self, db_session: AsyncSession):
        from app.models.entry import Entry

        entry = Entry(entry_date=date(2026, 1, 2), title="beta", body="softdelete me")
        db_session.add(entry)
        await db_session.commit()
        assert await self._fts_ids(db_session) == {entry.id}

        entry.is_deleted = True
        await db_session.commit()
        assert await self._fts_ids(db_session) == set()

        entry.is_deleted = False
        await db_session.commit()
        assert await self._fts_ids(db_session) == {entry.id}

    async def test_encrypt_and_decrypt_never_index_ciphertext(self, db_session: AsyncSession):
        from app.models.entry import Entry

        entry = Entry(entry_date=date(2026, 1, 3), title="gamma", body="plaintext secret")
        db_session.add(entry)
        await db_session.commit()
        assert await self._fts_ids(db_session) == {entry.id}

        entry.is_encrypted = True
        entry.body = "c1ph3rt3xt"
        await db_session.commit()
        assert await self._fts_ids(db_session) == set()

        entry.is_encrypted = False
        entry.body = "plaintext secret again"
        await db_session.commit()
        assert await self._fts_ids(db_session) == {entry.id}

    async def test_note_triggers_maintain_notes_fts(self, db_session: AsyncSession):
        from app.models.note import Note

        note = Note(title="delta", body="note body words")
        db_session.add(note)
        await db_session.commit()
        ids = {int(r[0]) for r in (await db_session.execute(text("SELECT rowid FROM notes_fts")))}
        assert ids == {note.id}

        note.is_deleted = True
        await db_session.commit()
        ids = {int(r[0]) for r in (await db_session.execute(text("SELECT rowid FROM notes_fts")))}
        assert ids == set()

    async def test_hard_delete_removes_index_row(self, db_session: AsyncSession):
        from app.models.entry import Entry

        entry = Entry(entry_date=date(2026, 1, 4), title="epsilon", body="gone soon")
        db_session.add(entry)
        await db_session.commit()
        await db_session.delete(entry)
        await db_session.commit()
        assert await self._fts_ids(db_session) == set()


class TestBootFtsBehaviour:
    """``_setup_fts`` heals drift and no longer rebuilds triggers every boot."""

    async def test_id_set_drift_is_healed(self, db_engine, monkeypatch):
        """A row deleted straight from the index (missing trigger) is restored."""
        from app.core import database as dbmod


        # Point the module engine at this test DB so _setup_fts touches it.
        monkeypatch.setattr(dbmod, "engine", db_engine)
        async with db_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO entries (entry_date, body, is_deleted, is_encrypted) "
                    "VALUES ('2026-02-01', 'drift probe', 0, 0)"
                )
            )
            entry_id = (
                await conn.execute(text("SELECT id FROM entries WHERE body = 'drift probe'"))
            ).scalar_one()
            # Manufacture drift the triggers would have prevented.
            await conn.execute(text("DELETE FROM entries_fts WHERE rowid = :i"), {"i": entry_id})

        await dbmod._setup_fts()
        async with db_engine.begin() as conn:
            ids = {int(r[0]) for r in (await conn.execute(text("SELECT rowid FROM entries_fts")))}
        assert ids == {entry_id}

    async def test_triggers_are_not_recreated_when_stamp_is_current(
        self, db_engine, monkeypatch, caplog
    ):
        """A second boot must not DROP/CREATE 14 triggers (concurrent-start race).

        Recreating on every boot let two processes starting together race: one
        dropped a trigger while the other wrote. Assert on the *observable*: with
        the stamp current, a second ``_setup_fts()`` leaves every trigger row's
        ``sqlite_master`` rowid untouched (a DROP+CREATE would renumber them) and
        never logs the install message.
        """
        import logging

        from app.core import database as dbmod
        from app.core.fts import FTS_BASE_TABLES, fts_trigger_names

        monkeypatch.setattr(dbmod, "engine", db_engine)
        await dbmod._setup_fts()  # first call installs + stamps

        async with db_engine.begin() as conn:
            installed = {
                row[0]: int(row[1])
                for row in (
                    await conn.execute(
                        text("SELECT name, rowid FROM sqlite_master WHERE type='trigger'")
                    )
                ).fetchall()
            }
        assert set(installed) == set().union(
            *(set(fts_trigger_names(base)) for base in FTS_BASE_TABLES)
        )

        caplog.clear()  # ignore the first (installing) call's records
        with caplog.at_level(logging.INFO, logger=dbmod.logger.name):
            await dbmod._setup_fts()  # second call: must be a no-op

        async with db_engine.begin() as conn:
            after = {
                row[0]: int(row[1])
                for row in (
                    await conn.execute(
                        text("SELECT name, rowid FROM sqlite_master WHERE type='trigger'")
                    )
                ).fetchall()
            }
            stamp = (
                await conn.execute(
                    text(
                        "SELECT value FROM _schema_meta WHERE key = 'fts_trigger_version'"
                    )
                )
            ).scalar()
        assert after == installed  # same triggers, same rowids → nothing recreated
        assert int(stamp) == dbmod._FTS_TRIGGER_VERSION
        assert "FTS sync triggers installed" not in caplog.text

    async def test_version_bump_forces_rebuild(self, db_engine, monkeypatch):
        """Lowering the recorded stamp (upgrade path) re-populates the index."""
        from app.core import database as dbmod

        monkeypatch.setattr(dbmod, "engine", db_engine)
        await dbmod._setup_fts()
        async with db_engine.begin() as conn:
            await conn.execute(
                text("UPDATE _schema_meta SET value = '0' WHERE key = 'fts_notes_version'")
            )
            await conn.execute(text("DELETE FROM notes_fts"))
        await dbmod._setup_fts()
        async with db_engine.begin() as conn:
            stamp = (
                await conn.execute(
                    text("SELECT value FROM _schema_meta WHERE key = 'fts_notes_version'")
                )
            ).scalar()
            rows = (await conn.execute(text("SELECT COUNT(*) FROM notes_fts"))).scalar()
        assert int(stamp) == dbmod._NOTES_FTS_REBUILD_VERSION
        assert rows == 0  # no notes in this DB — but the rebuild ran cleanly

    @pytest.mark.usefixtures("db_session")
    async def test_shared_ddl_matches_installed_triggers(self, db_engine):
        """The conftest/production DDL and the installed triggers agree by name."""
        from app.core.fts import FTS_BASE_TABLES, fts_trigger_names

        async with db_engine.begin() as conn:
            installed = {
                row[0]
                for row in (
                    await conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))
                ).fetchall()
            }
        for base in FTS_BASE_TABLES:
            assert set(fts_trigger_names(base)) <= installed


class TestRebuildReinstallsTriggers:
    """A rebuild drops the triggers, so the installer must put them back."""

    async def test_forced_rebuild_reinstalls_triggers(self, db_engine, monkeypatch):
        from app.core import database as dbmod

        monkeypatch.setattr(dbmod, "engine", db_engine)
        await dbmod._setup_fts()  # installs + stamps everything

        # Simulate an index-contract bump: rebuild, and the trigger stamp must
        # be cleared so the (dropped) triggers are re-created.
        async with db_engine.begin() as conn:
            await conn.execute(
                text("UPDATE _schema_meta SET value = '0' WHERE key = 'fts_trigger_version'")
            )
            await conn.execute(text(f"PRAGMA user_version = {dbmod._FTS_REBUILD_VERSION - 1}"))
        await dbmod._setup_fts()

        async with db_engine.begin() as conn:
            stamp = (
                await conn.execute(
                    text("SELECT value FROM _schema_meta WHERE key = 'fts_trigger_version'")
                )
            ).scalar()
            installed = {
                row[0]
                for row in (
                    await conn.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))
                ).fetchall()
            }
        assert int(stamp) == dbmod._FTS_TRIGGER_VERSION  # re-stamped, not left at 0
        assert len(installed) == 14  # 7 per table
