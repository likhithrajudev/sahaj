import httpx
from config import SARVAM_API_KEY, SARVAM_BASE_URL

async def transcribe_audio(audio: bytes, filename: str, content_type: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{SARVAM_BASE_URL}/speech-to-text",
            headers={"api-subscription-key": SARVAM_API_KEY},
            files={"file": (filename, audio, content_type)},
            data={
                "model": "saaras:v4",
                "mode": "transcribe",
                "language_code": "unknown",
            },
        )

    r.raise_for_status()
    return r.json()