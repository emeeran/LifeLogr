# ADR-006: Whisper for Local Voice Transcription

## Status: Retired (2026-10-24)

> **Retired (2026-10-24):** the local-transcription feature this ADR decided on is
> **gone from the product**, not merely deferred. Voice *recording* remains (entries
> can attach audio/video clips), but there is no speech-to-text anywhere in the app —
> no `whisper` dependency, no transcribe endpoint, no UI (see
> `docs/manual/USER_MANUAL.md` §7, which states transcription is unavailable).
> The decision is unmade rather than superseded by an alternative: Whisper's ~1 GB
> RAM footprint and ~140 MB first-run model download were unacceptable for a
> single-user, privacy-first desktop app, and no lighter offline engine was chosen
> to replace it. The `pyinstaller.spec` still mentions the name only in a comment.
> This ADR is kept as a historical record; do **not** implement from it without a
> fresh decision.

_History: previously marked "Superseded — removed in 0.7.1", when on-device
transcription was first dropped._

## Context

Voice recordings must be transcribed locally on-device (FR-018). Transcription is user-triggered (not automatic). Options:

- **OpenAI Whisper (local)** — open-source speech-to-text model, runs fully on-device
- **Cloud speech API** (Google, Azure, etc.) — requires network, costs money
- **Vosk** — lightweight offline speech recognition
- **SpeechRecognition library** — wrapper around various engines

## Decision

Use OpenAI Whisper (`whisper` Python package) for local transcription, running the `base` model for a balance of speed and accuracy.

## Consequences

- **Offline-first** — no network required (NFR-001).
- **No API costs** — runs entirely on local CPU/GPU.
- **Quality** — Whisper `base` model provides good accuracy for English and reasonable support for other languages.
- **Resource usage** — `base` model uses ~1 GB RAM and runs in seconds for typical voice memos (< 5 minutes). Acceptable on a desktop Linux machine.
- **First-run delay** — the model weights (~140 MB) are downloaded on first use. Subsequent runs are fully offline.
- **Format support** — Whisper accepts mp3 and mp4 natively, matching the specified audio formats.

## Alternatives Considered

| Alternative | Rejected because |
|-------------|-----------------|
| Cloud speech API | Requires network; violates offline-first; per-request cost |
| Vosk | Smaller model, lower accuracy; less maintained than Whisper |
| SpeechRecognition library | Wrapper with inconsistent engine support; adds dependency complexity |
