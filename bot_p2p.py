import json
import os
import ssl as ssl_mod
import threading
import time
import urllib.request
import urllib.error
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# CONFIGURACION (persistente via HF Secrets)
# ============================================================
HF_TOKEN = os.getenv("HF_TOKEN", "")
NAMESPACE = "KelvinMz/VesArbitrajeP2P"

CONFIG = {
    "capital": int(float(os.getenv("CAPITAL", "100"))),
    "margen_objetivo": 0.8,
}


def guardar_capital():
    """Persiste el capital en HF Secrets para que sobreviva a reinicios."""
    if not HF_TOKEN:
        return
    try:
        requests.post(
            f"https://huggingface.co/api/spaces/{NAMESPACE}/secrets",
            headers={"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"},
            json={"key": "CAPITAL", "value": str(int(CONFIG["capital"]))},
            timeout=10
        )
    except Exception as e:
        print(f"Error guardando capital: {e}", flush=True)

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

# Sesion HTTP con SSL verification desactivado (HF bloquea ciertos certificados)
import urllib3
import ssl as ssl_mod
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_sesion = requests.Session()
_sesion.verify = False
# Configurar adapter SSL mas permisivo
_adapter = requests.adapters.HTTPAdapter(
    pool_connections=1, pool_maxsize=1,
    max_retries=urllib3.Retry(total=2, backoff_factor=0.5)
)
_sesion.mount('https://', _adapter)
_sesion.headers.update({
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})
# ============================================================


# ============================================================
# FUNCIONES TELEGRAM
# ============================================================
def _raw_ssl_post(url, json_data, timeout=60):
    """Fallback raw HTTP client para bypassear errores SSL de urllib3."""
    import http.client
    import urllib.parse
    ctx = ssl_mod.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl_mod.CERT_NONE
    try:
        ctx.minimum_version = ssl_mod.TLSVersion.TLSv1_2
    except AttributeError:
        pass
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=0')
    except ssl_mod.SSLError:
        pass
    parsed = urllib.parse.urlparse(url)
    body = json.dumps(json_data).encode()
    headers = {'Content-Type': 'application/json'}
    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, context=ctx, timeout=timeout)
    try:
        conn.request("POST", parsed.path, body=body, headers=headers)
        resp = conn.getresponse()
        return json.loads(resp.read())
    finally:
        conn.close()


# Construir URLs para proxy (HTTP) y directa (HTTPS)
_DIRECT_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
_PROXY_HTTP = (CF_PROXY.replace("https://", "http://") if CF_PROXY else "") if USE_PROXY else ""


def _tg_call(method, payload=None, params=None, ignore_400=False):
    if not TELEGRAM_TOKEN:
        return None

    # Estrategia 1: Proxy via HTTP (evita SSL handshake failures)
    if _PROXY_HTTP:
        proxy_url = f"{_PROXY_HTTP}/telegram-api/{TELEGRAM_TOKEN}/{method}"
        try:
            r = requests.post(proxy_url, json=payload, timeout=30)
            if r.status_code == 400 and ignore_400:
                return None
            r.raise_for_status()
            return r.json()
        except Exception:
            pass

    # Estrategia 2: Directo HTTPS con verify=True
    direct_url = f"{_DIRECT_BASE}/{method}"
    try:
        r = requests.post(direct_url, json=payload, timeout=60)
        if r.status_code == 400 and ignore_400:
            return None
        r.raise_for_status()
        return r.json()
    except requests.exceptions.SSLError:
        pass
    except Exception:
        pass

    # Estrategia 3: Directo sin verify SSL
    try:
        r = requests.post(direct_url, json=payload, timeout=60, verify=False)
        if r.status_code == 400 and ignore_400:
            return None
        r.raise_for_status()
        return r.json()
    except Exception:
        pass

    # Estrategia 4: Raw http.client (bypasses urllib3 completamente)
    try:
        return _raw_ssl_post(direct_url, payload, timeout=60)
    except Exception:
        pass

    print(f"TG {method}: No se pudo conectar", flush=True)
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
    }, ignore_400=True)
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
                guardar_capital()
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
            desc = ((r['venta'] - r['compra']) / r['venta']) * 100
            pri = ((r['venta'] - r['compra']) / r['compra']) * 100
            editar_mensaje(chat_id, msg_id,
                f"\U0001F4B0 *USDT / VES*\n"
                f"Compra: {r['compra']:.2f} VES (desc. {desc:.1f}%)\n"
                f"Venta:  {r['venta']:.2f} VES (prima {pri:.1f}%)\n"
                f"Margen: {r['margen']:.2f}%\n"
                f"Ganancia: ${r['ganancia_usd']:.2f} \u00d7 ${CONFIG['capital']}"
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

        best = resultados[0]
        worst = resultados[-1] if len(resultados) > 1 else best

        # Señales independientes de compra y venta
        mejor_compra = max(resultados, key=lambda x: ((x['venta'] - x['compra']) / x['venta']))
        mejor_venta = max(resultados, key=lambda x: ((x['venta'] - x['compra']) / x['compra']))

        texto = (
            f"\U0001F4CA *Multi-cripto*\n"
            f"\U0001F3C6 *Mejor margen:* {best['asset']} ({best['margen']:+.2f}%)\n"
            f"\U0001F4E5 *Señal COMPRA:* {mejor_compra['asset']} "
            f"(desc. {(mejor_compra['venta']-mejor_compra['compra'])/mejor_compra['venta']*100:.1f}%)\n"
            f"\U0001F4E4 *Señal VENTA:* {mejor_venta['asset']} "
            f"(prima {(mejor_venta['venta']-mejor_venta['compra'])/mejor_venta['compra']*100:.1f}%)\n"
            f"\u26A0 Evitar: {worst['asset']} ({worst['margen']:+.2f}%)\n\n"
            f"Selecciona para detalle:\n"
        )
        kb = {"inline_keyboard": []}
        for r in resultados:
            label = f"{r['asset']} ({r['margen']:+.2f}%)"
            if r == best:
                label = f"\U0001F3C6 {r['asset']} ({r['margen']:+.2f}%)"
            kb["inline_keyboard"].append([
                {"text": label, "callback_data": f"detalle_{r['asset']}"}
            ])
        kb["inline_keyboard"].append([{"text": "\U0001F519 Volver", "callback_data": "menu"}])
        _tg_call("editMessageText", {
            "chat_id": chat_id, "message_id": msg_id,
            "text": texto, "parse_mode": "Markdown",
            "reply_markup": json.dumps(kb)
        }, ignore_400=True)

    elif data.startswith("detalle_"):
        asset = data.split("_", 1)[1]
        r = calcular_margen(asset)
        if not r:
            editar_mensaje(chat_id, msg_id, f"No se pudo obtener precio de {asset}.")
            return
        descuento = ((r['venta'] - r['compra']) / r['venta']) * 100
        prima = ((r['venta'] - r['compra']) / r['compra']) * 100
        best_asset = max(ULTIMOS.items(), key=lambda x: x[1].get("margen", -999))[0] if ULTIMOS else "USDT"
        estrella = " \U0001F3C6" if asset == best_asset else ""
        kb = json.dumps({
            "inline_keyboard": [
                [{"text": "\U0001F4CA Volver", "callback_data": "arbitraje"},
                 {"text": "\U0001F504 Actualizar", "callback_data": f"detalle_{asset}"}]
            ]
        })
        _tg_call("editMessageText", {
            "chat_id": chat_id, "message_id": msg_id,
            "text": (
                f"\U0001F4B0 *{asset} / VES*{estrella}\n"
                f"Compra: {r['compra']:.2f} VES\n"
                f"Venta:   {r['venta']:.2f} VES\n"
                f"Desc. compra: {descuento:.1f}%\n"
                f"Prima venta: {prima:.1f}%\n"
                f"Margen neto: {r['margen']:+.2f}%\n"
                f"Ganancia: ${r['ganancia_usd']:.2f} \u00d7 ${CONFIG['capital']}"
            ),
            "parse_mode": "Markdown", "reply_markup": kb
        })

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


def _get_updates(offset):
    payload = {"offset": offset, "timeout": 10}

    # Proxy via HTTP
    if _PROXY_HTTP:
        try:
            r = requests.post(f"{_PROXY_HTTP}/telegram-api/{TELEGRAM_TOKEN}/getUpdates", json=payload, timeout=20)
            r.raise_for_status()
            return r.json().get("result", [])
        except:
            pass

    # Directo HTTPS
    url = f"{_DIRECT_BASE}/getUpdates"
    for verify in [True, False]:
        try:
            r = requests.post(url, json=payload, timeout=30, verify=verify)
            r.raise_for_status()
            return r.json().get("result", [])
        except:
            pass

    return []


def polling_telegram():
    offset = 0
    while True:
        updates = _get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            if "callback_query" in update:
                procesar_callback(update["callback_query"])
            elif "message" in update and update["message"].get("text"):
                procesar_mensaje(update["message"]["text"], update["message"]["chat"]["id"])
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
