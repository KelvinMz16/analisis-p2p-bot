# Bot P2P Binance Venezuela — Contexto

## Propósito
Bot Python que monitorea el mercado P2P de Binance para USDT/VES (y otras criptos). Calcula márgenes de arbitraje Maker (compra y venta), alerta cuando supera un umbral, y permite interactuar vía Telegram con botones inline.

## Stack
- **Python 3.11** (Docker, `python:3.11-slim`)
- **requests** (única dependencia, sin `python-telegram-bot` ni `httpx`)
- **Cloudflare Worker** como proxy para llegar a Telegram API (HF Spaces no puede conectar directo a `api.telegram.org`)

## Conexión a Telegram (patrón exacto de `youtube-shorts-bot`)
- `_get_session()` → `requests.Session()` con `HTTPAdapter(pool=10, retries=1)`
- Proxy vía **HTTP** (no HTTPS, porque SSL entre HF y Cloudflare falla con `SSLEOFError`)
- `_try_url()` → 2 intentos con 1s sleep, si SSL error → `_raw_ssl_post()` (http.client con `CERT_NONE`)
- `_api_call()` → proxy primero (usa respuesta incluso con `ok=false`), solo fallback a directo si proxy no responde
- `USE_PROXY=true` por defecto
- Worker espera `/telegram-api/{method}`, usa `env.BOT_TOKEN`

## Variables de entorno (HF Secrets)
| Secret | Valor |
|--------|-------|
| `TELEGRAM_TOKEN` | `8656204241:AAFuDdUCTLisChwSSak51lgkZzJF_Onxd6s` |
| `TELEGRAM_CHAT_ID` | `591442241` |
| `CLOUDFLARE_PROXY` | `https://ves-arbitraje-p2p.kelvinyohan14.workers.dev` |
| `USE_PROXY` | `true` |
| `CAPITAL` | `90` (persistido desde el bot) |
| `UMBRAL` | `0.8` (persistido desde el bot) |
| `HF_TOKEN` | Token de Hugging Face para guardar secrets |

## Cloudflare Worker
- **Archivo:** `cloudflare-worker.js`
- **Formato:** `addEventListener('fetch', ...)` (service worker)
- **Ruta:** `/telegram-api/{method}` → reenvía a `https://api.telegram.org/bot{BOT_TOKEN}/{method}`
- **`BOT_TOKEN` debe estar configurado como variable de entorno en el dashboard de Cloudflare Workers**
- URL: `https://ves-arbitraje-p2p.kelvinyohan14.workers.dev`

## Binance P2P API
- **Endpoint:** `POST https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search`
- **Payload sin `payTypes`** (la API no reconoce nombres textuales de métodos de pago)
- **Promedio:** índices 2,3,4 (3er a 5to anuncio), requiere mínimo 5 anuncios
- **Assets monitoreados:** `["USDT", "BTC", "ETH", "BNB", "USDC", "SOL"]` (solo los que tienen 5+ ads en ambos lados en VES)

## Cálculos
- **Margen neto:** `((venta - compra) - (venta*0.0025) - (compra*0.0025)) / compra * 100`
- **Comisión:** 0.25% por lado (0.5% total)
- **Ganancia USD:** `capital * (margen / 100)`
- **Ganancia VES:** `ganancia_usd * tasa_venta_USDT`
- **Señal COMPRA:** asset con mayor descuento = `(venta - compra) / venta * 100`
- **Señal VENTA:** asset con mayor prima = `(venta - compra) / compra * 100`
- **Umbral:** 0.8% fijo por defecto, ajustable desde Telegram

## Estructura del bot
- `bot_p2p.py` → Script principal (todo en un archivo)
- `cloudflare-worker.js` → Worker de Cloudflare
- `Dockerfile` → `python:3.11-slim`, `PYTHONUNBUFFERED=1`, `CMD ["python", "-u", "bot_p2p.py"]`
- `requirements.txt` → `requests>=2.31.0`
- `README.md` → Frontmatter `sdk:docker` para HF Spaces

## Funcionalidades
- **Precio USDT**: Muestra compra/venta/margen/ganancia de USDT/VES
- **Multi-cripto**: Lista todas las criptos con botones, mejor/peor margen, señales COMPRA/VENTA
- **Detalle por cripto**: Click en cualquier cripto del multi-cripto → muestra detalle individual
- **Capital**: Botón para cambiar capital (persiste vía HF Secrets)
- **Umbral**: Botón para cambiar umbral de alerta (persiste vía HF Secrets)
- **Estado**: Muestra capital, umbral, y márgenes de todas las criptos
- **Monitoreo automático**: Cada 60s revisa todos los assets, alerta si alguno supera el umbral
- **Heartbeat**: Cada 30 ciclos (~30 min) envía el mejor margen del momento
- **Alerta de recuperación**: Cuando un asset pasa de margen negativo a positivo
- **Modo silencioso**: Sin notificaciones entre 12 AM y 7 AM (hora Venezuela)
- **Ganancia en VES**: Muestra ganancia en USD y Bs.

## Horario de silencio
- `VENEZUELA_TZ = timezone(timedelta(hours=-4))`
- `SLEEP_START = 0` (medianoche)
- `SLEEP_END = 7` (7 AM)
- `en_horario()` → retorna True si está dentro del horario activo
- El monitoreo sigue corriendo pero salta alertas y heartbeat
- Los botones de Telegram siguen funcionando (polling activo 24/7)
- Al cambiar a modo activo envía "Buenos días"
- No hay mensaje de "Buenas noches" al dormir (silencio completo)

## Datos críticos
- Rama: `main` (obligatorio para HF Spaces)
- HF Space: `KelvinMz/VesArbitrajeP2P`
- Health check: puerto 7860
- No usar `python-telegram-bot` ni `httpx` (fallan en HF con `ConnectError`)
- `getUpdates` usa POST con JSON (timeout=10)
- Output unbuffered forzado (`PYTHONUNBUFFERED=1`, `python -u`)
