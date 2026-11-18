"""Body-driven hashtag extraction + tag resolution.

Tags "live in the text": an entry/note's tags are re-derived from its body on
every save (``entry_service`` / ``note_service``), so the extractor's edge
behaviour *is* the tagging behaviour. These lock it: what starts a tag, what
terminates one, unicode, dedup order, and the resolve/create path.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import Tag
from app.services.hashtag import extract_hashtags, resolve_tag_ids


class TestExtractHashtags:
    def test_none_body_yields_no_tags(self):
        assert extract_hashtags(None) == []

    def test_empty_body(self):
        assert extract_hashtags("") == []

    def test_single_tag(self):
        assert extract_hashtags("went hiking #trailrun today") == ["trailrun"]

    def test_duplicates_are_deduped_in_first_seen_order(self):
        body = "#alpha then #beta then #alpha again and #beta #gamma"
        assert extract_hashtags(body) == ["alpha", "beta", "gamma"]

    def test_tag_at_start_end_and_punctuation_boundaries(self):
        assert extract_hashtags("#start middle #end.") == ["start", "end"]
        assert extract_hashtags("(#paren), #comma; #colon:") == ["paren", "comma", "colon"]

    def test_hyphenated_and_underscored_names_survive(self):
        assert extract_hashtags("#work-life #snake_case") == ["work-life", "snake_case"]

    def test_digits_only_and_mixed_alnum(self):
        assert extract_hashtags("#2026 #2026goals") == ["2026", "2026goals"]

    def test_no_space_after_word_char_is_not_a_tag(self):
        # `foo#bar` — the # is preceded by a word char, so it isn't a tag start.
        assert extract_hashtags("foo#bar") == []

    def test_markdown_heading_is_not_a_tag(self):
        # "# heading" has a space after # — the regex requires a word char.
        assert extract_hashtags("# My Heading\n\nbody text") == []

    def test_preceding_hyphen_blocks_a_tag(self):
        # A `-` before # is excluded too (it's in the lookbehind class).
        assert extract_hashtags("option -#notag") == []

    def test_unicode_names_are_kept(self):
        assert extract_hashtags("gratitude #géñi and #日本語") == ["géñi", "日本語"]

    def test_adjacent_tags_without_space_between_words(self):
        # "#a#b": the second # IS preceded by a word char, so only `a` counts.
        assert extract_hashtags("#a#b") == ["a"]

    def test_code_fence_tags_are_still_extracted(self):
        """Hashtags are extracted everywhere in the body — fenced code included.

        Documented current behaviour: there is no code-awareness in the
        extractor, so ``#include`` inside a C snippet becomes a real tag.
        """
        body = "```c\n#include <stdio.h>\n```\nnote"
        assert extract_hashtags(body) == ["include"]

    def test_case_is_preserved_not_folded(self):
        assert extract_hashtags("#Alpha #alpha") == ["Alpha", "alpha"]


class TestResolveTagIds:
    async def test_creates_missing_tags_and_returns_ids_in_order(self, db_session: AsyncSession):
        ids = await resolve_tag_ids(db_session, ["fresh1", "fresh2"])
        assert len(ids) == 2
        names = {row[0] for row in (await db_session.execute(select(Tag.name))).all()}
        assert names == {"fresh1", "fresh2"}

        # Same order as the input list, whatever the ids are.
        again = await resolve_tag_ids(db_session, ["fresh2", "fresh1"])
        assert again == list(reversed(ids))

    async def test_reuses_existing_tag_without_duplicating(self, db_session: AsyncSession):
        existing = Tag(name="shared")
        db_session.add(existing)
        await db_session.flush()

        ids = await resolve_tag_ids(db_session, ["shared"])
        assert ids == [existing.id]

        total = len((await db_session.execute(select(Tag))).all())
        assert total == 1

    async def test_empty_input_short_circuits(self, db_session: AsyncSession):
        assert await resolve_tag_ids(db_session, []) == []
