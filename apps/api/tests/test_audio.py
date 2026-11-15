import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.audio import MP3, MP4, OGG, WAV, WEBM, sniff


def test_safari_mp4_recording():
    # MediaRecorder on iOS Safari: ISO base media with an M4A brand
    assert sniff(b"\x00\x00\x00\x1cftypM4A \x00\x00\x00\x00") == MP4
    assert sniff(b"\x00\x00\x00\x18ftypiso5\x00\x00\x02\x00") == MP4


def test_chrome_webm_recording():
    assert sniff(b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01") == WEBM


def test_other_formats():
    assert sniff(b"OggS\x00\x02" + b"\x00" * 10) == OGG
    assert sniff(b"RIFF\x24\x08\x00\x00WAVEfmt ") == WAV
    assert sniff(b"ID3\x04\x00\x00\x00\x00\x00\x00") == MP3


def test_unknown_falls_back_to_webm():
    assert sniff(b"") == WEBM
    assert sniff(b"garbage bytes") == WEBM
