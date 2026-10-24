"""Transcribe notas de voz con una API compatible con OpenAI (por defecto Groq, que tiene plan gratuito)."""
import httpx

from .config import settings


async def transcribe(audio: bytes, mime: str) -> str:
    ext = "ogg" if "ogg" in mime else mime.split("/")[-1].split(";")[0] or "ogg"
    files = {"file": (f"nota.{ext}", audio, mime.split(";")[0])}
    data = {"model": settings.TRANSCRIBE_MODEL, "language": "es", "response_format": "json"}
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            f"{settings.TRANSCRIBE_BASE_URL}/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.TRANSCRIBE_API_KEY}"},
            data=data,
            files=files,
        )
    r.raise_for_status()
    return r.json().get("text", "").strip()
