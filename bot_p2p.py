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
    "margen_objetivo": float(os.getenv("UMBRAL", "0.8")),
}


def _guardar_secret(key, value):
    if not HF_TOKEN:
        return
    try:
        requests.post(
            f"https://huggingface.co/api/spaces/{NAMESPACE}/secrets",
            headers={"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"},
            json={"key": key, "value": str(value)},
            timeout=10
        )
    except Exception as e:
        print(f"Error guardando {key}: {e}", flush=True)


def guardar_capital():
    _guardar_secret("CAPITAL", int(CONFIG["capital"]))


def guardar_umbral():
    _guardar_secret("UMBRAL", CONFIG["margen_objetivo"])

COMISION = 0.0025
ULTIMOS = {}
ESTADOS_USUARIO = {}
MARGE_ANTERIOR = {}  # asset -> ultimo margen, para detectar recuperacion
ALERTA_ENVIADA = set()  # assets con alerta ya enviada en este ciclo positivo

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}

URL_BINANCE = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
ASSETS_VES = ["USDT", "BTC", "ETH", "BNB", "USDC", "SOL"]
# ============================================================


# ============================================================
# TELEGRAM - CONFIG
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CF_PROXY = os.getenv("CLOUDFLARE_PROXY", "").rstrip("/")
USE_PROXY = os.getenv("USE_PROXY", "false").lower() == "true"

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
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
    headers = {'Content-Type': 'application/json', 'Content-Length': str(len(body))}
    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, context=ctx, timeout=timeout)
    try:
        conn.request("POST", parsed.path, body=body, headers=headers)
        resp = conn.getresponse()
        return json.loads(resp.read())
    finally:
        conn.close()


_DIRECT_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
_PROXY_URL = CF_PROXY if (CF_PROXY and USE_PROXY) else ""


def _api_call(method, payload, timeout=60):
    """Intenta proxy primero. Si responde (ok o error), devuelve eso.
    Solo si el proxy no responde (timeout/connection error), prueba directo."""
    if _PROXY_URL:
        proxy_url = f"{_PROXY_URL}/telegram-api/{TELEGRAM_TOKEN}/{method}"
        try:
            r = requests.post(proxy_url, json=payload, timeout=timeout)
            return r.json()
        except requests.exceptions.Timeout:
            print(f"  api/{method} proxy timeout", flush=True)
        except Exception as ex:
            print(f"  api/{method} proxy {type(ex).__name__}", flush=True)

    direct = f"{_DIRECT_BASE}/{method}"
    try:
        return _raw_ssl_post(direct, payload, timeout=timeout)
    except Exception as ex:
        print(f"  api/{method} raw {type(ex).__name__}", flush=True)
    try:
        r = requests.post(direct, json=payload, timeout=timeout, verify=False)
        return r.json()
    except Exception as ex:
        print(f"  api/{method} req {type(ex).__name__}", flush=True)
    return None


def _tg_call(method, payload=None, params=None, ignore_400=False):
    if not TELEGRAM_TOKEN:
        return None
    result = _api_call(method, payload, timeout=60)
    if result is None:
        print(f"  ! tg/{method}: sin respuesta", flush=True)
    elif ignore_400 and not result.get("ok") and result.get("error_code") == 400:
        return None
    return result


def enviar_menu(chat_id=None, texto=None):
    cid = chat_id or TELEGRAM_CHAT_ID
    if not texto:
        texto = f"\U0001F916 *Bot P2P Venezuela*\nCapital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%"
    _kb_menu = [
        [{"text": "\U0001F4B0 Precio USDT", "callback_data": "precio"},
         {"text": "\U0001F4CA Multi-cripto", "callback_data": "arbitraje"}],
        [{"text": f"\u2699\ufe0f Capital (${CONFIG['capital']})", "callback_data": "capital"},
         {"text": f"\U0001F3AF Umbral ({CONFIG['margen_objetivo']}%)", "callback_data": "umbral"}],
        [{"text": "\U0001F4CB Estado", "callback_data": "status"},
         {"text": "\U0001F504 Actualizar", "callback_data": "menu"}],
    ]
    kb = json.dumps({"inline_keyboard": _kb_menu})
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
    _kb_menu = [
        [{"text": "\U0001F4B0 Precio USDT", "callback_data": "precio"},
         {"text": "\U0001F4CA Multi-cripto", "callback_data": "arbitraje"}],
        [{"text": f"\u2699\ufe0f Capital (${CONFIG['capital']})", "callback_data": "capital"},
         {"text": f"\U0001F3AF Umbral ({CONFIG['margen_objetivo']}%)", "callback_data": "umbral"}],
        [{"text": "\U0001F4CB Estado", "callback_data": "status"},
         {"text": "\U0001F504 Actualizar", "callback_data": "menu"}],
    ]
    kb = json.dumps({"inline_keyboard": _kb_menu})
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
    tasa_ves = ULTIMOS.get("USDT", {}).get("venta") or None
    ganancia_ves = (ganancia_usd * tasa_ves) if tasa_ves else None
    ULTIMOS[asset] = {"compra": compra, "venta": venta, "margen": margen}
    return {"asset": asset, "compra": compra, "venta": venta, "margen": margen, "ganancia_usd": ganancia_usd, "ganancia_ves": ganancia_ves}
# ============================================================


# ============================================================
# PROCESAR ACTUALIZACIONES TELEGRAM
# ============================================================
def procesar_mensaje(texto, chat_id):
    estado = ESTADOS_USUARIO.get(chat_id, {})
    if estado.get("esperando") == "capital":
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
        ESTADOS_USUARIO.pop(chat_id, None)
        return
    elif estado.get("esperando") == "umbral":
        try:
            nuevo = float(texto.strip())
            if 0 < nuevo <= 100:
                viejo = CONFIG["margen_objetivo"]
                CONFIG["margen_objetivo"] = nuevo
                guardar_umbral()
                ALERTA_ENVIADA.clear()
                enviar_menu(chat_id, f"Umbral actualizado: {viejo:.1f}% -> {nuevo:.1f}%")
            else:
                _tg_call("sendMessage", {"chat_id": chat_id, "text": "Debe estar entre 0 y 100."})
        except ValueError:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Ingresa un numero, ej: 1.5"})
        ESTADOS_USUARIO.pop(chat_id, None)
        return
    enviar_menu(chat_id)


def procesar_callback(cq):
    chat_id = cq["message"]["chat"]["id"]
    msg_id = cq["message"]["message_id"]
    data = cq["data"]
    responder_callback(cq["id"])

    def _linea_ganancia(r):
        v = f"${r['ganancia_usd']:.2f} USD"
        if r.get('ganancia_ves'):
            v += f" | Bs.{r['ganancia_ves']:.2f}"
        return v

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
                f"Ganancia: {_linea_ganancia(r)} \u00d7 ${CONFIG['capital']}"
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
                f"Ganancia: {_linea_ganancia(r)} \u00d7 ${CONFIG['capital']}"
            ),
            "parse_mode": "Markdown", "reply_markup": kb
        })

    elif data == "umbral":
        ESTADOS_USUARIO[chat_id] = {"esperando": "umbral"}
        _tg_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"\U0001F3AF Umbral actual: {CONFIG['margen_objetivo']}%\nResponde con el nuevo umbral (ej: 1.0 para 1%):"
        })

    elif data == "capital":
        ESTADOS_USUARIO[chat_id] = {"esperando": "capital"}
        _tg_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"\u2699\ufe0f Capital actual: ${CONFIG['capital']}\nResponde con el nuevo monto en USDT:"
        })

    elif data == "status":
        lines = [f"\U0001F4CB *Estado*\nCapital: ${CONFIG['capital']}\nUmbral: {CONFIG['margen_objetivo']}%"]
        for a in ASSETS_VES:
            u = ULTIMOS.get(a)
            if u:
                lines.append(f"{a}: {u['margen']:+.2f}%")
        editar_mensaje(chat_id, msg_id, "\n".join(lines))

    elif data == "menu":
        editar_mensaje(chat_id, msg_id,
            f"\U0001F916 *Bot P2P Venezuela*\nCapital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%"
        )


def _get_updates(offset):
    payload = {"offset": offset, "timeout": 10}
    result = _api_call("getUpdates", payload, timeout=30)
    if result and result.get("ok"):
        return result.get("result", [])
    print("  ! getUpdates: fallo", flush=True)
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
            mejores = []
            for asset in ASSETS_VES:
                r = calcular_margen(asset)
                if r:
                    mejores.append(r)
                    print(f"  {asset}: {r['margen']:+.2f}%", flush=True)
                time.sleep(0.5)

            if mejores:
                mejores.sort(key=lambda x: x["margen"], reverse=True)
                top = mejores[0]
                ganancia_ves_top = ""
                if top.get("ganancia_ves"):
                    ganancia_ves_top = f" | Bs.{top['ganancia_ves']:.2f}"

                for r in mejores:
                    ant = MARGE_ANTERIOR.get(r["asset"])
                    MARGE_ANTERIOR[r["asset"]] = r["margen"]
                    if ant is not None and ant < 0 <= r["margen"]:
                        _tg_call("sendMessage", {
                            "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                            "text": (
                                f"\U0001F7E2 *RECUPERACION* {r['asset']}\n"
                                f"Margen pas\u00f3 de {ant:+.2f}% a {r['margen']:+.2f}%\n"
                                f"Compra: {r['compra']:.2f} VES\n"
                                f"Venta:  {r['venta']:.2f} VES"
                            )
                        })

                if top["margen"] >= CONFIG["margen_objetivo"] and top["asset"] not in ALERTA_ENVIADA:
                    ALERTA_ENVIADA.add(top["asset"])
                    print(f">>> OPORTUNIDAD {top['asset']} <<<", flush=True)
                    _tg_call("sendMessage", {
                        "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                        "text": (
                            f"\U0001F514 *ALERTA P2P*\n"
                            f"\U0001F3C6 {top['asset']} | Margen: {top['margen']:+.2f}%\n"
                            f"Compra: {top['compra']:.2f} VES\n"
                            f"Venta:  {top['venta']:.2f} VES\n"
                            f"Ganancia: ${top['ganancia_usd']:.2f}{ganancia_ves_top} \u00d7 ${CONFIG['capital']}"
                        )
                    })
                elif top["margen"] < CONFIG["margen_objetivo"]:
                    ALERTA_ENVIADA.discard(top["asset"])

            ciclo += 1
            if ciclo % 30 == 0 and mejores:
                enviar_menu(texto=(
                    f"\u23F1 *Heartbeat* - {ciclo} ciclos\n"
                    f"\U0001F3C6 Mejor: {top['asset']} ({top['margen']:+.2f}%)"
                ))
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
