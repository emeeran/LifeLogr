"""Pydantic schemas for AI assistance (Ollama) endpoints."""

from pydantic import BaseModel, ConfigDict, Field


class GrammarCheckRequest(BaseModel):
    text: str = Field(
        min_length=1, max_length=50000, description="Text to check for grammar and spelling errors"
    )
    language: str = Field(default="en", max_length=5, description="Language code (e.g. en, fr, de)")

    model_config = ConfigDict(
        json_schema_extra={"example": {"text": "She dont like to goes there.", "language": "en"}}
    )


class Suggestion(BaseModel):
    offset: int = Field(description="Character offset in the original text")
    length: int = Field(description="Length of the flagged text")
    original: str = Field(description="The flagged text")
    suggestion: str = Field(description="Suggested replacement")
    rule_id: str = Field(description="Identifier for the grammar rule")
    message: str = Field(description="Human-readable explanation")


class GrammarCheckResponse(BaseModel):
    original_text: str
    corrected_text: str
    suggestions: list[Suggestion]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "original_text": "She dont like it.",
                "corrected_text": "She doesn't like it.",
                "suggestions": [
                    {
                        "offset": 4,
                        "length": 4,
                        "original": "dont",
                        "suggestion": "doesn't",
                        "rule_id": "MORFOLOGIK_RULE",
                        "message": "Possible spelling mistake",
                    }
                ],
            }
        }
    )


class SpellCheckRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000, description="Text to spell-check")
    language: str = Field(default="en", max_length=5, description="Language code")

    model_config = ConfigDict(
        json_schema_extra={"example": {"text": "The qwick brown foxx jumps.", "language": "en"}}
    )


class SpellCheckResponse(BaseModel):
    original_text: str
    corrected_text: str
    misspellings: list[Suggestion]

    model_config = ConfigDict(from_attributes=True)


class RewriteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000, description="Text to rewrite")
    style: str = Field(description="Rewrite style: formal, casual, concise, elaborate, creative")
    instructions: str | None = Field(
        default=None, max_length=500, description="Additional rewrite instructions"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "Hey wanna grab food?",
                "style": "formal",
                "instructions": "Make it a lunch invitation",
            }
        }
    )


class RewriteResponse(BaseModel):
    original_text: str
    rewritten_text: str
    style: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "original_text": "Hey wanna grab food?",
                "rewritten_text": "Would you be available to join me for lunch?",
                "style": "formal",
            }
        }
    )


class AIStatusResponse(BaseModel):
    ollama_available: bool
    model_name: str
    model_loaded: bool
    embed_model_available: bool = False
    model_names: list[str] = []
    error: str | None = None


# ── Tag suggestions ────────────────────────────────────────────────────


class TagSuggestionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000, description="Entry text to suggest tags for")


class TagSuggestionResponse(BaseModel):
    tags: list[str]


# ── Writer's block ─────────────────────────────────────────────────────


class ContinueWritingRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


class ContinueWritingResponse(BaseModel):
    continuation: str


# ── Theme detection ────────────────────────────────────────────────────


class ThemeInsight(BaseModel):
    theme: str
    frequency: str
    months_mentioned: list[str]
    insight: str


class ThemesResponse(BaseModel):
    themes: list[ThemeInsight]


# ── Smart Tools (expand, change tone) ──────────


class ExpandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)


class ExpandResponse(BaseModel):
    expanded_text: str


class ChangeToneRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    tone: str = Field(
        description="Desired tone: formal, casual, friendly, professional, empathetic, humorous"
    )


class ChangeToneResponse(BaseModel):
    changed_text: str
    tone: str


# ── Analyze Text ──────────────────────────────────────────────────────


class AnalyzeTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000, description="Text to analyze")


class AnalyzeTextResponse(BaseModel):
    emotions: list[str] = []
    themes: list[str] = []
    summary: str = ""


# ── Define Text ───────────────────────────────────────────────────────


class DefineTextRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000, description="Text to define")


class DefineTextResponse(BaseModel):
    definition: str


# ── Voice (active/passive) ────────────────────────────────────────────


class VoiceChangeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000, description="Text to convert")
    voice: str = Field(description="Target voice: active or passive")


class VoiceChangeResponse(BaseModel):
    changed_text: str
    voice: str


# ── Rewrite for clarity ───────────────────────────────────────────────


class RewriteForClarityRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000, description="Text to rewrite for clarity")


class RewriteForClarityResponse(BaseModel):
    rewritten_text: str


# ── Generic registry tools (summarize, translate, …) ───────────────────


class GenericToolRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50000, description="Text to process")
    param: str | None = Field(
        default=None, description="Optional tool parameter (e.g. target language)"
    )


class GenericToolResponse(BaseModel):
    result: str
