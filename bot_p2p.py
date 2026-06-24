import json
import os
import ssl as ssl_mod
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta, date
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# CONFIGURACION (persistente via HF Secrets)
# ============================================================
HF_TOKEN = os.getenv("HF_TOKEN", "")
NAMESPACE = "KelvinMz/VesArbitrajeP2P"

CONFIG_PATH = "config_usuario.json"


def cargar_config_local():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Error cargando config local: {e}", flush=True)
    return {}


_config_local = cargar_config_local()
CONFIG = {
    "capital": float(_config_local.get("capital", os.getenv("CAPITAL", "100"))),
    "margen_objetivo": float(_config_local.get("margen_objetivo", os.getenv("UMBRAL", "0.8"))),
}


def guardar_config_local():
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(CONFIG, f)
    except Exception as e:
        print(f"Error guardando config local: {e}", flush=True)


def guardar_capital():
    guardar_config_local()


def guardar_umbral():
    guardar_config_local()

COMISION = 0.0025
ULTIMOS = {}
ESTADOS_USUARIO = {}
MARGE_ANTERIOR = {}  # asset -> ultimo margen, para detectar recuperacion
ALERTA_ENVIADA = set()  # assets con alerta ya enviada en este ciclo positivo
VPS_EXPIRY = date(2026, 7, 24)
VPS_EXPIRY_NOTIFIED = False

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}

URL_BINANCE = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
ASSETS_VES = ["USDT", "BTC", "ETH", "BNB", "USDC", "SOL"]
HISTORIAL_PATH = "historial_precios.jsonl"

VENEZUELA_TZ = timezone(timedelta(hours=-4))
SLEEP_START = 0  # 12 AM
SLEEP_END = 7    # 7 AM


def en_horario():
    return not (SLEEP_START <= datetime.now(VENEZUELA_TZ).hour < SLEEP_END)
# ============================================================


# ============================================================
# TELEGRAM - CONFIG (exact pattern from youtube-shorts-bot)
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
CLOUDFLARE_PROXY = os.getenv("CLOUDFLARE_PROXY", "https://ves-arbitraje-p2p.kelvinyohan14.workers.dev").rstrip("/")
USE_PROXY = os.getenv("USE_PROXY", "true").lower() == "true"

_PROXY_HTTP = CLOUDFLARE_PROXY
if _PROXY_HTTP.startswith("https://"):
    _PROXY_HTTP = "http://" + _PROXY_HTTP[8:]

_DIRECT_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
if USE_PROXY:
    API_URL = f"{_PROXY_HTTP}/telegram-api"
else:
    API_URL = _DIRECT_API_BASE
# ============================================================


# ============================================================
# FUNCIONES TELEGRAM (exact pattern from youtube-shorts-bot)
# ============================================================
_session = None
def _get_session():
    global _session
    if _session is None:
        from requests.adapters import HTTPAdapter
        _session = requests.Session()
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=1)
        _session.mount("http://", adapter)
        _session.mount("https://", adapter)
    return _session


def _raw_ssl_post(url, json_data, timeout=60):
    import http.client
    import urllib.parse
    ctx = ssl_mod.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl_mod.CERT_NONE
    try:
        ctx.minimum_version = ssl_mod.TLSVersion.TLSv1_2
    except AttributeError:
        ctx.options |= ssl_mod.OP_NO_TLSv1 | ssl_mod.OP_NO_TLSv1_1
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=0')
    except ssl_mod.SSLError:
        pass
    parsed = urllib.parse.urlparse(url)
    body = json.dumps(json_data).encode()
    headers = {'Content-Type': 'application/json', 'Content-Length': str(len(body))}
    conn = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, context=ctx, timeout=timeout)
    path = parsed.path + ('?' + parsed.query if parsed.query else '')
    try:
        conn.request('POST', path, body=body, headers=headers)
        resp = conn.getresponse()
        result = json.loads(resp.read().decode())
        conn.close()
        return result
    except Exception:
        conn.close()
        raise


def _try_url(method, prefix, url, data, timeout):
    sess = _get_session()
    for attempt in range(2):
        try:
            resp = sess.post(url, json=data, timeout=timeout)
            return resp.json(), None
        except Exception as e:
            err_str = str(e)
            if attempt == 1 and data and ('SSLError' in err_str or 'UNEXPECTED_EOF' in err_str or 'EOF occurred' in err_str):
                try:
                    return _raw_ssl_post(url, json_data=data, timeout=timeout), None
                except Exception:
                    pass
            if attempt < 1:
                import time
                time.sleep(1)
    return None, "All retries failed"


def _api_call(method, data=None, timeout=15):
    if USE_PROXY:
        proxy_url = f"{API_URL}/{method}"
        result, error = _try_url(method, "Proxy", proxy_url, data, timeout)
        # Usar respuesta del proxy siempre que haya respuesta (incluso ok=false)
        # Solo intentar directo si el proxy no respondio (timeout/connection error)
        if result:
            return result
        if error:
            direct_url = f"{_DIRECT_API_BASE}/{method}"
            result, error = _try_url(method, "Direct", direct_url, data, timeout)
            if result:
                return result
    else:
        direct_url = f"{_DIRECT_API_BASE}/{method}"
        result, error = _try_url(method, "Direct", direct_url, data, timeout)
        if result:
            return result
    return {"ok": False, "error": "All retries failed"}


def _tg_call(method, payload=None, params=None, ignore_400=False):
    if not TELEGRAM_TOKEN:
        return None
    result = _api_call(method, payload, timeout=15)
    if ignore_400 and not result.get("ok") and result.get("error_code") == 400:
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
         {"text": "\U0001F4C5 Historial", "callback_data": "historial"}],
        [{"text": "\U0001F504 Actualizar", "callback_data": "menu"}],
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
         {"text": "\U0001F4C5 Historial", "callback_data": "historial"}],
        [{"text": "\U0001F504 Actualizar", "callback_data": "menu"}],
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
    payload = {
        "asset": asset,
        "fiat": "VES",
        "page": 1,
        "rows": 10,
        "tradeType": trade_type,
        "payTypes": ["BancoDeVenezuela", "PagoMovil"]
    }
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
        mejor_compra = min(resultados, key=lambda x: x['compra'])
        mejor_venta = max(resultados, key=lambda x: x['venta'])

        texto = (
            f"\U0001F4CA *Multi-cripto*\n"
            f"\U0001F3C6 *Mejor margen:* {best['asset']} ({best['margen']:+.2f}%)\n"
            f"\U0001F4E5 *COMPRAR {mejor_compra['asset']} a:* {mejor_compra['compra']:.2f} VES\n"
            f"\U0001F4E4 *VENDER {mejor_venta['asset']} a:* {mejor_venta['venta']:.2f} VES\n"
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

    elif data == "historial":
        try:
            if not os.path.exists(HISTORIAL_PATH):
                editar_mensaje(chat_id, msg_id, "Aún no hay datos históricos.")
                return
            with open(HISTORIAL_PATH) as f:
                lineas = f.readlines()
            if not lineas:
                editar_mensaje(chat_id, msg_id, "Aún no hay datos históricos.")
                return
            
            hoy_vet = datetime.now(VENEZUELA_TZ).date()
            lineas_hoy = []
            for l in lineas:
                try:
                    d = json.loads(l)
                    dt_ts = datetime.fromisoformat(d["ts"])
                    if dt_ts.date() == hoy_vet:
                        lineas_hoy.append(d)
                except Exception:
                    continue
            
            total_hoy = len(lineas_hoy)
            if total_hoy == 0:
                editar_mensaje(chat_id, msg_id, f"Aún no hay datos históricos para hoy ({hoy_vet}).")
            else:
                primera = lineas_hoy[0]
                ultima = lineas_hoy[-1]
                lines = [
                    f"\U0001F4C5 *Historial Hoy ({hoy_vet})*\n",
                    f"Desde: {primera['ts'][11:19]} VET",
                    f"Hasta: {ultima['ts'][11:19]} VET",
                    f"Total registros: {total_hoy}\n",
                    "*Resumen USDT de Hoy*"
                ]
                usdt_margenes = [r["USDT"]["margen"] for r in lineas_hoy if "USDT" in r]
                if usdt_margenes:
                    lines.append(f"Min: {min(usdt_margenes):+.2f}%")
                    lines.append(f"Máx: {max(usdt_margenes):+.2f}%")
                    lines.append(f"Prom: {sum(usdt_margenes)/len(usdt_margenes):+.2f}%")
                
                activos_resumen = []
                for asset in ASSETS_VES:
                    if asset == "USDT":
                        continue
                    m_asset = [r[asset]["margen"] for r in lineas_hoy if asset in r]
                    if m_asset:
                        activos_resumen.append(f"{asset}: Prom {sum(m_asset)/len(m_asset):+.2f}% (Máx {max(m_asset):+.2f}%)")
                if activos_resumen:
                    lines.append("\n*Otros activos hoy*:")
                    lines.extend(activos_resumen)

                _tg_call("sendMessage", {
                    "chat_id": chat_id, "parse_mode": "Markdown",
                    "text": "\n".join(lines)
                })
        except Exception as e:
            print(f"Error procesando historial: {e}", flush=True)
            editar_mensaje(chat_id, msg_id, "Error al procesar el historial.")

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
    result = _api_call("getUpdates", payload, timeout=20)
    if result and result.get("ok"):
        return result.get("result", [])
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
_ESTADO_SUENO = None  # "dormido" | "despierto" | None


def loop_monitoreo():
    global _ESTADO_SUENO, VPS_EXPIRY_NOTIFIED
    print("  Monitoreo cada 60s...", flush=True)
    ciclo = 0
    while True:
        try:
            activo = en_horario()

            # Notificar vencimiento VPS 5 dias antes
            if not VPS_EXPIRY_NOTIFIED and (VPS_EXPIRY - date.today()).days <= 5:
                VPS_EXPIRY_NOTIFIED = True
                _tg_call("sendMessage", {
                    "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                    "text": (
                        f"\u26A0\ufe0f *El VPS vence en {(VPS_EXPIRY - date.today()).days} d\u00edas*\n"
                        f"Fecha: {VPS_EXPIRY}\n"
                        f"Cancelar en Kamatera para evitar cobros."
                    )
                })

            # Cambio de estado sueño -> despierto
            if activo and _ESTADO_SUENO == "dormido":
                _ESTADO_SUENO = "despierto"
                enviar_menu(texto="\u2600\ufe0f *Buenos d\u00edas!* Bot activo.")
                print("  >>> Buenos dias!", flush=True)
            elif not activo and _ESTADO_SUENO != "dormido":
                _ESTADO_SUENO = "dormido"
                print("  >>> Modo silencioso (12 AM - 7 AM)", flush=True)

            if _ESTADO_SUENO is None:
                _ESTADO_SUENO = "despierto" if activo else "dormido"

            mejores = []
            for asset in ASSETS_VES:
                r = calcular_margen(asset)
                if r:
                    mejores.append(r)
                    print(f"  {asset}: {r['margen']:+.2f}%", flush=True)
                time.sleep(0.5)

            if mejores:
                registro = {"ts": datetime.now(VENEZUELA_TZ).isoformat()}
                for r in mejores:
                    registro[r["asset"]] = {"compra": r["compra"], "venta": r["venta"], "margen": r["margen"]}
                try:
                    # Cargar y podar registros de más de 7 días
                    lineas = []
                    if os.path.exists(HISTORIAL_PATH):
                        with open(HISTORIAL_PATH, "r") as f:
                            lineas = f.readlines()
                    lineas.append(json.dumps(registro) + "\n")
                    
                    limite = datetime.now(VENEZUELA_TZ) - timedelta(days=7)
                    lineas_filtradas = []
                    for l in lineas:
                        try:
                            d = json.loads(l)
                            dt_ts = datetime.fromisoformat(d["ts"])
                            if dt_ts >= limite:
                                lineas_filtradas.append(l)
                        except Exception:
                            continue
                    with open(HISTORIAL_PATH, "w") as f:
                        f.writelines(lineas_filtradas)
                except Exception as e:
                    print(f"Error actualizando historial: {e}", flush=True)

            if not activo:
                time.sleep(60)
                continue

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
        extra = ""
        if not en_horario():
            extra = "\n\U0001F634 Modo silencioso (12AM - 7AM)"
        enviar_menu(texto=f"\U0001F4E1 *Bot P2P Iniciado*\nCapital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%{extra}")

    try:
        loop_monitoreo()
    except KeyboardInterrupt:
        print("\nDetenido.", flush=True)
