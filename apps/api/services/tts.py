import base64
import json
from typing import Optional

import websockets
from config import SARVAM_API_KEY, SARVAM_BASE_URL

WS_URL = SARVAM_BASE_URL.replace("https", "wss", 1) + "/text-to-speech/ws?model={model}&send_completion_event=true"

# Languages with a native Bulbul voice: code -> (name, model, speaker).
# Malayalam and Odia have no v4 voices yet, so they use v3 (v3 uses short speaker names).
VOICES = {
    "en-IN": ("English", "bulbul:v4-flash", "simran_en_customer"),
    "hi-IN": ("Hindi", "bulbul:v4-flash", "aparna_hi_customer"),
    "bn-IN": ("Bengali", "bulbul:v4-flash", "roopa_bn_conversational"),
    "ta-IN": ("Tamil", "bulbul:v4-flash", "gokul_ta_narration"),  # no conversational Tamil voice yet
    "te-IN": ("Telugu", "bulbul:v4-flash", "kavitha_te_conversation"),
    "kn-IN": ("Kannada", "bulbul:v4-flash", "chaitra_kn_conversation"),
    "mr-IN": ("Marathi", "bulbul:v4-flash", "ishita_mr_conversational"),
    "gu-IN": ("Gujarati", "bulbul:v4-flash", "pooja_gu_customer"),
    "pa-IN": ("Punjabi", "bulbul:v4-flash", "anand_pa_customer"),
    "ml-IN": ("Malayalam", "bulbul:v3", "pooja"),
    "od-IN": ("Odia", "bulbul:v3", "ritu"),
}

# Languages Sarvam can transcribe but cannot speak yet (TTS needs beta access from
# Sarvam support). code -> (name, voice to borrow). A voice can only read text in its
# own script, so Devanagari languages borrow Hindi and Assamese borrows Bengali.
# None = no readable voice, so the reply is text only.
BORROWED = {
    "ne-IN": ("Nepali", "hi-IN"),
    "mai-IN": ("Maithili", "hi-IN"),
    "doi-IN": ("Dogri", "hi-IN"),
    "kok-IN": ("Konkani", "hi-IN"),
    "sa-IN": ("Sanskrit", "hi-IN"),
    "brx-IN": ("Bodo", "hi-IN"),
    "as-IN": ("Assamese", "bn-IN"),
    "ur-IN": ("Urdu", None),
    "ks-IN": ("Kashmiri", None),
    "sd-IN": ("Sindhi", None),
    "sat-IN": ("Santali", None),
    "mni-IN": ("Manipuri", None),
}

SUPPORTED_LANGUAGES = {**{code: value[0] for code, value in VOICES.items()},
                      **{code: value[0] for code, value in BORROWED.items()}}


def resolve_language(code) -> str:
    """The detected language if we support it, otherwise English."""
    return code if code in SUPPORTED_LANGUAGES else "en-IN"


def language_name(code: str) -> str:
    return SUPPORTED_LANGUAGES[resolve_language(code)]


def detect_script_language(text: str, preferred: str = "") -> Optional[str]:
    ranges = (
        (0x0900, 0x097F, ("hi-IN", "mr-IN", "ne-IN", "mai-IN", "doi-IN", "kok-IN", "sa-IN", "brx-IN")),
        (0x0980, 0x09FF, ("bn-IN", "as-IN")),
        (0x0A00, 0x0A7F, ("pa-IN",)),
        (0x0A80, 0x0AFF, ("gu-IN",)),
        (0x0B00, 0x0B7F, ("od-IN",)),
        (0x0B80, 0x0BFF, ("ta-IN",)),
        (0x0C00, 0x0C7F, ("te-IN",)),
        (0x0C80, 0x0CFF, ("kn-IN",)),
        (0x0D00, 0x0D7F, ("ml-IN",)),
        (0x1C50, 0x1C7F, ("sat-IN",)),
        (0xABC0, 0xABFF, ("mni-IN",)),
        (0x0600, 0x06FF, ("ur-IN", "ks-IN", "sd-IN")),
    )
    counts = {codes[0]: 0 for _, _, codes in ranges}
    for char in text:
        point = ord(char)
        for start, end, codes in ranges:
            if start <= point <= end:
                counts[codes[0]] += 1
                break
    if not any(counts.values()):
        return None
    dominant = max(counts, key=counts.get)
    return preferred if preferred in next(codes for _, _, codes in ranges if codes[0] == dominant) else dominant


def resolve_text_language(requested: Optional[str], profile: str, text: str) -> str:
    requested = resolve_language(requested) if requested else ""
    profile = resolve_language(profile)
    preferred = requested if requested and requested != "en-IN" else profile
    detected = detect_script_language(text, preferred=preferred)
    if detected:
        return detected
    if requested and requested != "en-IN":
        return requested
    return profile if requested == "en-IN" and profile != "en-IN" else requested or profile


async def speak(text: str, language_code: str):
    """Yield mp3 audio chunks for `text`. Yields nothing if the language has no readable voice."""
    code = resolve_language(language_code)
    if code in BORROWED:
        code = BORROWED[code][1]
        if code is None:
            return
    _, model, speaker = VOICES[code]

    config = {"speaker": speaker, "language_code": code, "output_audio_codec": "mp3"}
    headers = {"Api-Subscription-Key": SARVAM_API_KEY}

    async with websockets.connect(WS_URL.format(model=model), additional_headers=headers) as ws:
        await ws.send(json.dumps({"type": "config", "data": config}))
        await ws.send(json.dumps({"type": "text", "data": {"text": text}}))
        await ws.send(json.dumps({"type": "flush"}))

        async for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "audio":
                yield base64.b64decode(msg["data"]["audio"])
            elif msg["type"] == "error":
                raise RuntimeError(msg["data"]["message"])
            elif msg["type"] == "event":  # "final" = Sarvam is done
                break
