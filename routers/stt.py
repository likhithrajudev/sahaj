import httpx
from fastapi import APIRouter, HTTPException, UploadFile

from services.stt import transcribe_audio

router = APIRouter(prefix="/stt", tags=["Speech-to-Text"])

@router.post("")
async def speech_to_text(file: UploadFile):
    audio = await file.read()
    try:
        result = await transcribe_audio(audio, file.filename, file.content_type)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Sarvam API error: {e.response.text}")
    return {"text": result["transcript"], "language": result["language_code"]}
