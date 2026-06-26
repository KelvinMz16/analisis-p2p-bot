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

def step2b():
    try:
        print("STEP2b: import bot_p2p", flush=True)
        import bot_p2p
        
        print("STEP2b: guardar_config_local (SOLO config, sin calcular_margen)", flush=True)
        bot_p2p.guardar_config_local()
        print("STEP2b: OK, completado", flush=True)
    except Exception as e:
        print(f"STEP2b ERROR: {e}", flush=True)
        import traceback
        traceback.print_exc()

threading.Thread(target=step2b, daemon=True).start()
print("SERVE: starting", flush=True)
server.serve_forever()
