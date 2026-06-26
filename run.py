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

print("IMPORT: importing bot_p2p...", flush=True)
import bot_p2p
print("IMPORT: OK", flush=True)

print("STEP: guardar_config_local", flush=True)
bot_p2p.guardar_config_local()
print("STEP: config OK", flush=True)

# loop_monitoreo en thread DAEMON
def run_loop():
    print("STEP: entering loop_monitoreo (no Telegram threads)", flush=True)
    try:
        bot_p2p.loop_monitoreo()
    except Exception as e:
        print(f"LOOP DIED: {e}", flush=True)
        import traceback
        traceback.print_exc()

threading.Thread(target=run_loop, daemon=True).start()
print("STEP: loop_monitoreo started", flush=True)

print("SERVE: starting", flush=True)
server.serve_forever()
