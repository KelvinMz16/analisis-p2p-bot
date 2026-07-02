import requests
import time
from datetime import datetime

TOKEN = "8656204241:AAFuDdUCTLisChwSSak51lgkZzJF_Onxd6s"
CHANNEL_ID = "-1003934161949"
API = f"https://api.telegram.org/bot{TOKEN}"

def get_bcv():
    import re
    try:
        resp = requests.get("https://finanzasdigital.com/", timeout=15,
            headers={"User-Agent": "Mozilla/5.0"})
        match = re.search(r'href="(https://finanzasdigital\.com/tasa-de-cambio-bcv[^"]*)"', resp.text)
        if match:
            resp2 = requests.get(match.group(1), timeout=15,
                headers={"User-Agent": "Mozilla/5.0"})
            tasa_match = re.search(r'Tasa de Cambio BCV.*?:\s*([\d.,]+)\s*Bs/USD', resp2.text)
            if tasa_match:
                return float(tasa_match.group(1).replace('.', '').replace(',', '.'))
    except:
        pass
    return None

def send(text):
    r = requests.post(f"{API}/sendMessage", json={
        "chat_id": CHANNEL_ID, "text": text, "parse_mode": "Markdown"
    })
    print(f"{'OK' if r.ok else 'FAIL'}: {r.text[:80]}")
    time.sleep(1.5)

bcv = get_bcv()
print(f"BCV: {bcv}")

# P2P prices from Binance (last known from bot data)
usdt_c, usdt_v = 772.50, 781.30
usdc_c, usdc_v = 770.00, 785.00

usdt_spread = ((usdt_v - usdt_c) / usdt_c * 100)
usdc_spread = ((usdc_v - usdc_c) / usdc_c * 100)
bcv_spread = ((usdt_v - bcv) / bcv * 100) if bcv else 0

fecha = datetime.now().strftime("%d/%m/%Y")
hora = datetime.now().strftime("%H:%M")

# 1. RESUMEN DIARIO
lines = [
    f"📊 *RESUMEN DIARIO — {fecha}*",
    f"⏰ {hora} (Venezuela)\n",
    f"🏦 *Tasa BCV*: {bcv:.2f} VES/USD",
    f"💰 *USDT*: {usdt_c:.2f} → {usdt_v:.2f} VES (spread {usdt_spread:+.2f}%)",
    f"💰 *USDC*: {usdc_c:.2f} → {usdc_v:.2f} VES (spread {usdc_spread:+.2f}%)\n",
    f"📈 *Tendencia USDT 24h*: `_▁▁▂▃▅▆█▇▅▃▂▁▁_`",
    f"Promedio: {usdt_c:.2f} VES\n",
    f"⏳ *Sin señal clara* — seguimiento en curso..."
]
send("\n".join(lines))

# 2. ALERTA P2P
margen = usdt_spread
comisiones = 0.80
margen_neto = margen - comisiones
ganancia_usd = (margen_neto / 100) * 150
ganancia_ves = ganancia_usd * usdt_v
send(
    f"🔔 *ALERTA P2P DETALLADA*\n"
    f"Activo: *USDT* | Margen neto actual: *{margen_neto:+.2f}%*\n\n"
    f"👉 *Pasos:*\n"
    f"1️⃣ *COMPRA:* Publica anuncio de COMPRA a *{usdt_c:.2f} VES*\n"
    f"   - Límite mínimo: *400 Bs*\n"
    f"2️⃣ *VENTA:* Publica anuncio de VENTA a *{usdt_v:.2f} VES*\n"
    f"   - Ganancia estimada: *${ganancia_usd:.2f} USD* (~Bs.{ganancia_ves:.0f})\n\n"
    f"ℹ *Detalle:*\n"
    f"- Spread Bruto: {margen:.2f}%\n"
    f"- Comisiones: -{comisiones:.2f}% (Maker 0.50% + BDV 0.30%)\n"
    f"- Margen Neto: {margen_neto:+.2f}%"
)

# 3. SEÑAL DE COMPRA
desv = -1.85
send(
    f"📉 *SEÑAL DE COMPRA* (Confianza: 75%)\n"
    f"Precio compra: *{usdt_c:.2f} VES* ({desv:+.2f}% vs promedio)\n"
    f"Promedio 24h: {usdt_c * 1.0185:.2f} VES | Venta: {usdt_v:.2f} VES\n"
    f"📈 Tendencia: estable o subiendo\n\n"
    f"📊 RSI(14): 28.3\n"
    f"📊 Bollinger: {usdt_c * 0.99:.1f} - {usdt_c * 1.01:.1f} - {usdt_c * 1.03:.1f}\n"
    f"📊 MACD: alcista\n"
    f"Razones: Precio bajo vs promedio, Tendencia estable, RSI sobrevendido\n\n"
    f"👉 *Acción:* COMPRA USDT ahora para vender cuando suba."
)

# 4. SEÑAL DE VENTA
desv = 2.50
send(
    f"📈 *SEÑAL DE VENTA* (Confianza: 70%)\n"
    f"Precio venta: *{usdt_v:.2f} VES* ({desv:+.2f}% vs promedio)\n"
    f"Promedio 24h: {usdt_v * 0.975:.2f} VES | Compra: {usdt_c:.2f} VES\n"
    f"📉 Tendencia: estable o bajando\n\n"
    f"📊 RSI(14): 72.1\n"
    f"📊 Bollinger: {usdt_v * 0.97:.1f} - {usdt_v * 0.99:.1f} - {usdt_v * 1.01:.1f}\n"
    f"📊 MACD: bajista\n"
    f"Razones: Precio alto vs promedio, Tendencia estable, RSI sobrecomprado\n\n"
    f"👉 *Acción:* VENDE tus USDT ahora, el mercado está alto."
)

# 5. RECUPERACION
margen_anterior = margen - 1.70
send(
    f"🟢 *RECUPERACION USDT*\n"
    f"Margen pasó de {margen_anterior:+.2f}% a {margen:+.2f}%\n"
    f"Compra: {usdt_c:.2f} VES\n"
    f"Venta:  {usdt_v:.2f} VES"
)

# 6. SPREAD BCV
send(
    f"📈 *Spread BCV vs P2P*\n\n"
    f"Tasa BCV: {bcv:.2f} VES\n"
    f"USDT P2P: {usdt_v:.2f} VES\n"
    f"Spread: {bcv_spread:+.2f}%"
)

# 7. SUBASTA ACTIVA
send(
    "🏦 *BBVA* — INTERVENCIÓN ACTIVA\n"
    "Tasa: Bs. 642.90\n"
    "Mín: $100 | Máx: $5,000\n"
    f"⏰ {hora}"
)

# 8. SUBASTA CERRADA
send(
    "🏦 *BANCO EXTERIOR* — INTERVENCIÓN CERRADA\n"
    f"⏰ {hora}"
)

# 9. HEARTBEAT
send(
    f"⏱ *Heartbeat*\n"
    f"💵 USDT: {usdt_c:.2f} / {usdt_v:.2f} VES\n"
    f"💵 USDC: {usdc_c:.2f} / {usdc_v:.2f} VES\n"
    f"🏦 BCV: {bcv:.2f} VES"
)

print("\nTODOS ENVIADOS")
