import threading
import json, os, ssl, time
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
import requests

# Supabase configuration (read from HF Secrets / environment variables)
SUPABASE_CONFIG_TABLE = "bot_config"
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "historical_prices")
SUPABASE_SIGNAL_TABLE = "signal_log"

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
    resp = requests.post(url, json=record, headers=headers, timeout=(5, 5))
    print(f"[Supabase] POST status={resp.status_code} body={resp.text[:200]}", flush=True)
    if resp.status_code not in (200, 201):
        print(f"[DEBUG] Supabase POST failed: {resp.text[:300]}", flush=True)
    try:
        return resp.json()
    except Exception:
        return None


RETENTION_DAYS = 7


def supabase_cleanup():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    until = (datetime.now(VENEZUELA_TZ) - timedelta(days=RETENTION_DAYS)).isoformat()
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?ts=lt.{until}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        resp = requests.delete(url, headers=headers, timeout=(5, 5))
        print(f"[Supabase] Cleanup status={resp.status_code} deleted={len(resp.text) if resp.status_code==200 else '?'}", flush=True)
    except Exception as e:
        print(f"[Supabase] Cleanup error: {e}", flush=True)

def supabase_select_all():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase credentials not set in environment")
    result = []
    def _do_select():
        try:
            url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?select=*&order=id.desc&limit=10000"
            headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
            resp = requests.get(url, headers=headers, timeout=(5, 5))
            if resp.status_code != 200:
                print(f"[DEBUG] Supabase GET status={resp.status_code} response={resp.text[:300]}", flush=True)
                raise RuntimeError(f"Supabase GET failed: {resp.status_code}")
            result.append(resp.json())
        except Exception as e:
            result.append(e)
    t = threading.Thread(target=_do_select, daemon=True)
    t.start()
    t.join(6)
    if t.is_alive():
        raise RuntimeError("Supabase select_all timeout")
    if not result:
        raise RuntimeError("Supabase select_all returned no result")
    if isinstance(result[0], Exception):
        raise result[0]
    return result[0]


def supabase_load_config():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {}
    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_CONFIG_TABLE}?id=eq.1&select=config"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    try:
        resp = requests.get(url, headers=headers, timeout=(5, 5))
        resp.raise_for_status()
        rows = resp.json()
        if rows and "config" in rows[0]:
            return rows[0]["config"]
        return {}
    except Exception as e:
        print(f"[Supabase] Error loading config: {e}", flush=True)
        return {}


def supabase_save_config(config_dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    def _do_save():
        url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_CONFIG_TABLE}?on_conflict=id"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        }
        try:
            resp = requests.post(url, json={"id": 1, "config": config_dict}, headers=headers, timeout=(5, 5))
            if resp.status_code not in (200, 201):
                print(f"[Supabase] Save config returned {resp.status_code}", flush=True)
        except Exception as e:
            print(f"[Supabase] Error saving config: {e}", flush=True)
    t = threading.Thread(target=_do_save, daemon=True)
    t.start()
    t.join(6)
    if t.is_alive():
        print("[Supabase] Save config timeout - skipping", flush=True)


CONFIG_PATH = "config_usuario.json"


def cargar_config_local():
    sb = supabase_load_config()
    if sb:
        return sb
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Error cargando config local: {e}", flush=True)
    return {}


_config_local = cargar_config_local()

def _safe_float(v, default):
    try:
        return float(v)
    except (ValueError, TypeError):
        return default

def _safe_int(v, default):
    try:
        return int(v)
    except (ValueError, TypeError):
        return default

CONFIG = {
    "capital": _safe_float(_config_local.get("capital", os.getenv("CAPITAL", "100")), 100),
    "margen_objetivo": _safe_float(_config_local.get("margen_objetivo", os.getenv("UMBRAL", "0.8")), 0.8),
    "monto_filtro": _safe_int(_config_local.get("monto_filtro", os.getenv("MONTO_FILTRO", "0")), 0),
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


def guardar_config_local():
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(CONFIG, f)
        config_dict = {
            "capital": CONFIG.get("capital", 100),
            "margen_objetivo": CONFIG.get("margen_objetivo", 0.8),
            "monto_filtro": CONFIG.get("monto_filtro", 0),
            "default_crypto": CONFIG.get("default_crypto", "USDT"),
        }
        supabase_save_config(config_dict)
    except Exception as e:
        print(f"Error guardando config: {e}", flush=True)

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

# Timing de mercado: seguimiento de tendencias USDT/VES
_ULTIMA_ALERTA_TIMING = {}
TIMING_COOLDOWN = 3600       # 1h entre alertas del mismo tipo
TIMING_THRESHOLD_PCT = 2.0   # % de desviacion respecto al promedio para alertar
_SENALES_PENDIENTES = {}     # signal_key -> {"ciclos": int, "confianza": int, ...}
_ULTIMOS_LOCK = threading.Lock()
_AUTO_REFRESH_LOCK = threading.Lock()
VPS_EXPIRY_NOTIFIED = False

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
_session_local = threading.local()
def _get_session():
    if not hasattr(_session_local, 'session') or _session_local.session is None:
        from requests.adapters import HTTPAdapter
        _session_local.session = requests.Session()
        adapter = HTTPAdapter(pool_connections=2, pool_maxsize=2, max_retries=1)
        _session_local.session.mount("http://", adapter)
        _session_local.session.mount("https://", adapter)
    return _session_local.session


def _raw_ssl_post(url, json_data, timeout=60):
    import http.client
    import urllib.parse
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    except AttributeError:
        ctx.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
    try:
        ctx.set_ciphers('DEFAULT:@SECLEVEL=0')
    except ssl.SSLError:
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


def _try_url(url, data, timeout):
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
                time.sleep(1)
    return None, "All retries failed"


def _api_call(method, data=None, timeout=15):
    if USE_PROXY:
        proxy_url = f"{API_URL}/{method}"
        result, error = _try_url(proxy_url, data, timeout)
        # Usar respuesta del proxy siempre que haya respuesta (incluso ok=false)
        # Solo intentar directo si el proxy no respondio (timeout/connection error)
        if result:
            return result
        if error:
            direct_url = f"{_DIRECT_API_BASE}/{method}"
            result, error = _try_url(direct_url, data, timeout)
            if result:
                return result
    else:
        direct_url = f"{_DIRECT_API_BASE}/{method}"
        result, error = _try_url(direct_url, data, timeout)
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
         {"text": "\U0001F4C8 Horarios", "callback_data": "mejor_horario"},
         {"text": "\U0001F4C9 Mercado", "callback_data": "timing_mercado"}],
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


_COINGECKO_CACHE = {"data": None, "ts": 0}


def _fetch_spot_single(network_key):
    """Fallback individual si el batch falla."""
    cfg = DEX_NETWORKS.get(network_key)
    if not cfg or not cfg.get("coingecko_id"):
        return None
    try:
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={cfg['coingecko_id']}&vs_currencies=usd",
            headers=HEADERS, timeout=5
        )
        resp.raise_for_status()
        return float(resp.json().get(cfg["coingecko_id"], {}).get("usd", 0))
    except Exception as e:
        print(f"[CoinGecko/{network_key}] Error: {e}", flush=True)
    return None


def _fetch_all_spot_prices():
    """Batch todos los assets en una llamada, cacheado 10s."""
    ahora = time.time()
    if _COINGECKO_CACHE["data"] and (ahora - _COINGECKO_CACHE["ts"]) < 10:
        return _COINGECKO_CACHE["data"]
    ids = ",".join(cfg["coingecko_id"] for nk, cfg in DEX_NETWORKS.items() if cfg.get("coingecko_id"))
    try:
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd",
            headers=HEADERS, timeout=5
        )
        resp.raise_for_status()
        data = resp.json()
        _COINGECKO_CACHE["data"] = data
        _COINGECKO_CACHE["ts"] = ahora
        return data
    except Exception as e:
        print(f"[CoinGecko/batch] Error: {e}", flush=True)
        return _COINGECKO_CACHE["data"] or {}


def _fetch_spot_p2p():
    usdt_buy = obtener_precio_p2p("BUY", "USDT")
    usdc_buy = obtener_precio_p2p("BUY", "USDC")
    if usdt_buy and usdc_buy:
        return usdc_buy / usdt_buy
    return None


def obtener_precio_spot(network_key):
    cfg = DEX_NETWORKS.get(network_key)
    if not cfg or not cfg.get("coingecko_id"):
        return None
    # CoinGecko es fuente primaria para criptos (SOL/POL/BNB).
    # P2P-derivado solo para USDC (mercado USDT/USDC es confiable).
    if network_key == "USDC":
        price = _fetch_spot_p2p()
        if price and price > 0:
            print(f"  [Spot/{network_key}] P2P-derivado: ${price:.4f}", flush=True)
            return price
    data = _fetch_all_spot_prices()
    price = float(data.get(cfg["coingecko_id"], {}).get("usd", 0))
    if price > 0:
        print(f"  [Spot/{network_key}] CoinGecko: ${price:.4f}", flush=True)
        return price
    time.sleep(1.5)
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


def _calc_margen(buy, sell, capital=None):
    neto = (sell - buy) - (buy * COMISION) - (sell * COMISION) - (buy * COMISION_BANCO)
    pct = (neto / buy) * 100
    cap = capital or CONFIG["capital"]
    return {"neto": neto, "pct": pct, "usd": cap * (pct / 100)}

def _calc_margen_taker(buy, sell, capital=None):
    neto = (buy - sell) - (sell * COMISION) - (buy * COMISION) - (sell * COMISION_BANCO)
    pct = (neto / sell) * 100
    cap = capital or CONFIG["capital"]
    return {"neto": neto, "pct": pct, "usd": cap * (pct / 100)}

def calcular_margen(asset, trans_amount=None):
    monto = trans_amount if trans_amount is not None else CONFIG["monto_filtro"]
    maker_venta = obtener_precio_p2p("BUY", asset, monto)
    maker_compra = obtener_precio_p2p("SELL", asset, monto)
    if maker_venta is None or maker_compra is None:
        return None

    m = _calc_margen(maker_compra, maker_venta)
    t = _calc_margen_taker(maker_venta, maker_compra)

    tasa_ves = ULTIMOS.get("USDT", {}).get("venta") or None

    with _ULTIMOS_LOCK:
        ULTIMOS[asset] = {"compra": maker_compra, "venta": maker_venta, "margen": m["pct"]}

    return {
        "asset": asset, "compra": maker_compra, "venta": maker_venta,
        "margen": m["pct"], "ganancia_usd": m["usd"],
        "ganancia_ves": (m["usd"] * tasa_ves) if tasa_ves else None,
        "taker_compra": maker_venta, "taker_venta": maker_compra,
        "taker_margen": t["pct"], "taker_ganancia_usd": t["usd"],
        "taker_ganancia_ves": (t["usd"] * tasa_ves) if tasa_ves else None,
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

    m = _calc_margen(usdt_compra_maker, usdc_venta_maker)
    t = _calc_margen(usdt_compra_taker, usdc_venta_taker)

    tasa_ves = ULTIMOS.get("USDT", {}).get("venta")

    return {
        "asset": "USDT→USDC",
        "compra_usdt": usdt_compra_maker,
        "venta_usdc": usdc_venta_maker,
        "margen": m["pct"],
        "ganancia_usd": m["usd"],
        "ganancia_ves": (m["usd"] * tasa_ves) if tasa_ves else None,
        "taker_compra_usdt": usdt_compra_taker,
        "taker_venta_usdc": usdc_venta_taker,
        "taker_margen": t["pct"],
        "taker_ganancia_usd": t["usd"],
        "taker_ganancia_ves": (t["usd"] * tasa_ves) if tasa_ves else None,
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
        ts_raw = rec.get("ts")
        if not ts_raw:
            continue
        try:
            hour = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).hour
        except Exception:
            continue
        usdt = rec.get("USDT")
        if not isinstance(usdt, dict):
            continue
        compra = usdt.get("compra")
        venta = usdt.get("venta")
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
# SISTEMA DE SEÑALES MULTICAPA (90%+ precision objetivo)
# ============================================================

def _calcular_tendencia_6h():
    """Regresion lineal simple sobre ultimas 6h de precio compra USDT.
    Retorna pendiente (positiva=subiendo, negativa=bajando) o None."""
    precios, timestamps = [], []
    try:
        if os.path.exists(HISTORIAL_PATH):
            with open(HISTORIAL_PATH, "r") as f:
                for linea in f:
                    try:
                        d = json.loads(linea)
                        if "USDT" not in d:
                            continue
                        ts = d.get("ts", "")
                        if not ts:
                            continue
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        horas = (datetime.now(VENEZUELA_TZ) - dt).total_seconds() / 3600
                        if horas > 6:
                            continue
                        compra = d["USDT"].get("compra")
                        if compra:
                            precios.append(float(compra))
                            timestamps.append(horas)
                    except Exception:
                        continue
    except Exception as e:
        print(f"Error calculando tendencia: {e}", flush=True)
        return None
    if len(precios) < 5:
        return None
    n = len(precios)
    x_sum, y_sum = sum(timestamps), sum(precios)
    xy_sum = sum(x * y for x, y in zip(timestamps, precios))
    x2_sum = sum(x * x for x in timestamps)
    denom = n * x2_sum - x_sum * x_sum
    return (n * xy_sum - x_sum * y_sum) / denom if denom else None


def _detectar_niveles_clave():
    """Encuentra niveles de soporte (compra) y resistencia (venta) del USDT.
    Retorna (soportes, resistencias) como listas de precios."""
    compras, ventas = [], []
    try:
        if os.path.exists(HISTORIAL_PATH):
            with open(HISTORIAL_PATH, "r") as f:
                for linea in f:
                    try:
                        d = json.loads(linea)
                        if "USDT" not in d:
                            continue
                        ts = d.get("ts", "")
                        if not ts:
                            continue
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if (datetime.now(VENEZUELA_TZ) - dt).total_seconds() > 86400 * 7:
                            continue
                        c = d["USDT"].get("compra")
                        v = d["USDT"].get("venta")
                        if c: compras.append(float(c))
                        if v: ventas.append(float(v))
                    except Exception:
                        continue
    except Exception:
        return [], []
    if len(compras) < 20:
        return [], []

    def _agrupar(precios, bucket=2):
        buckets = defaultdict(list)
        for p in precios:
            buckets[round(p / bucket) * bucket].append(p)
        umbral = max(len(v) for v in buckets.values()) * 0.6
        return sorted([k for k, v in buckets.items() if len(v) >= umbral])

    return _agrupar(compras)[:3], _agrupar(ventas)[-3:]


def _cerca_de(precio, niveles, tolerancia=3):
    return any(abs(precio - n) <= tolerancia for n in niveles)


def _evaluar_senal_multicapa():
    """Evalua todas las capas y retorna (senal, confianza, detalles, mensaje)."""
    r = calcular_margen("USDT")
    if not r:
        return None, 0, {}, None

    precios_compra, precios_venta = [], []
    try:
        if os.path.exists(HISTORIAL_PATH):
            with open(HISTORIAL_PATH, "r") as f:
                for linea in f:
                    try:
                        d = json.loads(linea)
                        if "USDT" not in d:
                            continue
                        ts = d.get("ts", "")
                        if not ts:
                            continue
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if (datetime.now(VENEZUELA_TZ) - dt).total_seconds() > 86400:
                            continue
                        c = d["USDT"].get("compra")
                        v = d["USDT"].get("venta")
                        if c: precios_compra.append(float(c))
                        if v: precios_venta.append(float(v))
                    except Exception:
                        continue
    except Exception as e:
        print(f"Error historial: {e}", flush=True)
        return None, 0, {}, None
    if len(precios_compra) < 10 or len(precios_venta) < 10:
        return None, 0, {}, None

    avg_compra = sum(precios_compra) / len(precios_compra)
    avg_venta = sum(precios_venta) / len(precios_venta)
    desv_compra = ((r["compra"] - avg_compra) / avg_compra) * 100
    desv_venta = ((r["venta"] - avg_venta) / avg_venta) * 100
    pendiente = _calcular_tendencia_6h()
    soportes, resistencias = _detectar_niveles_clave()
    en_soporte = _cerca_de(r["compra"], soportes)
    en_resistencia = _cerca_de(r["venta"], resistencias)

    detalles = {
        "desv_compra": desv_compra, "desv_venta": desv_venta,
        "pendiente": pendiente, "en_soporte": en_soporte,
        "en_resistencia": en_resistencia, "avg_compra": avg_compra,
        "avg_venta": avg_venta,
    }

    if desv_compra <= -TIMING_THRESHOLD_PCT:
        conf, razones = 60, ["Precio bajo vs promedio 24h"]
        if pendiente is not None:
            if pendiente >= -0.5:
                conf += 15; razones.append("Tendencia estable o subiendo")
            else:
                conf -= 10; razones.append("Sigue cayendo (esperar)")
        if en_soporte:
            conf += 15; razones.append("Cerca de soporte histórico")
        if desv_compra <= -3:
            conf += 10; razones.append("Oportunidad fuerte (>3%)")
        if soportes:
            razones.append(f"Soporte en {soportes[0]} VES")
        return ("compra", min(conf, 100), detalles,
            f"\U0001F4C9 *SEÑAL DE COMPRA* (Confianza: {min(conf,100)}%)\n"
            f"Precio compra: *{r['compra']:.2f} VES* ({desv_compra:+.2f}% vs promedio)\n"
            f"Promedio 24h: {avg_compra:.2f} VES | Venta: {r['venta']:.2f} VES\n"
            f"{'📈 Tendencia: estable o subiendo' if pendiente is None or pendiente >= -0.5 else '📉 Tendencia: sigue cayendo'}\n"
            + (f"✅ Cerca de soporte histórico ({soportes[0]} VES)" if en_soporte else "")
            + f"\nRazones: {', '.join(razones)}\n\n"
            f"\U0001F449 *Acción:* COMPRA USDT ahora para vender cuando suba.")

    if desv_venta >= TIMING_THRESHOLD_PCT:
        conf, razones = 60, ["Precio alto vs promedio 24h"]
        if pendiente is not None:
            if pendiente <= 0.5:
                conf += 15; razones.append("Tendencia estable o bajando")
            else:
                conf -= 10; razones.append("Sigue subiendo (esperar)")
        if en_resistencia:
            conf += 15; razones.append("Cerca de resistencia histórica")
        if desv_venta >= 3:
            conf += 10; razones.append("Oportunidad fuerte (>3%)")
        if resistencias:
            razones.append(f"Resistencia en {resistencias[-1]} VES")
        return ("venta", min(conf, 100), detalles,
            f"\U0001F4C8 *SEÑAL DE VENTA* (Confianza: {min(conf,100)}%)\n"
            f"Precio venta: *{r['venta']:.2f} VES* ({desv_venta:+.2f}% vs promedio)\n"
            f"Promedio 24h: {avg_venta:.2f} VES | Compra: {r['compra']:.2f} VES\n"
            f"{'📉 Tendencia: estable o bajando' if pendiente is None or pendiente <= 0.5 else '📈 Tendencia: sigue subiendo'}\n"
            + (f"✅ Cerca de resistencia histórica ({resistencias[-1]} VES)" if en_resistencia else "")
            + f"\nRazones: {', '.join(razones)}\n\n"
            f"\U0001F449 *Acción:* VENDE tus USDT ahora, el mercado está alto.")

    return None, 0, detalles, None


def _registrar_senal_supabase(senal_data):
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    def _do():
        url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_SIGNAL_TABLE}"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                   "Content-Type": "application/json", "Prefer": "return=representation"}
        try:
            resp = requests.post(url, json=senal_data, headers=headers, timeout=(5, 5))
            if resp.status_code not in (200, 201):
                print(f"[Supabase] Signal log: {resp.status_code} {resp.text[:200]}", flush=True)
        except Exception as e:
            print(f"[Supabase] Error saving signal: {e}", flush=True)
    t = threading.Thread(target=_do, daemon=True)
    t.start(); t.join(6)
    if t.is_alive():
        print("[Supabase] Signal log timeout", flush=True)


def _verificar_resultados_senales():
    """Revisa senales previas en Supabase y verifica si fueron aciertos.
    Compra: acierto si precio venta subio >=0.5% en 4h.
    Venta: acierto si precio compra bajo >=0.5% en 4h."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    result = []
    def _do_query():
        try:
            url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_SIGNAL_TABLE}?select=*&result=is.null&order=id.desc&limit=20"
            headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
            resp = requests.get(url, headers=headers, timeout=(5, 5))
            if resp.status_code == 200:
                result.append(resp.json())
        except Exception:
            pass
    t = threading.Thread(target=_do_query, daemon=True)
    t.start(); t.join(6)
    if t.is_alive() or not result:
        return

    ahora = datetime.now(VENEZUELA_TZ)
    r_actual = calcular_margen("USDT")
    if not r_actual:
        return

    for senal in result[0]:
        ts_senal = senal.get("ts", "")
        if not ts_senal:
            continue
        try:
            dt_senal = datetime.fromisoformat(ts_senal.replace("Z", "+00:00"))
        except Exception:
            continue
        horas_diff = (ahora - dt_senal).total_seconds() / 3600
        if horas_diff < 3.5:
            continue  # aun es muy pronto

        tipo = senal.get("signal_type")
        precio_orig = float(senal.get("precio_compra_actual") or 0)
        if tipo == "compra":
            precio_hoy = r_actual["venta"]
            cambio = ((precio_hoy - precio_orig) / precio_orig) * 100 if precio_orig else 0
            result_text = "acierto" if cambio >= 0.5 else "fallo"
        elif tipo == "venta":
            precio_hoy = r_actual["compra"]
            precio_orig = float(senal.get("precio_venta_actual") or 0)
            cambio = ((precio_orig - precio_hoy) / precio_orig) * 100 if precio_orig else 0
            result_text = "acierto" if cambio >= 0.5 else "fallo"
        else:
            continue

        def _do_update(sid, res, precio):
            url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_SIGNAL_TABLE}?id=eq.{sid}"
            headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                       "Content-Type": "application/json", "Prefer": "return=representation"}
            try:
                requests.patch(url, json={"result": res, "result_checked_at": ahora.isoformat(),
                                          "precio_resultado": round(precio, 2)}, headers=headers, timeout=(5, 5))
            except Exception:
                pass
        tu = threading.Thread(target=_do_update, args=(senal["id"], result_text, precio_hoy), daemon=True)
        tu.start()


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
                guardar_config_local()
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
                guardar_config_local()
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
    usd = r.get('ganancia_usd', 0)
    v = f"${usd:.2f} USD"
    if r.get('ganancia_ves'):
        v += f" | Bs.{r['ganancia_ves']:.2f}"
    return v


def registrar_refresh(chat_id, msg_id, data):
    with _AUTO_REFRESH_LOCK:
        AUTO_REFRESH[(chat_id, msg_id)] = {"data": data, "ticks": 5}


def limpiar_refresh(chat_id, msg_id=None):
    with _AUTO_REFRESH_LOCK:
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
    r = calcular_margen(asset)
    if not r:
        editar_mensaje(chat_id, msg_id, f"No se pudo obtener precio de {asset}.")
        registrar_refresh(chat_id, msg_id, f"detalle_{asset}")
        return
    CONFIG["default_crypto"] = asset
    guardar_config_local()
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
    with _AUTO_REFRESH_LOCK:
        snapshot = list(AUTO_REFRESH.items())
        to_del = [k for k, v in AUTO_REFRESH.items() if v["ticks"] <= 1]
        for k in to_del:
            del AUTO_REFRESH[k]
        for k, v in AUTO_REFRESH.items():
            if k not in to_del:
                v["ticks"] -= 1
    for (chat_id, msg_id), info in snapshot:
        if (chat_id, msg_id) in to_del:
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
            registros = []
            try:
                registros = supabase_select_all()
            except Exception as e:
                print(f"Supabase lectura fallo, usando JSONL: {e}", flush=True)
                if os.path.exists(HISTORIAL_PATH):
                    with open(HISTORIAL_PATH, "r") as f:
                        for l in f:
                            try:
                                registros.append(json.loads(l))
                            except Exception:
                                continue
            if not registros:
                editar_mensaje(chat_id, msg_id, "Aún no hay datos históricos.")
                return

            hoy_vet = datetime.now(VENEZUELA_TZ).date()
            lineas_hoy = []
            for d in registros:
                try:
                    dt_ts = datetime.fromisoformat(str(d["ts"]).replace("Z", "+00:00"))
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

    elif data == "timing_mercado":
        senal, confianza, det, msg_senal = _evaluar_senal_multicapa()
        if msg_senal:
            texto = msg_senal
        else:
            rr = calcular_margen("USDT")
            if rr:
                texto = (
                    f"\U0001F4CA *Mercado USDT/VES*\n\n"
                    f"Precio compra: {rr['compra']:.2f} VES\n"
                    f"Precio venta: {rr['venta']:.2f} VES\n\n"
                    f"\u23F3 Sin señal clara ahora.\n"
                    f"Se necesitan m\u00ednimo 10 registros en las \u00faltimas 24h.\n"
                    f"El bot monitorea y alertará autom\u00e1ticamente."
                )
            else:
                texto = "No se pudo obtener el precio actual de USDT."
        kb = json.dumps({
            "inline_keyboard": [
                [{"text": "\U0001F504 Actualizar", "callback_data": "timing_mercado"},
                 {"text": "\U0001F519 Inicio", "callback_data": "menu"}]
            ]
        })
        _tg_call("editMessageText", {
            "chat_id": chat_id, "message_id": msg_id,
            "text": texto, "parse_mode": "Markdown",
            "reply_markup": kb
        }, ignore_400=True)

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
        try:
            updates = _get_updates(offset)
            for update in updates:
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    procesar_callback(update["callback_query"])
                elif "message" in update and update["message"].get("text"):
                    procesar_mensaje(update["message"]["text"], update["message"]["chat"]["id"])
        except Exception as e:
            print(f"Error en polling: {e}", flush=True)
        time.sleep(3)
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
                    t = threading.Thread(target=supabase_upsert, args=(registro,), daemon=True)
                    t.start()
                    t.join(6)
                    if t.is_alive():
                        print("Supabase upsert timeout - skipping", flush=True)
                except Exception as e:
                    print(f"Error guardando en Supabase: {e}", flush=True)
                try:
                    with open(HISTORIAL_PATH, "a") as f:
                        f.write(json.dumps(registro) + "\n")
                except Exception as e:
                    print(f"Error guardando JSONL: {e}", flush=True)
                supabase_cleanup()

            if not activo:
                time.sleep(60)
                continue

            if mejores:
                mejores.sort(key=lambda x: x["margen"], reverse=True)
                
                # Solo alertas de USDT (USDC no es rentable según análisis)
                estables = [r for r in mejores if r["asset"] == "USDT"]
                top = estables[0] if estables else None
                top_general = mejores[0]

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
                    tasa_ves_alerta = ULTIMOS.get("USDT", {}).get("venta") or top['compra']
                    ves_ganancia_str = f"Bs.{top['ganancia_ves']:.2f}" if top.get("ganancia_ves") else f"Bs.{top['ganancia_usd'] * tasa_ves_alerta:.2f}"
                    
                    # Cómputo del escenario alternativo
                    comparativo_str = ""
                    maker_compra = top['compra']
                    tasa_ves_alt = ULTIMOS.get("USDT", {}).get("venta", maker_compra)
                    if CONFIG["monto_filtro"] > 0:
                        venta_may = obtener_precio_p2p("BUY", top['asset'], trans_amount=0)
                        if venta_may:
                            m = _calc_margen(maker_compra, venta_may)
                            comparativo_str = (
                                f"\n\U0001F504 *Escenario Alternativo (Vender todo de golpe - Mayorista):*\n"
                                f"- Vender todo a: *{venta_may:.2f} VES*\n"
                                f"- Margen Neto: {m['pct']:+.2f}%\n"
                                f"- Ganancia Neta Total: *${m['usd']:.2f} USD* (~Bs.{m['usd'] * tasa_ves_alt:.2f})\n"
                            )
                    else:
                        venta_frac = obtener_precio_p2p("BUY", top['asset'], trans_amount=8000)
                        if venta_frac:
                            m = _calc_margen(maker_compra, venta_frac)
                            comparativo_str = (
                                f"\n\U0001F504 *Escenario Alternativo (Vender fraccionado de a $10 / 8K Bs):*\n"
                                f"- Vender en partes a: *{venta_frac:.2f} VES*\n"
                                f"- Margen Neto: {m['pct']:+.2f}%\n"
                                f"- Ganancia Neta Total: *${m['usd']:.2f} USD* (~Bs.{m['usd'] * tasa_ves_alt:.2f})\n"
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
            # SISTEMA DE SEÑALES MULTICAPA (con confirmacion 2 ciclos)
            # ============================================================
            senal, confianza, det, msg_senal = _evaluar_senal_multicapa()

            if senal:
                signal_key = f"{senal}_{datetime.now(VENEZUELA_TZ).strftime('%Y%m%d%H')}"
                prev = _SENALES_PENDIENTES.get(signal_key)
                if prev is None:
                    _SENALES_PENDIENTES[signal_key] = {
                        "ciclos": 1, "confianza": confianza,
                        "detalles": det, "msg": msg_senal, "ts": time.time(),
                    }
                else:
                    prev["ciclos"] += 1
                    if prev["ciclos"] >= 2 and not prev.get("enviada"):
                        prev["enviada"] = True
                        last_ts = _ULTIMA_ALERTA_TIMING.get(senal, 0)
                        if time.time() - last_ts > TIMING_COOLDOWN:
                            _ULTIMA_ALERTA_TIMING[senal] = time.time()
                            _tg_call("sendMessage", {
                                "chat_id": TELEGRAM_CHAT_ID, "parse_mode": "Markdown",
                                "text": msg_senal
                            })
                            print(f">>> SEÑAL {senal} (confianza {confianza}%) <<<", flush=True)
                            _registrar_senal_supabase({
                                "signal_type": senal,
                                "precio_compra_actual": round(det.get("avg_compra", 0), 2),
                                "precio_venta_actual": round(det.get("avg_venta", 0), 2),
                                "avg_compra_24h": round(det.get("avg_compra", 0), 2),
                                "avg_venta_24h": round(det.get("avg_venta", 0), 2),
                                "desviacion_pct": round(det.get("desv_compra" if senal == "compra" else "desv_venta", 0), 2),
                                "tendencia_6h": det.get("pendiente"),
                                "cerca_soporte": det.get("en_soporte", False),
                                "cerca_resistencia": det.get("en_resistencia", False),
                                "confirmada": True,
                                "detalles": json.dumps(det),
                            })

                ahora_ts = time.time()
                for k in list(_SENALES_PENDIENTES):
                    if ahora_ts - _SENALES_PENDIENTES[k]["ts"] > 1800:
                        del _SENALES_PENDIENTES[k]
            else:
                for k in list(_SENALES_PENDIENTES):
                    if not _SENALES_PENDIENTES[k].get("enviada"):
                        del _SENALES_PENDIENTES[k]

            # Verificar resultados de senales previas (cada 30 ciclos)
            if ciclo % 30 == 0:
                _verificar_resultados_senales()

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

    guardar_config_local()

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
