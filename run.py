import os, time, json
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

# TEST 1: Solo import, sin ejecutar nada
print("TEST1: importing bot_p2p...", flush=True)
import bot_p2p
print("TEST1: import OK, starting server...", flush=True)

HTTPServer(("0.0.0.0", PORT), H).serve_forever()
