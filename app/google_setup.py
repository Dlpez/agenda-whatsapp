"""Permiso de Google Calendar desde el propio bot, sin instalar nada en tu PC.

1. Abre https://TU-APP.onrender.com/google/login
2. Elige tu cuenta y presiona Permitir.
3. La página te muestra un texto: cópialo en la variable GOOGLE_TOKEN_JSON de Render.

Una vez configurado GOOGLE_TOKEN_JSON, esta página se desactiva sola.
La llave que muestra corresponde a la cuenta de quien dio el permiso, así que no expone la tuya.
"""
import html
import json
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import settings

router = APIRouter()
SCOPE = "https://www.googleapis.com/auth/calendar.events"
_states: set[str] = set()


def _base_url(request: Request) -> str:
    return (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL") or str(request.base_url)).rstrip("/")


def _check_enabled():
    if settings.GOOGLE_TOKEN_JSON:
        raise HTTPException(404, "Google ya está configurado. Para rehacerlo, borra GOOGLE_TOKEN_JSON en Render.")
    if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET):
        raise HTTPException(500, "Faltan GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET en Render.")


@router.get("/google/login")
async def login(request: Request):
    _check_enabled()
    state = secrets.token_urlsafe(24)
    _states.add(state)
    q = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": _base_url(request) + "/google/callback",
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(q))


@router.get("/google/callback", response_class=HTMLResponse)
async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    _check_enabled()
    if error:
        return HTMLResponse(f"<p>Google respondió: {html.escape(error)}</p>", 400)
    if state not in _states:
        return HTMLResponse("<p>El enlace expiró. Vuelve a abrir <a href='/google/login'>/google/login</a>.</p>", 400)
    _states.discard(state)
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": _base_url(request) + "/google/callback",
            "grant_type": "authorization_code",
        })
    data = r.json()
    if r.status_code != 200 or not data.get("refresh_token"):
        return HTMLResponse(f"<p>No se pudo obtener el permiso: {html.escape(json.dumps(data))}</p>", 400)
    token = json.dumps({
        "token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "scopes": [SCOPE],
    })
    t = html.escape(token)
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Permiso de Google listo</title>
<body style="font-family:system-ui;max-width:640px;margin:40px auto;padding:0 16px">
<h2>✅ Permiso de Google Calendar listo</h2>
<p>1. Presiona <b>Copiar</b>.<br>2. En Render → <i>Environment</i>, pega esto en la variable <b>GOOGLE_TOKEN_JSON</b> y guarda.</p>
<textarea id=t readonly style="width:100%;height:140px">{t}</textarea>
<p><button id=b style="font-size:18px;padding:10px 24px"
 onclick="navigator.clipboard.writeText(document.getElementById('t').value).then(()=>b.textContent='¡Copiado!')">Copiar</button></p>
<p style="color:#666">No compartas este texto: es la llave de tu calendario.</p>
</body>""")
