import os, time, json, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.getenv("PORT", 7860))
STARTED = time.time()

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass

server = ThreadingHTTPServer(("0.0.0.0", PORT), H)
print(f"SERVER: on port {PORT}", flush=True)

def test():
    try:
        print("TEST: import bot_p2p", flush=True)
        import bot_p2p
        print("TEST: guardar_config_local", flush=True)
        bot_p2p.guardar_config_local()
        print("TEST: completo, thread vivo", flush=True)
        while True:
            time.sleep(10)
    except Exception as e:
        print(f"TEST ERROR: {e}", flush=True)

threading.Thread(target=test, daemon=True).start()
time.sleep(0.5)
print("SERVE:", flush=True)
server.serve_forever()
