import os, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.getenv("PORT", 7860))

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass

# Solo un thread que duerme, SIN import bot_p2p
def dummy():
    while True:
        time.sleep(60)

threading.Thread(target=dummy, daemon=True).start()
print("SERVER: on port " + str(PORT), flush=True)
HTTPServer(("0.0.0.0", PORT), H).serve_forever()
