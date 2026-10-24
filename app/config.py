"""Configuración leída desde variables de entorno (.env en local, panel de Render en producción)."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _req(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val:
        raise RuntimeError(f"Falta la variable de entorno {name} (revisa tu .env)")
    return val


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


class Settings:
    # --- WhatsApp Cloud API (Meta) ---
    WA_TOKEN = _opt("WA_TOKEN")                    # token permanente del usuario de sistema
    WA_PHONE_NUMBER_ID = _opt("WA_PHONE_NUMBER_ID")  # ID del número del bot
    WA_VERIFY_TOKEN = _opt("WA_VERIFY_TOKEN")      # texto que inventas tú, para verificar el webhook
    WA_APP_SECRET = _opt("WA_APP_SECRET")          # para validar la firma de Meta (recomendado)
    GRAPH_VERSION = _opt("GRAPH_VERSION", "v23.0")

    # Solo este número puede darle órdenes al bot (formato internacional sin +, ej: 56912345678)
    OWNER_WHATSAPP = _opt("OWNER_WHATSAPP")

    # --- Claude ---
    ANTHROPIC_API_KEY = _opt("ANTHROPIC_API_KEY")
    CLAUDE_MODEL = _opt("CLAUDE_MODEL", "claude-sonnet-5-5")

    # --- Transcripción de audios (API compatible con OpenAI: Groq u OpenAI) ---
    TRANSCRIBE_BASE_URL = _opt("TRANSCRIBE_BASE_URL", "https://api.groq.com/openai/v1")
    TRANSCRIBE_API_KEY = _opt("TRANSCRIBE_API_KEY")
    TRANSCRIBE_MODEL = _opt("TRANSCRIBE_MODEL", "whisper-large-v3-turbo")

    # --- Google Calendar ---
    GOOGLE_TOKEN_JSON = _opt("GOOGLE_TOKEN_JSON")  # contenido de token.json (lo genera scripts/google_auth.py)
    CALENDAR_ID = _opt("CALENDAR_ID", "primary")
    TIMEZONE = _opt("TIMEZONE", "America/Santiago")
    DEFAULT_DURATION_MIN = int(_opt("DEFAULT_DURATION_MIN", "60"))

    # --- Recordatorios por WhatsApp ---
    REMINDER_MINUTES = int(_opt("REMINDER_MINUTES", "60"))       # cuánto antes avisar
    REMINDER_TEMPLATE = _opt("REMINDER_TEMPLATE", "recordatorio_reunion")
    REMINDER_TEMPLATE_LANG = _opt("REMINDER_TEMPLATE_LANG", "es")
    REMIND_INVITEES = _opt("REMIND_INVITEES", "false").lower() == "true"
    CRON_SECRET = _opt("CRON_SECRET")

    CONTACTS_FILE = _opt("CONTACTS_FILE", str(Path(__file__).resolve().parent.parent / "contacts.json"))


settings = Settings()


def load_contacts() -> list[dict]:
    """Agenda de contactos: [{"nombre": "Juan Pérez", "alias": ["Juan"], "email": "...", "whatsapp": "569..."}]"""
    raw = _opt("CONTACTS_JSON")
    if raw:
        return json.loads(raw)
    p = Path(settings.CONTACTS_FILE)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []
