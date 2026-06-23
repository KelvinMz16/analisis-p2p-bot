import asyncio
import os
import threading
import time
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest

# ============================================================
# CONFIGURACION
# ============================================================
CONFIG = {
    "capital": 100,
    "margen_objetivo": 0.8,
}

COMISION = 0.0025
ULTIMOS = {}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}

URL_BINANCE = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
ASSETS_VES = ["USDT", "BTC", "ETH", "BNB", "USDC", "DAI", "BUSD"]
# ============================================================


# ============================================================
# API BINANCE P2P
# ============================================================
def obtener_precio_p2p(trade_type, asset="USDT"):
    payload = {"asset": asset, "fiat": "VES", "page": 1, "rows": 10, "tradeType": trade_type}
    try:
        resp = requests.post(URL_BINANCE, json=payload, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        anuncios = resp.json().get("data", [])
        if len(anuncios) < 5:
            return None
        return sum(float(anuncios[i]["adv"]["price"]) for i in range(2, 5)) / 3
    except Exception as e:
        print(f"[{asset}/{trade_type}] Error: {e}")
        return None


def calcular_margen(asset):
    compra = obtener_precio_p2p("BUY", asset)
    venta = obtener_precio_p2p("SELL", asset)
    if compra is None or venta is None:
        return None
    ganancia_neta = (venta - compra) - (venta * COMISION) - (compra * COMISION)
    margen = (ganancia_neta / compra) * 100
    ganancia_usd = CONFIG["capital"] * (margen / 100)
    ULTIMOS[asset] = {"compra": compra, "venta": venta, "margen": margen}
    return {"asset": asset, "compra": compra, "venta": venta, "margen": margen, "ganancia_usd": ganancia_usd}
# ============================================================


# ============================================================
# TELEGRAM - ENVIO DIRECTO (para alertas desde el monitoreo)
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CF_PROXY = os.getenv("CLOUDFLARE_PROXY", "").rstrip("/")
USE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"

if CF_PROXY and USE_PROXY:
    API_BASE = f"{CF_PROXY}/telegram-api/"
else:
    API_BASE = "https://api.telegram.org/bot"


def enviar_telegram(mensaje, parse_mode="Markdown"):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": parse_mode}
        requests.post(f"{API_BASE}{TELEGRAM_TOKEN}/sendMessage", json=payload, timeout=15)
        return True
    except Exception as e:
        print(f"Error enviar Telegram: {e}", flush=True)
        return False
# ============================================================


# ============================================================
# TELEGRAM - BOT INTERACTIVO (PTB v20+)
# ============================================================
def build_menu():
    kb = [
        [InlineKeyboardButton("\U0001F4B0 Precio USDT", callback_data="precio"),
         InlineKeyboardButton("\U0001F4CA Multi-cripto", callback_data="arbitraje")],
        [InlineKeyboardButton(f"\u2699\ufe0f Capital (${CONFIG['capital']})", callback_data="capital"),
         InlineKeyboardButton("\U0001F4CB Estado", callback_data="status")],
        [InlineKeyboardButton("\U0001F504 Actualizar", callback_data="menu")],
    ]
    return InlineKeyboardMarkup(kb)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"\U0001F916 *Bot P2P Venezuela*\nCapital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%",
        parse_mode="Markdown", reply_markup=build_menu()
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "precio":
        r = calcular_margen("USDT")
        if r:
            ahorro = ((r['venta'] - r['compra']) / r['venta']) * 100
            await q.edit_message_text(
                f"\U0001F4B0 *USDT / VES*\n"
                f"Compra Maker: {r['compra']:.2f} VES (ahorras {ahorro:.2f}%)\n"
                f"Venta Maker:  {r['venta']:.2f} VES\n"
                f"Margen neto: {r['margen']:.2f}%\n"
                f"Ganancia: ${r['ganancia_usd']:.2f} por ${CONFIG['capital']}",
                parse_mode="Markdown", reply_markup=build_menu()
            )
        else:
            await q.edit_message_text("No se pudieron obtener precios.", reply_markup=build_menu())

    elif data == "arbitraje":
        resultados = []
        for asset in ASSETS_VES:
            r = calcular_margen(asset)
            if r:
                resultados.append(r)
            time.sleep(0.5)
        if not resultados:
            await q.edit_message_text("No se pudieron obtener datos.", reply_markup=build_menu())
            return
        resultados.sort(key=lambda x: x["margen"], reverse=True)
        lines = [f"\U0001F4CA *Mejor: {resultados[0]['asset']}* | {resultados[0]['margen']:.2f}%\n"]
        for r in resultados:
            signo = "+" if r["margen"] >= 0 else ""
            lines.append(f"{r['asset']}: C {r['compra']:.2f} | V {r['venta']:.2f} | *{signo}{r['margen']:.2f}%*")
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=build_menu())

    elif data == "capital":
        context.user_data["esperando_capital"] = True
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"\u2699\ufe0f Capital actual: ${CONFIG['capital']}\nResponde con el nuevo monto en USDT:"
        )

    elif data == "status":
        u = ULTIMOS.get("USDT", {})
        await q.edit_message_text(
            f"\U0001F4CB *Estado*\nCapital: ${CONFIG['capital']}\n"
            f"Umbral: {CONFIG['margen_objetivo']}%\n"
            f"USDT: {u.get('margen', 'N/A'):.2f}%\n"
            f"C {u.get('compra', 'N/A')} | V {u.get('venta', 'N/A')}",
            parse_mode="Markdown", reply_markup=build_menu()
        )

    elif data == "menu":
        await q.edit_message_text(
            f"\U0001F916 *Bot P2P Venezuela*\nCapital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%",
            parse_mode="Markdown", reply_markup=build_menu()
        )


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if context.user_data.get("esperando_capital"):
        try:
            nuevo = float(update.message.text.strip())
            if nuevo > 0:
                viejo = CONFIG["capital"]
                CONFIG["capital"] = nuevo
                await update.message.reply_text(
                    f"Capital actualizado: ${viejo:.0f} -> ${nuevo:.0f}",
                    reply_markup=build_menu()
                )
            else:
                await update.message.reply_text("Debe ser mayor a 0.")
        except ValueError:
            await update.message.reply_text("Ingresa un número, ej: 150")
        finally:
            context.user_data["esperando_capital"] = False
        return
    await cmd_start(update, context)


def run_telegram():
    if not TELEGRAM_TOKEN:
        print("[PTB] Token no configurado.", flush=True)
        return

    base_url = f"{CF_PROXY}/telegram-api/" if (CF_PROXY and USE_PROXY) else "https://api.telegram.org/bot"
    print(f"[PTB] Usando base_url: {base_url}", flush=True)

    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .base_url(base_url)
        .request(HTTPXRequest(connect_timeout=15, read_timeout=15))
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CommandHandler("capital", text_handler))

    try:
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        print(f"[PTB] Error: {e}", flush=True)
# ============================================================


# ============================================================
# SERVIDOR WEB (UptimeRobot)
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "running"}')
    def log_message(self, *a):
        pass

threading.Thread(target=lambda: HTTPServer(("0.0.0.0", 7860), HealthHandler).serve_forever(), daemon=True).start()
# ============================================================


# ============================================================
# MONITOREO (hilo principal)
# ============================================================
def loop_monitoreo():
    print("  Monitoreo cada 60s...", flush=True)
    ciclo = 0
    while True:
        try:
            r = calcular_margen("USDT")
            if r:
                ahorro = ((r['venta'] - r['compra']) / r['venta']) * 100
                print(f"USDT: C {r['compra']:.2f} | V {r['venta']:.2f} | {r['margen']:.2f}% | ${r['ganancia_usd']:.2f}", flush=True)
                if r["margen"] >= CONFIG["margen_objetivo"]:
                    print(">>> OPORTUNIDAD <<<", flush=True)
                    enviar_telegram(
                        f"\U0001F514 *ALERTA P2P - USDT*\n"
                        f"Compra: {r['compra']:.2f} VES\n"
                        f"Venta:  {r['venta']:.2f} VES\n"
                        f"Margen: {r['margen']:.2f}%\n"
                        f"Ganancia: ${r['ganancia_usd']:.2f} por ${CONFIG['capital']}"
                    )

            ciclo += 1
            if ciclo % 30 == 0:
                print(f"Heartbeat: {ciclo} ciclos", flush=True)
                enviar_telegram(f"\u23F1 *Heartbeat* - {ciclo} ciclos sin novedades")

        except Exception as e:
            print(f"Error: {e}", flush=True)
        time.sleep(60)


if __name__ == "__main__":
    print("=" * 60, flush=True)
    print("  Bot P2P Binance - Venezuela", flush=True)
    print(f"  Capital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%", flush=True)
    print("=" * 60, flush=True)

    # Monitoreo en hilo secundario (no usa asyncio)
    threading.Thread(target=loop_monitoreo, daemon=True).start()
    time.sleep(2)

    # PTB en el hilo PRINCIPAL (requiere asyncio en main thread)
    if TELEGRAM_TOKEN:
        enviar_telegram(f"\U0001F4E1 *Bot P2P Iniciado*\nCapital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%")
        run_telegram()
    else:
        print("[Bot] TELEGRAM_TOKEN no configurado.", flush=True)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            print("\nDetenido.", flush=True)
