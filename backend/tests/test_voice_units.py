"""Voice building blocks that need no database and no model."""
from __future__ import annotations

import uuid

import numpy as np
import pytest

from app.voice.audio import AudioValidationError, sniff_audio_container, validate_upload
from app.voice.storage import StorageError, VoiceStorageService, write_atomic
from app.voice.workers import _frames
from app.voice.workers._streaming import ContextBuffer, Sola, SpeechGate, from_pcm16, to_pcm16
from app.voice.workers._text import chunk_text, max_speech_seconds, reconcile_transcript


def test_chunking_keeps_every_word_and_respects_limit():
    text = ("First sentence here. Second one follows! Third asks why? " * 30).strip() + "\n\nA new paragraph."
    chunks = chunk_text(text, limit=120)
    assert all(len(c.text) <= 120 for c in chunks)
    assert " ".join(c.text for c in chunks).split() == text.split()


def test_chunking_marks_paragraph_pause_but_not_the_end():
    chunks = chunk_text("One sentence.\n\nAnother paragraph.")
    assert [c.pause for c in chunks] == ["paragraph", "none"]


def test_chunking_breaks_oversized_sentence_without_losing_words():
    text = ", ".join(f"clause number {i}" for i in range(100))
    chunks = chunk_text(text, limit=80)
    assert all(len(c.text) <= 80 for c in chunks)
    assert " ".join(c.text for c in chunks).split() == text.split()


def test_chunking_handles_a_single_unbroken_token():
    assert all(len(c.text) <= 50 for c in chunk_text("x" * 500, limit=50))


def test_chunking_splits_chinese_punctuation():
    assert len(chunk_text("第一句话。第二句话！第三句话？", limit=6)) == 3


def test_chunking_empty_text():
    assert chunk_text("  \n\n  ") == []


@pytest.mark.parametrize("head,expected", [
    (b"RIFF\x00\x00\x00\x00WAVEfmt ", "wav"),
    (b"fLaC\x00\x00", "flac"),
    (b"OggS\x00\x00", "ogg"),
    (b"\x1a\x45\xdf\xa3\x00", "webm"),
    (b"ID3\x04\x00", "mp3"),
    (b"\xff\xfb\x90\x00", "mp3"),
    (b"\xff\xf1\x50\x80", "aac"),
    (b"\x00\x00\x00\x20ftypM4A ", "m4a"),
])
def test_sniff_accepts_real_audio(head, expected):
    assert sniff_audio_container(head) == expected


@pytest.mark.parametrize("head", [b"<?php echo 1;", b"MZ\x90\x00", b"\x7fELF", b"%PDF-1.7", b""])
def test_sniff_rejects_other_files(head):
    assert sniff_audio_container(head) is None


def test_validate_rejects_disguised_file_and_bad_extension():
    with pytest.raises(AudioValidationError):
        validate_upload("voice.wav", b"\x7fELF\x02\x01")
    with pytest.raises(AudioValidationError):
        validate_upload("voice.exe", b"RIFF\x00\x00\x00\x00WAVE")


def test_frames_round_trip():
    import io

    stream = io.BytesIO(_frames.encode({"id": 7, "op": "push"}, b"\x01\x02") + _frames.encode({"id": 8}))
    assert _frames.read_blocking(stream) == ({"id": 7, "op": "push"}, b"\x01\x02")
    assert _frames.read_blocking(stream) == ({"id": 8}, b"")
    assert _frames.read_blocking(stream) is None


def test_frames_reject_absurd_lengths():
    with pytest.raises(_frames.FrameError):
        _frames.parse_prefix((2**31).to_bytes(4, "big") + (0).to_bytes(4, "big"))


def test_storage_refuses_escape_and_overwrite(tmp_path):
    storage = VoiceStorageService(tmp_path)
    (tmp_path / "users").mkdir()
    with pytest.raises(StorageError):
        storage.resolve("../../etc/passwd")
    target = tmp_path / "a.wav"
    write_atomic(target, b"one")
    with pytest.raises(StorageError):
        write_atomic(target, b"two")
    assert target.read_bytes() == b"one"


def test_storage_delete_tree_only_touches_that_profile(tmp_path):
    storage = VoiceStorageService(tmp_path)
    user, keep, drop = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    (storage.profile_dir(user, keep) / "k.wav").write_bytes(b"k")
    (storage.profile_dir(user, drop) / "d.wav").write_bytes(b"d")
    storage.delete_profile_tree(user, drop)
    assert not storage.profile_dir(user, drop).joinpath("d.wav").exists()
    assert storage.profile_dir(user, keep).joinpath("k.wav").exists()
    with pytest.raises(ValueError):
        storage.delete_profile_tree(user, "../..")  # type: ignore[arg-type]


def test_context_buffer_keeps_newest_samples():
    buffer = ContextBuffer(4)
    buffer.push(np.array([1, 2, 3], dtype=np.float32))
    assert buffer.push(np.array([4, 5], dtype=np.float32)).tolist() == [2, 3, 4, 5]
    assert buffer.push(np.arange(10, 20, dtype=np.float32)).tolist() == [16, 17, 18, 19]


def _max_jump(audio: np.ndarray) -> float:
    return float(np.max(np.abs(np.diff(audio))))


def test_sola_hides_the_seam_between_misaligned_blocks():
    rate, block, fade, search = 22050, 3969, 882, 264
    t = np.arange(rate * 2) / rate
    tone = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sola = Sola(block, fade, search)
    out, position = [], 0
    for i in range(6):
        # Each "inference" starts at a phase unrelated to where the last block ended.
        start = position + (i * 37) % 100
        out.append(sola.process(tone[start: start + sola.required]))
        position += block
    joined = np.concatenate(out[1:])
    naive = np.concatenate([tone[(i * 37) % 100 + i * block: (i * 37) % 100 + (i + 1) * block] for i in range(1, 6)])
    assert len(out[0]) == block
    assert _max_jump(joined) < _max_jump(naive) / 2
    assert _max_jump(joined) < 0.1


def test_sola_fades_out_without_a_click():
    sola = Sola(1000, 200, 50)
    sola.process(np.full(1250, 0.5, dtype=np.float32))
    out = sola.fade_to_silence()
    assert out[0] == pytest.approx(0.5, abs=0.01)
    assert out[199] == pytest.approx(0, abs=0.01)
    assert not sola.has_tail


def test_speech_gate_holds_through_short_pauses_then_closes():
    gate = SpeechGate(hangover_blocks=2)
    assert gate.update(True)
    assert gate.update(False) and gate.update(False)
    assert not gate.update(False)


def test_pcm_round_trip_and_clipping():
    audio = np.array([0.0, 0.5, -0.5, 2.0, -2.0], dtype=np.float32)
    decoded = from_pcm16(to_pcm16(audio))
    assert decoded[:3] == pytest.approx([0.0, 0.5, -0.5], abs=1e-3)
    assert abs(decoded[3]) <= 1 and abs(decoded[4]) <= 1


def test_block_size_follows_measured_speed():
    from app.voice.realtime import block_for_speed

    assert block_for_speed(0.1, 0.38) == 0.5  # fast machine: the minimum long block
    assert block_for_speed(0.75, 0.38) == pytest.approx(1.9)
    assert block_for_speed(0.9, 0.38) is None  # can never keep up, whatever the block
    assert block_for_speed(1.4, 0.38) is None


def test_block_chosen_really_keeps_up():
    from app.voice.realtime import block_for_speed

    for cost in (0.2, 0.5, 0.75, 0.85):
        block = block_for_speed(cost, 0.38)
        assert cost * (block + 0.38) <= 0.9 * block + 1e-9


def test_performance_cpus_are_real_cpu_ids():
    import os

    from app.voice.manager import performance_cpus

    assert set(performance_cpus()) <= os.sched_getaffinity(0) | set(range(os.cpu_count() or 1))


def test_transcript_is_cut_to_what_the_audio_says():
    given = "Hello, how are you today? I hope you are well. Life is full of surprises and we keep moving."
    heard = "hello how are you today i hope you are well"
    assert reconcile_transcript(given, heard) == "Hello, how are you today? I hope you are well."


def test_exact_transcript_keeps_the_operators_wording():
    given = "Dr. Rivera said: it's fine, really."
    assert reconcile_transcript(given, "doctor rivera said it's fine really") == given


def test_transcript_of_other_audio_is_replaced():
    assert reconcile_transcript("Completely unrelated words here today", "the cat sat on the mat") == "the cat sat on the mat"


def test_missing_transcript_uses_what_was_heard():
    assert reconcile_transcript("", "spoken words") == "spoken words"


def test_speech_limit_allows_natural_reading_but_stops_runaways():
    text = "x" * 300
    assert 20 < max_speech_seconds(text) < 120  # 300 characters is about 20 seconds aloud
    assert max_speech_seconds("hi") == 6.0
    assert max_speech_seconds("你好" * 50) >= 25
