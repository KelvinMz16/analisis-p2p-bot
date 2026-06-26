import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        # Print logs to stdout to debug health checks
        print(f"HEALTH_LOG: {format % args}", flush=True)

def start_health_server(port):
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), HealthCheckHandler)
        print(f"HEALTH_SERVER_PORT:{port}", flush=True)
        server.serve_forever()
    except Exception as e:
        print(f"HEALTH_SERVER_ERROR_PORT:{port}:{e}", flush=True)

# Start health servers on both ports in daemon threads
for p in [8080, 7860]:
    threading.Thread(target=start_health_server, args=(p,), daemon=True).start()

print("RUN: health servers started", flush=True)

while True:
    print("RUN: starting bot_p2p.py", flush=True)
    r = subprocess.call([sys.executable, "-u", "bot_p2p.py"])
    print(f"RUN: bot_p2p.py EXIT_CODE={r} - restarting in 5s", flush=True)
    time.sleep(5)

