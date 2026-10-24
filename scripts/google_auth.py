"""Ejecuta esto UNA vez en tu computador para autorizar el bot en tu Google Calendar.

    python scripts/google_auth.py

Necesita credentials.json (descargado de Google Cloud Console, tipo "App de escritorio")
en la carpeta del proyecto. Abre el navegador, eliges tu cuenta y genera token.json.
El contenido de token.json va en la variable GOOGLE_TOKEN_JSON del servidor.
"""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
root = Path(__file__).resolve().parent.parent

flow = InstalledAppFlow.from_client_secrets_file(str(root / "credentials.json"), SCOPES)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
(root / "token.json").write_text(creds.to_json(), encoding="utf-8")
print("\n✅ Listo. Se creó token.json. Copia TODO su contenido (una sola línea) en GOOGLE_TOKEN_JSON.\n")
