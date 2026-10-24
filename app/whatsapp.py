"""Cliente mínimo de WhatsApp Cloud API: enviar texto, enviar plantilla, descargar audios."""
import hashlib
import hmac
import logging

import httpx

from .config import settings

log = logging.getLogger("whatsapp")


def _base() -> str:
    return f"https://graph.facebook.com/{settings.GRAPH_VERSION}"


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.WA_TOKEN}"}


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Valida que el POST venga realmente de Meta. Si no configuraste WA_APP_SECRET, se omite."""
    if not settings.WA_APP_SECRET:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(settings.WA_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


async def send_text(to: str, text: str) -> None:
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text[:4000]},
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{_base()}/{settings.WA_PHONE_NUMBER_ID}/messages", headers=_headers(), json=payload)
    if r.status_code >= 400:
        log.error("Error enviando texto: %s %s", r.status_code, r.text)


async def send_template(to: str, params: list[str]) -> bool:
    """Las plantillas son obligatorias para escribir a alguien que no te habló en las últimas 24 h."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": settings.REMINDER_TEMPLATE,
            "language": {"code": settings.REMINDER_TEMPLATE_LANG},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}
            ],
        },
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{_base()}/{settings.WA_PHONE_NUMBER_ID}/messages", headers=_headers(), json=payload)
    if r.status_code >= 400:
        log.error("Error enviando plantilla: %s %s", r.status_code, r.text)
        return False
    return True


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Devuelve (bytes, mime_type) de un audio/nota de voz."""
    async with httpx.AsyncClient(timeout=60) as c:
        meta = await c.get(f"{_base()}/{media_id}", headers=_headers())
        meta.raise_for_status()
        info = meta.json()
        data = await c.get(info["url"], headers=_headers())
        data.raise_for_status()
    return data.content, info.get("mime_type", "audio/ogg")
