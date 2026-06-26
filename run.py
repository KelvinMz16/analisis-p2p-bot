import os, time, json
from http.server import BaseHTTPRequestHandler, HTTPServer

STARTED = time.time()

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "status": "ok",
            "uptime": int(time.time() - STARTED)
        }).encode())
    def log_message(self, *a): pass

port = int(os.getenv("PORT", 7860))
print(f"HEALTH_ONLY: listening on port {port}", flush=True)
HTTPServer(("0.0.0.0", port), H).serve_forever()
