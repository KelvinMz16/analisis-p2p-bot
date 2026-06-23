import requests
import time
import os
import json
import threading
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}

URL_API = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
ASSETS_VES = ["USDT", "BTC", "ETH", "BNB", "USDC", "DAI", "BUSD"]
# ============================================================


# ============================================================
# API BINANCE P2P
# ============================================================
def obtener_precio_p2p(trade_type, asset="USDT"):
    payload = {
        "asset": asset, "fiat": "VES",
        "page": 1, "rows": 10,
        "tradeType": trade_type
    }
    try:
        resp = requests.post(URL_API, json=payload, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        anuncios = data.get("data", [])
        if len(anuncios) < 5:
            return None
        precios = [float(anuncios[i]["adv"]["price"]) for i in range(2, 5)]
        return sum(precios) / len(precios)
    except requests.exceptions.Timeout:
        print(f"[{asset}/{trade_type}] Timeout")
    except requests.exceptions.RequestException as e:
        print(f"[{asset}/{trade_type}] Error de red: {e}")
    except (KeyError, ValueError, IndexError) as e:
        print(f"[{asset}/{trade_type}] Error al procesar: {e}")
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
    return {
        "asset": asset, "compra": compra, "venta": venta,
        "margen": margen, "ganancia_usd": ganancia_usd
    }


def monitorear_usdt():
    r = calcular_margen("USDT")
    if r is None:
        print("No se pudieron obtener tasas. Reintentando en 60s...")
        return
    ahorro = ((r['venta'] - r['compra']) / r['venta']) * 100
    print("=" * 55)
    print(f"  USDT/VES  -  Capital: ${CONFIG['capital']}")
    print(f"  Compra Maker: {r['compra']:.2f} VES  (ahorras {ahorro:.2f}% vs comprar directo)")
    print(f"  Venta Maker:  {r['venta']:.2f} VES  (ganas {r['margen']:.2f}% = ${r['ganancia_usd']:.2f})")
    print("=" * 55)
    if r["margen"] >= CONFIG["margen_objetivo"]:
        print("  >>>  OPORTUNIDAD DETECTADA  <<<")
        enviar_telegram(
            f"\U0001F514 *ALERTA P2P - Oportunidad USDT*\n"
            f"Compra Maker: {r['compra']:.2f} VES\n"
            f"Venta Maker:  {r['venta']:.2f} VES\n"
            f"Margen: {r['margen']:.2f}%\n"
            f"Ganancia: ${r['ganancia_usd']:.2f} por ${CONFIG['capital']}"
        )
# ============================================================


# ============================================================
# TELEGRAM - MENSAJES CON BOTONES
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")

def boton(texto, callback_data):
    return {"text": texto, "callback_data": callback_data}

def menu_principal():
    capital = CONFIG['capital']
    return json.dumps({
        "inline_keyboard": [
            [
                boton("💰 Precio USDT", "precio"),
                boton("📊 Multi-cripto", "arbitraje"),
            ],
            [
                boton(f"⚙️ Capital (${capital})", "capital"),
                boton("📋 Estado", "status"),
            ],
            [
                boton("🔄 Actualizar menú", "menu"),
            ]
        ]
    })


def enviar_telegram(mensaje, chat_id=None, reply_markup=None):
    if not TELEGRAM_TOKEN:
        return False
    cid = chat_id or TELEGRAM_CHAT_ID
    if not cid:
        return False
    try:
        payload = {"chat_id": cid, "text": mensaje, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup if isinstance(reply_markup, str) else json.dumps(reply_markup)
        requests.post(
            f"{TELEGRAM_API_BASE}/bot{TELEGRAM_TOKEN}/sendMessage",
            json=payload, timeout=10
        )
        return True
    except Exception as e:
        print(f"Error al enviar Telegram: {e}")
        return False


def responder_callback(callback_id, texto=None):
    try:
        payload = {"callback_query_id": callback_id}
        if texto:
            payload["text"] = texto
        requests.post(
            f"{TELEGRAM_API_BASE}/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
            json=payload, timeout=10
        )
    except Exception as e:
        print(f"Error answerCallbackQuery: {e}")


def editar_mensaje(chat_id, message_id, texto, reply_markup=None):
    try:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": texto, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup if isinstance(reply_markup, str) else json.dumps(reply_markup)
        requests.post(
            f"{TELEGRAM_API_BASE}/bot{TELEGRAM_TOKEN}/editMessageText",
            json=payload, timeout=10
        )
    except Exception as e:
        print(f"Error editMessageText: {e}")
# ============================================================


# ============================================================
# TELEGRAM - MANEJO DE ACTUALIZACIONES
# ============================================================
ESTADOS_USUARIO = {}  # {chat_id: {"esperando": "capital"}}

def procesar_actualizacion(update):
    """Procesa un update de Telegram (mensaje o callback_query)."""
    cq = update.get("callback_query")
    if cq:
        return procesar_callback(cq)

    msg = update.get("message")
    if not msg or not msg.get("text"):
        return

    chat_id = msg["chat"]["id"]
    texto = msg["text"].strip()

    # Verificar si el usuario esta en medio de un dialogo
    estado = ESTADOS_USUARIO.get(chat_id)
    if estado and estado.get("esperando") == "capital":
        try:
            nuevo = float(texto)
            if nuevo > 0:
                viejo = CONFIG["capital"]
                CONFIG["capital"] = nuevo
                enviar_telegram(f"Capital actualizado: ${viejo:.0f} -> ${nuevo:.0f}", chat_id, menu_principal())
            else:
                enviar_telegram("El capital debe ser mayor a 0.", chat_id)
        except ValueError:
            enviar_telegram("Ingresa un numero valido, ej: 150", chat_id)
        finally:
            ESTADOS_USUARIO.pop(chat_id, None)
        return

    # Comandos de texto
    if texto.lower() == "/start":
        enviar_telegram(
            f"\U0001F916 *Bot P2P Venezuela activo*\n"
            f"Capital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%\n\n"
        , chat_id, menu_principal())


def procesar_callback(cq):
    chat_id = cq["message"]["chat"]["id"]
    message_id = cq["message"]["message_id"]
    data = cq["data"]

    responder_callback(cq["id"])

    if data == "precio":
        r = calcular_margen("USDT")
        if r:
            ahorro = ((r['venta'] - r['compra']) / r['venta']) * 100
            editar_mensaje(chat_id, message_id,
                f"💰 *USDT / VES*\n"
                f"Compra Maker: {r['compra']:.2f} VES (ahorras {ahorro:.2f}%)\n"
                f"Venta Maker:  {r['venta']:.2f} VES\n"
                f"Margen neto: {r['margen']:.2f}%\n"
                f"Ganancia: ${r['ganancia_usd']:.2f} por ${CONFIG['capital']}",
                menu_principal()
            )
        else:
            editar_mensaje(chat_id, message_id, "No se pudieron obtener precios.", menu_principal())

    elif data == "arbitraje":
        resultados = []
        for asset in ASSETS_VES:
            r = calcular_margen(asset)
            if r:
                resultados.append(r)
            time.sleep(0.5)

        if not resultados:
            editar_mensaje(chat_id, message_id, "No se pudieron obtener datos.", menu_principal())
            return

        resultados.sort(key=lambda x: x["margen"], reverse=True)
        mejor = resultados[0]
        lines = [f"📊 *Mejor: {mejor['asset']}* | {mejor['margen']:.2f}%\n"]
        for r in resultados:
            signo = "+" if r["margen"] >= 0 else ""
            lines.append(
                f"{r['asset']}: C {r['compra']:.2f} | V {r['venta']:.2f} | *{signo}{r['margen']:.2f}%*"
            )
        editar_mensaje(chat_id, message_id, "\n".join(lines), menu_principal())

    elif data == "capital":
        ESTADOS_USUARIO[chat_id] = {"esperando": "capital"}
        enviar_telegram(
            f"⚙️ Capital actual: ${CONFIG['capital']}\n"
            f"Responde con el nuevo monto en USDT:",
            chat_id
        )

    elif data == "status":
        ultimo = ULTIMOS.get("USDT", {})
        editar_mensaje(chat_id, message_id,
            f"📋 *Estado del Bot*\n"
            f"Capital: ${CONFIG['capital']}\n"
            f"Umbral: {CONFIG['margen_objetivo']}%\n"
            f"Último USDT: {ultimo.get('margen', 'N/A'):.2f}%\n"
            f"Compra: {ultimo.get('compra', 'N/A')} | Venta: {ultimo.get('venta', 'N/A')}",
            menu_principal()
        )

    elif data == "menu":
        editar_mensaje(chat_id, message_id,
            "\U0001F916 *Bot P2P Venezuela*\n"
            f"Capital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%",
            menu_principal()
        )


def polling_telegram():
    offset = 0
    while True:
        try:
            r = requests.get(
                f"{TELEGRAM_API_BASE}/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 15},
                timeout=20
            )
            r.raise_for_status()
            for update in r.json().get("result", []):
                offset = update["update_id"] + 1
                procesar_actualizacion(update)
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            print(f"Error en polling Telegram: {e}")
        time.sleep(3)


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

def iniciar_servidor():
    HTTPServer(("0.0.0.0", 7860), HealthHandler).serve_forever()

threading.Thread(target=iniciar_servidor, daemon=True).start()
# ============================================================


# ============================================================
# BUCLE PRINCIPAL
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  Bot de Monitoreo P2P Binance - Venezuela")
    print(f"  Capital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%")
    print("  Consultando cada 60s | Botones via Telegram")
    print("=" * 60)

    if TELEGRAM_TOKEN:
        threading.Thread(target=polling_telegram, daemon=True).start()
        time.sleep(2)
        enviar_telegram(
            f"\U0001F4E1 *Bot P2P Iniciado*\n"
            f"Capital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%",
            reply_markup=menu_principal()
        )

    ciclo = 0
    while True:
        try:
            monitorear_usdt()
            ciclo += 1
            if ciclo % 30 == 0:
                enviar_telegram(
                    f"\u23F1 *Heartbeat* - {ciclo} ciclos sin novedades",
                    reply_markup=menu_principal()
                )
        except KeyboardInterrupt:
            print("\nBot detenido.")
            enviar_telegram("\u274C *Bot P2P Detenido*")
            break
        except Exception as e:
            print(f"Error en bucle principal: {e}")
        time.sleep(60)
