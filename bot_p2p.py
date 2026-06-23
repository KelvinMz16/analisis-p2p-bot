import requests
import time
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# ============================================================
# CONFIGURACION
# ============================================================
CONFIG = {
    "capital": 100,          # Capital en USDT por operacion
    "margen_objetivo": 0.8,  # % minimo de margen neto para activar alerta
}

COMISION = 0.0025  # 0.25% por lado del trade
ULTIMOS = {}       # cache: {asset: {"compra": X, "venta": Y}}

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
    """Retorna precio promedio (3er-5to anuncio) para un activo en VES."""
    payload = {
        "asset": asset,
        "fiat": "VES",
        "page": 1,
        "rows": 10,
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
    """Calcula margen neto para un activo. Retorna dict con resultados."""
    compra = obtener_precio_p2p("BUY", asset)
    venta = obtener_precio_p2p("SELL", asset)
    if compra is None or venta is None:
        return None
    ganancia_neta = (venta - compra) - (venta * COMISION) - (compra * COMISION)
    margen = (ganancia_neta / compra) * 100
    ganancia_usd = CONFIG["capital"] * (margen / 100)
    ULTIMOS[asset] = {"compra": compra, "venta": venta, "margen": margen}
    return {
        "asset": asset,
        "compra": compra,
        "venta": venta,
        "margen": margen,
        "ganancia_usd": ganancia_usd
    }


def monitorear_usdt():
    """Loop principal de monitoreo del USDT."""
    r = calcular_margen("USDT")
    if r is None:
        print("No se pudieron obtener tasas. Reintentando en 60s...")
        return

    compra = r["compra"]
    venta = r["venta"]
    margen = r["margen"]
    ganancia_usd = r["ganancia_usd"]

    # Ahorro al comprar como Maker vs comprar directo de anuncios SELL
    # (La tasa SELL es lo que pagarias comprando de anuncios existentes)
    ahorro_compra = ((venta - compra) / venta) * 100 if venta > 0 else 0

    print("=" * 55)
    print(f"  USDT/VES  -  Capital: ${CONFIG['capital']}")
    print(f"  Compra Maker: {compra:.2f} VES  (ahorras {ahorro_compra:.2f}% vs comprar directo)")
    print(f"  Venta Maker:  {venta:.2f} VES  (ganas {margen:.2f}% = ${ganancia_usd:.2f} por ${CONFIG['capital']})")
    print("=" * 55)

    if margen >= CONFIG["margen_objetivo"]:
        print("  >>>  OPORTUNIDAD DETECTADA  <<<")
        enviar_telegram(
            f"\U0001F514 *ALERTA P2P - Oportunidad USDT*\n"
            f"Compra Maker: {compra:.2f} VES\n"
            f"Venta Maker:  {venta:.2f} VES\n"
            f"Margen: {margen:.2f}%\n"
            f"Ganancia: ${ganancia_usd:.2f} por ${CONFIG['capital']}"
        )
# ============================================================


# ============================================================
# TELEGRAM - ENVIO DE MENSAJES
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")

def enviar_telegram(mensaje, chat_id=None):
    if not TELEGRAM_TOKEN:
        return False
    cid = chat_id or TELEGRAM_CHAT_ID
    if not cid:
        return False
    try:
        payload = {"chat_id": cid, "text": mensaje, "parse_mode": "Markdown"}
        r = requests.post(
            f"{TELEGRAM_API_BASE}/bot{TELEGRAM_TOKEN}/sendMessage",
            json=payload, timeout=10
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"Error al enviar Telegram: {e}")
        return False
# ============================================================


# ============================================================
# TELEGRAM - RECEPCION DE COMANDOS (POLLING)
# ============================================================
def procesar_comando(texto, chat_id):
    """Procesa comandos entrantes y responde."""
    cmd = texto.strip().lower()

    if cmd == "/start":
        enviar_telegram(
            f"\U0001F916 *Bot P2P Venezuela activo*\n\n"
            f"*Comandos:*\n"
            f"/precio - Precio actual USDT\n"
            f"/capital <monto> - Cambiar capital\n"
            f"/arbitraje - Mejor margen entre criptos\n"
            f"/status - Estado actual del bot",
            chat_id
        )

    elif cmd == "/precio":
        r = calcular_margen("USDT")
        if r:
            ahorro = ((r['venta'] - r['compra']) / r['venta']) * 100
            enviar_telegram(
                f"*USDT / VES*\n"
                f"Compra Maker: {r['compra']:.2f} (ahorras {ahorro:.2f}%)\n"
                f"Venta Maker:  {r['venta']:.2f}\n"
                f"Margen neto: {r['margen']:.2f}%\n"
                f"Ganancia: ${r['ganancia_usd']:.2f} por ${CONFIG['capital']}",
                chat_id
            )
        else:
            enviar_telegram("No se pudieron obtener precios.", chat_id)

    elif cmd.startswith("/capital"):
        partes = texto.split()
        if len(partes) == 2:
            try:
                nuevo = float(partes[1])
                if nuevo > 0:
                    viejo = CONFIG["capital"]
                    CONFIG["capital"] = nuevo
                    enviar_telegram(f"Capital actualizado: ${viejo} -> ${nuevo}", chat_id)
                else:
                    enviar_telegram("El capital debe ser mayor a 0.", chat_id)
            except ValueError:
                enviar_telegram("Usa: /capital <numero>", chat_id)
        else:
            enviar_telegram(f"Capital actual: ${CONFIG['capital']}", chat_id)

    elif cmd == "/arbitraje":
        resultados = []
        for asset in ASSETS_VES:
            r = calcular_margen(asset)
            if r:
                resultados.append(r)
            time.sleep(0.5)  # pausa entre consultas para no saturar

        if not resultados:
            enviar_telegram("No se pudieron obtener datos.", chat_id)
            return

        resultados.sort(key=lambda x: x["margen"], reverse=True)
        mejor = resultados[0]
        lines = [f"*Mejor: {mejor['asset']}* | {mejor['margen']:.2f}%\n"]
        for r in resultados:
            signo = "+" if r["margen"] >= 0 else ""
            lines.append(
                f"{r['asset']}: Compra {r['compra']:.2f} | "
                f"Venta {r['venta']:.2f} | "
                f"*{signo}{r['margen']:.2f}%*"
            )
        enviar_telegram("\n".join(lines), chat_id)

    elif cmd == "/status":
        enviar_telegram(
            f"*Estado del Bot*\n"
            f"Capital: ${CONFIG['capital']}\n"
            f"Umbral: {CONFIG['margen_objetivo']}%\n"
            f"Ultimo USDT: "
            f"{ULTIMOS.get('USDT', {}).get('margen', 'N/A'):.2f}%",
            chat_id
        )

    else:
        enviar_telegram(
            "Comando no reconocido. Usa /start para ver los disponibles.",
            chat_id
        )


def polling_telegram():
    """Hilo que escucha comandos de Telegram cada 5s."""
    offset = 0
    while True:
        try:
            r = requests.get(
                f"{TELEGRAM_API_BASE}/bot{TELEGRAM_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35
            )
            r.raise_for_status()
            for update in r.json().get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message")
                if msg and msg.get("text"):
                    procesar_comando(msg["text"], msg["chat"]["id"])
        except requests.exceptions.Timeout:
            pass  # timeout largo es normal en polling
        except Exception as e:
            print(f"Error en polling Telegram: {e}")
        time.sleep(5)


if TELEGRAM_TOKEN:
    t_polling = threading.Thread(target=polling_telegram, daemon=True)
    t_polling.start()
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
    print("  Consultando cada 60s | Comandos via Telegram")
    print("=" * 60)

    ciclo = 0
    enviar_telegram(
        f"\U0001F4E1 *Bot P2P Iniciado*\n"
        f"Capital: ${CONFIG['capital']} | Umbral: {CONFIG['margen_objetivo']}%\n"
        f"Comandos: /precio /capital /arbitraje /status"
    )

    while True:
        try:
            monitorear_usdt()
            ciclo += 1
            if ciclo % 30 == 0:
                enviar_telegram(f"\u23F1 *Heartbeat* - {ciclo} ciclos sin novedades")
        except KeyboardInterrupt:
            print("\nBot detenido.")
            enviar_telegram("\u274C *Bot P2P Detenido*")
            break
        except Exception as e:
            print(f"Error en bucle principal: {e}")
        time.sleep(60)
