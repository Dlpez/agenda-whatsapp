"""El 'cerebro': Claude interpreta tus mensajes, consulta la agenda y propone eventos.
Nada se crea sin que confirmes con un "sí"."""
import json
import logging
import time
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from anthropic import AsyncAnthropic

from . import calendar_client as cal
from .config import load_contacts, settings

log = logging.getLogger("agent")
_client: AsyncAnthropic | None = None

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

SESSION_TTL = 30 * 60  # la conversación se olvida tras 30 min sin mensajes
MAX_HISTORY = 12

# estado por número: {"history": [...], "pending": dict|None, "ts": float}
sessions: dict[str, dict] = {}

TOOLS = [
    {
        "name": "proponer_evento",
        "description": "Propone una reunión/evento para que el usuario la confirme. Úsalo solo cuando "
                       "tengas título, fecha, hora de inicio y el correo de cada invitado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string"},
                "inicio": {"type": "string", "description": "ISO 8601 con offset, ej 2026-10-28T15:00:00-03:00"},
                "fin": {"type": "string", "description": "ISO 8601 con offset"},
                "invitados": {"type": "array", "items": {"type": "object", "properties": {
                    "nombre": {"type": "string"},
                    "email": {"type": "string"},
                    "whatsapp": {"type": "string", "description": "Solo si está en la agenda de contactos"},
                }, "required": ["email"]}},
                "descripcion": {"type": "string"},
                "ubicacion": {"type": "string"},
                "videollamada": {"type": "boolean", "description": "true si pide Meet/videollamada/online"},
            },
            "required": ["titulo", "inicio", "fin", "invitados"],
        },
    },
    {
        "name": "consultar_agenda",
        "description": "Lista los eventos del calendario entre dos fechas. Úsalo si pregunta qué tiene "
                       "agendado o para revisar choques de horario antes de proponer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "desde": {"type": "string", "description": "ISO 8601 con offset"},
                "hasta": {"type": "string", "description": "ISO 8601 con offset"},
            },
            "required": ["desde", "hasta"],
        },
    },
]


def _claude() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    return _client


def fecha_humana(iso: str) -> str:
    d = datetime.fromisoformat(iso).astimezone(ZoneInfo(settings.TIMEZONE))
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}, {d:%H:%M}"


def _system_prompt() -> str:
    n = cal.now_local()
    contactos = load_contacts()
    return f"""Eres un asistente de agenda que funciona por WhatsApp para un usuario en Chile.
Ahora es {DIAS[n.weekday()]} {n.day} de {MESES[n.month - 1]} de {n.year}, {n:%H:%M} (zona {settings.TIMEZONE}, offset {n:%z}).

Tu trabajo: entender pedidos como "agéndame una reunión el martes a las 3 con Juan" y llamar a proponer_evento.
Reglas:
- Interpreta fechas relativas ("mañana", "el martes", "la próxima semana") desde la fecha de hoy. "El martes" = el próximo martes.
- Horas sin am/pm: entre 1 y 7 asume tarde (15:00), 8 a 12 asume mañana, salvo que el contexto diga otra cosa.
- Si no dan duración, usa {settings.DEFAULT_DURATION_MIN} minutos.
- Los invitados se buscan en la agenda de contactos (abajo). Si el nombre no está o es ambiguo, pide el correo. Nunca inventes correos.
- Si dan un correo directamente, úsalo tal cual.
- Si falta algo esencial (día u hora), pregunta solo eso, en una línea.
- Título breve y claro, ej: "Reunión con Juan".
- Respuestas cortas, estilo WhatsApp, en español de Chile, sin markdown (puedes usar *negritas* de WhatsApp).
- No digas que el evento ya está creado: tú solo lo propones; el sistema pide la confirmación.

Agenda de contactos (JSON):
{json.dumps(contactos, ensure_ascii=False)}"""


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower().strip())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return "".join(c for c in t if c.isalnum() or c.isspace()).strip()


SI = {"si", "s", "ok", "okay", "dale", "confirmo", "confirmar", "listo", "ya", "perfecto",
      "agendalo", "agendala", "hazlo", "de una", "si dale", "si porfa", "si por favor", "sip", "yes"}
NO = {"no", "cancela", "cancelar", "nop", "olvidalo", "mejor no", "no gracias"}


def _resumen(ev: dict) -> str:
    ini = datetime.fromisoformat(ev["inicio"]).astimezone(ZoneInfo(settings.TIMEZONE))
    fin = datetime.fromisoformat(ev["fin"]).astimezone(ZoneInfo(settings.TIMEZONE))
    inv = ", ".join(f"{i.get('nombre') or ''} <{i['email']}>".strip() for i in ev["invitados"]) or "sin invitados"
    lineas = [
        f"📅 *{ev['titulo']}*",
        f"🕒 {fecha_humana(ev['inicio'])} – {fin:%H:%M}" if ini.date() == fin.date()
        else f"🕒 {fecha_humana(ev['inicio'])} → {fecha_humana(ev['fin'])}",
        f"👥 {inv}",
    ]
    if ev.get("ubicacion"):
        lineas.append(f"📍 {ev['ubicacion']}")
    if ev.get("videollamada"):
        lineas.append("💻 Con enlace de Google Meet")
    return "\n".join(lineas)


def _validar(ev: dict) -> str | None:
    try:
        ini = datetime.fromisoformat(ev["inicio"])
        fin = datetime.fromisoformat(ev["fin"])
    except Exception:
        return "fechas con formato inválido"
    if ini.tzinfo is None or fin.tzinfo is None:
        return "las fechas deben llevar zona horaria"
    if fin <= ini:
        return "la hora de término debe ser posterior al inicio"
    for i in ev.get("invitados", []):
        if "@" not in i.get("email", ""):
            return f"correo inválido para {i.get('nombre') or 'un invitado'}"
    return None


def _get_session(user: str) -> dict:
    s = sessions.get(user)
    if not s or time.time() - s["ts"] > SESSION_TTL:
        s = {"history": [], "pending": None, "ts": time.time()}
        sessions[user] = s
    s["ts"] = time.time()
    return s


def _push(s: dict, role: str, text: str) -> None:
    h = s["history"]
    if h and h[-1]["role"] == role:  # la API exige alternar usuario/asistente
        h[-1]["content"] += "\n" + text
    else:
        h.append({"role": role, "content": text})
    s["history"] = s["history"][-MAX_HISTORY:]
    # la API exige que el historial empiece con el usuario
    while s["history"] and s["history"][0]["role"] != "user":
        s["history"].pop(0)


async def handle_message(user: str, text: str) -> str:
    s = _get_session(user)
    t = _norm(text)

    # 1) ¿Está respondiendo a una propuesta pendiente?
    if s["pending"]:
        if t in SI or t.startswith("si "):
            ev = s["pending"]
            s["pending"] = None
            try:
                created = cal.create_event(ev)
            except Exception as e:  # noqa: BLE001
                log.exception("Error creando evento")
                return f"⚠️ No pude crear el evento en Google Calendar: {e}"
            msg = "✅ Listo, agendado."
            if ev["invitados"]:
                msg += " Google ya le envió la invitación por correo a " + \
                       ", ".join(i.get("nombre") or i["email"] for i in ev["invitados"]) + "."
            if settings.REMINDER_MINUTES:
                msg += f" Te aviso por acá {settings.REMINDER_MINUTES} min antes."
            if created.get("hangoutLink"):
                msg += f"\nMeet: {created['hangoutLink']}"
            _push(s, "user", text)
            _push(s, "assistant", msg)
            return msg
        if t in NO:
            s["pending"] = None
            _push(s, "user", text)
            _push(s, "assistant", "Ok, no lo agendé.")
            return "Ok, no lo agendé. ¿Algo más?"
        # cualquier otra cosa = una corrección ("mejor a las 4"): se la pasamos a Claude con contexto
        contexto = ("\n\n[Sistema: hay una propuesta sin confirmar: "
                    + json.dumps(s["pending"], ensure_ascii=False)
                    + ". Si el usuario la corrige, vuelve a llamar a proponer_evento con los cambios.]")
        s["pending"] = None
        _push(s, "user", text + contexto)
    else:
        _push(s, "user", text)
    messages = list(s["history"])

    for _ in range(5):
        resp = await _claude().messages.create(
            model=settings.CLAUDE_MODEL, max_tokens=1024,
            system=_system_prompt(), tools=TOOLS, messages=messages,
        )
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            reply = "".join(b.text for b in resp.content if b.type == "text").strip() or "¿Me lo repites?"
            _push(s, "assistant", reply)
            return reply

        results = []
        for tu in tool_uses:
            if tu.name == "proponer_evento":
                ev = dict(tu.input)
                ev.setdefault("invitados", [])
                err = _validar(ev)
                if err:
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": f"Error: {err}. Corrige o pregunta al usuario.", "is_error": True})
                    continue
                s["pending"] = ev
                reply = _resumen(ev) + "\n\n¿Lo agendo? Responde *sí* o *no* (o dime qué cambiar)."
                _push(s, "assistant", reply)
                return reply
            if tu.name == "consultar_agenda":
                try:
                    evs = cal.list_events(tu.input["desde"], tu.input["hasta"])
                    data = [{"titulo": e.get("summary", "(sin título)"),
                             "inicio": e["start"].get("dateTime", e["start"].get("date")),
                             "fin": e["end"].get("dateTime", e["end"].get("date"))} for e in evs]
                    content = json.dumps(data, ensure_ascii=False) if data else "Sin eventos en ese rango."
                except Exception as e:  # noqa: BLE001
                    content, data = f"Error consultando calendario: {e}", None
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content})

        messages = messages + [
            {"role": "assistant", "content": [b.model_dump() for b in resp.content]},
            {"role": "user", "content": results},
        ]

    return "Me enredé un poco 😅 ¿Me lo dices de nuevo, más simple?"
