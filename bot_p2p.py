import json
import os
import re
import ssl as ssl_mod
import threading
import time
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# CONFIGURACION (persistente via HF Secrets)
# ============================================================
HF_TOKEN = os.getenv("HF_TOKEN", "")
NAMESPACE = "KelvinMz/VesArbitrajeP2P"

# Supabase configuration (read from HF Secrets / environment variables)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "historical_prices")

if SUPABASE_KEY:
    # Clean any whitespace or quotes that might have been pasted
    SUPABASE_KEY = SUPABASE_KEY.strip().strip('"').strip("'")
    print(f"[DEBUG] SUPABASE_KEY length: {len(SUPABASE_KEY)}, starts with: {SUPABASE_KEY[:6]}..., ends with: ...{SUPABASE_KEY[-6:]}", flush=True)
else:
    print("[DEBUG] SUPABASE_KEY is None or empty", flush=True)

if SUPABASE_URL:
    SUPABASE_URL = SUPABASE_URL.strip().strip('"').strip("'")
    print(f"[DEBUG] SUPABASE_URL: {SUPABASE_URL}", flush=True)


def supabase_upsert(record):
    """Insert a record into the Supabase table.
    The function uses the REST API with the provided URL and API key.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase credentials not set in environment")
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = requests.post(url, json=record, headers=headers)
    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"[DEBUG] Supabase POST failed. Response: {resp.text}", flush=True)
        raise e
    return resp.json()

def supabase_select_all():
    """Retrieve all records from the Supabase table.
    Returns a list of dicts.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase credentials not set in environment")
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?select=*"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    resp = requests.get(url, headers=headers)
    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"[DEBUG] Supabase GET failed. Response: {resp.text}", flush=True)
        raise e
    return resp.json()


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
    "monto_filtro": int(_config_local.get("monto_filtro", os.getenv("MONTO_FILTRO", "0"))),
    "default_crypto": _config_local.get("default_crypto", os.getenv("DEFAULT_CRYPTO", "USDT")),
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


def _sync_hf_secret(key, value):
    if not HF_TOKEN:
        return
    try:
        url = f"https://huggingface.co/api/spaces/{NAMESPACE}/secrets"
        headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/json"}
        requests.post(url, json={"key": key, "value": str(value)}, headers=headers, timeout=10)
    except Exception as e:
        print(f"Error sync secret {key}: {e}", flush=True)


def guardar_config_local():
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(CONFIG, f)
        _sync_hf_secret("CAPITAL", str(CONFIG["capital"]))
        _sync_hf_secret("UMBRAL", str(CONFIG["margen_objetivo"]))
        _sync_hf_secret("MONTO_FILTRO", str(CONFIG["monto_filtro"]))
        _sync_hf_secret("DEFAULT_CRYPTO", str(CONFIG["default_crypto"]))
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
ALERTA_ENVIADA_DEX = set()  # redes DEX con alerta ya enviada
MARGE_ANTERIOR_DEX = {}     # network_key -> ultimo margen neto DEX
VPS_EXPIRY = date(2026, 7, 24)
VPS_EXPIRY_NOTIFIED = False

# Monitoreo BCV via @subastasBCV
_BCV_BANCOS_CONFIG = {
    "bdv":  {"nombres": ["BDV", "BANCO DE VENEZUELA"], "label": "BDV"},
    "mer":  {"nombres": ["MERCANTIL"], "label": "Mercantil"},
    "bnc":  {"nombres": ["BNC"], "label": "BNC"},
    "bbva": {"nombres": ["BBVA", "PROVINCIAL"], "label": "BBVA"},
    "bt":   {"nombres": ["TRINIDAD", "BANCO DE LA TRINIDAD", "BT"], "label": "BT"},
}
# Estado actual por banco: banco_key -> {"activo": bool/None, "datos": dict, "ultimo_post_ts": float}
_BCV_ESTADOS = {}
_BCV_ULTIMO_POST_ID = None   # ultimo post_id procesado
_BCV_STALE_TIMEOUT = 7200    # 2h sin posts -> considerar cerrado
_BCV_FALSE_POSITIVE_TERMS = [
    "falso positivo", "desactivar el bot", "error del bot",
    "prueba temporal", "revisando bot",
]

# Hourly aggregation containers (populated from Supabase history)
compras_por_hora = defaultdict(list)  # key: hour 0-23, value: list of buy prices
ventas_por_hora = defaultdict(list)   # key: hour 0-23, value: list of sell prices

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
        [{"text": "🌌 DEX Multi-Red", "callback_data": "dex_multired"}],
        [{"text": f"\u2699\ufe0f Capital (${CONFIG['capital']:.0f})", "callback_data": "capital"},
         {"text": f"\U0001F3AF Umbral ({CONFIG['margen_objetivo']}%)", "callback_data": "umbral"}],
        [{"text": f"\U0001F6D2 Filtro: {nombre_filtro()}", "callback_data": "ciclo_filtro"},
         {"text": "\U0001F4CB Estado", "callback_data": "status"}],
        [{"text": "\U0001F4C5 Historial", "callback_data": "historial"},
         {"text": "\U0001F4C8 Horarios", "callback_data": "mejor_horario"}],
        [{"text": "\U0001F504 Actualizar", "callback_data": "menu"}],
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


# ============================================================
# ARBITRAJE DEX MULTI-RED
# ============================================================
# Configuración de redes soportadas para arbitraje Spot vs DEX
DEX_NETWORKS = {
    "SOL": {
        "nombre": "Solana",
        "chain_id": "solana",
        "token_address": "So11111111111111111111111111111111111111112",
        "coingecko_id": "solana",
        "costo_retiro_usd": 0.03,
        "swap_fee_pct": 0.002,
        "wallet": "Phantom (Solana)",
        "dex_principales": "Jupiter/Orca/Raydium",
    },
    "POL": {
        "nombre": "Polygon",
        "chain_id": "polygon",
        "token_address": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",
        "coingecko_id": "polygon-ecosystem-token",
        "costo_retiro_usd": 0.01,
        "swap_fee_pct": 0.003,
        "wallet": "Phantom (Polygon)",
        "dex_principales": "QuickSwap/Uniswap",
    },
    "BNB": {
        "nombre": "BNB Chain",
        "chain_id": "bsc",
        "token_address": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "coingecko_id": "binancecoin",
        "costo_retiro_usd": 0.28,
        "swap_fee_pct": 0.002,
        "wallet": "Phantom (BSC)",
        "dex_principales": "PancakeSwap/Uniswap",
    },
}


# Mapeo de coingecko_id → símbolo Bybit
_CG_TO_BYBIT = {
    "solana": "SOLUSDT",
    "polygon-ecosystem-token": "POLUSDT",
    "binancecoin": "BNBUSDT",
}
_BYBIT_CACHE = {"data": None, "ts": 0}


def _fetch_spot_single(network_key):
    """Fallback individual si el batch falla."""
    cfg = DEX_NETWORKS.get(network_key)
    if not cfg or not cfg.get("coingecko_id"):
        return None
    symbol = _CG_TO_BYBIT.get(cfg["coingecko_id"])
    if not symbol:
        return None
    try:
        resp = requests.get(
            f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}",
            headers=HEADERS, timeout=5
        )
        resp.raise_for_status()
        items = resp.json().get("result", {}).get("list", [])
        if items:
            return float(items[0].get("lastPrice", 0))
    except Exception as e:
        print(f"[Bybit/{network_key}] Error: {e}", flush=True)
    return None


def _fetch_all_spot_prices():
    """Batch vía Bybit (filtra 3 símbolos), cacheado 10s."""
    ahora = time.time()
    if _BYBIT_CACHE["data"] and (ahora - _BYBIT_CACHE["ts"]) < 10:
        return _BYBIT_CACHE["data"]
    wanted = set(_CG_TO_BYBIT.values())
    try:
        resp = requests.get(
            "https://api.bybit.com/v5/market/tickers?category=spot",
            headers=HEADERS, timeout=5
        )
        resp.raise_for_status()
        result = resp.json()
        data = {}
        for item in result.get("result", {}).get("list", []):
            sym = item.get("symbol")
            if sym in wanted:
                for cg_id, s in _CG_TO_BYBIT.items():
                    if s == sym:
                        data[cg_id] = {"usd": float(item.get("lastPrice", 0))}
                        break
        _BYBIT_CACHE["data"] = data
        _BYBIT_CACHE["ts"] = ahora
        return data
    except Exception as e:
        print(f"[Bybit/batch] Error: {e}", flush=True)
        return _BYBIT_CACHE["data"] or {}


def obtener_precio_spot(network_key):
    cfg = DEX_NETWORKS.get(network_key)
    if not cfg or not cfg.get("coingecko_id"):
        return None
    data = _fetch_all_spot_prices()
    price = float(data.get(cfg["coingecko_id"], {}).get("usd", 0))
    if price > 0:
        print(f"  [Spot/{network_key}] Bybit: ${price:.4f}", flush=True)
        return price
    time.sleep(0.5)
    price = _fetch_spot_single(network_key)
    if price and price > 0:
        return price
    print(f"  [Spot/{network_key}] Sin precio disponible", flush=True)
    return None


# Rangos de precio para filtrar pares falsos en DexScreener
PRICE_RANGES = {
    "SOL": (50, 300),     # SOL tipico $60-200
    "POL": (0.01, 3),     # POL tipico $0.02-1
    "BNB": (200, 1500),   # BNB tipico $300-800
}


def obtener_precio_dex(network_key):
    """Precio DEX vía DexScreener, filtrando pares con precio fuera de rango."""
    cfg = DEX_NETWORKS.get(network_key)
    if not cfg:
        return None
    min_p, max_p = PRICE_RANGES.get(network_key, (0, float("inf")))
    url = f"https://api.dexscreener.com/latest/dex/tokens/{cfg['token_address']}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        resp.raise_for_status()
        pairs = resp.json().get("pairs", [])
        best_price = None
        best_liq = 0
        for p in pairs:
            if p.get("chainId") != cfg["chain_id"]:
                continue
            if p.get("quoteToken", {}).get("symbol") not in ["USDC", "USDT"]:
                continue
            price_str = p.get("priceUsd")
            if not price_str:
                continue
            price = float(price_str)
            if not (min_p <= price <= max_p):
                continue
            liq_raw = p.get("liquidity", {})
            liq = float(liq_raw.get("usd", 0)) if isinstance(liq_raw, dict) else 0
            if liq > best_liq:
                best_price = price
                best_liq = liq
        if best_price:
            print(f"  [DEX/{network_key}] DexScreener most-liquid: ${best_price:.4f} (liq: ${best_liq:.0f})", flush=True)
            return best_price
    except Exception as e:
        print(f"[DEX/{network_key}] Error: {e}", flush=True)
    return None


def calcular_arbitraje_dex(network_key):
    """Calcula la oportunidad de arbitraje Spot vs DEX para una red específica."""
    cfg = DEX_NETWORKS.get(network_key)
    if not cfg:
        return None
    spot = obtener_precio_spot(network_key)
    dex = obtener_precio_dex(network_key)
    if not spot or not dex:
        return None

    diff = dex - spot
    pct_bruto = (diff / spot) * 100

    costo_retiro = cfg["costo_retiro_usd"]
    costo_swap = cfg["swap_fee_pct"] * CONFIG["capital"]
    costos_totales = costo_retiro + costo_swap

    ganancia_bruta = (CONFIG["capital"] / spot) * dex - CONFIG["capital"]
    ganancia_neta = ganancia_bruta - costos_totales
    pct_neto = (ganancia_neta / CONFIG["capital"]) * 100 if CONFIG["capital"] > 0 else 0

    return {
        "network": network_key,
        "nombre": cfg["nombre"],
        "spot": spot,
        "dex": dex,
        "diff": diff,
        "pct_bruto": pct_bruto,
        "costos": costos_totales,
        "ganancia_bruta": ganancia_bruta,
        "ganancia_neta": ganancia_neta,
        "pct_neto": pct_neto,
        "wallet": cfg["wallet"],
        "dex_principales": cfg["dex_principales"],
        "costo_retiro": costo_retiro,
    }
# ============================================================


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


def analizar_historico_horarios():
    """Carga el historial de Supabase y agrupa compras/ventas por hora."""
    # Cargar historial desde Supabase
    try:
        registros = supabase_select_all()
    except Exception as e:
        print(f"Error al cargar historial de Supabase: {e}", flush=True)
        registros = []

    if not registros:
        return None

    # Reiniciar los contenedores antes de poblarlos
    compras_por_hora.clear()
    ventas_por_hora.clear()

    for rec in registros:
        # Soporte para campo 'fecha' o 'created_at'
        timestamp = rec.get("fecha") or rec.get("created_at")
        if not timestamp:
            continue
        try:
            if isinstance(timestamp, str):
                # Eliminar sufijo Z o zona horaria si es necesario
                ts_clean = timestamp.replace("Z", "+00:00")
                hour = datetime.fromisoformat(ts_clean).hour
            else:
                hour = int(timestamp)
        except Exception:
            continue
        compra = rec.get("compra") or rec.get("maker_compra") or rec.get("precio_compra")
        venta = rec.get("venta") or rec.get("maker_venta") or rec.get("precio_venta")
        if compra is not None:
            try:
                compras_por_hora[hour].append(float(compra))
            except (ValueError, TypeError):
                pass
        if venta is not None:
            try:
                ventas_por_hora[hour].append(float(venta))
            except (ValueError, TypeError):
                pass

    resumen = {}
    for h in range(24):
        c_list = compras_por_hora[h]
        v_list = ventas_por_hora[h]
        if c_list and v_list:
            resumen[h] = {
                "avg_compra": sum(c_list) / len(c_list),
                "avg_venta": sum(v_list) / len(v_list),
                "muestras": len(c_list)
            }

    if not resumen:
        return None

    return resumen


def generar_reporte_horarios():
    datos = analizar_historico_horarios()
    if not datos:
        return "⚠️ *No hay suficientes datos* históricos para realizar el análisis de horarios aún. Se necesitan al menos 24 horas de ejecución continua del bot."
        
    # Encontrar mejores horas individuales
    mejor_maker_compra = min(datos.keys(), key=lambda h: datos[h]["avg_compra"])
    mejor_maker_venta = max(datos.keys(), key=lambda h: datos[h]["avg_venta"])
    
    # Calcular promedios por bloques
    bloques = {
        "Mañana (6 AM - 12 PM)": list(range(6, 12)),
        "Tarde (12 PM - 6 PM)": list(range(12, 18)),
        "Noche (6 PM - 12 AM)": list(range(18, 24)),
        "Madrugada (12 AM - 6 AM)": list(range(0, 6)),
    }
    
    bloque_stats = {}
    for nombre, horas in bloques.items():
        c_vals = []
        v_vals = []
        for h in horas:
            if h in datos:
                c_vals.append(datos[h]["avg_compra"])
                v_vals.append(datos[h]["avg_venta"])
        if c_vals and v_vals:
            bloque_stats[nombre] = {
                "compra": sum(c_vals) / len(c_vals),
                "venta": sum(v_vals) / len(v_vals)
            }
            
    texto = (
        f"📊 *ANÁLISIS DE HORARIOS (USDT)*\n"
        f"Basado en los últimos 7 días de historial.\n\n"
        f"🟢 *Mejor hora para COMPRAR (anuncio Maker):*\n"
        f"   ➔ *{mejor_maker_compra:02d}:00 VET* (Promedio: {datos[mejor_maker_compra]['avg_compra']:.2f} VES)\n"
        f"🔴 *Mejor hora para VENDER (anuncio Maker):*\n"
        f"   ➔ *{mejor_maker_venta:02d}:00 VET* (Promedio: {datos[mejor_maker_venta]['avg_venta']:.2f} VES)\n\n"
        f"📈 *Promedios por Bloques de Horas:*\n"
    )
    
    for bloque, stats in bloque_stats.items():
        spread_bruto = ((stats['venta'] - stats['compra']) / stats['compra']) * 100
        texto += (
            f"📍 *{bloque}*\n"
            f"   • Compra Maker: {stats['compra']:.2f} VES\n"
            f"   • Venta Maker:  {stats['venta']:.2f} VES\n"
            f"   • Spread Promedio: {spread_bruto:+.2f}%\n"
        )
        
    texto += (
        f"\n💡 *Tip P2P:* En las mañanas suele haber menor volumen y precios de compra más económicos. "
        f"En las noches suele aumentar la demanda, elevando los precios de venta."
    )
    return texto


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


# ============================================================
# AUTO-REFRESH DE PANELES (se actualizan sin presionar boton)
# ============================================================
AUTO_REFRESH = {}  # (chat_id, msg_id) -> {"data": str, "ticks": int}


def _linea_ganancia(r):
    v = f"${r['ganancia_usd']:.2f} USD"
    if r.get('ganancia_ves'):
        v += f" | Bs.{r['ganancia_ves']:.2f}"
    return v


def registrar_refresh(chat_id, msg_id, data):
    AUTO_REFRESH[(chat_id, msg_id)] = {"data": data, "ticks": 5}


def limpiar_refresh(chat_id, msg_id=None):
    if msg_id:
        AUTO_REFRESH.pop((chat_id, msg_id), None)
    else:
        for k in list(AUTO_REFRESH):
            if k[0] == chat_id:
                del AUTO_REFRESH[k]


def _render_precio(chat_id, msg_id):
    asset = CONFIG.get("default_crypto", "USDT")
    r = calcular_margen(asset)
    if r:
        pri = ((r['venta'] - r['compra']) / r['compra']) * 100
        rentable = "\u2705 RENTABLE" if r['margen'] > 0 else "\u274C NO RENTABLE"
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
            f"Comisiones: -{COMISION_TOTAL*100:.2f}% (Binance {COMISION*200:.1f}% + Banco {COMISION_BANCO*100:.1f}%)")
    else:
        editar_mensaje(chat_id, msg_id, f"No se pudieron obtener precios de {asset}.")
    registrar_refresh(chat_id, msg_id, "precio")


def _render_arbitraje(chat_id, msg_id):
    resultados = []
    for asset in ASSETS_VES:
        r = calcular_margen(asset)
        if r:
            resultados.append(r)
        time.sleep(0.5)
    if not resultados:
        editar_mensaje(chat_id, msg_id, "No se pudieron obtener datos.")
        registrar_refresh(chat_id, msg_id, "arbitraje")
        return
    resultados.sort(key=lambda x: x["margen"], reverse=True)
    best = resultados[0]
    worst = resultados[-1] if len(resultados) > 1 else best
    rentables = [r for r in resultados if r['margen'] > 0]
    texto = (
        f"\U0001F4CA *Multi-cripto* ({nombre_filtro()})\n"
        f"Comisiones totales: {COMISION_TOTAL*100:.2f}%\n\n")
    if rentables:
        texto += f"\u2705 *{len(rentables)} RENTABLE(S):*\n"
        for r in rentables:
            texto += f"  {r['asset']}: {r['margen']:+.2f}% (${r['ganancia_usd']:.2f})\n"
    else:
        texto += "\u274C *Ninguno rentable ahora*\n"
    texto += (
        f"\n\U0001F3C6 *Mejor:* {best['asset']} ({best['margen']:+.2f}%)\n"
        f"\u26A0 *Peor:* {worst['asset']} ({worst['margen']:+.2f}%)\n\n"
        f"Selecciona para detalle y predeterminar:\n")
    kb = {"inline_keyboard": []}
    for r in resultados:
        icono = "\u2705" if r['margen'] > 0 else "\u274C"
        label = f"{icono} {r['asset']} ({r['margen']:+.2f}%) ${r['ganancia_usd']:.2f}"
        if r == best:
            label = f"\U0001F3C6 {r['asset']} ({r['margen']:+.2f}%) ${r['ganancia_usd']:.2f}"
        kb["inline_keyboard"].append([{"text": label, "callback_data": f"detalle_{r['asset']}"}])
    kb["inline_keyboard"].append([{"text": "\U0001F519 Volver", "callback_data": "menu"}])
    _tg_call("editMessageText", {
        "chat_id": chat_id, "message_id": msg_id,
        "text": texto, "parse_mode": "Markdown",
        "reply_markup": json.dumps(kb)
    }, ignore_400=True)
    registrar_refresh(chat_id, msg_id, "arbitraje")


def _render_combo(chat_id, msg_id):
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
            "parse_mode": "Markdown", "reply_markup": kb
        }, ignore_400=True)
    else:
        editar_mensaje(chat_id, msg_id, "No se pudieron obtener precios del combo.")
    registrar_refresh(chat_id, msg_id, "combo")


def _render_detalle(chat_id, msg_id, asset):
    CONFIG["default_crypto"] = asset
    guardar_config_local()
    r = calcular_margen(asset)
    if not r:
        editar_mensaje(chat_id, msg_id, f"No se pudo obtener precio de {asset}.")
        registrar_refresh(chat_id, msg_id, f"detalle_{asset}")
        return
    spread_bruto = ((r['venta'] - r['compra']) / r['compra']) * 100
    rentable = "\u2705 RENTABLE" if r['margen'] > 0 else "\u274C NO RENTABLE"
    best_asset = max(ULTIMOS.items(), key=lambda x: x[1].get("margen", -999))[0] if ULTIMOS else "USDT"
    estrella = " \U0001F3C6" if asset == best_asset else ""
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
    }, ignore_400=True)
    registrar_refresh(chat_id, msg_id, f"detalle_{asset}")


def _render_estado(chat_id, msg_id):
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
    registrar_refresh(chat_id, msg_id, "status")


def _render_dex(chat_id, msg_id):
    msg = f"🌌 *Arbitraje DEX Multi-Red* (Capital: ${CONFIG['capital']:.0f})\n\n"
    fallos = []
    for nk in DEX_NETWORKS:
        r = calcular_arbitraje_dex(nk)
        if r:
            icono = "🟢" if r["ganancia_neta"] > 0 else "🔴"
            msg += (f"{icono} *{r['network']}* ({r['nombre']})\n"
                    f"   Spot: ${r['spot']:.4f} | DEX: ${r['dex']:.4f}\n"
                    f"   Spread: {r['pct_bruto']:+.2f}% | Costos: ${r['costos']:.3f}\n"
                    f"   *Neto: ${r['ganancia_neta']:.4f}* ({r['pct_neto']:+.2f}%)\n"
                    f"   Wallet: {r['wallet']} | DEX: {r['dex_principales']}\n\n")
        else:
            fallos.append(nk)
        time.sleep(0.3)
    if fallos:
        msg += f"⚠️ Sin datos: {', '.join(fallos)}\n"
    if not msg.strip(" *\n"):
        msg = "⚠️ No se pudieron obtener precios de ninguna red."
    else:
        msg += "\n_Tip: Usa el botón Operar de Phantom para hacer swap._"
    kb = json.dumps({
        "inline_keyboard": [
            [{"text": "🏠 Inicio", "callback_data": "menu"},
             {"text": "🔄 Actualizar", "callback_data": "dex_multired"}]
        ]
    })
    _tg_call("editMessageText", {
        "chat_id": chat_id, "message_id": msg_id,
        "text": msg, "parse_mode": "Markdown",
        "reply_markup": kb
    }, ignore_400=True)
    registrar_refresh(chat_id, msg_id, "dex_multired")


def _refrescar_paneles():
    for (chat_id, msg_id), info in list(AUTO_REFRESH.items()):
        info["ticks"] -= 1
        if info["ticks"] <= 0:
            del AUTO_REFRESH[(chat_id, msg_id)]
            continue
        cb_data = info["data"]
        try:
            if cb_data == "precio":
                _render_precio(chat_id, msg_id)
            elif cb_data == "arbitraje":
                _render_arbitraje(chat_id, msg_id)
            elif cb_data == "combo":
                _render_combo(chat_id, msg_id)
            elif cb_data.startswith("detalle_"):
                asset = cb_data.split("_", 1)[1]
                _render_detalle(chat_id, msg_id, asset)
            elif cb_data == "status":
                _render_estado(chat_id, msg_id)
            elif cb_data == "dex_multired":
                _render_dex(chat_id, msg_id)
        except Exception as e:
            print(f"Error refrescando {cb_data}: {e}", flush=True)


# ============================================================
# PROCESADOR DE CALLBACKS
# ============================================================
def procesar_callback(cq):
    chat_id = cq["message"]["chat"]["id"]
    msg_id = cq["message"]["message_id"]
    data = cq["data"]
    responder_callback(cq["id"])

    if data == "precio":
        _render_precio(chat_id, msg_id)

    elif data == "arbitraje":
        _render_arbitraje(chat_id, msg_id)

    elif data == "combo":
        _render_combo(chat_id, msg_id)

    elif data.startswith("detalle_"):
        asset = data.split("_", 1)[1]
        _render_detalle(chat_id, msg_id, asset)

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
            lineas = []
            try:
                registros = supabase_select_all()
                lineas = [json.dumps(r) + "\n" for r in registros]
            except Exception as e:
                print(f"Supabase lectura fallo, usando JSONL: {e}", flush=True)
                if os.path.exists(HISTORIAL_PATH):
                    with open(HISTORIAL_PATH, "r") as f:
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
                usdt_margenes = [r["USDT"]["margen"] for r in lineas_hoy if isinstance(r.get("USDT"), dict)]
                if usdt_margenes:
                    lines.append(f"Min: {min(usdt_margenes):+.2f}%")
                    lines.append(f"Máx: {max(usdt_margenes):+.2f}%")
                    lines.append(f"Prom: {sum(usdt_margenes)/len(usdt_margenes):+.2f}%")
                
                activos_resumen = []
                for asset in ASSETS_VES:
                    if asset == "USDT":
                        continue
                    m_asset = [r[asset]["margen"] for r in lineas_hoy if isinstance(r.get(asset), dict)]
                    if m_asset:
                        activos_resumen.append(f"{asset}: Prom {sum(m_asset)/len(m_asset):+.2f}% (Máx {max(m_asset):+.2f}%)")
                if activos_resumen:
                    lines.append("\n*Otros activos hoy*:")
                    lines.extend(activos_resumen)

                editar_mensaje(chat_id, msg_id, "\n".join(lines))
        except Exception as e:
            print(f"Error procesando historial: {e}", flush=True)
            editar_mensaje(chat_id, msg_id, "Error al procesar el historial.")

    elif data == "mejor_horario":
        try:
            reporte = generar_reporte_horarios()
            kb = json.dumps({
                "inline_keyboard": [
                    [{"text": "🏠 Inicio", "callback_data": "menu"},
                     {"text": "🔄 Actualizar", "callback_data": "mejor_horario"}]
                ]
            })
            _tg_call("editMessageText", {
                "chat_id": chat_id, "message_id": msg_id,
                "text": reporte, "parse_mode": "Markdown",
                "reply_markup": kb
            }, ignore_400=True)
        except Exception as e:
            print(f"Error procesando mejor_horario: {e}", flush=True)
            editar_mensaje(chat_id, msg_id, "Error al procesar el análisis de horarios.")

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
        _render_estado(chat_id, msg_id)

    elif data == "dex_multired":
        try:
            _render_dex(chat_id, msg_id)
        except Exception as e:
            print(f"Error en callback dex_multired: {e}", flush=True)
            editar_mensaje(chat_id, msg_id, "Error al calcular arbitraje DEX Multi-Red.")

    elif data == "menu":
        limpiar_refresh(chat_id)
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
# HEALTH SERVER (requerido por Hugging Face Spaces)
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status": "running"}')
    def log_message(self, *a):
        pass

def _run_health(port):
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        print(f"Health server listo en puerto {port}", flush=True)
        server.serve_forever()
    except Exception as e:
        print(f"Health server puerto {port} error: {e}", flush=True)

threading.Thread(target=_run_health, args=(8080,), daemon=True).start()
threading.Thread(target=_run_health, args=(7860,), daemon=True).start()
time.sleep(0.3)
# ============================================================


# ============================================================
# MONITOREO
# ============================================================
_ESTADO_SUENO = None  # "dormido" | "despierto" | None


def _normalizar_texto(text):
    """Elimina acentos/combining marks y chars invisibles.
    Esto permite que regex como 'MINIMO' funcione con 'MÍNIMO'."""
    import unicodedata
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = text.replace('\u200b', '')  # zero-width space
    return text


def _es_falso_positivo(msg):
    """Detecta si un post es una nota del admin (falso positivo, prueba, etc)."""
    lower = msg.lower()
    return any(term in lower for term in _BCV_FALSE_POSITIVE_TERMS)


def _identificar_banco(msg):
    """Detecta que banco(s) menciona el post. Retorna primera coincidencia o None."""
    for bk, cfg in _BCV_BANCOS_CONFIG.items():
        for nombre in cfg["nombres"]:
            if nombre in msg:
                return bk
    return None


def scrape_subastasbcv():
    """Scrapea @subastasBCV en busca de estado de intervencion por banco.
    Retorna dict con keys: banco(str), activo(bool), tasa(str), minimo(str),
    maximo(str), hora(str) o None si no encuentra cambios.
    Actualiza _BCV_ESTADOS[banco]['ultimo_post_ts'] al ver cualquier post."""
    global _BCV_ULTIMO_POST_ID
    try:
        r = requests.get("https://t.me/s/subastasBCV", timeout=15)
        html = r.text

        # Buscar todos los posts con data-post
        posts = re.findall(
            r'<div class="tgme_widget_message_wrap[^"]*">.*?data-post="([^"]+)".*?'
            r'<div class="tgme_widget_message_text[^"]*" dir="auto">(.*?)</div>',
            html, re.DOTALL
        )

        ahora = time.time()

        for post_id, msg_html in posts:
            msg = re.sub(r'<[^>]+>', '', msg_html)
            msg = msg.replace('&#36;', '$').replace('&#036;', '$')
            msg = msg.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
            msg = msg.replace('&#39;', "'").replace('&quot;', '"')
            msg = _normalizar_texto(msg)

            # Identificar que banco(s) menciona
            banco = _identificar_banco(msg)
            if not banco:
                continue

            # Actualizar timestamp de este banco
            est = _estado_bcv(banco)
            est["ultimo_post_ts"] = ahora

            # Saltar falsos positivos (notas del admin)
            if _es_falso_positivo(msg):
                continue

            # Activo — buscar estructura con TASA/MIN/MAX/HORA
            if "INTERVENCI" in msg and "ACTIVA" in msg:
                tasa = re.search(r'TASA:?\s*Bs\.?\s*([\d.,]+)', msg)
                minimo = re.search(r'(?:MINIMO|MIN|M[NI]NIMO):?\s*(\d{1,4}(?:[\d.,]*))', _normalizar_texto(msg))
                if not minimo:
                    minimo = re.search(r'MINIMO:\s*(\d[\d.]*)', msg)
                maximo = re.search(r'(?:MAXIMO|MAX|M[ÁA]XIMO):?\s*(\d{1,4}(?:[\d.,]*))', _normalizar_texto(msg))
                if not maximo:
                    maximo = re.search(r'MAXIMO:\s*(\d[\d.]*)', msg)
                hora = re.search(r'HORA:?\s*([\d]{1,2}:[\d]{2})', msg)
                # Fallback: buscar montos seguidos de signo $
                if not minimo or not maximo:
                    nums = re.findall(r'(\d+\.?\d*)\s*\$', msg)
                    if len(nums) >= 2:
                        if not minimo:
                            minimo = type('obj', (object,), {'group': lambda s, i: nums[0]})()
                        if not maximo:
                            maximo = type('obj', (object,), {'group': lambda s, i: nums[-1]})()

                data = {
                    "banco": banco,
                    "activo": True,
                    "tasa": tasa.group(1) if tasa else "",
                    "minimo": minimo.group(1) if minimo else "",
                    "maximo": maximo.group(1) if maximo else "",
                    "hora": hora.group(1) if hora else "",
                    "post_id": post_id,
                }

                if data["post_id"] != _BCV_ULTIMO_POST_ID:
                    _BCV_ULTIMO_POST_ID = data["post_id"]
                    return data

            # Cerrada
            if "INTERVENCI" in msg and "CERRADA" in msg:
                data = {
                    "banco": banco,
                    "activo": False,
                    "tasa": "",
                    "minimo": "",
                    "maximo": "",
                    "hora": "",
                    "post_id": post_id,
                }
                if data["post_id"] != _BCV_ULTIMO_POST_ID:
                    _BCV_ULTIMO_POST_ID = data["post_id"]
                    return data

        return None
    except Exception as e:
        print(f"Error scraping @subastasBCV: {e}", flush=True)
        return None


def _estado_bcv(banco_key):
    """Obtiene el estado actual de un banco, inicializandolo si es necesario."""
    if banco_key not in _BCV_ESTADOS:
        _BCV_ESTADOS[banco_key] = {"activo": None, "datos": {}, "ultimo_post_ts": 0.0}
    return _BCV_ESTADOS[banco_key]


def _loop_bcv_scrape():
    """Hilo separado: monitorea @subastasBCV cada 15s.
    Soporta multiples bancos via _BCV_BANCOS_CONFIG.
    Incluye deteccion de stale (2h sin posts -> considerar cerrado)."""
    print("  Monitoreo BCV cada 15s...", flush=True)
    _stale_notified = set()  # bancos con stale ya notificado
    while True:
        try:
            if not en_horario():
                time.sleep(15)
                continue
            bcv = scrape_subastasbcv()
            if bcv is not None:
                banco = bcv.get("banco", "bdv")
                estado = _estado_bcv(banco)
                _stale_notified.discard(banco)
                prev = estado["activo"]
                estado["activo"] = bcv["activo"]
                estado["ultimo_post_ts"] = time.time()
                if bcv["activo"]:
                    estado["datos"] = bcv
                if prev is not None and bcv["activo"] != prev:
                    label = _BCV_BANCOS_CONFIG.get(banco, {}).get("label", banco.upper())
                    if bcv["activo"]:
                        texto = (
                            f"\U0001F3E6\U0001F7E2 *{label} - Intervenci\u00f3n ACTIVA*\n"
                            f"Tasa: *Bs. {bcv['tasa']}*\n"
                            f"M\u00ednimo: *{bcv['minimo']}$* | M\u00e1ximo: *{bcv['maximo']}$*\n"
                            f"Hora: {bcv['hora']} VE\n"
                            f"Fuente: @subastasBCV"
                        )
                    else:
                        datos_prev = estado["datos"] if not bcv["activo"] else bcv
                        texto = (
                            f"\U0001F3E6\U0001F534 *{label} - Intervenci\u00f3n CERRADA*\n"
                            f"\u00daltimos datos: Bs. {datos_prev.get('tasa', '?')} "
                            f"| {datos_prev.get('minimo', '?')}$ - {datos_prev.get('maximo', '?')}$\n"
                            f"Fuente: @subastasBCV"
                        )
                    _tg_call("sendMessage", {
                        "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                        "text": texto
                    })
                    print(f">>> BCV {banco} cambio: {'ACTIVA' if bcv['activo'] else 'CERRADA'} <<<", flush=True)
                if prev is None:
                    estado["activo"] = bcv["activo"]

            # Stale detection: por cada banco con estado ACTIVO
            ahora = time.time()
            for bk, cfg in _BCV_BANCOS_CONFIG.items():
                est = _BCV_ESTADOS.get(bk)
                if not est or est["activo"] != True:
                    _stale_notified.discard(bk)
                    continue
                if est["ultimo_post_ts"] == 0:
                    continue
                if bk in _stale_notified:
                    continue
                tiempo_sin_datos = ahora - est["ultimo_post_ts"]
                if tiempo_sin_datos > _BCV_STALE_TIMEOUT:
                    _stale_notified.add(bk)
                    label = cfg.get("label", bk.upper())
                    est["activo"] = None  # estado incierto
                    print(f">>> BCV STALE {bk}: {tiempo_sin_datos/3600:.1f}h sin posts <<<", flush=True)
                    _tg_call("sendMessage", {
                        "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                        "text": (
                            f"\u26A0\ufe0f *{label} - Estado incierto*\n"
                            f"No se han visto publicaciones de @subastasBCV sobre {label} "
                            f"en las \u00faltimas {_BCV_STALE_TIMEOUT//3600}h.\n"
                            f"\u00daltimos datos conocidos: Bs. {est['datos'].get('tasa', '?')} "
                            f"| {est['datos'].get('minimo', '?')}$ - {est['datos'].get('maximo', '?')}$\n"
                            f"Posible cierre de intervenci\u00f3n no detectado."
                        )
                    })
        except Exception as e:
            print(f"Error en loop BCV: {e}", flush=True)
        time.sleep(15)


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
                    supabase_upsert(registro)
                except Exception as e:
                    print(f"Error guardando en Supabase: {e}", flush=True)
                try:
                    with open(HISTORIAL_PATH, "a") as f:
                        f.write(json.dumps(registro) + "\n")
                except Exception as e:
                    print(f"Error guardando JSONL: {e}", flush=True)

            if not activo:
                time.sleep(60)
                continue

            if mejores:
                mejores.sort(key=lambda x: x["margen"], reverse=True)
                
                # Solo alertas de USDT (USDC no es rentable según análisis)
                estables = [r for r in mejores if r["asset"] == "USDT"]
                top = estables[0] if estables else None
                top_general = mejores[0]
                
                ganancia_ves_top = ""
                if top and top.get("ganancia_ves"):
                    ganancia_ves_top = f" | Bs.{top['ganancia_ves']:.2f}"

                for r in mejores:
                    if r["asset"] != "USDT":
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

                if top:
                    print(f"  [debug] USDT margen={top['margen']:+.2f}% umbral={CONFIG['margen_objetivo']}% enviada={'USDT' in ALERTA_ENVIADA}", flush=True)
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

            # ============================================================
            # MONITOREO DEX MULTI-RED (usa mismo umbral configurado)
            # ============================================================
            for nk in DEX_NETWORKS:
                try:
                    r = calcular_arbitraje_dex(nk)
                    if not r:
                        continue
                    print(f"  DEX/{nk}: {r['pct_neto']:+.2f}% neto", flush=True)
                    ant = MARGE_ANTERIOR_DEX.get(nk)
                    MARGE_ANTERIOR_DEX[nk] = r["pct_neto"]
                    if ant is not None and ant < 0 <= r["pct_neto"]:
                        _tg_call("sendMessage", {
                            "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                            "text": (
                                f"\U0001F7E2 *RECUPERACION DEX* {r['network']} ({r['nombre']})\n"
                                f"Margen pasó de {ant:+.2f}% a {r['pct_neto']:+.2f}%\n"
                                f"Spot: ${r['spot']:.2f} | DEX: ${r['dex']:.2f}"
                            )
                        })
                    if r["pct_neto"] >= CONFIG["margen_objetivo"] and r["ganancia_neta"] > 0 and nk not in ALERTA_ENVIADA_DEX:
                        ALERTA_ENVIADA_DEX.add(nk)
                        _tg_call("sendMessage", {
                            "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                            "text": (
                                f"\U0001F514 *ALERTA DEX MULTI-RED* ({r['network']})\n"
                                f"Red: *{r['nombre']}* | Margen neto: *{r['pct_neto']:+.2f}%* \u2705 RENTABLE\n\n"
                                f"\U0001F449 *Pasos:*\n"
                                f"1\ufe0f\u20e3 Compra *{r['network']}* en Spot de Binance a *${r['spot']:.4f} USD*\n"
                                f"2\ufe0f\u20e3 Retira a tu wallet *{r['wallet']}* (costo: ~${r['costo_retiro']:.2f})\n"
                                f"3\ufe0f\u20e3 Vende en *{r['dex_principales']}* a *${r['dex']:.4f} USD*\n\n"
                                f"\U0001F4C8 *Finanzas estimadas* (Capital: ${CONFIG['capital']:.0f}):\n"
                                f"- Spread bruto: {r['pct_bruto']:+.2f}%\n"
                                f"- Costos (retiro+swap): *${r['costos']:.2f}*\n"
                                f"- *Ganancia Neta: ${r['ganancia_neta']:.4f} USD* ({r['pct_neto']:+.2f}%)\n"
                                f"\n_Umbral actual: {CONFIG['margen_objetivo']}%_"
                            )
                        })
                    elif r["pct_neto"] < CONFIG["margen_objetivo"]:
                        ALERTA_ENVIADA_DEX.discard(nk)
                except Exception as e:
                    print(f"Error DEX/{nk}: {e}", flush=True)

            ciclo += 1
            if ciclo % 30 == 0 and mejores:
                enviar_menu(texto=(
                    f"\u23F1 *Heartbeat* - {ciclo} ciclos\n"
                    f"\U0001F3C6 Mejor: {top_general['asset']} ({top_general['margen']:+.2f}%)"
                ))
            _refrescar_paneles()
        except Exception as e:
            print(f"Error: {e}", flush=True)
        time.sleep(60)




if __name__ == "__main__":
    print("=" * 60, flush=True)
    print("  Bot P2P Binance - Venezuela", flush=True)
    print(f"  Capital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%", flush=True)
    print("=" * 60, flush=True)

    threading.Thread(target=guardar_config_local, daemon=True).start()

    if TELEGRAM_TOKEN:
        threading.Thread(target=polling_telegram, daemon=True).start()
        threading.Thread(target=_loop_bcv_scrape, daemon=True).start()
        time.sleep(2)
        extra = ""
        if not en_horario():
            extra = " (modo silencioso)"
        print(f"Iniciando monitor{extra}...", flush=True)
        loop_monitoreo()
    else:
        print("Telegram token no configurado. Solo modo monitor", flush=True)
        loop_monitoreo()
