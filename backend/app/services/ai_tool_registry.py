"""Registry of generic, registry-driven AI text tools.

Each tool is a pure prompt builder plus generation settings. The tools here are
the "new productive tools" (summarize, translate, …) exposed through the single
generic endpoint ``POST /api/v1/ai/tool/{tool_id}``. They return plain text, so
unlike grammar/analyze they do NOT route through the JSON parser.

Adding a new tool = add one ``AiToolSpec`` to :data:`REGISTRY` and one entry to
the frontend registry that targets ``/ai/tool/<id>``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# A prompt builder takes the selected text and an optional parameter value
# (e.g. target language) and returns the full prompt string.
PromptBuilder = Callable[[str, str | None], str]


@dataclass(frozen=True, slots=True)
class AiToolParamSpec:
    """Optional single-value parameter for a tool (rendered as UI pills)."""

    name: str
    options: tuple[str, ...]
    default: str


@dataclass(frozen=True, slots=True)
class AiToolSpec:
    """Definition of a registry-driven AI text tool."""

    tool_id: str
    prompt_builder: PromptBuilder
    temperature: float
    num_predict: int
    param: AiToolParamSpec | None = None


# ── Prompt builders ──────────────────────────────────────────────────────


def _summarize_prompt(text: str, _: str | None) -> str:
    return (
        "You are an editor. Summarize the text in 2-3 sentences that capture the core message. "
        "Preserve the author's intent and do not add new information.\n\n"
        f"Text:\n{text[:4000]}\n\n"
        "Return ONLY the summary — no preamble, no quotation marks, no markdown."
    )


def _key_points_prompt(text: str, _: str | None) -> str:
    return (
        "You are an editor. Extract the 3-7 most important points from the text as a markdown "
        "bullet list (each line starts with '- '). Keep each point concise and faithful to the text.\n\n"
        f"Text:\n{text[:4000]}\n\n"
        "Return ONLY the bullet list — no preamble, no extra commentary."
    )


def _action_items_prompt(text: str, _: str | None) -> str:
    return (
        "You are a productivity coach. Extract only the actionable to-dos implied by the text and "
        "return them as a markdown checklist (each line '- [ ] task'). Phrase each as a concrete, "
        "startable action.\n\n"
        f"Text:\n{text[:4000]}\n\n"
        "If there are no actionable items, return exactly '- [ ] No action items found.'. "
        "Return ONLY the checklist — no preamble, no commentary."
    )


def _shorten_prompt(text: str, _: str | None) -> str:
    return (
        "You are an editor. Condense the text to roughly half its length while keeping all key "
        "information, the original meaning, and the tone. Do not drop important detail.\n\n"
        f"Text:\n{text[:4000]}\n\n"
        "Return ONLY the shortened text — no preamble, no quotation marks, no markdown."
    )


def _simplify_prompt(text: str, _: str | None) -> str:
    return (
        "You are an editor. Rewrite the text in plain language at about a 5th-grade reading level "
        "(ELI5). Keep the meaning and all key information; do not remove content. "
        "Prefer common words and short sentences.\n\n"
        f"Text:\n{text[:4000]}\n\n"
        "Return ONLY the simplified text — no preamble, no quotation marks, no markdown."
    )


def _polish_prompt(text: str, _: str | None) -> str:
    return (
        "You are an editor. Improve the word choice, sentence flow, and rhythm of the text. "
        "Fix awkward or repetitive phrasing while preserving the meaning and the author's voice. "
        "Do not change the subject or add new facts.\n\n"
        f"Text:\n{text[:4000]}\n\n"
        "Return ONLY the polished text — no preamble, no quotation marks, no markdown."
    )


def _translate_prompt(text: str, language: str | None) -> str:
    target = language or "Spanish"
    return (
        f"You are a translator. Translate the text into {target}. "
        "Preserve the meaning, tone, names, and proper nouns. "
        "Do not add explanations unless a term has no equivalent.\n\n"
        f"Text:\n{text[:4000]}\n\n"
        "Return ONLY the translation — no preamble, no quotation marks, no markdown."
    )


def _add_structure_prompt(text: str, _: str | None) -> str:
    return (
        "You are an editor. Reorganize the text using markdown headings (#) and bullet points where "
        "they help readability. Group related ideas under clear headings. Keep all content and the "
        "original meaning; do not invent new information.\n\n"
        f"Text:\n{text[:4000]}\n\n"
        "Return ONLY the restructured markdown — no preamble, no commentary."
    )


def _title_prompt(text: str, _: str | None) -> str:
    return (
        "You are an editor. Generate a concise, descriptive title for the text (at most 8 words). "
        "Capture the main idea; avoid clickbait and filler words.\n\n"
        f"Text:\n{text[:4000]}\n\n"
        "Return ONLY the title — no preamble, no quotation marks, no trailing punctuation."
    )


# ── Registry ─────────────────────────────────────────────────────────────

_LANGUAGE_OPTIONS: tuple[str, ...] = (
    "Spanish",
    "French",
    "German",
    "Italian",
    "Portuguese",
    "Japanese",
    "Chinese",
    "Hindi",
    "Arabic",
    "English",
)

REGISTRY: dict[str, AiToolSpec] = {
    "summarize": AiToolSpec("summarize", _summarize_prompt, 0.3, 512),
    "key-points": AiToolSpec("key-points", _key_points_prompt, 0.3, 768),
    "action-items": AiToolSpec("action-items", _action_items_prompt, 0.3, 768),
    "shorten": AiToolSpec("shorten", _shorten_prompt, 0.4, 2048),
    "simplify": AiToolSpec("simplify", _simplify_prompt, 0.4, 2048),
    "polish": AiToolSpec("polish", _polish_prompt, 0.5, 2048),
    "translate": AiToolSpec(
        "translate",
        _translate_prompt,
        0.3,
        2048,
        AiToolParamSpec("language", _LANGUAGE_OPTIONS, "Spanish"),
    ),
    "add-structure": AiToolSpec("add-structure", _add_structure_prompt, 0.4, 2048),
    "title": AiToolSpec("title", _title_prompt, 0.5, 64),
}


def get_spec(tool_id: str) -> AiToolSpec | None:
    """Return the spec for ``tool_id``, or ``None`` if unknown."""
    return REGISTRY.get(tool_id)
