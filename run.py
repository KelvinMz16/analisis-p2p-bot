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

# 1. Crear servidor PRIMERO (socket listening)
server = HTTPServer(("0.0.0.0", PORT), H)
print(f"SERVER: listening on port {PORT}", flush=True)

# 2. Importar bot_p2p (conexiones TCP se encolan mientras tanto)
print("IMPORT: importing bot_p2p...", flush=True)
import bot_p2p
print("IMPORT: OK", flush=True)

# 3. Serve forever (acepta conexiones encoladas inmediatamente)
print("SERVE: starting", flush=True)
server.serve_forever()
