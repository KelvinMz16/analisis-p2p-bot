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

def step1():
    try:
        print("STEP1: import bot_p2p", flush=True)
        import bot_p2p
        print("STEP1: OK", flush=True)
        
        print("STEP1: llamando obtener_precio_p2p(BUY, USDT)", flush=True)
        precio = bot_p2p.obtener_precio_p2p("BUY", "USDT")
        print(f"STEP1: USDT/BUY = {precio}", flush=True)
        
        print("STEP1: llamando obtener_precio_p2p(SELL, USDT)", flush=True)
        precio = bot_p2p.obtener_precio_p2p("SELL", "USDT")
        print(f"STEP1: USDT/SELL = {precio}", flush=True)
        
        print("STEP1: completo, esperando...", flush=True)
    except Exception as e:
        print(f"STEP1 ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()

threading.Thread(target=step1, daemon=True).start()
print("SERVE: starting", flush=True)
server.serve_forever()
