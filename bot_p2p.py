import requests
import time
import os


# ============================================================
# CONFIGURACION
# ============================================================
CAPITAL_INICIAL = 100       # Capital en USDT por operacion
MARGEN_OBJETIVO = 0.8       # % minimo de margen neto para activar alerta
COMISION = 0.0025           # 0.25% de comision por lado del trade

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}

URL_API = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

# Payload base comun para ambas consultas
PAYLOAD_BASE = {
    "asset": "USDT",
    "fiat": "VES",
    "merchantCheck": False,
    "page": 1,
    "rows": 10,
    "payTypes": ["Banco de Venezuela", "Pago Movil"]
}
# ============================================================


def obtener_precio_p2p(trade_type):
    """Consulta la API de Binance P2P y retorna el precio promedio
       del 3ro, 4to y 5to anuncio (indices 2, 3, 4)."""
    payload = {**PAYLOAD_BASE, "tradeType": trade_type}

    try:
        resp = requests.post(URL_API, json=payload, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        anuncios = data.get("data", [])
        if len(anuncios) < 5:
            print(f"[{trade_type}] Solo {len(anuncios)} anuncios disponibles, se requieren al menos 5.")
            return None

        precios = [float(anuncios[i]["adv"]["price"]) for i in range(2, 5)]
        return sum(precios) / len(precios)

    except requests.exceptions.Timeout:
        print(f"[{trade_type}] Timeout en la peticion a Binance.")
    except requests.exceptions.RequestException as e:
        print(f"[{trade_type}] Error de red: {e}")
    except (KeyError, ValueError, IndexError) as e:
        print(f"[{trade_type}] Error al procesar respuesta: {e}")
    except Exception as e:
        print(f"[{trade_type}] Error inesperado: {e}")

    return None


def calcular_arbitraje():
    """Obtiene tasas de compra y venta, calcula el margen neto y muestra resultado."""
    tasa_compra = obtener_precio_p2p("BUY")   # Compramos USDT (Maker Buy)
    tasa_venta  = obtener_precio_p2p("SELL")  # Vendemos USDT (Maker Sell)

    if tasa_compra is None or tasa_venta is None:
        print("No se pudieron obtener ambas tasas. Reintentando en 60s...")
        return

    # Formula de ganancia neta en VES por USDT
    # Ganancia = (PrecioVenta - PrecioCompra) - (PrecioVenta * 0.25%) - (PrecioCompra * 0.25%)
    ganancia_neta_ves = (tasa_venta - tasa_compra) - (tasa_venta * COMISION) - (tasa_compra * COMISION)

    # Margen neto porcentual respecto a la tasa de compra
    margen_neto = (ganancia_neta_ves / tasa_compra) * 100

    # Ganancia esperada en USD
    ganancia_usd = CAPITAL_INICIAL * (margen_neto / 100)

    # Salida formateada en consola
    print(f"Compra Maker: {tasa_compra:.2f} VES | "
          f"Venta Maker: {tasa_venta:.2f} VES | "
          f"Margen Neto: {margen_neto:.2f}%  "
          f"[{'+' if ganancia_usd >= 0 else ''}{ganancia_usd:.2f} USD]")

    if margen_neto >= MARGEN_OBJETIVO:
        print("=" * 60)
        print(f"  >>>  OPORTUNIDAD DETECTADA  <<<")
        print(f"  Margen:  {margen_neto:.2f}%  |  Ganancia: ${ganancia_usd:.2f}")
        print(f"  Compra:  {tasa_compra:.2f} VES")
        print(f"  Venta:   {tasa_venta:.2f} VES")
        print("=" * 60)
        enviar_alerta_telegram(margen_neto, tasa_compra, tasa_venta, ganancia_usd)


# ============================================================
# TELEGRAM
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def enviar_alerta_telegram(margen, compra, venta, ganancia):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    mensaje = (
        f"\U0001F514 *ALERTA P2P - Oportunidad Detectada*\n"
        f"Margen Neto: {margen:.2f}%\n"
        f"Compra: {compra:.2f} VES\n"
        f"Venta:  {venta:.2f} VES\n"
        f"Ganancia: ${ganancia:.2f} USD"
    )

    try:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "Markdown"
        }
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json=payload,
            timeout=10
        )
        r.raise_for_status()
    except Exception as e:
        print(f"Error al enviar mensaje Telegram: {e}")
# ============================================================


# ============================================================
# BUCLE PRINCIPAL
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("  Bot de Monitoreo P2P Binance - USDT/VES")
    print(f"  Capital: ${CAPITAL_INICIAL} USDT | Umbral: {MARGEN_OBJETIVO}%")
    print("  Consultando cada 60 segundos...")
    print("=" * 60)

    while True:
        try:
            calcular_arbitraje()
        except KeyboardInterrupt:
            print("\nBot detenido por el usuario.")
            break
        except Exception as e:
            print(f"Error en el bucle principal: {e}")

        time.sleep(60)
