# ADR-006: Whisper for Local Voice Transcription

## Status: Accepted

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
