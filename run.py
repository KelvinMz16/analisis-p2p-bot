import os, time, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.getenv("PORT", 7860))
STARTED = time.time()

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status":"ok","uptime":int(time.time()-STARTED)}).encode())
    def log_message(self, *a): pass

server = HTTPServer(("0.0.0.0", PORT), H)
print(f"SERVER: listening on port {PORT}", flush=True)

# MINI-BOT: solo consulta P2P una vez, sin import bot_p2p
def mini_bot():
    try:
        import requests
        print("MINI: consultando P2P...", flush=True)
        url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
        headers = {"Content-Type": "application/json"}
        for asset in ["USDT", "USDC", "BTC", "ETH", "BNB", "SOL"]:
            for side in ["BUY", "SELL"]:
                payload = {
                    "asset": asset,
                    "fiat": "VES",
                    "tradeType": side,
                    "payTypes": ["BancoDeVenezuela", "PagoMovil"],
                    "rows": 1,
                    "page": 1
                }
                try:
                    r = requests.post(url, json=payload, headers=headers, timeout=10)
                    data = r.json()
                    ads = data.get("data", [])
                    if ads:
                        price = float(ads[0]["adv"]["price"])
                        print(f"  {asset}/{side}: {price:.2f}", flush=True)
                except Exception as e:
                    print(f"  {asset}/{side}: {e}", flush=True)
                time.sleep(0.3)
        print("MINI: consulta completa, esperando...", flush=True)
    except Exception as e:
        print(f"MINI ERROR: {e}", flush=True)

threading.Thread(target=mini_bot, daemon=True).start()
print("SERVE: starting", flush=True)
server.serve_forever()
