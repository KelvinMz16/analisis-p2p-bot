import os, time, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.getenv("PORT", 7860))
STARTED = time.time()

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(json.dumps({"status":"ok","uptime":int(time.time()-STARTED)}).encode())
        except:
            pass
    def log_message(self, *a): pass

server = HTTPServer(("0.0.0.0", PORT), H)
print(f"SERVER: listening on port {PORT}", flush=True)

def test():
    try:
        print("TEST: import bot_p2p", flush=True)
        import bot_p2p
        print("TEST: guardar_config_local", flush=True)
        bot_p2p.guardar_config_local()
        
        print("TEST: obtener_precio_spot para SOL, POL, BNB", flush=True)
        for asset in ["SOL", "POL", "BNB"]:
            price = bot_p2p.obtener_precio_spot(asset)
            print(f"  Spot/{asset}: {price}", flush=True)
            time.sleep(0.5)
        
        print("TEST: completo, thread vivo", flush=True)
        while True:
            time.sleep(10)
    except Exception as e:
        print(f"TEST ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()

threading.Thread(target=test, daemon=True).start()
print("SERVE: starting", flush=True)
while True:
    try:
        server.serve_forever()
    except Exception as e:
        print(f"SERVE_RESTART: {e}", flush=True)
        time.sleep(1)
