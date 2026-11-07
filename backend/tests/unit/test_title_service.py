"""`derive_title` mirrors `frontend/src/utils/autoTitle.ts`.

The two suites use the same cases, so a divergence fails here or in Vitest
rather than silently producing titles the editor would not.
"""

from app.services.title_service import derive_title


def test_takes_first_non_empty_line_and_strips_headings() -> None:
    assert derive_title("# Trip to Sundarbans\n\nWe left at dawn.") == "Trip to Sundarbans"
    assert derive_title("\n\n  ## Second try  ") == "Second try"


def test_strips_list_quote_and_ordered_list_markers() -> None:
    assert derive_title("- bought tickets") == "bought tickets"
    assert derive_title("> quoted opener") == "quoted opener"
    assert derive_title("3. third item") == "third item"


def test_keeps_link_and_image_labels() -> None:
    assert derive_title("[Planning doc](https://example.com/x)") == "Planning doc"
    assert derive_title("![Sunset over the lake](https://x/y.jpg)") == "Sunset over the lake"


def test_strips_inline_markup_and_html() -> None:
    assert derive_title("**Bold** and _em_ and `code`") == "Bold and em and code"
    assert derive_title("<p>Wrapped in html</p>") == "Wrapped in html"


def test_trims_trailing_punctuation_and_collapses_whitespace() -> None:
    assert derive_title("A long   day...") == "A long day"
    assert derive_title("Done!") == "Done"


def test_keeps_emoji_and_hashtags() -> None:
    assert derive_title("🎉 Party time") == "🎉 Party time"
    assert derive_title("#travel plans") == "#travel plans"


def test_empty_and_photo_only_bodies_have_no_title() -> None:
    assert derive_title("![](/api/v1/media/1/file)") == ""
    assert derive_title("   \n\n\t\n") == ""
    assert derive_title("") == ""
    assert derive_title(None) == ""


def test_skips_lines_that_become_empty() -> None:
    assert derive_title("---\n![](x.png)\nReal first line") == "Real first line"


def test_word_boundary_truncation() -> None:
    out = derive_title(("word " * 40) + "end", 20)
    assert out.endswith("…")
    assert len(out) <= 21
    assert "  " not in out


def test_hard_truncation_for_scripts_without_spaces() -> None:
    out = derive_title("日記" * 100, 10)
    assert len(out) == 11  # 10 code points + ellipsis
    assert out.endswith("…")


def test_does_not_split_surrogate_pairs() -> None:
    out = derive_title("🎉" * 30, 5)
    assert out == "🎉🎉🎉🎉🎉…"
