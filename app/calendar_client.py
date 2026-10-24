"""Acceso a Google Calendar con las credenciales OAuth de tu cuenta."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_service = None


def _svc():
    global _service
    if _service is None:
        info = json.loads(settings.GOOGLE_TOKEN_JSON)
        creds = Credentials.from_authorized_user_info(info, SCOPES)
        _service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return _service


def create_event(ev: dict) -> dict:
    """ev: titulo, inicio, fin, invitados[{email, whatsapp?}], descripcion?, ubicacion?, videollamada?"""
    tz = settings.TIMEZONE
    phones = [i["whatsapp"] for i in ev.get("invitados", []) if i.get("whatsapp")]
    body = {
        "summary": ev["titulo"],
        "description": ev.get("descripcion") or "Agendado por WhatsApp",
        "start": {"dateTime": ev["inicio"], "timeZone": tz},
        "end": {"dateTime": ev["fin"], "timeZone": tz},
        "attendees": [{"email": i["email"]} for i in ev.get("invitados", []) if i.get("email")],
        # Recordatorios de Google (a ti; cada invitado usa los suyos por defecto)
        "reminders": {"useDefault": False, "overrides": [
            {"method": "popup", "minutes": 30},
            {"method": "email", "minutes": 24 * 60},
        ]},
        "extendedProperties": {"private": {
            "creadoPorBot": "1",
            "waTelefonos": ",".join(phones),
        }},
    }
    if ev.get("ubicacion"):
        body["location"] = ev["ubicacion"]
    kwargs = {}
    if ev.get("videollamada"):
        body["conferenceData"] = {"createRequest": {
            "requestId": f"bot-{datetime.now().timestamp()}",
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
        }}
        kwargs["conferenceDataVersion"] = 1
    # sendUpdates="all" => Google envía la invitación por correo a cada invitado
    return _svc().events().insert(
        calendarId=settings.CALENDAR_ID, body=body, sendUpdates="all", **kwargs
    ).execute()


def list_events(desde: str, hasta: str, solo_bot: bool = False) -> list[dict]:
    kwargs = dict(
        calendarId=settings.CALENDAR_ID, timeMin=desde, timeMax=hasta,
        singleEvents=True, orderBy="startTime", maxResults=50,
    )
    if solo_bot:
        kwargs["privateExtendedProperty"] = "creadoPorBot=1"
    return _svc().events().list(**kwargs).execute().get("items", [])


def mark_reminded(event_id: str) -> None:
    _svc().events().patch(
        calendarId=settings.CALENDAR_ID, eventId=event_id,
        body={"extendedProperties": {"private": {"waRecordado": "1"}}},
    ).execute()


def now_local() -> datetime:
    return datetime.now(ZoneInfo(settings.TIMEZONE))


def to_rfc3339(d: datetime) -> str:
    return d.isoformat()


def window(days: int = 1) -> tuple[str, str]:
    n = now_local()
    return to_rfc3339(n), to_rfc3339(n + timedelta(days=days))
