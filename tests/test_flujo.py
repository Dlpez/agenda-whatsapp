"""Pruebas del flujo completo con WhatsApp, Claude, Groq y Google simulados (no gasta nada)."""
import hashlib
import hmac
import json
import os
from datetime import timedelta
from types import SimpleNamespace

os.environ.update({
    "WA_VERIFY_TOKEN": "vt", "OWNER_WHATSAPP": "56900000000", "CRON_SECRET": "cs",
    "WA_APP_SECRET": "secreto", "REMINDER_MINUTES": "60",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import agent, calendar_client as cal, main, reminders, whatsapp as wa  # noqa: E402

OWNER = "56900000000"
enviados: list[tuple] = []
creados: list[dict] = []


class FakeBlock(SimpleNamespace):
    def model_dump(self):
        return {k: v for k, v in self.__dict__.items()}


def tool(name, inp):
    return FakeBlock(type="tool_use", id=f"tu_{name}", name=name, input=inp)


def text(t):
    return FakeBlock(type="text", text=t)


class FakeClaude:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self

    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=self.script.pop(0))


@pytest.fixture(autouse=True)
def mocks(monkeypatch):
    enviados.clear(); creados.clear(); agent.sessions.clear()

    async def send_text(to, t): enviados.append(("text", to, t))
    async def send_template(to, p): enviados.append(("tpl", to, p)); return True
    async def download_media(mid): return b"OggS...", "audio/ogg; codecs=opus"
    async def fake_transcribe(a, m): return "agéndame reunión con Juan el martes a las 3"

    monkeypatch.setattr(wa, "send_text", send_text)
    monkeypatch.setattr(wa, "send_template", send_template)
    monkeypatch.setattr(wa, "download_media", download_media)
    monkeypatch.setattr(main, "transcribe", fake_transcribe)
    monkeypatch.setattr(cal, "create_event", lambda ev: creados.append(ev) or {"id": "e1"})
    monkeypatch.setattr(cal, "list_events", lambda *a, **k: [])
    monkeypatch.setattr(agent, "load_contacts", lambda: [{"nombre": "Juan Pérez", "email": "juan@x.com"}])


EV = {"titulo": "Reunión con Juan", "inicio": "2026-10-27T15:00:00-03:00",
      "fin": "2026-10-27T16:00:00-03:00", "invitados": [{"nombre": "Juan", "email": "juan@x.com"}]}


def payload(msg):
    return {"entry": [{"changes": [{"value": {"messages": [msg]}}]}]}


def post(client, body):
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(b"secreto", raw, hashlib.sha256).hexdigest()
    return client.post("/webhook", content=raw, headers={"x-hub-signature-256": sig, "content-type": "application/json"})


def test_verificacion_webhook():
    c = TestClient(main.app)
    assert c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"}).text == "42"
    assert c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "mal"}).status_code == 403


def test_firma_invalida_rechazada():
    c = TestClient(main.app)
    r = c.post("/webhook", json=payload({"id": "x", "from": OWNER, "type": "text", "text": {"body": "hola"}}),
               headers={"x-hub-signature-256": "sha256=000"})
    assert r.status_code == 401


def test_texto_propone_y_confirma(monkeypatch):
    monkeypatch.setattr(agent, "_client", FakeClaude([[tool("proponer_evento", EV)]]))
    c = TestClient(main.app)
    post(c, payload({"id": "m1", "from": OWNER, "type": "text", "text": {"body": "reunión con Juan el martes a las 3"}}))
    assert "¿Lo agendo?" in enviados[-1][2] and "martes 27 de octubre, 15:00" in enviados[-1][2]
    assert not creados
    post(c, payload({"id": "m2", "from": OWNER, "type": "text", "text": {"body": "Sí!"}}))
    assert creados and creados[0]["invitados"][0]["email"] == "juan@x.com"
    assert "Listo" in enviados[-1][2]


def test_cancelar_no_crea(monkeypatch):
    monkeypatch.setattr(agent, "_client", FakeClaude([[tool("proponer_evento", EV)]]))
    c = TestClient(main.app)
    post(c, payload({"id": "c1", "from": OWNER, "type": "text", "text": {"body": "reunión"}}))
    post(c, payload({"id": "c2", "from": OWNER, "type": "text", "text": {"body": "no"}}))
    assert not creados


def test_correccion_vuelve_a_claude(monkeypatch):
    ev2 = {**EV, "inicio": "2026-10-27T16:00:00-03:00", "fin": "2026-10-27T17:00:00-03:00"}
    fc = FakeClaude([[tool("proponer_evento", EV)], [tool("proponer_evento", ev2)]])
    monkeypatch.setattr(agent, "_client", fc)
    c = TestClient(main.app)
    post(c, payload({"id": "k1", "from": OWNER, "type": "text", "text": {"body": "reunión"}}))
    post(c, payload({"id": "k2", "from": OWNER, "type": "text", "text": {"body": "mejor a las 4"}}))
    assert "16:00" in enviados[-1][2]
    roles = [m["role"] for m in fc.calls[1]["messages"]]
    assert roles[0] == "user" and all(a != b for a, b in zip(roles, roles[1:]))  # alternancia válida


def test_audio(monkeypatch):
    monkeypatch.setattr(agent, "_client", FakeClaude([[tool("proponer_evento", EV)]]))
    c = TestClient(main.app)
    post(c, payload({"id": "a1", "from": OWNER, "type": "audio", "audio": {"id": "media1"}}))
    assert "Entendí" in enviados[0][2] and "¿Lo agendo?" in enviados[1][2]


def test_consulta_agenda_y_pregunta(monkeypatch):
    fc = FakeClaude([[tool("consultar_agenda", {"desde": "2026-10-24T00:00:00-03:00", "hasta": "2026-10-25T00:00:00-03:00"})],
                     [text("Mañana tienes la agenda libre 🙌")]])
    monkeypatch.setattr(agent, "_client", fc)
    c = TestClient(main.app)
    post(c, payload({"id": "q1", "from": OWNER, "type": "text", "text": {"body": "¿qué tengo mañana?"}}))
    assert enviados[-1][2] == "Mañana tienes la agenda libre 🙌"
    assert fc.calls[1]["messages"][-1]["content"][0]["type"] == "tool_result"


def test_evento_invalido_se_rechaza(monkeypatch):
    malo = {**EV, "fin": "2026-10-27T14:00:00-03:00"}
    monkeypatch.setattr(agent, "_client", FakeClaude([[tool("proponer_evento", malo)], [text("¿A qué hora termina?")]]))
    c = TestClient(main.app)
    post(c, payload({"id": "v1", "from": OWNER, "type": "text", "text": {"body": "x"}}))
    assert enviados[-1][2] == "¿A qué hora termina?" and agent.sessions[OWNER]["pending"] is None


def test_numero_desconocido_ignorado(monkeypatch):
    monkeypatch.setattr(agent, "_client", FakeClaude([]))
    c = TestClient(main.app)
    post(c, payload({"id": "z1", "from": "56999999999", "type": "text", "text": {"body": "hola"}}))
    assert not enviados


def test_mensaje_duplicado(monkeypatch):
    monkeypatch.setattr(agent, "_client", FakeClaude([[text("hola")]]))
    c = TestClient(main.app)
    m = payload({"id": "d1", "from": OWNER, "type": "text", "text": {"body": "hola"}})
    post(c, m); post(c, m)
    assert len(enviados) == 1


@pytest.mark.anyio
async def test_recordatorios(monkeypatch):
    now = cal.now_local()
    evs = [
        {"id": "pronto", "summary": "Reunión con Juan", "start": {"dateTime": (now + timedelta(minutes=30)).isoformat()},
         "extendedProperties": {"private": {"creadoPorBot": "1", "waTelefonos": "56911111111"}}},
        {"id": "ya_avisado", "summary": "X", "start": {"dateTime": (now + timedelta(minutes=20)).isoformat()},
         "extendedProperties": {"private": {"waRecordado": "1"}}},
    ]
    marcados = []
    monkeypatch.setattr(cal, "list_events", lambda *a, **k: evs)
    monkeypatch.setattr(cal, "mark_reminded", marcados.append)
    assert await reminders.run_reminders() == 1
    assert marcados == ["pronto"] and enviados == [("tpl", OWNER, ["Reunión con Juan", agent.fecha_humana(evs[0]["start"]["dateTime"])])]
    c = TestClient(main.app)
    assert c.get("/cron/recordatorios", params={"key": "mala"}).status_code == 403


@pytest.fixture
def anyio_backend():
    return "asyncio"
