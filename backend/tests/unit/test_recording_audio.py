"""Unit tests for the voice-capture audio conditioning (mic pickup quality)."""

import numpy as np
import pytest

from app.services.recording_service import _condition_audio, _MAX_GAIN


def _sine(seconds: float, rate: int, freq: float, peak: float) -> np.ndarray:
    t = np.arange(int(seconds * rate), dtype=np.float32) / rate
    return (peak * np.sin(2 * np.pi * freq * t)).astype(np.float32)[:, None]


def _voice_like(seconds: float, rate: int, freq: float, peak: float) -> np.ndarray:
    """A tone with a speech-like 2 Hz amplitude envelope.

    The noise gate estimates the floor from the quietest frames, so tests
    must exercise it with *time-varying* energy like real speech — a fully
    stationary tone is by construction indistinguishable from stationary
    noise and is legitimately attenuated.
    """
    t = np.arange(int(seconds * rate), dtype=np.float32) / rate
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 2.0 * t)
    return (peak * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)[:, None]


def _rms(a: np.ndarray) -> float:
    return float(np.sqrt(np.mean(a.astype(np.float64) ** 2)))


def test_quiet_capture_is_brought_up_to_speech_level() -> None:
    """A quiet mic (peak 0.02) is amplified (gain-capped), not left quiet."""
    quiet = _voice_like(4.0, 44100, 220.0, 0.02)
    out = _condition_audio(quiet, 44100)
    # Gain caps at _MAX_GAIN, so RMS lands at rms_in * _MAX_GAIN.
    assert _rms(out) == pytest.approx(_rms(quiet) * _MAX_GAIN, rel=0.3)
    assert float(np.max(np.abs(out))) <= 1.0
    assert float(np.max(np.abs(out))) > float(np.max(np.abs(quiet)))


def test_gain_is_capped_so_noise_floor_stays_noise() -> None:
    """Near-silence must not be amplified by more than _MAX_GAIN."""
    noise = (np.random.default_rng(7).standard_normal(44100) * 1e-4).astype(np.float32)[
        :, None
    ]
    out = _condition_audio(noise, 44100)
    assert _rms(out) / max(_rms(noise), 1e-12) <= _MAX_GAIN + 0.1


def test_loud_capture_is_unchanged() -> None:
    """A healthy signal gets no gain (and no pumping) — peak stays ≤ 1."""
    loud = _voice_like(4.0, 44100, 220.0, 0.5)
    out = _condition_audio(loud, 44100)
    assert float(np.max(np.abs(out))) <= 1.0
    assert _rms(out) == pytest.approx(_rms(loud), rel=0.25)


def test_silence_stays_silence() -> None:
    """Digital zero must not explode (division guards) — stays ~zero."""
    silence = np.zeros((44100, 1), dtype=np.float32)
    out = _condition_audio(silence, 44100)
    assert float(np.max(np.abs(out))) < 1e-9


def test_highpass_removes_dc_and_rumble() -> None:
    """A DC offset + 40Hz rumble under the cutoff is filtered out."""
    voice = _sine(1.0, 44100, 220.0, 0.3)
    rumble = _sine(1.0, 44100, 40.0, 0.3)
    dirty = voice + rumble + 0.2
    out = _condition_audio(dirty, 44100)
    # The clean voice component is ~0.21 RMS; rumble+DC (~0.35 RMS) is mostly gone.
    assert _rms(out) < _rms(dirty)
    assert abs(float(np.mean(out))) < 0.02


def test_spectral_gate_removes_hiss_but_keeps_tone() -> None:
    """Broadband hiss under a voice-like tone is attenuated; the tone survives."""
    from app.services.recording_service import _spectral_gate

    rng = np.random.default_rng(11)
    tone = _voice_like(4.0, 44100, 220.0, 0.2)
    hiss = (rng.standard_normal(tone.shape[0]) * 0.02).astype(np.float32)[:, None]
    noisy = tone + hiss
    out = _spectral_gate(noisy, 44100)
    # Hiss alone is strongly attenuated (stationary noise → floor −20 dB),
    # and the tone's spectral peak survives the gate.
    gated_hiss = _spectral_gate(hiss, 44100)
    assert _rms(gated_hiss) < 0.5 * _rms(hiss)
    bin_hz = 44100 / 2048
    peak_bin = round(220.0 / bin_hz)
    spec_in = np.abs(np.fft.rfft(tone[:, 0]))
    spec_out = np.abs(np.fft.rfft(out[:, 0]))
    assert spec_out[peak_bin] > 0.5 * spec_in[peak_bin]


def test_spectral_gate_passes_short_captures_through() -> None:
    """Too-short audio has no stable noise profile — returned unchanged."""
    from app.services.recording_service import _spectral_gate

    short = _sine(0.2, 44100, 220.0, 0.3)
    out = _spectral_gate(short, 44100)
    assert out.shape == short.shape
    np.testing.assert_allclose(out, short, atol=1e-6)


def test_conditioned_audio_encodes_to_valid_ogg() -> None:
    """End-to-end: conditioned frames encode to a decodable Ogg/Vorbis payload."""
    import io

    import soundfile as sf

    from app.services.recording_service import _frames_to_ogg

    frames = [_voice_like(4.0, 44100, 220.0, 0.02)]
    ogg = _frames_to_ogg(frames, 44100)
    assert len(ogg) > 200
    audio, rate = sf.read(io.BytesIO(ogg))
    assert rate == 44100
    # Gain is capped at _MAX_GAIN for this very quiet input.
    assert _rms(np.asarray(audio, dtype=np.float32)[:, None]) == pytest.approx(
        _rms(frames[0]) * _MAX_GAIN, rel=0.3
    )
