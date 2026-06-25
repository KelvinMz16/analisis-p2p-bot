# Bot P2P Binance Venezuela — Contexto
> ⚠️ **LEER `CONTEXTO.md` primero** — contiene el historial completo de intentos, resultados y conclusión del proyecto general de generación de ingresos.

## Referencia cruzada
- `CONTEXTO.md` — historial completo del proyecto (qué se probó, qué funciona, qué no, lecciones aprendidas)
- `AGENTS.md` (este archivo) — detalles técnicos del bot P2P Binance

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
| `MONTO_FILTRO` | Filtro de monto (persistido desde el bot) |
| `DEFAULT_CRYPTO` | Cripto predeterminada (persistido desde el bot) |
| `HF_TOKEN` | Token de Hugging Face para guardar secrets |

## Guardado de configuración (HF Secrets)
- `guardar_config_local()` guarda en `config_usuario.json` (local, se pierde al redeploy)
- Y sincroniza a HF Secrets: `CAPITAL`, `UMBRAL`, `MONTO_FILTRO`, `DEFAULT_CRYPTO`
- `_sync_hf_secret(key, value)` → `POST https://huggingface.co/api/spaces/{NAMESPACE}/secrets`
- Al iniciar: lee de `config_usuario.json` primero, con fallback a env vars (`os.getenv`)
- Startup llama a `guardar_config_local()` para asegurar que secrets existan

## Cloudflare Worker
- **Archivo:** `cloudflare-worker.js`
- **Formato:** `addEventListener('fetch', ...)` (service worker)
- **Ruta:** `/telegram-api/{method}` → reenvía a `https://api.telegram.org/bot{BOT_TOKEN}/{method}`
- **Rutas adicionales:** `/binance-api/` y `/jupiter-api/` (NO FUNCIONAN actualmente — timeouts desde HF)
- **`BOT_TOKEN` debe estar configurado como variable de entorno en el dashboard de Cloudflare Workers**
- URL: `https://ves-arbitraje-p2p.kelvinyohan14.workers.dev`

## Binance P2P API
- **Endpoint:** `POST https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search`
- **Payload con `payTypes`** `["BancoDeVenezuela", "PagoMovil"]`
- **Promedio:** índices 0-2 (1er al 3er anuncio), requiere mínimo 3 anuncios
- **Assets monitoreados:** `["USDT", "BTC", "ETH", "BNB", "USDC", "SOL"]` (solo los que tienen 5+ ads en ambos lados en VES)

## Cálculos
- **Margen neto:** `((venta - compra) - (compra*0.0025) - (venta*0.0025) - (compra*0.003)) / compra * 100`
- **Comisiones:** 0.25% Maker compra + 0.25% Maker venta + 0.30% Pago Móvil BDV = **0.80% total**
- **Ganancia USD:** `capital * (margen / 100)`
- **Ganancia VES:** `ganancia_usd * tasa_venta_USDT`
- **Umbral:** 0.8% fijo por defecto, ajustable desde Telegram
- **Capital mínimo:** $100 USD para anuncios Maker

## Precios Spot y DEX (fuentes que funcionan desde HF Spaces)
| API | Estado | Uso |
|-----|--------|-----|
| `api.coingecko.com` | ✅ Funciona | Spot price (batch todos assets + cache 10s) |
| `api.dexscreener.com` | ✅ Funciona | DEX price (par con mayor liquidez) |
| `p2p.binance.com` | ✅ Funciona | P2P anuncios VES |
| `api.coincap.io` | ❌ DNS fail desde HF | Desactivado |
| `api.binance.com` | ❌ HTTP 451 bloqueado | Desactivado (ni Cloudflare proxy ayuda) |
| `quote-api.jup.ag` | ❌ DNS fail desde HF | Desactivado (ni Cloudflare proxy ayuda) |

## Estructura del bot
- `bot_p2p.py` → Script principal (~1480 líneas)
- `cloudflare-worker.js` → Worker de Cloudflare
- `Dockerfile` → `python:3.11-slim`, `PYTHONUNBUFFERED=1`, `CMD ["python", "-u", "bot_p2p.py"]`
- `requirements.txt` → `requests>=2.31.0`
- `README.md` → Frontmatter `sdk:docker` para HF Spaces
- `guia-mercado-spot.md` → Guía de cómo comprar en Spot

## Funcionalidades
- **Precio USDT**: Muestra compra/venta/margen/ganancia de USDT/VES
- **Multi-cripto**: Lista todas las criptos con botones, mejor/peor margen
- **Detalle por cripto**: Click en cualquier cripto → detalle individual + guarda como predeterminada
- **Capital**: Botón para cambiar capital (persiste vía HF Secrets)
- **Umbral**: Botón para cambiar umbral de alerta (persiste vía HF Secrets)
- **Estado**: Muestra capital, umbral, y márgenes de todas las criptos
- **Monitoreo automático**: Cada 60s revisa todos los assets, alerta solo si USDT supera umbral
- **Solo alertas USDT**: USDC ya no genera notificaciones (no rentable según análisis)
- **Heartbeat**: Cada 30 ciclos (~30 min) envía el mejor margen del momento
- **Alerta de recuperación**: Cuando USDT pasa de margen negativo a positivo
- **Auto-refresh de paneles**: Mensajes dinámicos (precio, multi-cripto, detalle, combo, estado, DEX) se actualizan cada 60s automáticamente. Expiran tras 5 ciclos (5 min).
- **Modo silencioso**: Sin notificaciones entre 12 AM y 7 AM (hora Venezuela)
- **Ganancia en VES**: Muestra ganancia en USD y Bs.
- **Historial**: Guarda precios cada 60s en Supabase + JSONL. Botón "📅 Historial" lee de Supabase con fallback a JSONL.

## Horario de silencio
- `VENEZUELA_TZ = timezone(timedelta(hours=-4))`
- `SLEEP_START = 0` (medianoche)
- `SLEEP_END = 7` (7 AM)
- `en_horario()` → retorna True si está dentro del horario activo
- El monitoreo sigue corriendo pero salta alertas y heartbeat
- Los botones de Telegram siguen funcionando (polling activo 24/7)
- Al cambiar a modo activo envía "Buenos días"
- No hay mensaje de "Buenas noches" al dormir (silencio completo)

## DEX Multi-Red
- **Redes monitoreadas:** SOL (Solana), POL (Polygon), BNB (BNB Chain)
- **Spot price:** CoinGecko (única fuente que funciona desde HF)
- **DEX price:** DexScreener (par USDC/USDT con mayor liquidez, por chain)
- **Cálculo:** Spread entre precio Spot y DEX, menos costos de retiro + swap
- **Alertas automáticas:** Usa mismo umbral configurable (`margen_objetivo`)
- **Alerta de recuperación DEX:** Cuando margen pasa de negativo a positivo

## Datos críticos
- Rama: `main` (obligatorio para HF Spaces)
- HF Space: `KelvinMz/VesArbitrajeP2P`
- Health check: puerto 7860
- No usar `python-telegram-bot` ni `httpx` (fallan en HF con `ConnectError`)
- `getUpdates` usa POST con JSON (timeout=10)
- Output unbuffered forzado (`PYTHONUNBUFFERED=1`, `python -u`)
- **Redes desde HF:** CoinGecko funciona, DexScreener funciona, P2P Binance funciona. Binance API (451), CoinCap (DNS fail), Jupiter (DNS fail) NO funcionan.
- **Supabase:** URL `wmedwtgfjjkmflfbftxs.supabase.co`, key almacenada como `SUPABASE_URL` y `SUPABASE_KEY`

## Investigación Kontigo + BPay (archivada)
- Kontigo **no permite transferencia directa** a BPay — solo vía redes blockchain (USDT/USDC)
- Redes soportadas por Kontigo: Arbitrum, Polygon, Avalanche, Gnosis, TRON (TRC-20), Ethereum (ERC-20, la más cara)
- Costo TRC-20: ~$1. Costo Arbitrum/Polygon/Avalanche/Gnosis: <$0.10-0.50
- Además Kontigo cobra comisión por retiro: 1.7% (BNC, Banco Plaza, Banco Activo) o 3.5% (Bancamiga)
- **Conclusión:** Con spread 775.50↔801 (~3.3% bruto), después de comisiones Kontigo + red, el resultado es pérdida (~2.3%). Se necesitaría spread >5% para que valga la pena. El bot P2P busca justamente esos picos anómalos en el P2P directo.

## ⚠️ Binance prohibió cuentas asociadas a Kontigo (Ene 2026)
- Binance prohibió "bajo efecto inmediato" el uso de cuentas bancarias asociadas a Kontigo ("Oha Technology") en transacciones P2P en Venezuela
- Penalizaciones: 1ra = 24h suspensión, 2da = 1 semana, 3ra = pérdida de insignia de comerciante verificado
- **Solución:** Usar Kontigo solo para COMPRAR USDT y enviarlos a Binance. Para la VENTA en P2P, recibir los bolívares en una cuenta personal (BDV, Banesco, Mercantil, etc.) no asociada a Kontigo.
