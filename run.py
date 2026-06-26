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

def step2():
    try:
        print("STEP2: import bot_p2p", flush=True)
        import bot_p2p
        
        print("STEP2: guardar_config_local", flush=True)
        bot_p2p.guardar_config_local()
        print("STEP2: OK", flush=True)
        
        print("STEP2: calcular_margen para 6 assets", flush=True)
        for asset in ["USDT", "USDC", "BTC", "ETH", "BNB", "SOL"]:
            r = bot_p2p.calcular_margen(asset)
            if r:
                print(f"  {asset}: compra={r['compra']:.2f} venta={r['venta']:.2f} margen={r['margen']:+.2f}%", flush=True)
            time.sleep(0.3)
        
        print("STEP2: completo, esperando...", flush=True)
    except Exception as e:
        print(f"STEP2 ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()

threading.Thread(target=step2, daemon=True).start()
print("SERVE: starting", flush=True)
server.serve_forever()
