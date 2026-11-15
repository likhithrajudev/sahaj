"""Identify the container of an uploaded recording from its first bytes.

Browsers record different formats: Chrome, Firefox and Android send WebM/Opus, while Safari on iPhone, iPad
and Mac sends MP4/AAC. The speech-to-text API needs a filename and content type that match the bytes, so we
detect the format instead of trusting the browser (the WebSocket carries no content type at all).
"""
from typing import Tuple

# (filename, content type) per detected container
WEBM = ("voice.webm", "audio/webm")
MP4 = ("voice.m4a", "audio/mp4")
OGG = ("voice.ogg", "audio/ogg")
WAV = ("voice.wav", "audio/wav")
MP3 = ("voice.mp3", "audio/mpeg")


def sniff(audio: bytes) -> Tuple[str, str]:
    """(filename, content type) for a recording. Falls back to WebM, the most common browser format."""
    head = audio[:12]
    if head[:4] == b"\x1a\x45\xdf\xa3":                 # EBML header: WebM / Matroska
        return WEBM
    if head[4:8] == b"ftyp":                            # ISO base media: MP4 / M4A (Safari)
        return MP4
    if head[:4] == b"OggS":
        return OGG
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return WAV
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return MP3
    return WEBM
