"""Registry of generic, registry-driven AI text tools.

Each tool is a pure prompt builder plus generation settings. Per spec §10 the
persona, journal-privacy framing, and paste-back output contract live in the
shared system prompt (:data:`app.services.ollama_service.SYSTEM_PROMPT`) that
every provider path attaches; the builders here carry ONLY tool-specific
behavior in the user message and must not restate a persona.

The menu presents the folded 8-tool contract set (spec.md §10 / impl-contract):
rewrite-style operations are one ``rewrite`` tool with a ``mode`` parameter,
and summarize/key-points/actions fold into one ``summarize`` tool with a mode
parameter. ``define`` stays reachable through its dedicated backend endpoint
but is not part of this registry.

Adding a new tool = add one ``AiToolSpec`` to :data:`REGISTRY` and one entry to
the frontend registry that targets ``/ai/tool/<id>``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

# Backend maximum accepted selection length for registry tools (chars). The
# frontend truncates against the same number and MUST surface the truncation
# to the user (spec AI3) — never cut silently.
MAX_TOOL_TEXT_CHARS = 4000

# A prompt builder takes the selected text and an optional parameter value
# (e.g. target language or mode) and returns the user-message prompt string.
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


# ── Prompt builders (tool-specific behavior only — no persona) ───────────

_REWRITE_INSTRUCTIONS: dict[str, str] = {
    "as-is": (
        "Rewrite the text to improve flow and readability without changing its "
        "style, register, or meaning."
    ),
    "polish": (
        "Improve the word choice, sentence flow, and rhythm. Fix awkward or "
        "repetitive phrasing without changing the subject."
    ),
    "clarity": (
        "Rewrite for maximum clarity: split long sentences, remove ambiguity, "
        "and prefer concrete words. Preserve meaning and formality."
    ),
    "simplify": (
        "Rewrite in plain language at about a 5th-grade reading level, keeping "
        "the meaning and all key information."
    ),
    "formal": (
        "Rewrite in a formal register. Keep the same meaning and facts; adjust "
        "only the style, register, and word choice."
    ),
    "casual": (
        "Rewrite in a casual, conversational register. Keep the same meaning "
        "and facts; adjust only the style, register, and word choice."
    ),
}

_SUMMARIZE_INSTRUCTIONS: dict[str, str] = {
    "sentences": (
        "Summarize the text in 2-3 sentences that capture the core message. "
        "Do not add new information."
    ),
    "bullets": (
        "Extract the 3-7 most important points as a markdown bullet list "
        "(each line starts with '- '). Keep each point concise and faithful."
    ),
    "actions": (
        "Extract only the actionable to-dos implied by the text as a markdown "
        "checklist (each line '- [ ] task'), phrased as concrete startable "
        "actions. If there are none, return exactly '- [ ] No action items "
        "found.'"
    ),
}


def _rewrite_prompt(text: str, mode: str | None) -> str:
    mode = mode or "as-is"
    return (
        f"{_REWRITE_INSTRUCTIONS[mode]}\n\n"
        f"Text:\n{text[:MAX_TOOL_TEXT_CHARS]}"
    )


def _summarize_prompt(text: str, mode: str | None) -> str:
    mode = mode or "sentences"
    return (
        f"{_SUMMARIZE_INSTRUCTIONS[mode]}\n\n"
        f"Text:\n{text[:MAX_TOOL_TEXT_CHARS]}"
    )


def _expand_prompt(text: str, _: str | None) -> str:
    return (
        "Expand and elaborate on the text, adding vivid detail, sensory "
        "description, and emotional depth. Do not change the subject or "
        "introduce unrelated facts.\n\n"
        f"Text:\n{text[:MAX_TOOL_TEXT_CHARS]}"
    )


def _shorten_prompt(text: str, _: str | None) -> str:
    return (
        "Condense the text to roughly half its length while keeping all key "
        "information, the original meaning, and the tone. Do not drop "
        "important detail.\n\n"
        f"Text:\n{text[:MAX_TOOL_TEXT_CHARS]}"
    )


def _title_prompt(text: str, _: str | None) -> str:
    return (
        "Generate a concise, descriptive title for the text (at most 8 "
        "words). Capture the main idea; avoid clickbait and filler words.\n\n"
        f"Text:\n{text[:MAX_TOOL_TEXT_CHARS]}"
    )


def _translate_prompt(text: str, language: str | None) -> str:
    target = language or "Spanish"
    return (
        f"Translate the text into {target}. Preserve the meaning, tone, "
        "names, and proper nouns. Do not add explanations unless a term has "
        "no equivalent.\n\n"
        f"Text:\n{text[:MAX_TOOL_TEXT_CHARS]}"
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
    "rewrite": AiToolSpec(
        "rewrite",
        _rewrite_prompt,
        0.5,
        2048,
        AiToolParamSpec("mode", tuple(_REWRITE_INSTRUCTIONS), "as-is"),
    ),
    "summarize": AiToolSpec(
        "summarize",
        _summarize_prompt,
        0.3,
        768,
        AiToolParamSpec("mode", tuple(_SUMMARIZE_INSTRUCTIONS), "sentences"),
    ),
    "expand": AiToolSpec("expand", _expand_prompt, 0.7, 2048),
    "shorten": AiToolSpec("shorten", _shorten_prompt, 0.4, 2048),
    "title": AiToolSpec("title", _title_prompt, 0.5, 64),
    "translate": AiToolSpec(
        "translate",
        _translate_prompt,
        0.3,
        2048,
        AiToolParamSpec("language", _LANGUAGE_OPTIONS, "Spanish"),
    ),
}


def get_spec(tool_id: str) -> AiToolSpec | None:
    """Return the spec for ``tool_id``, or ``None`` if unknown."""
    return REGISTRY.get(tool_id)
