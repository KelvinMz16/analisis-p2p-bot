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
3. **Restricción de Alertas:** Para evitar alertas basura basadas en spreads ficticios por falta de liquidez en altcoins, el bot **únicamente envía alertas de oportunidad y recuperación para USDT y USDC**. (Las criptomonedas volátiles como BTC, ETH, BNB y SOL se analizan y guardan en base de datos pero no generan spam en Telegram).
4. **Comparador Automático:** Si una alerta se genera en un mercado fraccionado ($5/$10/$20), el mensaje de Telegram calcula de forma automática un escenario comparativo vendiendo todo de golpe en el mercado Mayorista, y viceversa, para ayudar al operador a evaluar la mejor estrategia.
