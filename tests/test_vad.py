import numpy as np
import pytest

from clawsona.vad import CHUNK_SIZE, VADDetector


@pytest.fixture
def session(mocker):
    return mocker.patch("faster_whisper.vad.get_vad_model").return_value.session


def probabilities(session, values):
    session.run.side_effect = [
        (np.array([[p]], dtype=np.float32), np.ones((1, 1, 128)), np.ones((1, 1, 128)))
        for p in values
    ]


def test_real_silero_accepts_silence():
    detector = VADDetector()
    assert all(
        detector.process_chunk(np.zeros(CHUNK_SIZE, dtype=np.int16)) is None
        for _ in range(100)
    )


@pytest.mark.parametrize("kind", ["quiet_noise", "loud_noise", "hum", "clicks"])
def test_real_silero_rejects_synthetic_background_noise(kind):
    rng = np.random.default_rng(7)
    t = np.arange(32000) / 16000
    if kind == "hum":
        audio = 0.10 * np.sin(2 * np.pi * 180 * t) + rng.normal(0, 0.005, t.size)
    elif kind == "clicks":
        audio = np.zeros(t.size)
        for start in range(0, len(audio) - 100, 3500):
            audio[start : start + 100] = rng.normal(0, 0.25, 100)
    else:
        audio = rng.normal(0, 0.15 if kind == "loud_noise" else 0.005, t.size)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    detector = VADDetector()
    assert all(
        detector.process_chunk(pcm[offset : offset + CHUNK_SIZE]) is None
        for offset in range(0, len(pcm) - CHUNK_SIZE + 1, CHUNK_SIZE)
    )


def test_speech_start_debounce_and_audio_time_silence(session):
    probabilities(session, [0.9] * 3 + [0.1] * 3)
    detector = VADDetector(silence_duration_ms=90, min_speech_ms=90)
    chunk = np.zeros(CHUNK_SIZE, dtype=np.int16)
    assert [detector.process_chunk(chunk) for _ in range(6)] == [
        None,
        None,
        "speech_start",
        None,
        None,
        "speech_end",
    ]


def test_short_noise_does_not_start_speech(session):
    probabilities(session, [0.9, 0.1] * 8)
    detector = VADDetector(min_speech_ms=90)
    assert all(
        detector.process_chunk(np.zeros(CHUNK_SIZE, dtype=np.int16)) is None
        for _ in range(16)
    )


@pytest.mark.parametrize("pause_frames", [25, 40, 50])
def test_thinking_pause_does_not_end_turn_and_continuation_resets_timer(
    session, pause_frames
):
    # A language learner can pause for 0.8–1.6 seconds between two phrases.
    ending_frames = 57  # 1824 ms, the first 32 ms frame past the 1800 ms limit.
    values = [0.9] * 6 + [0.1] * pause_frames + [0.5] * 6 + [0.1] * ending_frames
    probabilities(session, values)
    detector = VADDetector()
    chunk = np.zeros(CHUNK_SIZE, dtype=np.int16)
    events = [detector.process_chunk(chunk) for _ in values]
    assert events.count("speech_start") == 1
    assert events.count("speech_end") == 1
    assert events[-1] == "speech_end"
    assert detector.last_end_silence_ms == ending_frames * 32
    detector.reset()
    assert detector.last_end_silence_ms == 0


def test_hysteresis_keeps_quieter_speech_until_real_pause(session):
    probabilities(session, [0.9, 0.5, 0.5, 0.1])
    detector = VADDetector(min_speech_ms=32, silence_duration_ms=32, threshold=0.6)
    chunk = np.zeros(CHUNK_SIZE, dtype=np.int16)
    assert [detector.process_chunk(chunk) for _ in range(4)] == [
        "speech_start",
        None,
        None,
        "speech_end",
    ]


def test_low_threshold_can_still_end_speech(session):
    probabilities(session, [0.9, 0.001])
    detector = VADDetector(min_speech_ms=32, silence_duration_ms=32, threshold=0.1)
    chunk = np.zeros(CHUNK_SIZE, dtype=np.int16)
    assert detector.process_chunk(chunk) == "speech_start"
    assert detector.process_chunk(chunk) == "speech_end"


def test_recurrent_state_and_audio_context_survive_frames_and_reset(session):
    probabilities(session, [0.9] * 3)
    detector = VADDetector(min_speech_ms=32)
    chunk = np.full(CHUNK_SIZE, 16384, dtype=np.int16)
    assert detector.process_chunk(chunk) == "speech_start"
    detector.process_chunk(chunk)
    second_input = session.run.call_args.args[1]
    np.testing.assert_allclose(second_input["input"][:, :64], 0.5)
    np.testing.assert_allclose(second_input["h"], 1)
    np.testing.assert_allclose(second_input["c"], 1)
    detector.reset()
    assert detector.last_probability == 0
    assert detector.process_chunk(chunk) == "speech_start"
    reset_input = session.run.call_args.args[1]
    np.testing.assert_allclose(reset_input["input"][:, :64], 0)
    np.testing.assert_allclose(reset_input["h"], 0)
    np.testing.assert_allclose(reset_input["c"], 0)


def test_incompatible_frame_fails_early():
    with pytest.raises(ValueError, match="512"):
        VADDetector().process_chunk(np.zeros(480, dtype=np.int16))
