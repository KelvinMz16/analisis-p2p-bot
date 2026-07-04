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
    PRECISION["supabase"]["ok" if resp.status_code in (200, 201) else "fail"] += 1
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
        if resp.status_code == 200: PRECISION["supabase"]["ok"] += 1
        print(f"[Supabase] Cleanup status={resp.status_code} deleted={len(resp.text) if resp.status_code==200 else '?'}", flush=True)
    except Exception as e:
        PRECISION["supabase"]["fail"] += 1
        print(f"[Supabase] Cleanup error: {e}", flush=True)

def supabase_select_all(ts_gte=None):
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase credentials not set in environment")
    result = []
    def _do_select():
        try:
            all_data = []
            page_size = 1000
            offset = 0
            filtro_ts = f"&ts=gte.{ts_gte}" if ts_gte else ""
            while True:
                url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}?select=*&order=id.desc&limit={page_size}&offset={offset}{filtro_ts}"
                headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
                resp = requests.get(url, headers=headers, timeout=(10, 10))
                if resp.status_code != 200:
                    print(f"[DEBUG] Supabase GET status={resp.status_code} response={resp.text[:300]}", flush=True)
                    raise RuntimeError(f"Supabase GET failed: {resp.status_code}")
                data = resp.json()
                if not data:
                    break
                all_data.extend(data)
                if len(data) < page_size:
                    break
                offset += page_size
            result.append(all_data)
        except Exception as e:
            result.append(e)
    t = threading.Thread(target=_do_select, daemon=True)
    t.start()
    t.join(30)
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
    "grupo_chat_id": _config_local.get("grupo_chat_id", os.getenv("GRUPO_CHAT_ID", "")),
}

WHITELIST = set()
_whitelist_raw = os.getenv("USER_WHITELIST", "").strip()
if _whitelist_raw:
    for cid in _whitelist_raw.split(","):
        cid = cid.strip()
        if cid:
            try:
                WHITELIST.add(int(cid))
            except ValueError:
                pass
CONFIG_POR_CHAT = {}

def _es_master(chat_id):
    return str(chat_id) == TELEGRAM_CHAT_ID

def _autorizado(chat_id):
    return _es_master(chat_id) or chat_id in WHITELIST

def _get_config(chat_id):
    base = dict(CONFIG)
    if chat_id in CONFIG_POR_CHAT:
        base.update(CONFIG_POR_CHAT[chat_id])
    return base

def _save_chat_config(chat_id, updates):
    if chat_id not in CONFIG_POR_CHAT:
        CONFIG_POR_CHAT[chat_id] = {}
    CONFIG_POR_CHAT[chat_id].update(updates)
    try:
        with open("config_por_chat.json", "w") as f:
            json.dump(CONFIG_POR_CHAT, f, default=str)
    except Exception:
        pass

def _cargar_chat_configs():
    try:
        if os.path.exists("config_por_chat.json"):
            with open("config_por_chat.json", "r") as f:
                data = json.load(f)
                CONFIG_POR_CHAT.update({int(k): v for k, v in data.items()})
    except Exception:
        pass

_cargar_chat_configs()

def _broadcast(texto, parse_mode="Markdown"):
    _send_channel(texto, parse_mode)

def _send_channel(texto, parse_mode="Markdown"):
    if not TELEGRAM_CHANNEL_ID:
        return
    try:
        _tg_call("sendMessage", {"chat_id": int(TELEGRAM_CHANNEL_ID), "text": texto, "parse_mode": parse_mode})
    except Exception:
        pass


def _verificar_nuevos_miembros():
    global _ULTIMO_CONTEO_MIEMBROS, _ULTIMO_CONTEO_TS
    if not TELEGRAM_CHANNEL_ID:
        return
    ahora = time.time()
    if ahora - _ULTIMO_CONTEO_TS < 10:
        return
    _ULTIMO_CONTEO_TS = ahora
    try:
        resp = _tg_call("getChat", {"chat_id": int(TELEGRAM_CHANNEL_ID)})
        if not resp or not resp.get("ok"):
            return
        nuevo = resp["result"].get("member_count", 0)
        if _ULTIMO_CONTEO_MIEMBROS and nuevo > _ULTIMO_CONTEO_MIEMBROS:
            diff = nuevo - _ULTIMO_CONTEO_MIEMBROS
            _send_channel(
                "👋 *¡Bienvenido al canal!*\n\n"
                "📊 *Contenido del canal:*\n"
                "• 💵 Precios USDT/USDC en VES en vivo (P2P Binance)\n"
                "• 📈 Alertas de arbitraje cuando el spread da margen\n"
                "• 🏦 Tasa BCV actualizada en tiempo real\n"
                "• 📊 Resumen diario del mercado a las 7am\n\n"
                "💬 *Grupo de discusión:*\n"
                "Únete para escribir /precio y ver el mercado al instante\n"
                "👉 https://t.me/arbitrajesp2p\n\n"
                "📌 *Reglas:* No spam, no scams, respeto mutuo.\n\n"
                "¡Aprovecha las oportunidades del mercado P2P!"
            )
        _ULTIMO_CONTEO_MIEMBROS = nuevo
    except Exception:
        pass

def _loop_detectar_miembros():
    time.sleep(5)
    while True:
        try:
            _verificar_nuevos_miembros()
        except Exception:
            pass
        time.sleep(5)

def _obtener_tasa_bcv():
    """Obtiene la tasa BCV oficial. Primero intenta bcv.org.ve directo, si falla usa finanzasdigital."""
    import re
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 1. Intentar BCV directo
    try:
        resp = requests.get("https://www.bcv.org.ve/", timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            verify=False)
        if resp.status_code == 200:
            rate = re.search(r'USD</span>.*?<strong\s+class="strong-tb">\s*([\d.,]+)\s*</strong>', resp.text, re.DOTALL)
            if rate:
                tasa_str = rate.group(1).replace(".", "").replace(",", ".")
                return {"tasa": float(tasa_str), "updated_at": datetime.now(VENEZUELA_TZ).isoformat()}
    except Exception as e:
        print(f"[BCV] Error scraping BCV directo: {e}", flush=True)

    # 2. Fallback: finanzasdigital
    try:
        resp = requests.get("https://finanzasdigital.com/", timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        if resp.status_code != 200:
            return None
        url_match = re.search(r'href="(https://finanzasdigital\.com/tasa-de-cambio-bcv[^"]*)"', resp.text)
        if not url_match:
            return None
        resp2 = requests.get(url_match.group(1), timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        if resp2.status_code != 200:
            return None
        match = re.search(r'Tasa de Cambio BCV.*?:\s*([\d.,]+)\s*Bs/USD', resp2.text)
        if match:
            tasa_str = match.group(1).replace('.', '').replace(',', '.')
            return {"tasa": float(tasa_str), "updated_at": datetime.now(VENEZUELA_TZ).isoformat()}
    except Exception as e:
        print(f"[BCV] Error scraping finanzasdigital: {e}", flush=True)
    return None


def _verificar_spread_bcv():
    """Compara tasa BCV vs P2P y envía alerta si el spread es significativo."""
    global _ULTIMO_SPREAD_BCV
    # Cooldown: una vez cada 6 horas
    if time.time() - _ULTIMO_SPREAD_BCV < 21600:
        return
    bcv = _obtener_tasa_bcv()
    if not bcv or not bcv.get("tasa"):
        return
    tasa_bcv = bcv["tasa"]
    usdt_p2p = ULTIMOS.get("USDT", {}).get("venta")
    if not usdt_p2p:
        return
    spread_pct = ((usdt_p2p - tasa_bcv) / tasa_bcv) * 100
    if abs(spread_pct) >= 5:
        _ULTIMO_SPREAD_BCV = time.time()
        emoji = "📈" if spread_pct > 0 else "📉"
        _send_channel(
            f"{emoji} *Spread BCV vs P2P*\n\n"
            f"Tasa BCV: {tasa_bcv:.2f} VES\n"
            f"USDT P2P: {usdt_p2p:.2f} VES\n"
            f"Spread: {spread_pct:+.2f}%",
            parse_mode="Markdown"
          )


def _verificar_cambio_tasa_bcv():
    """Detecta cambios en la tasa BCV y envía alerta inmediata."""
    global _ULTIMA_TASA_BCV
    bcv = _obtener_tasa_bcv()
    if not bcv or not bcv.get("tasa"):
        return
    tasa = bcv["tasa"]
    if _ULTIMA_TASA_BCV == 0:
        _ULTIMA_TASA_BCV = tasa
        return
    if tasa != _ULTIMA_TASA_BCV:
        cambio = tasa - _ULTIMA_TASA_BCV
        pct = (cambio / _ULTIMA_TASA_BCV) * 100
        emoji = "📈" if cambio > 0 else "📉"
        _send_channel(
            f"{emoji} *TCambio BCV*\n\n"
            f"Tasa anterior: {_ULTIMA_TASA_BCV:.2f} VES\n"
            f"Tasa actual: *{tasa:.2f} VES*\n"
            f"Cambio: {cambio:+.2f} ({pct:+.2f}%)",
            parse_mode="Markdown"
        )
        _ULTIMA_TASA_BCV = tasa


# ============================================================
# SCRAPER SUBASTAS BCV - Telegram @subastasBCV
# ============================================================
_SUBASTAS_ESTADO = {}  # banco -> {"status": "activa"|"cerrada", "ts": timestamp}
_ULTIMO_CONTEO_MIEMBROS = 0
_ULTIMO_CONTEO_TS = 0
_ULTIMA_HORA_ENVIADA = -1
_SUBASTAS_ULTIMO_SCRAPED = 0
_ULTIMO_SPREAD_BCV = 0  # timestamp del ultimo spread enviado
_ULTIMO_TOP_OPORT = 0  # timestamp del ultimo top oportunidades enviado


def _top_oportunidades():
    global _ULTIMO_TOP_OPORT
    if time.time() - _ULTIMO_TOP_OPORT < 21600:
        return
    ops = []
    for a in ASSETS_VES:
        if a == "BTC":
            continue
        r = ULTIMOS.get(a)
        if r and r.get("margen", -999) >= CONFIG["margen_objetivo"]:
            ops.append((a, r["margen"], r["compra"], r["venta"]))
    if not ops:
        return
    ops.sort(key=lambda x: x[1], reverse=True)
    usdt = ULTIMOS.get("USDT", {})
    bcv = _obtener_tasa_bcv()
    bcv_str = f"🏦 *BCV:* {bcv['tasa']:.2f} VES" if bcv and bcv.get('tasa') else ""
    lines = ["🔥 *TOP OPORTUNIDADES P2P*",
             f"🕐 {datetime.now(VENEZUELA_TZ).strftime('%H:%M')}\n"]
    for i, (a, m, c, v) in enumerate(ops[:3], 1):
        lines.append(f"{i}. *{a}:* +{m:.2f}% (Compra {c:.2f} | Venta {v:.2f} VES)")
    lines.append("")
    usdt_str = f"💵 *USDT:* Compra {usdt['compra']:.2f} | Venta {usdt['venta']:.2f} VES" if usdt.get("compra") else ""
    if usdt_str:
        lines.append(usdt_str)
    if bcv_str:
        lines.append(bcv_str)
    _ULTIMO_TOP_OPORT = time.time()
    _send_channel("\n".join(lines))

_ULTIMA_TASA_BCV = 0  # ultima tasa BCV conocida

def _obtener_intervalo_subastas():
    """Devuelve el intervalo de scraping segun la hora del dia."""
    hora = datetime.now(VENEZUELA_TZ).hour
    if 7 <= hora < 12:
        return 5    # manana: cada 5 segundos
    elif 12 <= hora < 23:
        return 120  # tarde/noche: cada 2 minutos
    else:
        return 0    # 11pm-7am: no scrapear

def _scrapear_subastas():
    """Scrapea el canal publico @subastasBCV y detecta cambios de estado."""
    global _SUBASTAS_ULTIMO_SCRAPED, _SUBASTAS_ESTADO
    intervalo = _obtener_intervalo_subastas()
    if intervalo == 0:
        return  # noche: no scrapear
    ahora = time.time()
    if ahora - _SUBASTAS_ULTIMO_SCRAPED < intervalo:
        return
    _SUBASTAS_ULTIMO_SCRAPED = ahora
    print("[Subastas] Scraping...", flush=True)

    try:
        proxy_tme = f"{CLOUDFLARE_PROXY.rstrip('/')}/t-me/s/subastasBCV"
        resp = requests.get(proxy_tme, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if resp.status_code != 200:
            return
        html = resp.text
    except Exception as e:
        print(f"[Subastas] Error scraping via proxy: {e}", flush=True)
        return

    import re
    mensajes = re.findall(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
    if not mensajes:
        return

    # Lista completa de bancos (nombres cortos y largos)
    BANCOS = {
        "BBVA": "BBVA",
        "BANCAMIGA": "BANCAMIGA",
        "BANCO PLAZA": "BANCO PLAZA",
        "BANCO EXTERIOR": "BANCO EXTERIOR",
        "EXTERIOR": "BANCO EXTERIOR",
        "BANCARIBE": "BANCARIBE",
        "BNC": "BNC",
        "BANCOCENTRO": "BANCOCENTRO",
        "BANCO VENEZOLANO DE CRÉDITO": "BANCO VENEZOLANO DE CRÉDITO",
        "100% BANCO": "100% BANCO",
        "BANCO MERCANTIL": "MERCANTIL",
        "MERCANTIL": "MERCANTIL",
        "BANCO NACIONAL DE CRÉDITO": "BANCO NACIONAL DE CRÉDITO",
        "BANCO PROVINCIAL": "PROVINCIAL",
        "BBVA PROVINCIAL": "PROVINCIAL",
        "PROVINCIAL": "PROVINCIAL",
        "BANCO DEL TESORO": "BANCO DEL TESORO",
        "BDT": "BDT",
        "BDV": "BDV",
        "BANCO DE VENEZUELA": "BDV",
        "BANESCO": "BANESCO",
        "BANCO MERCANTIL": "MERCANTIL",
    }

    for msg_html in mensajes[-30:]:
        msg = re.sub(r'<[^>]+>', ' ', msg_html).strip()
        msg = re.sub(r'\s+', ' ', msg)

        # Detectar bancos
        bancos_detectados = []
        for keyword, nombre in BANCOS.items():
            if keyword.upper() in msg.upper() and nombre not in bancos_detectados:
                bancos_detectados.append(nombre)

        # Detectar estado
        status = None
        tasa = None
        minimo = None
        maximo = None
        accion = ""

        msg_upper = msg.upper()

        # Estados de intervención
        if "INTERVENCIÓN ACTIVA" in msg_upper or "INTERVENCION ACTIVA" in msg_upper:
            status = "activa"
            accion = "INTERVENCIÓN ACTIVA"
        elif "INTERVENCIÓN CERRADA" in msg_upper or "INTERVENCION CERRADA" in msg_upper:
            status = "cerrada"
            accion = "INTERVENCIÓN CERRADA"
        elif "INTERVENCIÓN DIGITAL ACTIVA" in msg_upper or "INTERVENCION DIGITAL ACTIVA" in msg_upper:
            status = "activa"
            accion = "INTERVENCIÓN DIGITAL ACTIVA"
        elif "INTERVENCION ELECTRÓNICA ACTIVA" in msg_upper or "INTERVENCION ELECTRONICA ACTIVA" in msg_upper or "INTERVENCIÓN ELECTRÓNICO ACTIVA" in msg_upper or "INTERVENCION ELECTRONICO ACTIVA" in msg_upper:
            status = "activa"
            accion = "INTERVENCIÓN ELECTRÓNICA ACTIVA"
        elif "CONTINUA" in msg_upper or "ABIERTA" in msg_upper:
            status = "activa"
            accion = "INTERVENCIÓN ACTIVA"
        elif "CERRADA" in msg_upper:
            status = "cerrada"
            accion = "INTERVENCIÓN CERRADA"
        # Procesamiento de órdenes
        elif "RECHAZANDO" in msg_upper:
            status = "procesando"
            accion = "RECHAZANDO ÓRDENES"
        elif "APROBANDO" in msg_upper:
            status = "procesando"
            accion = "APROBANDO ÓRDENES"
        elif "ACREDITANDO" in msg_upper or "ACREDITARON" in msg_upper:
            status = "procesando"
            accion = "ACREDITANDO ÓRDENES"
        elif "PACTANDO" in msg_upper:
            status = "procesando"
            accion = "PACTANDO MONTO"
        # Noticias bancarias / BCV
        elif "BCV" in msg_upper and ("INTERVENCION" in msg_upper or "TASA" in msg_upper or "PUBLICA" in msg_upper or "NOTICIA" in msg_upper or "NUEVA" in msg_upper):
            status = "noticia"
            accion = "NOTICIA BCV"
        elif bancos_detectados and ("NUEVO" in msg_upper or "OPCIONES" in msg_upper or "AÑADE" in msg_upper or "HABILITA" in msg_upper or "INFORMAN" in msg_upper):
            status = "noticia"
            accion = "NOTICIA BANCARIA"

        # Extraer tasa
        tasa_match = re.search(r'(?:TASA|tasa)[:\s]*Bs\.?\s*([\d.,]+)', msg)
        if tasa_match:
            tasa = tasa_match.group(1).replace('.', '').replace(',', '.')

        # Extraer minimo/maximo
        min_match = re.search(r'(?:MÍNIMO|minimo)[:\s]*\$?\s*([\d.,]+)', msg)
        max_match = re.search(r'(?:MÁXIMO|maximo)[:\s]*\$?\s*([\d.,]+)', msg)
        if min_match:
            minimo = min_match.group(1).replace('.', '').replace(',', '.')
        if max_match:
            maximo = max_match.group(1).replace('.', '').replace(',', '.')

        if not bancos_detectados or not status:
            continue

        for banco in bancos_detectados:
            prev = _SUBASTAS_ESTADO.get(banco, {})
            # Para procesando y noticia, siempre enviar
            if prev.get("status") == status and status not in ("procesando", "noticia"):
                continue
            print(f"[Subastas] {banco} -> {status}", flush=True)

            _SUBASTAS_ESTADO[banco] = {"status": status, "ts": ahora}

            if status == "activa":
                tasa_str = f"Tasa: Bs. {tasa}" if tasa else ""
                rango_str = ""
                if minimo and maximo:
                    rango_str = f"Mín: ${minimo} | Máx: ${maximo}"
                _send_channel(
                    f"🏦 *{banco}* — {accion}\n"
                    f"{tasa_str}\n"
                    f"{rango_str}\n"
                    f"⏰ {datetime.now(VENEZUELA_TZ).strftime('%H:%M')}",
                    parse_mode="Markdown"
                )
            elif status == "cerrada":
                _send_channel(
                    f"🏦 *{banco}* — {accion}\n"
                    f"⏰ {datetime.now(VENEZUELA_TZ).strftime('%H:%M')}",
                    parse_mode="Markdown"
                )
            elif status == "procesando":
                _send_channel(
                    f"🏦 *{banco}* — {accion}\n"
                    f"⏰ {datetime.now(VENEZUELA_TZ).strftime('%H:%M')}",
                    parse_mode="Markdown"
                )
            elif status == "noticia":
                _send_channel(
                    f"📰 *{banco}* — {accion}\n"
                    f"{msg[:200]}\n"
                    f"⏰ {datetime.now(VENEZUELA_TZ).strftime('%H:%M')}",
                    parse_mode="Markdown"
                )


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


def _precio_p2p_resumen():
    usdt = ULTIMOS.get("USDT", {})
    if not usdt.get("compra"):
        return "No hay datos disponibles."
    precio_linea = f"💵 *USDT*: Compra {usdt['compra']:.2f} | Venta {usdt['venta']:.2f} VES"
    spread = usdt.get("margen")
    spread_linea = f"📊 *Spread:* {spread:+.2f}%" if spread is not None else ""
    bcv = _obtener_tasa_bcv()
    bcv_linea = f"🏦 *BCV:* {bcv['tasa']:.2f} VES" if bcv and bcv.get('tasa') else ""
    mejor_asset, mejor_margen = "", -999
    for a in ASSETS_VES:
        r = ULTIMOS.get(a)
        if r and r.get("margen", -999) > mejor_margen:
            mejor_margen = r["margen"]
            mejor_asset = a
    mejor = f"🔥 *Más vendido:* {mejor_asset} a {ULTIMOS[mejor_asset]['venta']:.2f} VES ({mejor_margen:+.2f}%)" if mejor_asset and mejor_asset != "USDT" else ""
    
    oportunidad = "✅ *Hay oportunidad de arbitraje*" if spread is not None and spread >= CONFIG["margen_objetivo"] else "❌ Sin oportunidad en este momento"
    return (
        f"💰 *MERCADO P2P VENEZUELA*\n"
        f"🕐 {datetime.now(VENEZUELA_TZ).strftime('%H:%M')}\n"
        f"{precio_linea}\n"
        f"{spread_linea}\n"
        f"{bcv_linea}\n"
        f"{mejor}\n\n"
        f"{oportunidad}"
    )


def guardar_config_local():
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(CONFIG, f)
        config_dict = {
            "capital": CONFIG.get("capital", 100),
            "margen_objetivo": CONFIG.get("margen_objetivo", 0.8),
            "monto_filtro": CONFIG.get("monto_filtro", 0),
            "default_crypto": CONFIG.get("default_crypto", "USDT"),
            "grupo_chat_id": CONFIG.get("grupo_chat_id", ""),
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
BIENVENIDA_ENVIADA = set()  # chat_ids que ya recibieron bienvenida
PRECISION = {
    "p2p": {"ok": 0, "fail": 0},
    "coingecko": {"ok": 0, "fail": 0},
    "dexscreener": {"ok": 0, "fail": 0},
    "telegram": {"ok": 0, "fail": 0},
    "supabase": {"ok": 0, "fail": 0},
    "inicio": time.time(),
    "ultimo_error": None,
    "ultimo_error_ts": None,
}
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

CLOUDFLARE_PROXY = os.getenv("CLOUDFLARE_PROXY", "https://ves-arbitraje-p2p.kelvinyohan14.workers.dev").rstrip("/")
URL_BINANCE = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
ASSETS_VES = ["USDT", "USDC", "BTC", "ETH", "BNB", "SOL"]
ASSETS_USD = ["USDC", "BTC", "ETH", "BNB", "SOL"]  # se muestran en USD internacional, no P2P VES
_COINGECKO_ASSET_IDS = {
    "USDC": "usd-coin",
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
}
HISTORIAL_PATH = "historial_precios.jsonl"

VENEZUELA_TZ = timezone(timedelta(hours=-4))
SLEEP_START = 23  # 11 PM
SLEEP_END = 7     # 7 AM


def en_horario():
    hora = datetime.now(VENEZUELA_TZ).hour
    if SLEEP_START <= SLEEP_END:
        return not (SLEEP_START <= hora < SLEEP_END)
    else:
        return not (hora >= SLEEP_START or hora < SLEEP_END)
# ============================================================


# ============================================================
# TELEGRAM - CONFIG (exact pattern from youtube-shorts-bot)
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")
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
            PRECISION["telegram"]["ok"] += 1
            return resp.json(), None
        except Exception as e:
            PRECISION["telegram"]["fail"] += 1
            err_str = str(e)
            if attempt == 1 and data and ('SSLError' in err_str or 'UNEXPECTED_EOF' in err_str or 'EOF occurred' in err_str):
                try:
                    res = _raw_ssl_post(url, json_data=data, timeout=timeout)
                    PRECISION["telegram"]["ok"] += 1
                    return res, None
                except Exception:
                    PRECISION["telegram"]["fail"] += 1
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


def _construir_teclado(chat_id=None):
    if chat_id and not _es_master(chat_id):
        return [
            [{"text": "\U0001F4B0 Precio", "callback_data": "precio"}],
            [{"text": f"\u2699\ufe0f Capital (${_get_config(chat_id)['capital']:.0f})", "callback_data": "capital"},
             {"text": f"\U0001F3AF Umbral ({_get_config(chat_id)['margen_objetivo']}%)", "callback_data": "umbral"}],
            [{"text": "\U0001F4C5 Historial", "callback_data": "historial"},
             {"text": "\U0001F9EE Calc", "callback_data": "calculadora"},
             {"text": "\U0001F504 Actualizar", "callback_data": "menu"}],
        ]
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
         [{"text": "\U0001F4CA Precisión", "callback_data": "precision"},
          {"text": "\U0001F9EE Calc", "callback_data": "calculadora"},
          {"text": "\U0001F504 Actualizar", "callback_data": "menu"}],
         [{"text": "\u2753 Ayuda", "callback_data": "ayuda"}],
    ]



def enviar_menu(chat_id=None, texto=None):
    cid = chat_id or int(TELEGRAM_CHAT_ID)
    if not texto:
        cfg = _get_config(cid)
        texto = (
            f"💰 *Arbitraje P2P VES*\n"
            f"Capital: ${cfg['capital']:.0f} | Umbral: {cfg['margen_objetivo']}%\n"
            f"Filtro: {nombre_filtro()} | Comisiones: {COMISION_TOTAL*100:.2f}%"
        )
    kb = json.dumps({"inline_keyboard": _construir_teclado(cid)})
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
    kb = json.dumps({"inline_keyboard": _construir_teclado(chat_id)})
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
            PRECISION["p2p"]["fail"] += 1
            return None
        PRECISION["p2p"]["ok"] += 1
        start = 0
        end = min(3, len(anuncios))
        precios = [float(anuncios[i]["adv"]["price"]) for i in range(start, end)]
        return sum(precios) / len(precios) if precios else None
    except Exception as e:
        PRECISION["p2p"]["fail"] += 1
        PRECISION["ultimo_error"] = f"P2P/{asset}/{trade_type}: {e}"
        PRECISION["ultimo_error_ts"] = time.time()
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
        PRECISION["coingecko"]["ok"] += 1
        return float(resp.json().get(cfg["coingecko_id"], {}).get("usd", 0))
    except Exception as e:
        PRECISION["coingecko"]["fail"] += 1
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
        PRECISION["coingecko"]["ok"] += 1
        return data
    except Exception as e:
        PRECISION["coingecko"]["fail"] += 1
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
            PRECISION["dexscreener"]["ok"] += 1
            print(f"  [DEX/{network_key}] DexScreener most-liquid: ${best_price:.4f} (liq: ${best_liq:.0f})", flush=True)
            return best_price
        PRECISION["dexscreener"]["fail"] += 1
    except Exception as e:
        PRECISION["dexscreener"]["fail"] += 1
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


def _obtener_precio_usd(asset):
    """Precio spot internacional en USD via CoinGecko."""
    cg_id = _COINGECKO_ASSET_IDS.get(asset)
    if not cg_id:
        return None
    try:
        data = _fetch_all_spot_prices()
        price = float(data.get(cg_id, {}).get("usd", 0))
        if price > 0:
            return price
        time.sleep(1)
        resp = requests.get(
            f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd",
            headers=HEADERS, timeout=5
        )
        resp.raise_for_status()
        price = float(resp.json().get(cg_id, {}).get("usd", 0))
        if price > 0:
            return price
    except Exception as e:
        print(f"[USD/{asset}] Error: {e}", flush=True)
    return None


def _calc_margen(buy, sell, capital=None):
    neto = (sell - buy) - (buy * COMISION) - (sell * COMISION) - (buy * COMISION_BANCO)
    pct = (neto / buy) * 100
    cap = capital or CONFIG["capital"]
    return {"neto": neto, "pct": pct, "usd": cap * (pct / 100)}

def calcular_margen(asset, trans_amount=None):
    if asset in ASSETS_USD:
        spot = _obtener_precio_usd(asset)
        if spot is None:
            return None
        dex = None
        if asset in DEX_NETWORKS:
            dex = obtener_precio_dex(asset)
        venta = dex if dex else spot
        with _ULTIMOS_LOCK:
            ULTIMOS[asset] = {"compra": spot, "venta": venta, "margen": 0.0, "moneda": "USDT"}
        return {
            "asset": asset, "compra": spot, "venta": venta,
            "margen": 0.0, "ganancia_usd": 0.0, "ganancia_ves": None,
            "moneda": "USDT", "spot": spot, "dex": dex,
            "filtro": "Internacional"
        }

    monto = trans_amount if trans_amount is not None else CONFIG["monto_filtro"]
    maker_venta = obtener_precio_p2p("BUY", asset, monto)
    maker_compra = obtener_precio_p2p("SELL", asset, monto)
    if maker_venta is None or maker_compra is None:
        return None

    m = _calc_margen(maker_compra, maker_venta)
    t = _calc_margen(maker_compra, maker_venta)

    tasa_ves = ULTIMOS.get("USDT", {}).get("venta") or None

    with _ULTIMOS_LOCK:
        ULTIMOS[asset] = {"compra": maker_compra, "venta": maker_venta, "margen": m["pct"], "moneda": "VES"}

    return {
        "asset": asset, "compra": maker_compra, "venta": maker_venta,
        "margen": m["pct"], "ganancia_usd": m["usd"],
        "ganancia_ves": (m["usd"] * tasa_ves) if tasa_ves else None,
        "moneda": "VES",
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
        return "⚠️ *No hay suficientes datos* históricos para realizar el análisis de horarios aún. Se necesitan al menos 24 horas de datos."

    # Obtener precio actual en vivo para comparar
    precio_compra_ahora = obtener_precio_p2p("BUY", asset="USDT", trans_amount=0)
    precio_venta_ahora = obtener_precio_p2p("SELL", asset="USDT", trans_amount=0)
    
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

    # Precio actual vs promedio histórico
    texto = (
        f"📊 *ANÁLISIS DE HORARIOS (USDT)*\n\n"
        f"💡 *¿Qué es esto?* Un promedio del precio del USDT a cada hora\n"
        f"durante los últimos 7 días. Sirve para ver *patrones*: saber a\n"
        f"qué horas suele estar más barato o más caro.\n"
        f"⚠️ No es el precio actual — son datos históricos.\n\n"
    )
    
    # Precio actual vs promedio general
    todos_precios = [datos[h] for h in datos]
    prom_gral_compra = sum(d['avg_compra'] for d in todos_precios) / len(todos_precios)
    prom_gral_venta = sum(d['avg_venta'] for d in todos_precios) / len(todos_precios)
    
    if precio_compra_ahora and precio_venta_ahora:
        dif_compra = ((precio_compra_ahora - prom_gral_compra) / prom_gral_compra) * 100
        dif_venta = ((precio_venta_ahora - prom_gral_venta) / prom_gral_venta) * 100
        texto += (
            f"📌 *Precio AHORA vs Promedio 7 días:*\n"
            f"   Compra: *{precio_compra_ahora:.2f}* VES ({dif_compra:+.2f}% vs prom.)\n"
            f"   Venta:  *{precio_venta_ahora:.2f}* VES ({dif_venta:+.2f}% vs prom.)\n"
            f"   Prom. gral. compra: {prom_gral_compra:.2f} VES\n"
            f"   Prom. gral. venta:  {prom_gral_venta:.2f} VES\n\n"
        )
    
    texto += (
        f"🟢 *Mejor hora para COMPRAR (más barato):*\n"
        f"   ➔ *{mejor_maker_compra:02d}:00* — Prom. 7 días: {datos[mejor_maker_compra]['avg_compra']:.2f} VES\n"
        f"🔴 *Mejor hora para VENDER (más caro):*\n"
        f"   ➔ *{mejor_maker_venta:02d}:00* — Prom. 7 días: {datos[mejor_maker_venta]['avg_venta']:.2f} VES\n\n"
        f"📈 *Promedio por Bloque Horario (7 días):*\n"
    )
    
    for bloque, stats in bloque_stats.items():
        spread_bruto = ((stats['venta'] - stats['compra']) / stats['compra']) * 100
        texto += (
            f"📍 *{bloque}*\n"
            f"   Compra: {stats['compra']:.2f} | Venta: {stats['venta']:.2f} | Spread: {spread_bruto:+.2f}%\n"
        )
        
    spread_por_bloque = [(b, ((s['venta'] - s['compra']) / s['compra']) * 100, s) for b, s in bloque_stats.items()]
    spread_por_bloque.sort(key=lambda x: x[1], reverse=True)
    mejor_bloque = spread_por_bloque[0]
    peor_bloque = spread_por_bloque[-1]

    tips = []
    tips.append(f"📍 *{mejor_bloque[0]}* — spread más alto ({mejor_bloque[1]:+.2f}%) → mejor ventana para operar.")
    tips.append(f"📍 *{peor_bloque[0]}* — spread más bajo ({peor_bloque[1]:+.2f}%) → menos oportunidad.")

    horas_top = sorted(datos.items(), key=lambda x: x[1]['avg_compra'])[:2]
    tips.append(f"🟢 Compras más baratas (prom. 7 días): ~{horas_top[0][0]:02d}:00 y ~{horas_top[1][0]:02d}:00.")

    horas_mas_muestras = sorted(datos.items(), key=lambda x: x[1]['muestras'], reverse=True)[:2]
    tips.append(f"📊 Mayor liquidez (más órdenes): ~{horas_mas_muestras[0][0]:02d}:00 y ~{horas_mas_muestras[1][0]:02d}:00.")

    horas_menos_muestras = sorted(datos.items(), key=lambda x: x[1]['muestras'])[:2]
    if horas_menos_muestras[0][1]['muestras'] < 10:
        tips.append(f"⚠️ Baja liquidez: ~{horas_menos_muestras[0][0]:02d}:00 ({horas_menos_muestras[0][1]['muestras']} muestras) — spreads erráticos.")

    texto += "\n💡 *Tips:*\n" + "\n".join(f"• {t}" for t in tips)
    texto += (
        "\n\n📖 *Cómo usar este análisis:*\n"
        "• Si el precio AHORA está por debajo del prom. 7 días → está barato\n"
        "• Si está por encima → está caro respecto al histórico\n"
        "• El spread alto = más ganancia potencial por operación\n"
        "• La liquidez alta = órdenes se ejecutan más rápido"
    )
    return texto


# ============================================================


# ============================================================
# SISTEMA DE SEÑALES MULTICAPA (90%+ precision objetivo)
# ============================================================

def _cargar_precios_usdt(horas=24):
    compras, ventas = [], []
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            desde = (datetime.now(VENEZUELA_TZ) - timedelta(hours=horas)).isoformat()
            registros = supabase_select_all(ts_gte=desde)
            for rec in registros:
                usdt = rec.get("USDT")
                if not isinstance(usdt, dict): continue
                c = usdt.get("compra")
                v = usdt.get("venta")
                if c: compras.append(float(c))
                if v: ventas.append(float(v))
        except Exception as e:
            print(f"Supabase error: {e}", flush=True)
    if len(compras) < 10:
        try:
            if os.path.exists(HISTORIAL_PATH):
                ahora = datetime.now(VENEZUELA_TZ)
                with open(HISTORIAL_PATH, "r") as f:
                    for linea in f:
                        try:
                            d = json.loads(linea)
                            if "USDT" not in d: continue
                            ts = d.get("ts", "")
                            if not ts: continue
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if (ahora - dt).total_seconds() > horas * 3600: continue
                            c = d["USDT"].get("compra")
                            v = d["USDT"].get("venta")
                            if c: compras.append(float(c))
                            if v: ventas.append(float(v))
                        except Exception:
                            continue
        except Exception:
            pass
    return compras, ventas


def _calcular_tendencia_6h():
    """Regresion lineal simple sobre ultimas 6h de precio compra USDT.
    Retorna pendiente (positiva=subiendo, negativa=bajando) o None."""
    precios, timestamps = [], []
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            desde = (datetime.now(VENEZUELA_TZ) - timedelta(hours=6)).isoformat()
            registros = supabase_select_all(ts_gte=desde)
            ahora = datetime.now(VENEZUELA_TZ)
            for rec in registros:
                usdt = rec.get("USDT")
                if not isinstance(usdt, dict): continue
                c = usdt.get("compra")
                if c is None: continue
                precios.append(float(c))
                ts = rec.get("ts", "")
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        timestamps.append((ahora - dt).total_seconds() / 3600)
                    except Exception:
                        timestamps.append(len(precios))
                else:
                    timestamps.append(len(precios))
        except Exception as e:
            print(f"Supabase tendencia error: {e}", flush=True)
    if len(precios) < 5:
        try:
            if os.path.exists(HISTORIAL_PATH):
                ahora = datetime.now(VENEZUELA_TZ)
                with open(HISTORIAL_PATH, "r") as f:
                    for linea in f:
                        try:
                            d = json.loads(linea)
                            if "USDT" not in d: continue
                            ts = d.get("ts", "")
                            if not ts: continue
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            h = (ahora - dt).total_seconds() / 3600
                            if h > 6: continue
                            c = d["USDT"].get("compra")
                            if c:
                                precios.append(float(c))
                                timestamps.append(h)
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


# ============================================================
# INDICADORES TECNICOS (Fase 2)
# ============================================================

SPARK_CHARS = ["\u2581", "\u2582", "\u2583", "\u2584", "\u2585", "\u2586", "\u2587", "\u2588"]

def _sparkline(datos, ancho=20):
    if not datos:
        return ""
    if ancho < 2:
        ancho = 2
    sampled = datos[::max(1, len(datos)//ancho)][:ancho]
    mn, mx = min(sampled), max(sampled)
    if mx - mn < 0.0001:
        return "\u2585" * len(sampled)
    n = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[min(int((v - mn) * n / (mx - mn)), n)] for v in sampled)


def _calcular_sma(precios, period):
    if len(precios) < period:
        return None
    return sum(precios[-period:]) / period


def _calcular_ema(precios, period):
    if len(precios) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(precios[:period]) / period
    for p in precios[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def _calcular_rsi(precios, period=14):
    if len(precios) < period + 1:
        return None
    ganancias, perdidas = 0, 0
    for i in range(-period, 0):
        diff = precios[i] - precios[i-1]
        if diff > 0:
            ganancias += diff
        else:
            perdidas -= diff
    if perdidas == 0:
        return 100
    rs = (ganancias / period) / (perdidas / period)
    return 100 - (100 / (1 + rs))


def _calcular_bollinger(precios, period=20, desv=2):
    if len(precios) < period:
        return None, None, None
    sma = sum(precios[-period:]) / period
    var = sum((p - sma) ** 2 for p in precios[-period:]) / period
    std = var ** 0.5
    return sma - desv * std, sma, sma + desv * std


def _calcular_macd(precios, fast=12, slow=26, signal=9):
    n = len(precios)
    if n < slow + signal:
        return None, None
    k_fast = 2 / (fast + 1)
    ema_fast_vals = [sum(precios[:fast]) / fast]
    for p in precios[fast:]:
        ema_fast_vals.append(p * k_fast + ema_fast_vals[-1] * (1 - k_fast))
    k_slow = 2 / (slow + 1)
    ema_slow_vals = [sum(precios[:slow]) / slow]
    for p in precios[slow:]:
        ema_slow_vals.append(p * k_slow + ema_slow_vals[-1] * (1 - k_slow))
    offset = slow - fast
    macd_vals = [ema_fast_vals[i + offset] - ema_slow_vals[i] for i in range(len(ema_slow_vals))]
    macd_line = macd_vals[-1]
    k_sig = 2 / (signal + 1)
    sig_vals = [sum(macd_vals[:signal]) / signal]
    for v in macd_vals[signal:]:
        sig_vals.append(v * k_sig + sig_vals[-1] * (1 - k_sig))
    return macd_line, sig_vals[-1]


def _detectar_niveles_clave():
    """Encuentra niveles de soporte (compra) y resistencia (venta) del USDT.
    Retorna (soportes, resistencias) como listas de precios."""
    compras, ventas = [], []
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            desde = (datetime.now(VENEZUELA_TZ) - timedelta(days=7)).isoformat()
            registros = supabase_select_all(ts_gte=desde)
            for rec in registros:
                usdt = rec.get("USDT")
                if not isinstance(usdt, dict): continue
                c = usdt.get("compra")
                v = usdt.get("venta")
                if c: compras.append(float(c))
                if v: ventas.append(float(v))
        except Exception as e:
            print(f"Supabase niveles error: {e}", flush=True)
    if len(compras) < 20:
        try:
            if os.path.exists(HISTORIAL_PATH):
                with open(HISTORIAL_PATH, "r") as f:
                    for linea in f:
                        try:
                            d = json.loads(linea)
                            if "USDT" not in d: continue
                            ts = d.get("ts", "")
                            if not ts: continue
                            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if (datetime.now(VENEZUELA_TZ) - dt).total_seconds() > 86400 * 7: continue
                            c = d["USDT"].get("compra")
                            v = d["USDT"].get("venta")
                            if c: compras.append(float(c))
                            if v: ventas.append(float(v))
                        except Exception:
                            continue
        except Exception:
            pass
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
    r = calcular_margen("USDT")
    if not r:
        return None, 0, {}, None

    precios_compra, precios_venta = _cargar_precios_usdt(24)
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

    rsi = _calcular_rsi(precios_compra, 14)
    bb_low, bb_mid, bb_high = _calcular_bollinger(precios_compra, 20, 2)
    macd_line, signal_line = _calcular_macd(precios_compra, 12, 26, 9)

    precio = r["compra"]
    toco_banda_baja = bb_low is not None and precio <= bb_low * 1.005
    toco_banda_alta = bb_high is not None and precio >= bb_high * 0.995
    rsi_bajo = rsi is not None and rsi < 35
    rsi_alto = rsi is not None and rsi > 65
    macd_arriba = macd_line is not None and signal_line is not None and macd_line > signal_line

    detalles = {
        "desv_compra": desv_compra, "desv_venta": desv_venta,
        "pendiente": pendiente, "en_soporte": en_soporte,
        "en_resistencia": en_resistencia, "avg_compra": avg_compra,
        "avg_venta": avg_venta, "rsi": rsi, "bb_low": bb_low,
        "bb_high": bb_high, "macd_arriba": macd_arriba,
    }

    if desv_compra <= -TIMING_THRESHOLD_PCT:
        conf, razones = 50, ["Precio bajo vs promedio 24h"]
        if pendiente is not None:
            if pendiente >= -0.5:
                conf += 10; razones.append("Tendencia estable o subiendo")
            else:
                conf -= 10; razones.append("Sigue cayendo (esperar)")
        if en_soporte:
            conf += 10; razones.append("Cerca de soporte histórico")
        if rsi_bajo:
            conf += 10; razones.append(f"RSI bajo ({rsi:.0f}) - mercado sobrevendido")
        if toco_banda_baja:
            conf += 10; razones.append("Tocando banda inferior de Bollinger")
        if desv_compra <= -3:
            conf += 10; razones.append("Oportunidad fuerte (>3%)")
        if soportes:
            razones.append(f"Soporte en {soportes[0]} VES")

        razones_simple = razones[:2]
        spark_compra = _sparkline(precios_compra, 16)
        return ("compra", min(conf, 100), detalles,
            f"📉 *SEÑAL DE COMPRA* (Confianza: {min(conf,100)}%)\n"
            f"💵 *Precio:* {r['compra']:.2f} VES\n"
            f"📊 *Vs promedio 24h:* {desv_compra:+.2f}%\n"
            f"{'📈 *Tendencia:* estable' if pendiente is None or pendiente >= -0.5 else '📉 *Tendencia:* bajando'}\n"
            + (f"✅ *Soporte:* {soportes[0]} VES\n" if en_soporte else "")
            + f"💡 *Razón:* {', '.join(razones_simple)}\n\n"
            f"🟢 *Acción:* Compra USDT ahora. Precio bajo vs promedio.")

    if desv_venta >= TIMING_THRESHOLD_PCT:
        conf, razones = 50, ["Precio alto vs promedio 24h"]
        if pendiente is not None:
            if pendiente <= 0.5:
                conf += 10; razones.append("Tendencia estable o bajando")
            else:
                conf -= 10; razones.append("Sigue subiendo (esperar)")
        if en_resistencia:
            conf += 10; razones.append("Cerca de resistencia histórica")
        if rsi_alto:
            conf += 10; razones.append(f"RSI alto ({rsi:.0f}) - mercado sobrecomprado")
        if toco_banda_alta:
            conf += 10; razones.append("Tocando banda superior de Bollinger")
        if desv_venta >= 3:
            conf += 10; razones.append("Oportunidad fuerte (>3%)")
        if resistencias:
            razones.append(f"Resistencia en {resistencias[-1]} VES")

        razones_simple = razones[:2]
        spark_venta = _sparkline(precios_venta, 16)
        return ("venta", min(conf, 100), detalles,
            f"📈 *SEÑAL DE VENTA* (Confianza: {min(conf,100)}%)\n"
            f"💵 *Precio:* {r['venta']:.2f} VES\n"
            f"📊 *Vs promedio 24h:* {desv_venta:+.2f}%\n"
            f"{'📉 *Tendencia:* estable' if pendiente is None or pendiente <= 0.5 else '📈 *Tendencia:* subiendo'}\n"
            + (f"✅ *Resistencia:* {resistencias[-1]} VES\n" if en_resistencia else "")
            + f"💡 *Razón:* {', '.join(razones_simple)}\n\n"
            f"🔴 *Acción:* Venta de USDT ahora. Precio alto vs promedio.")

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


def _resumen_diario():
    """Genera y envía el resumen diario del mercado al canal."""
    ahora = datetime.now(VENEZUELA_TZ)
    fecha = ahora.strftime("%d/%m/%Y")
    hora = ahora.strftime("%H:%M")

    lines = [
        f"🌅 *BUENOS DÍAS — RESUMEN DEL MERCADO*",
        f"📅 {fecha} | ⏰ {hora} (Venezuela)\n",
    ]

    bcv = _obtener_tasa_bcv()
    if bcv and bcv.get("tasa"):
        lines.append(f"🏦 *BCV:* {bcv['tasa']:.2f} VES/USD")

    for asset in ["USDT", "USDC"]:
        r = calcular_margen(asset)
        if not r:
            continue
        if r.get("moneda") == "USDT":
            lines.append(f"💵 *{asset} (P2P VES)*: ${r['compra']:.4f}")
        else:
            spread_pct = ((r["venta"] - r["compra"]) / r["compra"]) * 100 if r["compra"] else 0
            lines.append(f"💵 *{asset} VES*: Comprar {r['compra']:.2f} | Vender {r['venta']:.2f} (spread {spread_pct:+.2f}%)")
        time.sleep(0.3)

    precios_c, precios_v = _cargar_precios_usdt(24)
    if precios_c:
        min_c = min(precios_c)
        max_c = max(precios_c)
        avg_c = sum(precios_c) / len(precios_c)
        spark = _sparkline(precios_c, 16)
        lines.append(f"\n📈 *USDT 24h:* `{spark}`")
        lines.append(f"   Mín: {min_c:.2f} | Máx: {max_c:.2f} | Prom: {avg_c:.2f} VES")

    r_usdt = calcular_margen("USDT")
    if r_usdt:
        usdt_spread = ((r_usdt["venta"] - r_usdt["compra"]) / r_usdt["compra"]) * 100
        hay_arbitraje = usdt_spread >= CONFIG["margen_objetivo"]
        lines.append(f"\n📊 *Spread actual USDT:* {usdt_spread:+.2f}%")
        lines.append(f"{'✅ *Hay oportunidad de arbitraje*' if hay_arbitraje else '❌ *Sin oportunidad* — spread bajo'}")

    msg = "\n".join(lines)
    _send_channel(msg, parse_mode="Markdown")


# ============================================================
# PROCESAR ACTUALIZACIONES TELEGRAM
# ============================================================
def procesar_mensaje(texto, chat_id):
    if (texto.startswith("/precio") or texto.startswith("/p2p") or texto.startswith("/mercado")):
        grupo_id = CONFIG.get("grupo_chat_id", "")
        if grupo_id and str(chat_id) == grupo_id:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": _precio_p2p_resumen(), "parse_mode": "Markdown"})
        return
    if (texto.startswith("/ayuda") or texto.startswith("/comandos")):
        grupo_id = CONFIG.get("grupo_chat_id", "")
        if grupo_id and str(chat_id) == grupo_id and not _es_master(chat_id):
            _tg_call("sendMessage", {"chat_id": chat_id, "text":
                "📋 *Comandos disponibles:*\n\n"
                "💰 `/precio` — Precios P2P Venezuela en vivo\n"
                "   (también: /p2p, /mercado)\n\n"
                "🔒 *Funciones premium* próximamente.\n"
                "   Contacta al admin para más info.",
                "parse_mode": "Markdown"})
            return
        # si es master, deja que pase al /help handler privado
    if texto.startswith("/groupid"):
        if not _es_master(chat_id):
            return
        _tg_call("sendMessage", {"chat_id": chat_id, "text": f"Este chat ID es: `{chat_id}`", "parse_mode": "Markdown"})
        return
    if texto.startswith("/setgrupo"):
        if not _es_master(chat_id):
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Solo el master puede ejecutar este comando."})
            return
        partes = texto.split(maxsplit=1)
        if len(partes) > 1:
            grupo_id = partes[1].strip()
        else:
            grupo_id = str(chat_id)
        CONFIG["grupo_chat_id"] = grupo_id
        guardar_config_local()
        _tg_call("sendMessage", {"chat_id": chat_id, "text": f"Grupo configurado: `{grupo_id}`", "parse_mode": "Markdown"})
        return
    if not _autorizado(chat_id):
        return
    estado = ESTADOS_USUARIO.get(chat_id, {})
    if estado.get("esperando") == "capital":
        try:
            nuevo = float(texto.strip())
            if nuevo > 0:
                cfg = _get_config(chat_id)
                viejo = cfg["capital"]
                if _es_master(chat_id):
                    CONFIG["capital"] = nuevo
                    guardar_config_local()
                else:
                    _save_chat_config(chat_id, {"capital": nuevo})
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
                cfg = _get_config(chat_id)
                viejo = cfg["margen_objetivo"]
                if _es_master(chat_id):
                    CONFIG["margen_objetivo"] = nuevo
                    guardar_config_local()
                    ALERTA_ENVIADA.clear()
                else:
                    _save_chat_config(chat_id, {"margen_objetivo": nuevo})
                enviar_menu(chat_id, f"Umbral actualizado: {viejo:.1f}% -> {nuevo:.1f}%")
            else:
                _tg_call("sendMessage", {"chat_id": chat_id, "text": "Debe estar entre 0 y 100."})
        except ValueError:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Ingresa un numero, ej: 1.5"})
        ESTADOS_USUARIO.pop(chat_id, None)
        return
    elif estado.get("esperando") == "calculadora":
        try:
            compra = float(texto.strip())
            if compra <= 0:
                _tg_call("sendMessage", {"chat_id": chat_id, "text": "Debe ser mayor a 0."})
                ESTADOS_USUARIO.pop(chat_id, None)
                return
            venta_actual = ULTIMOS.get("USDT", {}).get("venta")
            cap = _get_config(chat_id)["capital"]
            be = compra * (1 + COMISION_TOTAL)
            lines = [
                f"\U0001F9EE *Calculadora P2P*",
                f"Compra: *{compra:.2f} VES*",
                f"Capital: ${cap:.0f} USD\n",
                f"\U0001F4CD *Punto de equilibrio:* *{be:.2f} VES/USDT*",
                f"(m\u00ednimo para no perder, comisiones incluidas)\n",
            ]
            if venta_actual:
                ganancia_unit = venta_actual - be
                pct = (ganancia_unit / compra) * 100
                ganancia_total = ganancia_unit * cap
                icono = "\u2705" if ganancia_unit > 0 else "\u274C"
                lines.append(f"{icono} *Venta actual (mercado):* {venta_actual:.2f} VES")
                lines.append(f"   Por USDT: {ganancia_unit:+.2f} VES ({pct:+.2f}%)")
                lines.append(f"   Total x {cap} USD: *{ganancia_total:+.2f} VES* (${ganancia_unit*cap/venta_actual:.2f} USD)")
                lines.append("")
            lines.append("*Proyecciones (precio venta → ganancia total):*")
            for pct_obj in [0.5, 0.8, 1.0, 1.5, 2.0]:
                pv = compra * (1 + pct_obj/100)
                g_unit = pv - be
                g_total = g_unit * cap
                g_usd = g_total / pv if pv > 0 else 0
                lines.append(f"   {pv:.2f} → {g_unit:+.2f} VES/USDT | *${g_usd:.2f} USD* ({g_total:+.2f} VES)")
            lines.append(f"\n\u2699 *Comisiones:* {COMISION_TOTAL*100:.2f}% total")
            kb_calc = json.dumps({
                "inline_keyboard": [
                    [{"text": "\U0001F519 Men\u00fa", "callback_data": "menu"},
                     {"text": "\U0001F9EE Nueva", "callback_data": "calculadora"}]
                ]
            })
            _tg_call("sendMessage", {
                "chat_id": chat_id, "text": "\n".join(lines),
                "parse_mode": "Markdown", "reply_markup": kb_calc
            })
        except ValueError:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Ingresa un n\u00famero, ej: 776"})
        ESTADOS_USUARIO.pop(chat_id, None)
        return
    if texto.startswith("/decirchan"):
        if not _es_master(chat_id):
            return
        msg = texto[len("/decirchan"):].strip()
        if msg and TELEGRAM_CHANNEL_ID:
            _tg_call("sendMessage", {"chat_id": int(TELEGRAM_CHANNEL_ID), "text": msg, "parse_mode": "Markdown"})
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Mensaje enviado al canal."})
        elif not TELEGRAM_CHANNEL_ID:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "No hay canal configurado."})
        else:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Uso: /decirchan <mensaje>"})
        return
    if texto.startswith("/decir"):
        if not _es_master(chat_id):
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Solo el master puede ejecutar este comando."})
            return
        msg = texto[len("/decir"):].strip()
        if msg:
            destino = CONFIG.get("grupo_chat_id")
            if destino:
                try:
                    destino_id = int(destino)
                    _tg_call("sendMessage", {"chat_id": destino_id, "text": msg, "parse_mode": "Markdown"})
                    _tg_call("sendMessage", {"chat_id": chat_id, "text": "Mensaje enviado al grupo."})
                except ValueError:
                    _tg_call("sendMessage", {"chat_id": chat_id, "text": "GRUPO_CHAT_ID no es un número válido. Configúralo primero."})
            else:
                _tg_call("sendMessage", {"chat_id": chat_id, "text": "No hay grupo configurado. Corre /setgrupo desde el grupo primero."})
        else:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Uso: /decir <mensaje>"})
        return
    if texto.startswith("/help") or texto.startswith("/ayuda") or texto.startswith("/comandos") or texto.startswith("/start") or texto == "/":
        if not _es_master(chat_id):
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Bot de señales P2P. Usa los botones del menú.", "parse_mode": "Markdown"})
            return
        _tg_call("sendMessage", {"chat_id": chat_id, "text":
            "*Comandos del bot:*\n\n"
            "📋 `/menu` — Menú principal\n"
            "🏷️ `/precio` — Precios P2P\n"
            "📊 `/multi` — Multi-cripto\n"
            "💰 `/capital` — Capital\n"
            "🎯 `/umbral` — Umbral de alerta\n"
            "📈 `/historial` — Historial\n"
            "🔍 `/filtro` — Filtro\n"
            "🔄 `/dex` — DEX\n"
            "⏰ `/horarios` — Horarios\n"
            "⚡ `/combo` — Combo\n"
            "📉 `/mercado` — Mercado\n"
            "🎯 `/precision` — Precisión\n"
            "🧮 `/calc` — Calculadora\n\n"
            "*Comandos de grupo (solo master):*\n"
            "📢 `/decir <msg>` — Enviar al grupo\n"
            "🚫 `/ban <id> [horas]` — Banear usuario\n"
            "✅ `/unban <id>` — Desbanear\n"
            "🆔 `/groupid` — ID del chat actual\n"
            "⚙️ `/setgrupo <id>` — Configurar grupo\n\n"
            "💡 *Tip:* También puedes usar los botones del menú.",
            "parse_mode": "Markdown"})
        return
    if texto.startswith("/ban"):
        if not _es_master(chat_id):
            return
        destino = CONFIG.get("grupo_chat_id")
        if not destino:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "No hay grupo configurado."})
            return
        partes = texto.split()
        if len(partes) < 2:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Uso: /ban <user_id> [horas]"})
            return
        try:
            user_id = int(partes[1])
            params = {"chat_id": int(destino), "user_id": user_id}
            if len(partes) >= 3:
                horas = float(partes[2])
                until = int(time.time()) + int(horas * 3600)
                params["until_date"] = until
                _tg_call("banChatMember", params)
                _tg_call("sendMessage", {"chat_id": chat_id, "text": f"Usuario `{user_id}` baneado por {horas}h.", "parse_mode": "Markdown"})
            else:
                _tg_call("banChatMember", params)
                _tg_call("sendMessage", {"chat_id": chat_id, "text": f"Usuario `{user_id}` baneado permanentemente.", "parse_mode": "Markdown"})
        except Exception as e:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": f"Error al banear: {e}"})
        return
    if texto.startswith("/unban"):
        if not _es_master(chat_id):
            return
        destino = CONFIG.get("grupo_chat_id")
        if not destino:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "No hay grupo configurado."})
            return
        partes = texto.split()
        if len(partes) < 2:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": "Uso: /unban <user_id>"})
            return
        try:
            user_id = int(partes[1])
            _tg_call("unbanChatMember", {"chat_id": int(destino), "user_id": user_id, "only_if_banned": True})
            _tg_call("sendMessage", {"chat_id": chat_id, "text": f"Usuario `{user_id}` desbaneado.", "parse_mode": "Markdown"})
        except Exception as e:
            _tg_call("sendMessage", {"chat_id": chat_id, "text": f"Error al desbanear: {e}"})
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
    cfg = _get_config(chat_id)
    asset = cfg.get("default_crypto", "USDT")
    r = calcular_margen(asset)
    if r:
        if r.get("moneda") == "USDT":
            dex_line = ""
            if r.get("dex"):
                diff = ((r["dex"] - r["compra"]) / r["compra"]) * 100
                dex_line = f"DEX (Phantom): ${r['dex']:.4f} ({diff:+.2f}% vs spot)\n"
            editar_mensaje(chat_id, msg_id,
                f"\U0001F4B0 *{asset} / USDT* (Internacional)\n\n"
                f"Spot (Binance): *${r['compra']:.4f}*\n"
                f"{dex_line}"
                f"\U0001F4C8 Precio internacional de referencia.\n"
                f"No aplica arbitraje P2P.")
        else:
            pri = ((r['venta'] - r['compra']) / r['compra']) * 100
            m = _calc_margen(r['compra'], r['venta'], cfg['capital'])
            rentable = "\u2705 RENTABLE" if m['pct'] > 0 else "\u274C NO RENTABLE"
            taker_rentable = "\u2705 RENTABLE" if r['taker_margen'] > 0 else "\u274C NO RENTABLE"
            taker_ves_str = f" | Bs.{r['taker_ganancia_ves']:.2f}" if r.get('taker_ganancia_ves') else ""
            editar_mensaje(chat_id, msg_id,
                f"\U0001F4B0 *{asset} / VES* ({r['filtro']})\n\n"
                f"\U0001F4A1 *MODO MAKER (Anuncios)*\n"
                f"Compra Maker: {r['compra']:.2f} VES\n"
                f"Venta Maker:  {r['venta']:.2f} VES\n"
                f"Spread bruto: {pri:.2f}%\n"
                f"Margen neto: *{m['pct']:+.2f}%* {rentable}\n"
                f"Ganancia: ${m['usd']:.2f} USD | Bs.{m['neto']:.2f} \u00d7 ${cfg['capital']:.0f}\n\n"
                f"\u26A0 *MODO TAKER (Instantáneo)*\n"
                f"Compra Taker: {r['taker_compra']:.2f} VES\n"
                f"Venta Taker:  {r['taker_venta']:.2f} VES\n"
                f"Margen neto: *{r['taker_margen']:+.2f}%* {taker_rentable}\n"
                f"Ganancia: ${r['taker_ganancia_usd']:.2f} USD{taker_ves_str} \u00d7 ${cfg['capital']:.0f}\n\n"
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
    usd_list = [r for r in resultados if r.get("moneda") == "USDT"]
    ves_list = [r for r in resultados if r.get("moneda") != "USDT"]
    ves_list.sort(key=lambda x: x["margen"], reverse=True)
    best = ves_list[0] if ves_list else (usd_list[0] if usd_list else resultados[0])
    worst = ves_list[-1] if ves_list else (usd_list[-1] if usd_list else resultados[-1])
    rentables = [r for r in ves_list if r['margen'] > 0]
    texto = (
        f"\U0001F4CA *Multi-cripto* ({nombre_filtro()})\n"
        f"Comisiones totales: {COMISION_TOTAL*100:.2f}%\n\n")
    if ves_list:
        if rentables:
            texto += f"\u2705 *{len(rentables)} RENTABLE(S):*\n"
            for r in rentables:
                texto += f"  {r['asset']}: {r['margen']:+.2f}% (${r['ganancia_usd']:.2f})\n"
        else:
            texto += "\u274C *Ninguno rentable en VES*\n"
        texto += f"\n\U0001F3C6 *Mejor VES:* {best['asset']} ({best['margen']:+.2f}%)\n"
    if usd_list:
        texto += f"\n\U0001F4B1 *Referencia USDT:*\n"
        for r in usd_list:
            dex_str = f" DEX: ${r['dex']:.4f}" if r.get("dex") else ""
            texto += f"  {r['asset']}: *${r['compra']:.4f}*{dex_str}\n"
    texto += f"\nSelecciona para detalle y predeterminar:\n"
    kb = {"inline_keyboard": []}
    for r in resultados:
        if r.get("moneda") == "USDT":
            label = f"\U0001F4B1 {r['asset']} ${r['compra']:.4f}"
            if r.get("dex"):
                label += f" (DEX ${r['dex']:.4f})"
        else:
            icono = "\u2705" if r['margen'] > 0 else "\u274C"
            label = f"{icono} {r['asset']} ({r['margen']:+.2f}%)"
            if r == best:
                label = f"\U0001F3C6 {r['asset']} ({r['margen']:+.2f}%)"
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
    cfg = _get_config(chat_id)
    if _es_master(chat_id):
        CONFIG["default_crypto"] = asset
        guardar_config_local()
    else:
        _save_chat_config(chat_id, {"default_crypto": asset})
    kb = json.dumps({
        "inline_keyboard": [
            [{"text": "🏠 Inicio", "callback_data": "menu"},
             {"text": "🔙 Volver", "callback_data": "arbitraje"}],
            [{"text": "🔄 Actualizar", "callback_data": f"detalle_{asset}"}]
        ]
    })
    if r.get("moneda") == "USDT":
        dex_line = ""
        if r.get("dex"):
            diff = ((r["dex"] - r["compra"]) / r["compra"]) * 100
            dex_line = f"DEX (Phantom): *${r['dex']:.4f}* ({diff:+.2f}% vs spot)\n"
        _tg_call("editMessageText", {
            "chat_id": chat_id, "message_id": msg_id,
            "text": (
                f"\U0001F4B0 *{asset} / USDT* (Internacional)\n\n"
                f"Spot (Binance): *${r['compra']:.4f}*\n"
                f"{dex_line}"
                f"\U0001F4C8 Precio internacional de referencia.\n"
                f"No aplica arbitraje P2P.\n\n"
                f"📌 *{asset}* se ha guardado como tu cripto predeterminada."
            ),
            "parse_mode": "Markdown", "reply_markup": kb
        }, ignore_400=True)
    else:
        spread_bruto = ((r['venta'] - r['compra']) / r['compra']) * 100
        m = _calc_margen(r['compra'], r['venta'], cfg['capital'])
        rentable = "\u2705 RENTABLE" if m['pct'] > 0 else "\u274C NO RENTABLE"
        with _ULTIMOS_LOCK:
            best_asset = max(ULTIMOS.items(), key=lambda x: x[1].get("margen", -999))[0] if ULTIMOS else "USDT"
        estrella = " \U0001F3C6" if asset == best_asset else ""
        taker_rentable = "\u2705 RENTABLE" if r['taker_margen'] > 0 else "\u274C NO RENTABLE"
        taker_ves_str = f" | Bs.{r['taker_ganancia_ves']:.2f}" if r.get('taker_ganancia_ves') else ""
        _tg_call("editMessageText", {
            "chat_id": chat_id, "message_id": msg_id,
            "text": (
                f"\U0001F4B0 *{asset} / VES*{estrella} ({r['filtro']})\n\n"
                f"\U0001F4A1 *MODO MAKER (Anuncios)*\n"
                f"Compra Maker: {r['compra']:.2f} VES\n"
                f"Venta Maker:  {r['venta']:.2f} VES\n"
                f"Spread bruto: {spread_bruto:.2f}%\n"
                f"Margen neto: *{m['pct']:+.2f}%* {rentable}\n"
                f"Ganancia: ${m['usd']:.2f} USD | Bs.{m['neto']:.2f} \u00d7 ${cfg['capital']:.0f}\n\n"
                f"\u26A0 *MODO TAKER (Instantáneo)*\n"
                f"Compra Taker: {r['taker_compra']:.2f} VES\n"
                f"Venta Taker:  {r['taker_venta']:.2f} VES\n"
                f"Margen neto: *{r['taker_margen']:+.2f}%* {taker_rentable}\n"
                f"Ganancia: ${r['taker_ganancia_usd']:.2f} USD{taker_ves_str} \u00d7 ${cfg['capital']:.0f}\n\n"
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
    usd_assets = []
    for a in ASSETS_VES:
        u = ULTIMOS.get(a)
        if u:
            if u.get("moneda") == "USDT":
                usd_assets.append(a)
            else:
                icono = "\u2705" if u['margen'] > 0 else "\u274C"
                lines.append(f"{icono} {a}: {u['margen']:+.2f}%")
                if u['margen'] > 0:
                    rentables += 1
    if rentables > 0:
        lines.append(f"\n\U0001F4B0 *{rentables} activo(s) rentable(s)*")
    else:
        lines.append(f"\n\u23F3 Sin oportunidades en VES")
    if usd_assets:
        lines.append(f"\n\U0001F4B1 *Referencia USDT:*")
        for a in usd_assets:
            u = ULTIMOS[a]
            dex_str = f" (DEX ${u['venta']:.4f})" if u.get('venta', u['compra']) != u['compra'] else ""
            lines.append(f"  {a}: ${u['compra']:.4f}{dex_str}")
    editar_mensaje(chat_id, msg_id, "\n".join(lines))
    registrar_refresh(chat_id, msg_id, "status")


def _render_precision(chat_id, msg_id):
    p = PRECISION
    segundos = time.time() - p["inicio"]
    horas = int(segundos // 3600)
    minutos = int((segundos % 3600) // 60)
    lines = [
        "\U0001F4CA *Precisión de Datos*",
        f"Tiempo activo: {horas}h {minutos}m\n",
    ]
    for src, label in [("p2p", "Binance P2P"), ("coingecko", "CoinGecko"),
                        ("dexscreener", "DexScreener"), ("telegram", "Telegram"),
                        ("supabase", "Supabase")]:
        ok = p[src]["ok"]
        fail = p[src]["fail"]
        total = ok + fail
        if total > 0:
            pct = (ok / total) * 100
            barra = "\u2588" * int(pct / 10) + "\u2591" * (10 - int(pct / 10))
            lines.append(f"*{label}:* {ok}/{total} ({pct:.0f}%)")
            lines.append(f"  `{barra}`")
        else:
            lines.append(f"*{label}:* 0 consultas aun")
    lines.append("")
    ultimo_err = p.get("ultimo_error")
    ultimo_ts = p.get("ultimo_error_ts")
    if ultimo_err and ultimo_ts:
        hace = int(time.time() - ultimo_ts)
        lines.append(f"\u26A0 *Ultimo error:* hace {hace}s")
        lines.append(f"  `{ultimo_err}`")
    else:
        lines.append("\u2705 Sin errores registrados")
    editar_mensaje(chat_id, msg_id, "\n".join(lines))
    registrar_refresh(chat_id, msg_id, "precision")


def _render_dex(chat_id, msg_id):
    msg = f"🌌 *Arbitraje DEX Multi-Red* (Capital: ${CONFIG['capital']:.0f})\n\n"
    fallos, resultados_dex = [], []
    for nk in DEX_NETWORKS:
        r = calcular_arbitraje_dex(nk)
        if r:
            resultados_dex.append(r)
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
        rentables = [r for r in resultados_dex if r["ganancia_neta"] > 0]
        mejores = sorted(resultados_dex, key=lambda x: x["pct_neto"], reverse=True)
        tips_dex = []
        if rentables:
            top = max(rentables, key=lambda x: x["pct_neto"])
            tips_dex.append(f"🟢 *{top['network']}* es la más rentable ahora ({top['pct_neto']:+.2f}%). Compra en Spot, swap en {top['dex_principales']}.")
        if mejores and mejores[0]["pct_neto"] < 0:
            mejores_bruto = sorted(resultados_dex, key=lambda x: x["pct_bruto"], reverse=True)
            tips_dex.append(f"⚠️ Ninguna red supera los costos. La mejor oportunidad bruta es *{mejores_bruto[0]['network']}* ({mejores_bruto[0]['pct_bruto']:+.2f}%).")
        if fallos:
            tips_dex.append(f"ℹ️ Sin datos de {', '.join(fallos)} —可能是 baja liquidez en DEX o red caída.")
        if not rentables and not fallos:
            tips_dex.append("ℹ️ Los spreads no cubren costos de retiro+swap. Espera a que el mercado se mueva.")
        msg += "\n💡 *Tips basados en datos:*\n" + "\n".join(f"• {t}" for t in tips_dex[:2])
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
        with _AUTO_REFRESH_LOCK:
            if (chat_id, msg_id) not in AUTO_REFRESH:
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
            elif cb_data == "precision":
                _render_precision(chat_id, msg_id)
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
    if not _autorizado(chat_id):
        return
    limpiar_refresh(chat_id)
    restringido = not _es_master(chat_id) and data in ("combo", "arbitraje", "ciclo_filtro", "dex_multired", "status", "precision", "mejor_horario", "timing_mercado")
    if data.startswith("detalle_") and not _es_master(chat_id):
        restringido = True
    if restringido:
        return

    if data == "ayuda":
        editar_mensaje(chat_id, msg_id,
            "*Comandos del bot:*\n\n"
            "📋 `/menu` — Menú principal\n"
            "🏷️ `/precio` — Precios P2P\n"
            "📊 `/multi` — Multi-cripto\n"
            "💰 `/capital` — Capital\n"
            "🎯 `/umbral` — Umbral de alerta\n"
            "📈 `/historial` — Historial\n"
            "🔍 `/filtro` — Filtro\n"
            "🔄 `/dex` — DEX\n"
            "⏰ `/horarios` — Horarios\n"
            "⚡ `/combo` — Combo\n"
            "📉 `/mercado` — Mercado\n"
            "🎯 `/precision` — Precisión\n"
            "🧮 `/calc` — Calculadora\n\n"
            "*Comandos de grupo (solo master):*\n"
            "📢 `/decir <msg>` — Enviar al grupo\n"
            "🚫 `/ban <id> [horas]` — Banear usuario\n"
            "✅ `/unban <id>` — Desbanear\n"
            "🆔 `/groupid` — ID del chat actual\n"
            "⚙️ `/setgrupo <id>` — Configurar grupo\n\n"
            "💡 *Tip:* Usa los botones del menú como atajo."
        )
        return
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
        cfg = _get_config(chat_id)
        ESTADOS_USUARIO[chat_id] = {"esperando": "umbral"}
        _tg_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"\U0001F3AF Umbral actual: {CONFIG['margen_objetivo']}%\nResponde con el nuevo umbral (ej: 1.0 para 1%):"
        })

    elif data == "capital":
        cfg = _get_config(chat_id)
        ESTADOS_USUARIO[chat_id] = {"esperando": "capital"}
        _tg_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"\u2699\ufe0f Capital actual: ${cfg['capital']}\nResponde con el nuevo monto en USDT:"
        })

    elif data == "calculadora":
        ESTADOS_USUARIO[chat_id] = {"esperando": "calculadora"}
        _tg_call("sendMessage", {
            "chat_id": chat_id,
            "text": (
                f"\U0001F9EE *Calculadora P2P*\n\n"
                f"Comisiones: {COMISION_TOTAL*100:.2f}%\n"
                f"Responde con el *precio de compra* (VES):\n"
                f"Ej: 776"
            )
        })

    elif data == "historial":
        try:
            hoy_vet = datetime.now(VENEZUELA_TZ).date()
            registros = []
            try:
                hoy_iso = datetime.now(VENEZUELA_TZ).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                registros = supabase_select_all(ts_gte=hoy_iso)
            except Exception as e:
                print(f"Supabase lectura fallo, usando JSONL: {e}", flush=True)
                if os.path.exists(HISTORIAL_PATH):
                    with open(HISTORIAL_PATH, "r") as f:
                        for l in f:
                            try:
                                d = json.loads(l)
                                dt_ts = datetime.fromisoformat(str(d.get("ts", "")).replace("Z", "+00:00"))
                                if dt_ts.date() == hoy_vet:
                                    registros.append(d)
                            except Exception:
                                continue
            if not registros:
                editar_mensaje(chat_id, msg_id, f"Aún no hay datos históricos para hoy ({hoy_vet}).")
                return

            lineas_hoy = registros
            
            total_hoy = len(lineas_hoy)
            if total_hoy == 0:
                editar_mensaje(chat_id, msg_id, f"Aún no hay datos históricos para hoy ({hoy_vet}).")
            else:
                primera = lineas_hoy[0]
                ultima = lineas_hoy[-1]
                usdt_compra = [r["USDT"]["compra"] for r in lineas_hoy if isinstance(r.get("USDT"), dict) and r["USDT"].get("compra")]
                usdt_venta = [r["USDT"]["venta"] for r in lineas_hoy if isinstance(r.get("USDT"), dict) and r["USDT"].get("venta")]
                usdt_margenes = [r["USDT"]["margen"] for r in lineas_hoy if isinstance(r.get("USDT"), dict) and r["USDT"].get("margen") is not None]

                lines = [
                    f"\U0001F4C5 *Historial Hoy ({hoy_vet})*\n",
                    f"Desde: {primera['ts'][11:19]} VET",
                    f"Hasta: {ultima['ts'][11:19]} VET",
                    f"Total registros: {total_hoy}\n",
                    "*USDT Hoy*"
                ]
                if usdt_compra:
                    lines.append(f"Compra: {usdt_compra[0]:.2f} → {usdt_compra[-1]:.2f} VES")
                    lines.append(f"  `{_sparkline(usdt_compra)}`")
                if usdt_venta:
                    lines.append(f"Venta:  {usdt_venta[0]:.2f} → {usdt_venta[-1]:.2f} VES")
                    lines.append(f"  `{_sparkline(usdt_venta)}`")
                if usdt_margenes:
                    lines.append(f"Margen: Min {min(usdt_margenes):+.2f}% | Máx {max(usdt_margenes):+.2f}%")
                    lines.append(f"  Prom {sum(usdt_margenes)/len(usdt_margenes):+.2f}%")
                    lines.append(f"  `{_sparkline(usdt_margenes)}`")
                
                activos_resumen = []
                for asset in ASSETS_VES:
                    if asset == "USDT" or asset in ASSETS_USD:
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
            f"Ahora calcula precios para ordenes de *{nombre_filtro()}*.\n"
            f"Comisiones totales: {COMISION_TOTAL*100:.2f}%"
        )

    elif data == "status":
        _render_estado(chat_id, msg_id)

    elif data == "precision":
        _render_precision(chat_id, msg_id)

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
                precios_24h_c, precios_24h_v = _cargar_precios_usdt(24)
                total = len(precios_24h_c)
                if total < 10:
                    texto = (
                        f"\U0001F4CA *Mercado USDT/VES*\n\n"
                        f"Precio compra: {rr['compra']:.2f} VES\n"
                        f"Precio venta: {rr['venta']:.2f} VES\n\n"
                        f"\u23F3 *Sin datos suficientes*\n"
                        f"Solo {total}/10 registros en las \u00faltimas 24h.\n"
                        f"Revisa en {max(1, 10-total)} min o verifica que el bot est\u00e9 corriendo."
                    )
                else:
                    avg_c = sum(precios_24h_c) / total
                    avg_v = sum(precios_24h_v) / total if precios_24h_v else avg_c
                    desv_c = ((rr['compra'] - avg_c) / avg_c) * 100
                    desv_v = ((rr['venta'] - avg_v) / avg_v) * 100
                    texto = (
                        f"\U0001F4CA *Mercado USDT/VES*\n\n"
                        f"Precio compra: {rr['compra']:.2f} VES\n"
                        f"Precio venta: {rr['venta']:.2f} VES\n"
                        f"Promedio 24h: {avg_c:.2f} / {avg_v:.2f} VES\n"
                        f"Desviaci\u00f3n compra: {desv_c:+.2f}%\n"
                        f"Desviaci\u00f3n venta:  {desv_v:+.2f}%\n"
                        f"Registros \u00faltimas 24h: {total}\n\n"
                        f"\u23F3 *Sin se\u00f1al clara ahora.*\n"
                        f"Se necesita desviaci\u00f3n \u2265{TIMING_THRESHOLD_PCT}% para generar se\u00f1al.\n"
                        f"El bot monitorea y alertar\u00e1 autom\u00e1ticamente."
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
            f"💰 *Arbitraje P2P VES*\n"
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
                elif "message" in update:
                    msg = update["message"]
                    # Detectar nuevos miembros en el canal
                    if "new_chat_members" in msg and msg["chat"]["id"] == int(TELEGRAM_CHANNEL_ID):
                        for member in msg["new_chat_members"]:
                            username = member.get("username", "")
                            nombre = member.get("first_name", "")
                            display = f"@{username}" if username else nombre
                            if member.get("is_bot"):
                                continue
                            _send_channel(
                                f"👋 *¡Bienvenido {display}!*\n\n"
                                "📊 *¿Qué ofrecemos?*\n"
                                "• Precios P2P USDT/USDC en VES en vivo\n"
                                "• Alertas de arbitraje cuando hay oportunidad\n"
                                "• 🏦 Cambios de tasa BCV en tiempo real\n"
                                "• 📈 Resumen diario del mercado a las 7am\n"
                                "• Alertas de subastas bancarias\n\n"
                                "💬 *En el grupo de discusión:*\n"
                                "Usa `/precio` para ver el mercado al instante\n\n"
                                "📌 *Reglas:* No spam, no scams, respeto mutuo.\n\n"
                                "¡Aprovecha las oportunidades del mercado P2P!"
                            )
                            time.sleep(1)
                            _send_channel(_precio_p2p_resumen())
                    elif "text" in msg:
                        procesar_mensaje(msg["text"], msg["chat"]["id"])
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
                print(f"  ⚠️ VPS vence en {(VPS_EXPIRY - date.today()).days} dias ({VPS_EXPIRY})", flush=True)

            # Cambio de estado sueño -> despierto
            if activo and _ESTADO_SUENO == "dormido":
                _ESTADO_SUENO = "despierto"
                _resumen_diario()
                print("  >>> Buenos dias! Resumen diario enviado.", flush=True)
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
                    if r.get("moneda") == "USDT":
                        dex_str = f" (DEX ${r['dex']:.4f})" if r.get("dex") else ""
                        print(f"  {asset}: USDT ${r['compra']:.4f}{dex_str}", flush=True)
                    else:
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
                ves_mejores = [r for r in mejores if r.get("moneda") != "USDT"]
                ves_mejores.sort(key=lambda x: x["margen"], reverse=True)
                
                # Solo alertas de USDT
                estables = [r for r in ves_mejores if r["asset"] == "USDT"] if ves_mejores else []
                top = estables[0] if estables else None
                top_general = ves_mejores[0] if ves_mejores else (mejores[0] if mejores else None)

                for r in mejores:
                    if r["asset"] != "USDT":
                        continue
                    ant = MARGE_ANTERIOR.get(r["asset"])
                    MARGE_ANTERIOR[r["asset"]] = r["margen"]
                    if ant is not None and ant < 0 <= r["margen"] and r["margen"] >= CONFIG["margen_objetivo"]:
                        _broadcast(
                            f"\U0001F7E2 *RECUPERACION* {r['asset']}\n"
                            f"Margen pasó de {ant:+.2f}% a {r['margen']:+.2f}%\n"
                            f"Compra: {r['compra']:.2f} VES\n"
                            f"Venta:  {r['venta']:.2f} VES"
                        )

                if top:
                    print(f"  [debug] USDT margen={top['margen']:+.2f}% umbral={CONFIG['margen_objetivo']}% enviada={'USDT' in ALERTA_ENVIADA}", flush=True)
                if top and top["margen"] >= CONFIG["margen_objetivo"] and top["asset"] not in ALERTA_ENVIADA:
                    ALERTA_ENVIADA.add(top["asset"])
                    print(f">>> OPORTUNIDAD {top['asset']} <<<", flush=True)
                    spread_bruto = ((top['venta'] - top['compra']) / top['compra']) * 100
                    
                    limite_anuncio = f"{CONFIG['monto_filtro']} Bs" if CONFIG['monto_filtro'] > 0 else "libre (ej. 400 Bs)"
                    tasa_ves_alerta = ULTIMOS.get("USDT", {}).get("venta") or top['compra']
                    ves_ganancia_str = f"Bs.{top['ganancia_ves']:.2f}" if top.get("ganancia_ves") else f"Bs.{top['ganancia_usd'] * tasa_ves_alerta:.2f}"
                    
                    # Cómputo del escenario alternativo (siempre: vender todo de golpe)
                    comparativo_str = ""
                    maker_compra = top['compra']
                    tasa_ves_alt = ULTIMOS.get("USDT", {}).get("venta", maker_compra)
                    venta_may = obtener_precio_p2p("BUY", top['asset'], trans_amount=0)
                    if venta_may:
                        m = _calc_margen(maker_compra, venta_may)
                        comparativo_str = (
                            f"\n\U0001F504 *Escenario Alternativo (Vender todo de golpe):*\n"
                            f"- Vender todo a: *{venta_may:.2f} VES*\n"
                            f"- Margen Neto: {m['pct']:+.2f}%\n"
                            f"- Ganancia Neta Total: *${m['usd']:.2f} USD* (~Bs.{m['usd'] * tasa_ves_alt:.2f})\n"
                        )

                    warning_msg = ""
                    if CONFIG["capital"] < MIN_AD_AMOUNT:
                        warning_msg = "\n> ⚠️ *Advertencia:* Tu capital es inferior al mínimo requerido ($100) para crear anuncios Maker. Considera operar como *Taker* o aumentar tu capital antes de publicar anuncios."

                    texto_alerta = (
                        f"\U0001F514 *ALERTA P2P DETALLADA*\n"
                        f"Activo: *{top['asset']}* | Margen neto actual: *{top['margen']:+.2f}%* \u2705 RENTABLE\n\n"
                        f"\U0001F449 *Pasos sugeridos:*\n"
                        f"1\ufe0f\u20e3 *COMPRA:* Publica un anuncio de *COMPRA* (pagas Bs y recibes {top['asset']}) con precio fijado en *{top['compra']:.2f} VES*.\n"
                        f"   - Configura el límite mínimo de tu anuncio en: *{limite_anuncio}*.\n"
                        f"2\ufe0f\u20e3 *VENTA:* Publica un anuncio de *VENTA* (recibes Bs en BDV/Pago Móvil) con precio fijado en *{top['venta']:.2f} VES*.\n"
                        f"{comparativo_str}\n"
                        f"\u2139 *Detalle financiero:*\n"
                        f"- Spread Bruto: {spread_bruto:.2f}%\n"
                        f"- Comisiones Totales: -{COMISION_TOTAL*100:.2f}% (Binance Maker 0.50% + BDV 0.30%)\n"
                        f"{warning_msg}"
                    )
                    
                    _broadcast(texto_alerta)
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
                            _broadcast(msg_senal)
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
                _top_oportunidades()

            # Detectar cambio de tasa BCV (cada ciclo)
            _verificar_cambio_tasa_bcv()

            # Subastas BCV se ejecuta cada ciclo (tiene su propio intervalo interno)
            _scrapear_subastas()

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
                    if ant is not None and ant < 0 <= r["pct_neto"] and r["pct_neto"] >= CONFIG["margen_objetivo"]:
                        print(f"  DEX/{nk} recuperado: {ant:+.2f}% -> {r['pct_neto']:+.2f}%", flush=True)
                    if r["pct_neto"] >= CONFIG["margen_objetivo"] and r["ganancia_neta"] > 0 and nk not in ALERTA_ENVIADA_DEX:
                        ALERTA_ENVIADA_DEX.add(nk)
                        print(f"  DEX/{nk} oportunidad: {r['pct_neto']:+.2f}%", flush=True)
                    elif r["pct_neto"] < CONFIG["margen_objetivo"]:
                        ALERTA_ENVIADA_DEX.discard(nk)
                except Exception as e:
                    print(f"Error DEX/{nk}: {e}", flush=True)

            global _ULTIMA_HORA_ENVIADA
            h = datetime.now(VENEZUELA_TZ).hour
            if h != _ULTIMA_HORA_ENVIADA:
                _ULTIMA_HORA_ENVIADA = h
                if h >= 7:
                    precio_msg = _precio_p2p_resumen()
                    enviar_menu(texto=precio_msg)
                    _send_channel(precio_msg)
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
        if TELEGRAM_CHANNEL_ID:
            threading.Thread(target=_loop_detectar_miembros, daemon=True).start()
        time.sleep(2)
        extra = ""
        if not en_horario():
            extra = " (modo silencioso)"
        print(f"Iniciando monitor{extra}...", flush=True)
        loop_monitoreo()
    else:
        print("Telegram token no configurado. Solo modo monitor", flush=True)
        loop_monitoreo()
