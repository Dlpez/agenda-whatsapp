"""Servidor web: recibe los mensajes de WhatsApp (webhook) y el pulso de recordatorios."""
import logging
from collections import deque

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from . import whatsapp as wa
from .agent import handle_message
from .config import settings
from .reminders import run_reminders
from .transcribe import transcribe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

app = FastAPI(title="Agenda por WhatsApp")
_seen: deque[str] = deque(maxlen=500)  # Meta a veces reenvía el mismo mensaje


@app.get("/")
async def health():
    return {"ok": True}


@app.get("/webhook")
async def verify(request: Request):
    """Meta llama esto una vez al configurar el webhook."""
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.WA_VERIFY_TOKEN:
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "token de verificación incorrecto")


@app.post("/webhook")
async def receive(request: Request, bg: BackgroundTasks):
    body = await request.body()
    if not wa.verify_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(401, "firma inválida")
    data = await request.json()
    for entry in data.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []) or []:
                if msg.get("id") in _seen:
                    continue
                _seen.append(msg.get("id"))
                bg.add_task(process, msg)
    return {"ok": True}  # responder rápido para que Meta no reintente


async def process(msg: dict) -> None:
    sender = msg.get("from", "")
    if settings.OWNER_WHATSAPP and sender != settings.OWNER_WHATSAPP:
        log.warning("Mensaje ignorado de número no autorizado: %s", sender)
        return
    try:
        mtype = msg.get("type")
        if mtype == "text":
            text = msg["text"]["body"]
        elif mtype == "audio":
            audio, mime = await wa.download_media(msg["audio"]["id"])
            text = await transcribe(audio, mime)
            if not text:
                await wa.send_text(sender, "No logré entender el audio 🙉 ¿Me lo mandas de nuevo o por escrito?")
                return
            await wa.send_text(sender, f"🎙️ Entendí: _{text}_")
        else:
            await wa.send_text(sender, "Por ahora entiendo texto y notas de voz 🙂")
            return
        reply = await handle_message(sender, text)
        await wa.send_text(sender, reply)
    except Exception:  # noqa: BLE001
        log.exception("Error procesando mensaje")
        await wa.send_text(sender, "⚠️ Tuve un error procesando eso. Intenta de nuevo en un rato.")


@app.api_route("/cron/recordatorios", methods=["GET", "POST"])
async def cron(key: str = ""):
    if not settings.CRON_SECRET or key != settings.CRON_SECRET:
        raise HTTPException(403, "clave incorrecta")
    n = await run_reminders()
    return {"enviados": n}
