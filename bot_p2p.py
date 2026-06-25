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
    "monto_filtro": int(_config_local.get("monto_filtro", 0)),
    "default_crypto": _config_local.get("default_crypto", "USDT"),
}

# Filtros de monto disponibles: 0 = Mayorista (sin filtro), 4000 = ~$5, 8000 = ~$10, 16000 = ~$20
FILTROS_MONTO = [0, 4000, 8000, 16000]


def nombre_filtro(valor=None):
    v = valor if valor is not None else CONFIG["monto_filtro"]
    if v == 0:
        return "Mayorista"
    elif v == 4000:
        return "$5 (4K Bs)"
    elif v == 8000:
        return "$10 (8K Bs)"
    elif v == 16000:
        return "$20 (16K Bs)"
    return f"{v} Bs"


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

COMISION = 0.0025          # 0.25% Binance Maker
COMISION_BANCO = 0.003     # 0.30% Pago Movil BDV
COMISION_TOTAL = COMISION * 2 + COMISION_BANCO  # 0.25% compra + 0.25% venta + 0.30% banco = 0.80%

# Binance P2P requires a minimum advertisement amount of $100 USD for Maker ads
MIN_AD_AMOUNT = 100  # USD

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
ASSETS_VES = ["USDT", "USDC", "BTC", "ETH", "BNB", "SOL"]
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


def _construir_teclado():
    return [
        [{"text": "\U0001F4B0 Precio", "callback_data": "precio"},
         {"text": "\U0001F500 Combo", "callback_data": "combo"},
         {"text": "\U0001F4CA Multi-cripto", "callback_data": "arbitraje"}],
        [{"text": f"\u2699\ufe0f Capital (${CONFIG['capital']:.0f})", "callback_data": "capital"},
         {"text": f"\U0001F3AF Umbral ({CONFIG['margen_objetivo']}%)", "callback_data": "umbral"}],
        [{"text": f"\U0001F6D2 Filtro: {nombre_filtro()}", "callback_data": "ciclo_filtro"},
         {"text": "\U0001F4CB Estado", "callback_data": "status"}],
        [{"text": "\U0001F4C5 Historial", "callback_data": "historial"},
         {"text": "\U0001F504 Actualizar", "callback_data": "menu"}],
    ]


def enviar_menu(chat_id=None, texto=None):
    cid = chat_id or TELEGRAM_CHAT_ID
    if not texto:
        texto = (
            f"\U0001F916 *Bot P2P Venezuela*\n"
            f"Capital: ${CONFIG['capital']:.0f} | Umbral: {CONFIG['margen_objetivo']}%\n"
            f"Filtro: {nombre_filtro()} | Comisiones: {COMISION_TOTAL*100:.2f}%"
        )
    kb = json.dumps({"inline_keyboard": _construir_teclado()})
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
    kb = json.dumps({"inline_keyboard": _construir_teclado()})
    _tg_call("editMessageText", {
        "chat_id": chat_id, "message_id": message_id,
        "text": texto, "parse_mode": "Markdown", "reply_markup": kb
    }, ignore_400=True)
# ============================================================


# ============================================================
# API BINANCE P2P
# ============================================================
def obtener_precio_p2p(trade_type, asset="USDT", trans_amount=0):
    payload = {
        "asset": asset,
        "fiat": "VES",
        "page": 1,
        "rows": 10,
        "tradeType": trade_type,
        "payTypes": ["BancoDeVenezuela", "PagoMovil"]
    }
    if trans_amount > 0:
        payload["transAmount"] = str(trans_amount)
    try:
        resp = requests.post(URL_BINANCE, json=payload, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        anuncios = resp.json().get("data", [])
        if len(anuncios) < 1:
            return None
        # Promedio posiciones 1-3 (índices 0 a 2) para obtener el precio competitivo real del mercado
        start = 0
        end = min(3, len(anuncios))
        precios = [float(anuncios[i]["adv"]["price"]) for i in range(start, end)]
        return sum(precios) / len(precios) if precios else None
    except Exception as e:
        print(f"[{asset}/{trade_type}] Error: {e}", flush=True)
        return None


def calcular_margen(asset, trans_amount=None):
    # En Binance P2P:
    # - "BUY" retorna anuncios donde Makers VENDEN (precio alto para el Taker que compra).
    # - "SELL" retorna anuncios donde Makers COMPRAN (precio bajo para el Taker que vende).
    # Para un Maker: compras barato (apareces en SELL) y vendes caro (apareces en BUY).
    monto = trans_amount if trans_amount is not None else CONFIG["monto_filtro"]
    maker_venta = obtener_precio_p2p("BUY", asset, monto)   # Precio de venta Maker (alto) / Compra Taker
    maker_compra = obtener_precio_p2p("SELL", asset, monto)  # Precio de compra Maker (bajo) / Venta Taker
    if maker_venta is None or maker_compra is None:
        return None
    
    # Maker Margen
    ganancia_neta_maker = (maker_venta - maker_compra) - (maker_compra * COMISION) - (maker_venta * COMISION) - (maker_compra * COMISION_BANCO)
    margen_maker = (ganancia_neta_maker / maker_compra) * 100
    ganancia_usd_maker = CONFIG["capital"] * (margen_maker / 100)
    
    # Taker Margen (compra a maker_venta, vende a maker_compra)
    ganancia_neta_taker = (maker_compra - maker_venta) - (maker_venta * COMISION) - (maker_compra * COMISION) - (maker_venta * COMISION_BANCO)
    margen_taker = (ganancia_neta_taker / maker_venta) * 100
    ganancia_usd_taker = CONFIG["capital"] * (margen_taker / 100)

    tasa_ves = ULTIMOS.get("USDT", {}).get("venta") or None
    ganancia_ves_maker = (ganancia_usd_maker * tasa_ves) if tasa_ves else None
    ganancia_ves_taker = (ganancia_usd_taker * tasa_ves) if tasa_ves else None

    ULTIMOS[asset] = {"compra": maker_compra, "venta": maker_venta, "margen": margen_maker}
    return {
        "asset": asset, "compra": maker_compra, "venta": maker_venta,
        "margen": margen_maker, "ganancia_usd": ganancia_usd_maker, "ganancia_ves": ganancia_ves_maker,
        "taker_compra": maker_venta, "taker_venta": maker_compra,
        "taker_margen": margen_taker, "taker_ganancia_usd": ganancia_usd_taker, "taker_ganancia_ves": ganancia_ves_taker,
        "filtro": nombre_filtro(monto)
    }
# ============================================================
# Función adicional: cálculo del combo USDT compra → USDC venta y análisis de opciones

def calcular_margen_usdt_usdc(trans_amount=None):
    """Calcular margen al comprar USDT y vender USDC.
    Devuelve un dict con precios, margen y ganancias estimadas tanto Maker como Taker.
    """
    monto = trans_amount if trans_amount is not None else CONFIG["monto_filtro"]
    # Maker: compra USDT (aparece en SELL), vende USDC (aparece en BUY)
    usdt_compra_maker = obtener_precio_p2p("SELL", "USDT", monto)
    usdc_venta_maker = obtener_precio_p2p("BUY", "USDC", monto)
    
    # Taker: compra USDT (compra del Maker Venta/BUY), vende USDC (vende al Maker Compra/SELL)
    usdt_compra_taker = obtener_precio_p2p("BUY", "USDT", monto)
    usdc_venta_taker = obtener_precio_p2p("SELL", "USDC", monto)
    
    if usdt_compra_maker is None or usdc_venta_maker is None or usdt_compra_taker is None or usdc_venta_taker is None:
        return None
        
    # Maker Margen
    ganancia_neta_maker = (usdc_venta_maker - usdt_compra_maker) - (usdt_compra_maker * COMISION) - (usdc_venta_maker * COMISION) - (usdt_compra_maker * COMISION_BANCO)
    margen_maker = (ganancia_neta_maker / usdt_compra_maker) * 100
    ganancia_usd_maker = CONFIG["capital"] * (margen_maker / 100)
    
    # Taker Margen
    ganancia_neta_taker = (usdc_venta_taker - usdt_compra_taker) - (usdt_compra_taker * COMISION) - (usdc_venta_taker * COMISION) - (usdt_compra_taker * COMISION_BANCO)
    margen_taker = (ganancia_neta_taker / usdt_compra_taker) * 100
    ganancia_usd_taker = CONFIG["capital"] * (margen_taker / 100)
    
    tasa_ves = ULTIMOS.get("USDT", {}).get("venta")
    ganancia_ves_maker = (ganancia_usd_maker * tasa_ves) if tasa_ves else None
    ganancia_ves_taker = (ganancia_usd_taker * tasa_ves) if tasa_ves else None
    
    return {
        "asset": "USDT→USDC",
        "compra_usdt": usdt_compra_maker,
        "venta_usdc": usdc_venta_maker,
        "margen": margen_maker,
        "ganancia_usd": ganancia_usd_maker,
        "ganancia_ves": ganancia_ves_maker,
        "taker_compra_usdt": usdt_compra_taker,
        "taker_venta_usdc": usdc_venta_taker,
        "taker_margen": margen_taker,
        "taker_ganancia_usd": ganancia_usd_taker,
        "taker_ganancia_ves": ganancia_ves_taker,
        "filtro": nombre_filtro(monto)
    }

def analizar_opciones(trans_amount=None):
    """Evalúa margen para USDT, USDC y la combinación USDT→USDC, y devuelve la lista ordenada."""
    resultados = []
    for asset in ["USDT", "USDC"]:
        r = calcular_margen(asset, trans_amount)
        if r:
            resultados.append(r)
    combo = calcular_margen_usdt_usdc(trans_amount)
    if combo:
        resultados.append(combo)
    resultados.sort(key=lambda x: x["margen"], reverse=True)
    return resultados

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
        asset = CONFIG.get("default_crypto", "USDT")
        r = calcular_margen(asset)
        if r:
            pri = ((r['venta'] - r['compra']) / r['compra']) * 100
            rentable = "\u2705 RENTABLE" if r['margen'] > 0 else "\u274C NO RENTABLE"
            
            # Taker calculations
            taker_rentable = "\u2705 RENTABLE" if r['taker_margen'] > 0 else "\u274C NO RENTABLE"
            taker_ves_str = f" | Bs.{r['taker_ganancia_ves']:.2f}" if r.get('taker_ganancia_ves') else ""

            editar_mensaje(chat_id, msg_id,
                f"\U0001F4B0 *{asset} / VES* ({r['filtro']})\n\n"
                f"\U0001F4A1 *MODO MAKER (Anuncios)*\n"
                f"Compra Maker: {r['compra']:.2f} VES\n"
                f"Venta Maker:  {r['venta']:.2f} VES\n"
                f"Spread bruto: {pri:.2f}%\n"
                f"Margen neto: *{r['margen']:+.2f}%* {rentable}\n"
                f"Ganancia: {_linea_ganancia(r)} \u00d7 ${CONFIG['capital']:.0f}\n\n"
                f"\u26A0 *MODO TAKER (Instantáneo)*\n"
                f"Compra Taker: {r['taker_compra']:.2f} VES\n"
                f"Venta Taker:  {r['taker_venta']:.2f} VES\n"
                f"Margen neto: *{r['taker_margen']:+.2f}%* {taker_rentable}\n"
                f"Ganancia: ${r['taker_ganancia_usd']:.2f} USD{taker_ves_str} \u00d7 ${CONFIG['capital']:.0f}\n\n"
                f"Comisiones: -{COMISION_TOTAL*100:.2f}% (Binance {COMISION*200:.1f}% + Banco {COMISION_BANCO*100:.1f}%)"
            )
        else:
            editar_mensaje(chat_id, msg_id, f"No se pudieron obtener precios de {asset}.")

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
        rentables = [r for r in resultados if r['margen'] > 0]

        texto = (
            f"\U0001F4CA *Multi-cripto* ({nombre_filtro()})\n"
            f"Comisiones totales: {COMISION_TOTAL*100:.2f}%\n\n"
        )
        if rentables:
            texto += f"\u2705 *{len(rentables)} RENTABLE(S):*\n"
            for r in rentables:
                texto += f"  {r['asset']}: {r['margen']:+.2f}% (${r['ganancia_usd']:.2f})\n"
        else:
            texto += "\u274C *Ninguno rentable ahora*\n"

        texto += (
            f"\n\U0001F3C6 *Mejor:* {best['asset']} ({best['margen']:+.2f}%)\n"
            f"\u26A0 *Peor:* {worst['asset']} ({worst['margen']:+.2f}%)\n\n"
            f"Selecciona para detalle y predeterminar:\n"
        )
        kb = {"inline_keyboard": []}
        for r in resultados:
            icono = "\u2705" if r['margen'] > 0 else "\u274C"
            label = f"{icono} {r['asset']} ({r['margen']:+.2f}%) ${r['ganancia_usd']:.2f}"
            if r == best:
                label = f"\U0001F3C6 {r['asset']} ({r['margen']:+.2f}%) ${r['ganancia_usd']:.2f}"
            kb["inline_keyboard"].append([
                {"text": label, "callback_data": f"detalle_{r['asset']}"}
            ])
        kb["inline_keyboard"].append([{"text": "\U0001F519 Volver", "callback_data": "menu"}])
        _tg_call("editMessageText", {
            "chat_id": chat_id, "message_id": msg_id,
            "text": texto, "parse_mode": "Markdown",
            "reply_markup": json.dumps(kb)
        }, ignore_400=True)

    elif data == "combo":
        r = calcular_margen_usdt_usdc()
        if r:
            rentable = "\u2705 RENTABLE" if r['margen'] > 0 else "\u274C NO RENTABLE"
            taker_rentable = "\u2705 RENTABLE" if r['taker_margen'] > 0 else "\u274C NO RENTABLE"
            taker_ves_str = f" | Bs.{r['taker_ganancia_ves']:.2f}" if r.get('taker_ganancia_ves') else ""
            
            kb = json.dumps({
                "inline_keyboard": [
                    [{"text": "🏠 Inicio", "callback_data": "menu"},
                     {"text": "🔄 Actualizar", "callback_data": "combo"}]
                ]
            })
            _tg_call("editMessageText", {
                "chat_id": chat_id, "message_id": msg_id,
                "text": (
                    f"\U0001F500 *Combo USDT \u2794 USDC / VES* ({r['filtro']})\n\n"
                    f"\U0001F4A1 *MODO MAKER (Anuncios)*\n"
                    f"Compra Maker (USDT): {r['compra_usdt']:.2f} VES\n"
                    f"Venta Maker (USDC):  {r['venta_usdc']:.2f} VES\n"
                    f"Margen neto: *{r['margen']:+.2f}%* {rentable}\n"
                    f"Ganancia: {_linea_ganancia(r)} \u00d7 ${CONFIG['capital']:.0f}\n\n"
                    f"\u26A0 *MODO TAKER (Instantáneo)*\n"
                    f"Compra Taker (USDT): {r['taker_compra_usdt']:.2f} VES\n"
                    f"Venta Taker (USDC):  {r['taker_venta_usdc']:.2f} VES\n"
                    f"Margen neto: *{r['taker_margen']:+.2f}%* {taker_rentable}\n"
                    f"Ganancia: ${r['taker_ganancia_usd']:.2f} USD{taker_ves_str} \u00d7 ${CONFIG['capital']:.0f}\n\n"
                    f"Comisiones: -{COMISION_TOTAL*100:.2f}% (Binance {COMISION*200:.1f}% + Banco {COMISION_BANCO*100:.1f}%)\n\n"
                    f"📌 Compra USDT (Maker) y venta USDC (Maker)."
                ),
                "parse_mode": "Markdown",
                "reply_markup": kb
            }, ignore_400=True)
        else:
            editar_mensaje(chat_id, msg_id, "No se pudieron obtener precios del combo.")

    elif data.startswith("detalle_"):
        asset = data.split("_", 1)[1]
        
        # Guardar como criptomoneda predeterminada
        CONFIG["default_crypto"] = asset
        guardar_config_local()

        r = calcular_margen(asset)
        if not r:
            editar_mensaje(chat_id, msg_id, f"No se pudo obtener precio de {asset}.")
            return
        spread_bruto = ((r['venta'] - r['compra']) / r['compra']) * 100
        rentable = "\u2705 RENTABLE" if r['margen'] > 0 else "\u274C NO RENTABLE"
        best_asset = max(ULTIMOS.items(), key=lambda x: x[1].get("margen", -999))[0] if ULTIMOS else "USDT"
        estrella = " \U0001F3C6" if asset == best_asset else ""

        # Taker calculations
        taker_rentable = "\u2705 RENTABLE" if r['taker_margen'] > 0 else "\u274C NO RENTABLE"
        taker_ves_str = f" | Bs.{r['taker_ganancia_ves']:.2f}" if r.get('taker_ganancia_ves') else ""

        kb = json.dumps({
            "inline_keyboard": [
                [{"text": "🏠 Inicio", "callback_data": "menu"},
                 {"text": "🔙 Volver", "callback_data": "arbitraje"}],
                [{"text": "🔄 Actualizar", "callback_data": f"detalle_{asset}"}]
            ]
        })
        _tg_call("editMessageText", {
            "chat_id": chat_id, "message_id": msg_id,
            "text": (
                f"\U0001F4B0 *{asset} / VES*{estrella} ({r['filtro']})\n\n"
                f"\U0001F4A1 *MODO MAKER (Anuncios)*\n"
                f"Compra Maker: {r['compra']:.2f} VES\n"
                f"Venta Maker:  {r['venta']:.2f} VES\n"
                f"Spread bruto: {spread_bruto:.2f}%\n"
                f"Margen neto: *{r['margen']:+.2f}%* {rentable}\n"
                f"Ganancia: {_linea_ganancia(r)} \u00d7 ${CONFIG['capital']:.0f}\n\n"
                f"\u26A0 *MODO TAKER (Instantáneo)*\n"
                f"Compra Taker: {r['taker_compra']:.2f} VES\n"
                f"Venta Taker:  {r['taker_venta']:.2f} VES\n"
                f"Margen neto: *{r['taker_margen']:+.2f}%* {taker_rentable}\n"
                f"Ganancia: ${r['taker_ganancia_usd']:.2f} USD{taker_ves_str} \u00d7 ${CONFIG['capital']:.0f}\n\n"
                f"Comisiones: -{COMISION_TOTAL*100:.2f}% (Binance {COMISION*200:.1f}% + Banco {COMISION_BANCO*100:.1f}%)\n\n"
                f"📌 *{asset}* se ha guardado como tu cripto predeterminada."
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

    elif data == "ciclo_filtro":
        idx_actual = FILTROS_MONTO.index(CONFIG["monto_filtro"]) if CONFIG["monto_filtro"] in FILTROS_MONTO else 0
        idx_nuevo = (idx_actual + 1) % len(FILTROS_MONTO)
        viejo = nombre_filtro()
        CONFIG["monto_filtro"] = FILTROS_MONTO[idx_nuevo]
        guardar_config_local()
        ALERTA_ENVIADA.clear()
        editar_mensaje(chat_id, msg_id,
            f"\U0001F6D2 *Filtro actualizado*\n"
            f"{viejo} \u27A1 {nombre_filtro()}\n\n"
            f"El bot ahora calcula precios para ordenes de *{nombre_filtro()}*.\n"
            f"Comisiones totales: {COMISION_TOTAL*100:.2f}%"
        )

    elif data == "status":
        lines = [
            f"\U0001F4CB *Estado*",
            f"Capital: ${CONFIG['capital']:.0f}",
            f"Umbral: {CONFIG['margen_objetivo']}%",
            f"Filtro: {nombre_filtro()}",
            f"Comisiones: {COMISION_TOTAL*100:.2f}% (Binance {COMISION*200:.1f}% + Banco {COMISION_BANCO*100:.1f}%)\n",
        ]
        rentables = 0
        for a in ASSETS_VES:
            u = ULTIMOS.get(a)
            if u:
                icono = "\u2705" if u['margen'] > 0 else "\u274C"
                lines.append(f"{icono} {a}: {u['margen']:+.2f}%")
                if u['margen'] > 0:
                    rentables += 1
        if rentables > 0:
            lines.append(f"\n\U0001F4B0 *{rentables} activo(s) rentable(s)*")
        else:
            lines.append(f"\n\u23F3 Sin oportunidades ahora")
        editar_mensaje(chat_id, msg_id, "\n".join(lines))

    elif data == "menu":
        editar_mensaje(chat_id, msg_id,
            f"\U0001F916 *Bot P2P Venezuela*\n"
            f"Capital: ${CONFIG['capital']:.0f} | Umbral: {CONFIG['margen_objetivo']}%\n"
            f"Filtro: {nombre_filtro()} | Comisiones: {COMISION_TOTAL*100:.2f}%"
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
                
                # Para alertas de oportunidad, filtramos solo estables (USDT, USDC)
                estables = [r for r in mejores if r["asset"] in ["USDT", "USDC"]]
                top = estables[0] if estables else None
                top_general = mejores[0]
                
                ganancia_ves_top = ""
                if top and top.get("ganancia_ves"):
                    ganancia_ves_top = f" | Bs.{top['ganancia_ves']:.2f}"

                for r in mejores:
                    if r["asset"] not in ["USDT", "USDC"]:
                        continue
                    ant = MARGE_ANTERIOR.get(r["asset"])
                    MARGE_ANTERIOR[r["asset"]] = r["margen"]
                    if ant is not None and ant < 0 <= r["margen"]:
                        _tg_call("sendMessage", {
                            "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                            "text": (
                                f"\U0001F7E2 *RECUPERACION* {r['asset']}\n"
                                f"Margen pasó de {ant:+.2f}% a {r['margen']:+.2f}%\n"
                                f"Compra: {r['compra']:.2f} VES\n"
                                f"Venta:  {r['venta']:.2f} VES"
                            )
                        })

                if top and top["margen"] >= CONFIG["margen_objetivo"] and top["asset"] not in ALERTA_ENVIADA:
                    ALERTA_ENVIADA.add(top["asset"])
                    print(f">>> OPORTUNIDAD {top['asset']} <<<", flush=True)
                    spread_bruto = ((top['venta'] - top['compra']) / top['compra']) * 100
                    
                    limite_anuncio = f"{CONFIG['monto_filtro']} Bs" if CONFIG['monto_filtro'] > 0 else "libre (ej. 400 Bs)"
                    ves_ganancia_str = f"Bs.{top['ganancia_ves']:.2f}" if top.get("ganancia_ves") else f"Bs.{(top['ganancia_usd'] * top['compra']):.2f}"
                    
                    # Cómputo del escenario alternativo
                    comparativo_str = ""
                    maker_compra = top['compra']
                    if CONFIG["monto_filtro"] > 0:
                        # Filtrado fraccionado: comparar con vender todo de golpe (Mayorista)
                        venta_may = obtener_precio_p2p("BUY", top['asset'], trans_amount=0)
                        if venta_may:
                            gan_net_may = (venta_may - maker_compra) - (maker_compra * COMISION) - (venta_may * COMISION) - (maker_compra * COMISION_BANCO)
                            margen_may = (gan_net_may / maker_compra) * 100
                            gan_usd_may = CONFIG["capital"] * (margen_may / 100)
                            gan_ves_may = gan_usd_may * maker_compra
                            comparativo_str = (
                                f"\n\U0001F504 *Escenario Alternativo (Vender todo de golpe - Mayorista):*\n"
                                f"- Vender todo a: *{venta_may:.2f} VES*\n"
                                f"- Margen Neto: {margen_may:+.2f}%\n"
                                f"- Ganancia Neta Total: *${gan_usd_may:.2f} USD* (~Bs.{gan_ves_may:.2f})\n"
                            )
                    else:
                        # Filtrado Mayorista: comparar con vender fraccionado a $10 (8000 Bs)
                        venta_frac = obtener_precio_p2p("BUY", top['asset'], trans_amount=8000)
                        if venta_frac:
                            gan_net_frac = (venta_frac - maker_compra) - (maker_compra * COMISION) - (venta_frac * COMISION) - (maker_compra * COMISION_BANCO)
                            margen_frac = (gan_net_frac / maker_compra) * 100
                            gan_usd_frac = CONFIG["capital"] * (margen_frac / 100)
                            gan_ves_frac = gan_usd_frac * maker_compra
                            comparativo_str = (
                                f"\n\U0001F504 *Escenario Alternativo (Vender fraccionado de a $10 / 8K Bs):*\n"
                                f"- Vender en partes a: *{venta_frac:.2f} VES*\n"
                                f"- Margen Neto: {margen_frac:+.2f}%\n"
                                f"- Ganancia Neta Total: *${gan_usd_frac:.2f} USD* (~Bs.{gan_ves_frac:.2f})\n"
                            )

                    warning_msg = ""
                    if CONFIG["capital"] < MIN_AD_AMOUNT:
                        warning_msg = "\n> ⚠️ *Advertencia:* Tu capital es inferior al mínimo requerido ($100) para crear anuncios Maker. Considera operar como *Taker* o aumentar tu capital antes de publicar anuncios."

                    texto_alerta = (
                        f"\U0001F514 *ALERTA P2P DETALLADA* ({nombre_filtro()})\n"
                        f"Activo: *{top['asset']}* | Margen neto actual: *{top['margen']:+.2f}%* \u2705 RENTABLE\n\n"
                        f"\U0001F449 *Pasos sugeridos para tu configuración actual ({nombre_filtro()}):*\n"
                        f"1\ufe0f\u20e3 *COMPRA:* Publica un anuncio de *COMPRA* (pagas Bs y recibes {top['asset']}) con precio fijado en *{top['compra']:.2f} VES*.\n"
                        f"   - Configura el límite mínimo de tu anuncio en: *{limite_anuncio}*.\n"
                        f"2\ufe0f\u20e3 *VENTA:* Publica un anuncio de *VENTA* (recibes Bs en BDV/Pago Móvil) con precio fijado en *{top['venta']:.2f} VES*.\n"
                        f"   - Ganancia neta estimada con tu capital: *${top['ganancia_usd']:.2f} USD* (~{ves_ganancia_str})\n"
                        f"{comparativo_str}\n"
                        f"\u2139 *Detalle financiero de la alerta:*\n"
                        f"- Spread Bruto: {spread_bruto:.2f}%\n"
                        f"- Comisiones Totales: -{COMISION_TOTAL*100:.2f}% (Binance Maker 0.50% + BDV 0.30%)\n"
                        f"{warning_msg}"
                    )
                    
                    _tg_call("sendMessage", {
                        "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                        "text": texto_alerta
                    })
                elif top and top["margen"] < CONFIG["margen_objetivo"]:
                    ALERTA_ENVIADA.discard(top["asset"])

            ciclo += 1
            if ciclo % 30 == 0 and mejores:
                enviar_menu(texto=(
                    f"\u23F1 *Heartbeat* - {ciclo} ciclos\n"
                    f"\U0001F3C6 Mejor: {top_general['asset']} ({top_general['margen']:+.2f}%)"
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
            extra = " (modo silencioso)"
        print(f"Iniciando monitor{extra}...", flush=True)
        loop_monitoreo()
    else:
        print("Telegram token no configurado. Solo modo monitor", flush=True)
        loop_monitoreo()
