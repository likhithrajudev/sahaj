import httpx
from fastapi import APIRouter, HTTPException, UploadFile

from services.audio import sniff
from services.stt import transcribe_audio

router = APIRouter(prefix="/stt", tags=["Speech-to-Text"])

@router.post("")
async def speech_to_text(file: UploadFile):
    audio = await file.read()
    try:
        filename, content_type = sniff(audio)  # browsers often mislabel recordings; trust the bytes
        result = await transcribe_audio(audio, filename, content_type)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Sarvam API error: {e.response.text}")
    return {"text": result["transcript"], "language": result["language_code"]}
