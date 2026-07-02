import requests
import time

TOKEN = "8656204241:AAFuDdUCTLisChwSSak51lgkZzJF_Onxd6s"
CHANNEL_ID = "-1003934161949"
API = f"https://api.telegram.org/bot{TOKEN}"

def send(text):
    r = requests.post(f"{API}/sendMessage", json={
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "Markdown"
    })
    print(f"{'OK' if r.ok else 'FAIL'}: {r.text[:100]}")
    time.sleep(1.5)

# 1. RESUMEN DIARIO
send(
    "📊 *RESUMEN DIARIO — 02/07/2026*\n"
    "⏰ 07:00 (Venezuela)\n\n"
    "🏦 *Tasa BCV*: 639.70 VES/USD\n"
    "💰 *USDT*: $1.0023 (DEX $1.0021)\n"
    "💰 *USDC*: 5.20 → 6.10 VES (spread +1.05%)\n"
    "💰 *BTC*: 65420.00 → 67890.00 VES (spread +3.77%)\n"
    "💰 *ETH*: 3890.00 → 4020.00 VES (spread +3.34%)\n"
    "💰 *BNB*: 612.00 → 635.00 VES (spread +3.76%)\n"
    "💰 *SOL*: 152.00 → 158.50 VES (spread +4.28%)\n\n"
    "📈 *Tendencia USDT 24h*: `_▁▁▂▃▅▆█▇▅▃▂▁▁_`\n"
    "Promedio: 774.52 VES | Registros: 1440\n\n"
    "⏳ *Sin señal clara* — seguimiento en curso..."
)

# 2. ALERTA P2P DETALLADA
send(
    "🔔 *ALERTA P2P DETALLADA* (Perfil Conservador)\n"
    "Activo: *USDT* | Margen neto actual: *+2.35%* ✅ RENTABLE\n\n"
    "👉 *Pasos sugeridos para tu configuración actual (Perfil Conservador):*\n"
    "1️⃣ *COMPRA:* Publica un anuncio de *COMPRA* (pagas Bs y recibes USDT) con precio fijado en *772.50 VES*.\n"
    "   - Configura el límite mínimo de tu anuncio en: *400 Bs*.\n"
    "2️⃣ *VENTA:* Publica un anuncio de *VENTA* (recibes Bs en BDV/Pago Móvil) con precio fijado en *790.70 VES*.\n"
    "   - Ganancia neta estimada con tu capital: *$4.70 USD* (~Bs.3,685.00)\n\n"
    "🔄 *Escenario Alternativo (Vender todo de golpe - Mayorista):*\n"
    "- Vender todo a: *788.40 VES*\n"
    "- Margen Neto: +2.05%\n"
    "- Ganancia Neta Total: *$4.10 USD* (~Bs.3,230.00)\n\n"
    "ℹ *Detalle financiero de la alerta:*\n"
    "- Spread Bruto: 2.35%\n"
    "- Comisiones Totales: -0.80% (Binance Maker 0.50% + BDV 0.30%)"
)

# 3. SEÑAL DE COMPRA
send(
    "📉 *SEÑAL DE COMPRA* (Confianza: 75%)\n"
    "Precio compra: *770.20 VES* (-1.85% vs promedio)\n"
    "  `_▁▁▂▃▅▆█▇▅▃▂▁▁_`\n"
    "Promedio 24h: 784.75 VES | Venta: 788.50 VES\n"
    "📈 Tendencia: estable o subiendo\n"
    "✅ Cerca de soporte histórico (768 VES)\n\n"
    "📊 RSI(14): 28.3\n"
    "📊 Bollinger: 765.0 - 784.0 - 803.0\n"
    "📊 MACD: alcista\n"
    "Razones: Precio bajo vs promedio 24h, Tendencia estable o subiendo, Cerca de soporte histórico, RSI bajo (28) - mercado sobrevendido, Tocando banda inferior de Bollinger\n\n"
    "👉 *Acción:* COMPRA USDT ahora para vender cuando suba."
)

# 4. SEÑAL DE VENTA
send(
    "📈 *SEÑAL DE VENTA* (Confianza: 70%)\n"
    "Precio venta: *798.50 VES* (+2.50% vs promedio)\n"
    "  `_▁▂▃▅▆█▇▅▃▂▁▁_`\n"
    "Promedio 24h: 779.10 VES | Compra: 772.30 VES\n"
    "📉 Tendencia: estable o bajando\n"
    "✅ Cerca de resistencia histórica (800 VES)\n\n"
    "📊 RSI(14): 72.1\n"
    "📊 Bollinger: 765.0 - 784.0 - 803.0\n"
    "📊 MACD: bajista\n"
    "Razones: Precio alto vs promedio 24h, Tendencia estable o bajando, Cerca de resistencia histórica, RSI alto (72) - mercado sobrecomprado\n\n"
    "👉 *Acción:* VENDE tus USDT ahora, el mercado está alto."
)

# 5. RECUPERACION
send(
    "🟢 *RECUPERACION USDT*\n"
    "Margen pasó de -0.50% a +1.20%\n"
    "Compra: 772.30 VES\n"
    "Venta:  781.55 VES"
)

# 6. SPREAD BCV
send(
    "📈 *Spread BCV vs P2P*\n\n"
    "Tasa BCV: 639.70 VES\n"
    "USDT P2P: 774.50 VES\n"
    "Spread: +21.07%"
)

# 7. SUBASTA ACTIVA
send(
    "🏦 *BBVA* — INTERVENCIÓN ACTIVA\n"
    "Tasa: Bs. 642.90\n"
    "Mín: $100 | Máx: $5,000\n"
    "⏰ 09:30"
)

# 8. SUBASTA CERRADA
send(
    "🏦 *BBVA* — INTERVENCIÓN CERRADA\n"
    "⏰ 14:20"
)

# 9. HEARTBEAT
send(
    "⏱ *Heartbeat* - 120 ciclos\n"
    "💵 USDT: 772.50 / 781.30 VES\n"
    "💱 Mejor USDT: USDT ($1.0023)\n"
    "📊 Precisión P2P: 85% (42/50)"
)

# 10. ALERTA DEX
send(
    "🔔 *ALERTA DEX MULTI-RED* (BSC)\n"
    "Red: *BSC* | Margen neto: *+1.80%* ✅ RENTABLE\n\n"
    "👉 *Pasos:*\n"
    "1️⃣ Compra *BNB* en Spot de Binance a *$612.40 USD*\n"
    "2️⃣ Retira a tu wallet 0x... (costo: ~$0.15)\n"
    "3️⃣ Vende en *PancakeSwap* a *$623.50 USD*\n\n"
    "📈 *Finanzas estimadas* (Capital: $150):\n"
    "- Spread bruto: 1.80%\n"
    "- Costos (retiro+swap): *$0.15*\n"
    "- *Ganancia Neta: $2.55 USD* (+1.70%)\n\n"
    "_Umbral actual: 1.5%_"
)

# 11. VPS POR VENCER
send(
    "⚠️ *El VPS vence en 5 días*\n"
    "Fecha: 2026-07-07\n"
    "Cancelar en Kamatera para evitar cobros."
)

print("TODOS ENVIADOS")
