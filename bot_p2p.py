import json
import os
import threading
import time
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# CONFIGURACION
# ============================================================
CONFIG = {
    "capital": 100,
    "margen_objetivo": 0.8,
}

COMISION = 0.0025
ULTIMOS = {}
ESTADOS_USUARIO = {}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}

URL_BINANCE = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
ASSETS_VES = ["USDT", "BTC", "ETH", "BNB", "USDC", "DAI", "BUSD"]
# ============================================================


# ============================================================
# TELEGRAM - CONFIG
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CF_PROXY = os.getenv("CLOUDFLARE_PROXY", "").rstrip("/")
USE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"

if CF_PROXY and USE_PROXY:
    API_BASE = f"{CF_PROXY}/telegram-api/"
else:
    API_BASE = "https://api.telegram.org/bot"
# ============================================================


# ============================================================
# FUNCIONES TELEGRAM
# ============================================================
def _tg_call(method, payload=None, params=None):
    if not TELEGRAM_TOKEN:
        return None
    try:
        url = f"{API_BASE}{TELEGRAM_TOKEN}/{method}"
        if payload is not None:
            r = requests.post(url, json=payload, timeout=15)
        else:
            r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"TG {method}: {e}", flush=True)
        return None


def enviar_menu(chat_id=None, texto=None):
    cid = chat_id or TELEGRAM_CHAT_ID
    if not texto:
        texto = f"\U0001F916 *Bot P2P Venezuela*\nCapital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%"
    kb = json.dumps({
        "inline_keyboard": [
            [{"text": "\U0001F4B0 Precio USDT", "callback_data": "precio"},
             {"text": "\U0001F4CA Multi-cripto", "callback_data": "arbitraje"}],
            [{"text": f"\u2699\ufe0f Capital (${CONFIG['capital']})", "callback_data": "capital"},
             {"text": "\U0001F4CB Estado", "callback_data": "status"}],
            [{"text": "\U0001F504 Actualizar", "callback_data": "menu"}],
        ]
    })
    _tg_call("sendMessage", {
        "chat_id": cid, "text": texto,
        "parse_mode": "Markdown", "reply_markup": kb
    })


def responder_callback(callback_id, texto=None):
    p = {"callback_query_id": callback_id}
    if texto:
        p["text"] = texto
    _tg_call("answerCallbackQuery", p)


def editar_mensaje(chat_id, message_id, texto):
    kb = json.dumps({
        "inline_keyboard": [
            [{"text": "\U0001F4B0 Precio USDT", "callback_data": "precio"},
             {"text": "\U0001F4CA Multi-cripto", "callback_data": "arbitraje"}],
            [{"text": f"\u2699\ufe0f Capital (${CONFIG['capital']})", "callback_data": "capital"},
             {"text": "\U0001F4CB Estado", "callback_data": "status"}],
            [{"text": "\U0001F504 Actualizar", "callback_data": "menu"}],
        ]
    })
    _tg_call("editMessageText", {
        "chat_id": chat_id, "message_id": message_id,
        "text": texto, "parse_mode": "Markdown", "reply_markup": kb
    })
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
        print(f"[{asset}/{trade_type}] Error: {e}", flush=True)
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
# PROCESAR ACTUALIZACIONES TELEGRAM
# ============================================================
def procesar_mensaje(texto, chat_id):
    if chat_id in ESTADOS_USUARIO and ESTADOS_USUARIO[chat_id].get("esperando") == "capital":
        try:
            nuevo = float(texto.strip())
            if nuevo > 0:
                viejo = CONFIG["capital"]
                CONFIG["capital"] = nuevo
                enviar_menu(chat_id, f"Capital actualizado: ${viejo:.0f} -> ${nuevo:.0f}")
            else:
                _tg_call("sendMessage", {"chat_id": chat_id, "text": "Debe ser mayor a 0."})
        except ValueError:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Ingresa un numero, ej: 150"})
        finally:
            ESTADOS_USUARIO.pop(chat_id, None)
        return
    enviar_menu(chat_id)


def procesar_callback(cq):
    chat_id = cq["message"]["chat"]["id"]
    msg_id = cq["message"]["message_id"]
    data = cq["data"]
    responder_callback(cq["id"])

    if data == "precio":
        r = calcular_margen("USDT")
        if r:
            ahorro = ((r['venta'] - r['compra']) / r['venta']) * 100
            editar_mensaje(chat_id, msg_id,
                f"\U0001F4B0 *USDT / VES*\n"
                f"Compra Maker: {r['compra']:.2f} VES (ahorras {ahorro:.2f}%)\n"
                f"Venta Maker:  {r['venta']:.2f} VES\n"
                f"Margen neto: {r['margen']:.2f}%\n"
                f"Ganancia: ${r['ganancia_usd']:.2f} por ${CONFIG['capital']}"
            )
        else:
            editar_mensaje(chat_id, msg_id, "No se pudieron obtener precios.")

    elif data == "arbitraje":
        resultados = []
        for asset in ASSETS_VES:
            r = calcular_margen(asset)
            if r:
                resultados.append(r)
            time.sleep(0.5)
        if not resultados:
            editar_mensaje(chat_id, msg_id, "No se pudieron obtener datos.")
            return
        resultados.sort(key=lambda x: x["margen"], reverse=True)
        lines = [f"\U0001F4CA *Mejor: {resultados[0]['asset']}* | {resultados[0]['margen']:.2f}%\n"]
        for r in resultados:
            signo = "+" if r["margen"] >= 0 else ""
            lines.append(f"{r['asset']}: C {r['compra']:.2f} | V {r['venta']:.2f} | *{signo}{r['margen']:.2f}%*")
        editar_mensaje(chat_id, msg_id, "\n".join(lines))

    elif data == "capital":
        ESTADOS_USUARIO[chat_id] = {"esperando": "capital"}
        _tg_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"\u2699\ufe0f Capital actual: ${CONFIG['capital']}\nResponde con el nuevo monto en USDT:"
        })

    elif data == "status":
        u = ULTIMOS.get("USDT", {})
        editar_mensaje(chat_id, msg_id,
            f"\U0001F4CB *Estado*\nCapital: ${CONFIG['capital']}\n"
            f"Umbral: {CONFIG['margen_objetivo']}%\n"
            f"USDT: {u.get('margen', 'N/A'):.2f}%\n"
            f"C {u.get('compra', 'N/A')} | V {u.get('venta', 'N/A')}"
        )

    elif data == "menu":
        editar_mensaje(chat_id, msg_id,
            f"\U0001F916 *Bot P2P Venezuela*\nCapital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%"
        )


def polling_telegram():
    offset = 0
    while True:
        try:
            r = requests.post(
                f"{API_BASE}{TELEGRAM_TOKEN}/getUpdates",
                json={"offset": offset, "timeout": 15},
                timeout=20
            )
            r.raise_for_status()
            for update in r.json().get("result", []):
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    procesar_callback(update["callback_query"])
                elif "message" in update and update["message"].get("text"):
                    procesar_mensaje(update["message"]["text"], update["message"]["chat"]["id"])
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"TG polling: {e}", flush=True)
        time.sleep(3)
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
# MONITOREO
# ============================================================
def loop_monitoreo():
    print("  Monitoreo cada 60s...", flush=True)
    ciclo = 0
    while True:
        try:
            r = calcular_margen("USDT")
            if r:
                print(f"USDT: C {r['compra']:.2f} | V {r['venta']:.2f} | {r['margen']:.2f}%", flush=True)
                if r["margen"] >= CONFIG["margen_objetivo"]:
                    print(">>> OPORTUNIDAD <<<", flush=True)
                    _tg_call("sendMessage", {
                        "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                        "text": f"\U0001F514 *ALERTA P2P - USDT*\nCompra: {r['compra']:.2f} VES\nVenta: {r['venta']:.2f} VES\nMargen: {r['margen']:.2f}%\nGanancia: ${r['ganancia_usd']:.2f}"
                    })
            ciclo += 1
            if ciclo % 30 == 0:
                enviar_menu(texto=f"\u23F1 *Heartbeat* - {ciclo} ciclos sin novedades")
        except Exception as e:
            print(f"Error: {e}", flush=True)
        time.sleep(60)


if __name__ == "__main__":
    print("=" * 60, flush=True)
    print("  Bot P2P Binance - Venezuela", flush=True)
    print(f"  Capital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%", flush=True)
    print("=" * 60, flush=True)

    if TELEGRAM_TOKEN:
        threading.Thread(target=polling_telegram, daemon=True).start()
        time.sleep(2)
        enviar_menu(texto=f"\U0001F4E1 *Bot P2P Iniciado*\nCapital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%")

    try:
        loop_monitoreo()
    except KeyboardInterrupt:
        print("\nDetenido.", flush=True)
