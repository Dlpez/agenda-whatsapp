"""Recordatorios por WhatsApp. Un servicio externo (cron-job.org, gratis) llama a /cron/recordatorios
cada 5 minutos; así funciona aunque el servidor gratuito se duerma o se reinicie."""
import logging
from datetime import datetime, timedelta

from . import calendar_client as cal
from . import whatsapp as wa
from .agent import fecha_humana
from .config import settings

log = logging.getLogger("reminders")


async def run_reminders() -> int:
    now = cal.now_local()
    hasta = now + timedelta(minutes=settings.REMINDER_MINUTES + 1)
    events = cal.list_events(cal.to_rfc3339(now), cal.to_rfc3339(hasta), solo_bot=True)
    sent = 0
    for e in events:
        priv = e.get("extendedProperties", {}).get("private", {})
        start = e["start"].get("dateTime")
        if not start or priv.get("waRecordado") == "1":
            continue
        if datetime.fromisoformat(start) - now > timedelta(minutes=settings.REMINDER_MINUTES):
            continue
        params = [e.get("summary", "Reunión"), fecha_humana(start)]
        destinos = [settings.OWNER_WHATSAPP]
        if settings.REMIND_INVITEES:
            destinos += [p for p in priv.get("waTelefonos", "").split(",") if p]
        ok = False
        for to in destinos:
            ok = await wa.send_template(to, params) or ok
        if ok:
            cal.mark_reminded(e["id"])
            sent += 1
    return sent
