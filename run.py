import time, os, socket
from http.server import BaseHTTPRequestHandler, HTTPServer

PAGE = b"""<!DOCTYPE html><html><body>
<h1>Bot P2P Venezuela</h1>
<p>Status: OK</p>
</body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)
    def log_message(self, *a): pass

print("MINIMAL_TEST: starting on port 7860", flush=True)
try:
    HTTPServer(("0.0.0.0", 7860), H).serve_forever()
except Exception as e:
    print(f"MINIMAL_TEST: server error: {e}", flush=True)
    time.sleep(300)
