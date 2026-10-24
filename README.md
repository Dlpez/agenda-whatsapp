# 📅 Agenda por WhatsApp

Le escribes o le mandas un audio a tu bot de WhatsApp:

> "Agéndame una reunión con Juan el martes a las 3, por Meet"

y el bot responde:

> 📅 *Reunión con Juan*
> 🕒 martes 27 de octubre, 15:00 – 16:00
> 👥 Juan Pérez <juan@ejemplo.com>
> 💻 Con enlace de Google Meet
>
> ¿Lo agendo? Responde *sí* o *no* (o dime qué cambiar).

Contestas "sí" → se crea en tu Google Calendar, **Google le manda la invitación por correo a Juan** (con sus recordatorios), y el bot **te avisa por WhatsApp** 60 minutos antes.

También entiende:
- Correcciones: "mejor a las 4", "agrega a María", "que dure media hora"
- Preguntas: "¿qué tengo mañana?", "¿estoy libre el jueves en la tarde?"
- Personas por nombre o apodo, si están en `contacts.json`, o un correo dicho directamente.

Solo responde a **tu** número; cualquier otro se ignora.

---

## Cómo funciona

```
Tú (WhatsApp) ──► Meta ──► tu servidor (Render) ──► Groq (audio → texto)
                                  │                 Claude (entiende el pedido)
                                  └──────────────► Google Calendar (crea evento + invitación)
cron-job.org ── cada 5 min ──► /cron/recordatorios ──► WhatsApp (aviso antes de la reunión)
```

| Archivo | Qué hace |
|---|---|
| `app/main.py` | Servidor: recibe los mensajes de WhatsApp y el pulso de recordatorios |
| `app/agent.py` | Claude interpreta, consulta la agenda y propone; maneja el "sí / no" |
| `app/calendar_client.py` | Crea y lista eventos en Google Calendar |
| `app/whatsapp.py` | Envía mensajes y descarga audios |
| `app/transcribe.py` | Audio → texto |
| `app/reminders.py` | Avisos por WhatsApp antes de cada reunión |
| `contacts.json` | Tu agenda de contactos (nombre, apodos, correo, WhatsApp) |

---

## Instalación (una sola vez, ~1 a 2 horas)

Necesitas: Python 3.11+, Git, una cuenta de GitHub y tu cuenta de Google.

### 1. Claves de Claude y de transcripción

1. **Claude:** entra a <https://console.anthropic.com>, carga algo de crédito y crea una API key → `ANTHROPIC_API_KEY`. Cada mensaje cuesta una fracción de centavo.
2. **Groq (audios):** entra a <https://console.groq.com>, crea una API key gratis → `TRANSCRIBE_API_KEY`.
   (Si prefieres OpenAI: `TRANSCRIBE_BASE_URL=https://api.openai.com/v1` y `TRANSCRIBE_MODEL=whisper-1`.)

### 2. Google Calendar

1. Entra a <https://console.cloud.google.com> y crea un proyecto (ej: "agenda-bot").
2. **APIs y servicios → Biblioteca →** busca **Google Calendar API** → Habilitar.
3. **Pantalla de consentimiento OAuth:** tipo *Externo*, nombre de la app, tu correo. En *Usuarios de prueba* agrega tu Gmail.
4. **Credenciales → Crear credenciales → ID de cliente OAuth →** tipo **App de escritorio**. Descarga el JSON y guárdalo en la carpeta del proyecto como `credentials.json`.
5. En tu computador:
   ```bash
   pip install -r requirements.txt
   python scripts/google_auth.py
   ```
   Se abre el navegador; eliges tu cuenta y aceptas (aparece un aviso de "app no verificada": es tu propia app, dale *Continuar*). Se crea `token.json`.
6. ⚠️ **Importante:** mientras la app esté en modo *Prueba*, Google invalida el permiso cada 7 días. Para que no pase, en la pantalla de consentimiento presiona **Publicar app** (pasa a *En producción*; no necesitas verificarla para uso propio) y repite el paso 5.

> **Alternativa sin instalar nada:** crea el cliente OAuth como **Aplicación web** con la redirección `https://TU-APP.onrender.com/google/callback`, pon `GOOGLE_CLIENT_ID` y `GOOGLE_CLIENT_SECRET` en Render y abre `https://TU-APP.onrender.com/google/login`. La página te muestra el texto para `GOOGLE_TOKEN_JSON`.

### 3. WhatsApp (Meta)

1. Entra a <https://developers.facebook.com> → **Mis apps → Crear app →** caso de uso *Otro* → tipo **Negocios**.
2. Agrega el producto **WhatsApp**. Meta te da un **número de prueba gratis**: sirve perfecto para uso personal (puede escribirle a hasta 5 números que verifiques). Agrega tu celular como destinatario y verifícalo con el código.
   - Si después quieres un número propio para el bot, tiene que ser uno que **no** esté usando WhatsApp normal (un chip extra).
3. En **WhatsApp → Configuración de la API** copia el **Phone number ID** → `WA_PHONE_NUMBER_ID`.
4. **Token permanente** (el temporal dura 24 h): en <https://business.facebook.com> → Configuración del negocio → **Usuarios del sistema** → crea uno *Administrador* → *Asignar activos* (tu app, control total) → **Generar token** con los permisos `whatsapp_business_messaging` y `whatsapp_business_management` → `WA_TOKEN`.
5. En la app: **Configuración de la app → Básica → Clave secreta de la app** → `WA_APP_SECRET`.

### 4. Plantilla del recordatorio

WhatsApp solo deja que el bot te escriba primero usando plantillas aprobadas. En **WhatsApp Manager → Plantillas de mensajes → Crear**:

- Categoría: **Utilidad**
- Nombre: `recordatorio_reunion`
- Idioma: **Español** (`es`)
- Cuerpo: `Hola 👋 Te recuerdo: {{1}} el {{2}}.`
- Ejemplos: `Reunión con Juan` y `martes 27 de octubre, 15:00`

La aprobación suele tardar desde minutos hasta un día. Estos mensajes iniciados por el bot tienen un costo pequeño por mensaje que cobra Meta; responderte cuando tú le escribes no tiene ese cobro.

### 5. Tus contactos

Edita `contacts.json` con las personas que agendas seguido. El campo `whatsapp` es opcional (solo se usa si activas `REMIND_INVITEES=true` para avisarles a ellos también).

### 6. Subir a internet (Render, gratis)

1. Sube esta carpeta a un repositorio **privado** de GitHub (privado porque `contacts.json` tiene correos). El `.gitignore` ya evita subir `.env`, `token.json` y `credentials.json`.
2. En <https://render.com> → **New → Blueprint** → elige el repo (usa `render.yaml`).
3. En **Environment** agrega todas las variables de `.env.example`. En `GOOGLE_TOKEN_JSON` pega el contenido completo de `token.json`. `OWNER_WHATSAPP` es tu número con código de país sin `+` (ej: `56912345678`).
4. Cuando termine el deploy, tu URL será algo como `https://agenda-whatsapp.onrender.com`. Abre esa URL: debe mostrar `{"ok": true}`.

### 7. Conectar el webhook

En Meta → **WhatsApp → Configuración → Webhook → Editar**:
- URL de devolución: `https://TU-APP.onrender.com/webhook`
- Token de verificación: el mismo `WA_VERIFY_TOKEN` que pusiste en Render
- Luego, en *Campos del webhook*, suscríbete a **messages**.

### 8. Pulso de recordatorios

En <https://cron-job.org> (gratis) crea un cronjob cada **5 minutos** a:

```
https://TU-APP.onrender.com/cron/recordatorios?key=TU_CRON_SECRET
```

De paso, esto mantiene despierto el servidor gratuito de Render (si no, el primer mensaje después de 15 min de inactividad demora ~1 minuto en responder).

### 9. ¡Prueba!

Escríbele al número del bot: *"¿qué tengo mañana?"* y luego *"agéndame una reunión con [alguien de tu contacts.json] el lunes a las 10"*.

---

## Probar en tu computador

```bash
cp .env.example .env      # y rellénalo
uvicorn app.main:app --reload
```

Para que Meta llegue a tu PC usa un túnel (ej: `ngrok http 8000`) y pon esa URL en el webhook.

Pruebas automáticas (simulan WhatsApp, Claude y Google; no gastan nada):

```bash
pip install pytest anyio
pytest -q
```

## Ajustes útiles (variables de entorno)

| Variable | Por defecto | Para qué |
|---|---|---|
| `REMINDER_MINUTES` | `60` | Cuántos minutos antes te avisa |
| `DEFAULT_DURATION_MIN` | `60` | Duración si no la dices |
| `REMIND_INVITEES` | `false` | `true` = también avisa por WhatsApp a invitados con número en contactos |
| `CALENDAR_ID` | `primary` | Otro calendario tuyo |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` | Modelo que interpreta los mensajes |

## Problemas comunes

- **El bot no responde:** revisa los *Logs* en Render. Si no aparece nada, el webhook no está suscrito a `messages` o la URL está mal.
- **"Mensaje ignorado de número no autorizado":** `OWNER_WHATSAPP` no coincide con tu número (sin `+`, con `569…`).
- **Error de Google `invalid_grant`:** el permiso venció (app en modo *Prueba*). Publica la app y repite `google_auth.py`.
- **No llega el recordatorio:** la plantilla aún no está aprobada, o el nombre/idioma no coincide con `REMINDER_TEMPLATE` / `REMINDER_TEMPLATE_LANG`.
- **Error 401 en el webhook:** `WA_APP_SECRET` no corresponde a tu app.
