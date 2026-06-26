# Contexto del Proyecto — Análisis P2P Bot

## Objetivo
Analizar los precios de compra y venta del mercado P2P de Binance para bolívares venezolanos (VES) utilizando métodos de pago autorizados (Banco de Venezuela y Pago Móvil) a fin de identificar oportunidades de arbitraje rentable de stablecoins (USDT/USDC). El sistema genera alertas estructuradas y educativas a través de Telegram y almacena un histórico de precios en Supabase para el análisis de horarios óptimos.

## Arquitectura y Despliegue Actual

### 1. Servidor de Ejecución (Hugging Face Spaces)
* **Space URL:** [VesArbitrajeP2P](https://huggingface.co/spaces/KelvinMz/VesArbitrajeP2P)
* **SDK:** **Docker** (definido en [README.md](file:///c:/Users/Kelvin/proyectos/analisis-p2p-bot/README.md) con `app_port: 8080`).
* **Servidor de Salud (Health Check):** Para cumplir con los requisitos de Hugging Face, el bot corre un servidor HTTP liviano en el puerto `8080` en un hilo secundario (daemon) que responde `{"status": "running"}`.
* **Seguridad y Restricciones:** La carpeta `grass_bot` (relacionada con bots de compartición de ancho de banda y proxies) **fue eliminada permanentemente** del repositorio debido a que activaba las alertas automáticas de Hugging Face por uso de "Proxy", bloqueando el espacio. Actualmente el repositorio está libre de cualquier código de proxy.

### 2. Base de Datos (Supabase)
* **Instancia:** `https://wmedwtgfjjkmflfbftxs.supabase.co`
* **Tabla de Historial:** `public.historical_prices`
* **Estructura de la Tabla:**
  * `id` (`int8`, Autogenerado, Primary Key)
  * `ts` (`timestamptz`, Timestamp del registro en hora local de Venezuela)
  * `USDT`, `USDC`, `BTC`, `ETH`, `BNB`, `SOL` (todas de tipo `jsonb` para almacenar los precios de compra, venta y el margen calculado).
* **Permisos:** RLS (Row Level Security) está desactivado para esta tabla y los privilegios `SELECT` e `INSERT` están concedidos al rol público (`anon`) para permitir la escritura del bot desde Hugging Face usando la clave anónima.

### 3. Configuración del Bot (Telegram & Variables)
* **Notificaciones:** Envío de alertas detalladas mediante llamadas HTTPS a la API de Telegram. Para evadir bloqueos o censuras de IP de Hugging Face por parte de Telegram, utiliza un Cloudflare Worker como proxy (`CLOUDFLARE_PROXY`).
* **Variables y Secretos (HF Secrets):**
  * `HF_TOKEN`: Token de escritura para interactuar con la API de Hugging Face.
  * `TELEGRAM_TOKEN`: Token del bot de Telegram obtenido con `@BotFather`.
  * `TELEGRAM_CHAT_ID`: ID del chat de destino de las alertas.
  * `SUPABASE_URL`: Enlace API de Supabase.
  * `SUPABASE_KEY`: Clave JWT pública (`anon`) obtenida del dashboard de Supabase.
* **Configuración del Usuario:** Para evitar reinicios del contenedor al cambiar parámetros de operación, el bot almacena y lee el capital actual y el margen objetivo desde un archivo local persistente llamado `config_usuario.json`.

## Reglas Financieras y de Alertas
1. **Comisiones Descontadas (0.80% total):**
   * **0.50%** comisiones Maker de Binance (0.25% compra + 0.25% venta).
   * **0.30%** comisión bancaria estimada por transferencias de Pago Móvil / BDV.
2. **Filtro Inteligente de Monto:** Permite alternar mediante botones de Telegram entre montos de órdenes mínimas: Mayorista (0 Bs), $5 (4K Bs), $10 (8K Bs) y $20 (16K Bs).
## Estado Actual (2026-06-25)
- **Servidor de salud:** iniciado en `0.0.0.0:8080` sin errores de puerto.
- **Supabase:** inserciones exitosas en la tabla `historical_prices` (permiso `SELECT, INSERT` concedido al rol `anon`).
- **Código:** eliminación del servidor HTTP duplicado y consolidación en una única función `_run_health_server()`.
- **Space:** despliegue exitoso y logs sin excepciones.
- **Scraping BCV:** Implementado `scrape_subastasbcv()` + `_loop_bcv_scrape()` (thread aparte cada 15s). Filtro de falsos positivos, stale detection (2h), multi-banco listo (BDV, Mercantil, BNC, BBVA, BT). Commit `d352f8c`.

## Investigación @subastasBCV / BiciVe Ecosystem (2026-06-25)

### Fuente principal: @subastasBCV (Telegram)
- Canal público scraping vía `https://t.me/s/subastasBCV`
- Posteado por **@SubastasVe_bot** (nombre: "BiciVe Bot", logo bicicleta)
- Formato estructurado de bot: `INTERVENCIÓN ACTIVA/CERRADA`, `TASA:`, `MÍNIMO:`, `MÁXIMO:`, `HORA:`
- Monitorea BDV en tiempo real (apertura/cierre de ventanilla de intervención)
- **Mejor fuente para scraping** por ser formato de bot consistente

### Calculadora asociada: bicical.online / bicical.vercel.app
- Next.js app en Vercel, proyecto "bicical"
- Footer: "© SUBASTAS⌁VE · v1.1"
- Código de acceso: **KH5U**
- APIs públicas:
  - `GET /api/rates` → `{bcvUsd, bcvEur, intervencion, fechaValor}`
  - `GET /api/binance-rate` → `{best, bestBank, timestamp}`
- Funcionalidad: calculadora de arbitraje (tasa BCV vs P2P Binance)
- No expone más datos de los que ya tenemos

### Bots del mismo ecosistema
| Bot | Nombre | Rol |
|-----|--------|-----|
| @SubastasVe_bot | BiciVe Bot | Publica intervenciones en @subastasBCV |
| @Bicicalbot | BiciCal Bot | Bot de la calculadora bicical.online |
| @pasandobot | Bici Bot 🚲 | Probablemente relay de información |

### Dueño: ANÓNIMO (no identificado)
- Dominio bicical.online: NameCheap con privacidad WHOIS (Islandia)
- Registrado: 21 abril 2026
- Sin presencia en LinkedIn, GitHub, HF Spaces, Reddit, foros
- No se encontraron repositorios públicos con el nombre BiciVe
- Todos los bots comparten el mismo logo de bicicleta (branding unificado)

### Alternativas investigadas (no aptas para scraping)
- **@e_positivo** (69.9K subs) — Monitoreo humano, formato inconsistente, stickers/emojis, no parseable
- **@vemioficial** (25.7K subs) — Semi-estructurado pero humano, mezcla análisis con datos
- **Descifrado / prensa** — Solo resúmenes diarios, no tiempo real
- **BCV oficial** — Solo tasas de cierre, no estado de intervención
- No existe página web que muestre estado de intervención por banco en tiempo real

### Decisión
Mantener @subastasBCV como única fuente de scraping. Es la más confiable por ser bot-generated. El multi-banco ya está implementado en el código para cuando @subastasBCV publique de otros bancos.

3. **Restricción de Alertas:** Para evitar alertas basura basadas en spreads ficticios por falta de liquidez en altcoins, el bot **únicamente envía alertas de oportunidad y recuperación para USDT y USDC**. (Las criptomonedas volátiles como BTC, ETH, BNB y SOL se analizan y guardan en base de datos pero no generan spam en Telegram).
4. **Comparador Automático:** Si una alerta se genera en un mercado fraccionado ($5/$10/$20), el mensaje de Telegram calcula de forma automática un escenario comparativo vendiendo todo de golpe en el mercado Mayorista, y viceversa, para ayudar al operador a evaluar la mejor estrategia.

## Arbitraje DEX Multi-Red (Nuevo)
El bot ahora incluye un panel de **Arbitraje DEX Multi-Red** accesible desde el menú de Telegram (`🌌 DEX Multi-Red`). Este módulo compara en tiempo real el precio **Spot** (vía CoinGecko con fallback a DexScreener) contra el precio promedio en **DEX descentralizados** para tres redes:

| Red | Token | DEX Monitoreados | Costo Retiro Estimado |
|-----|-------|-------------------|----------------------|
| **Solana** | SOL | Jupiter, Orca, Raydium | ~$0.03 |
| **Polygon** | POL | QuickSwap, Uniswap V3 | ~$0.01 |
| **BNB Chain** | BNB | PancakeSwap, Uniswap | ~$0.28 |

* **Fuente de precios Spot:** CoinGecko API (gratuita, sin bloqueo regional). Si da error 429 (rate limit), usa DexScreener como fallback.
* **Fuente de precios DEX:** DexScreener API (busca pares USDC/USDT en la cadena nativa).
* **Wallet recomendada:** Phantom (soporta Solana, Polygon, BSC y Ethereum). El botón "Operar" dentro de Phantom ejecuta swaps vía Jupiter (Solana) o agregadores nativos (otras redes).
* **Modo de operación:** Semi-automático. El bot detecta y alerta; el usuario ejecuta manualmente desde Phantom y Binance.
