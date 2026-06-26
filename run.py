import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone

print("RUN: starting", flush=True)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, format, *args):
        pass

# Health server FIRST, before anything else
server = ThreadingHTTPServer(("0.0.0.0", 7860), HealthHandler)
print("HEALTH_SERVER: listening on port 7860", flush=True)

# Bot in daemon thread after health server is ready
def run_bot():
    print("RUN: starting bot_p2p.py", flush=True)
    try:
        import bot_p2p
        bot_p2p.guardar_config_local()
        if bot_p2p.TELEGRAM_TOKEN:
            threading.Thread(target=bot_p2p.polling_telegram, daemon=True).start()
            threading.Thread(target=bot_p2p._loop_bcv_scrape, daemon=True).start()
            time.sleep(2)
        print("RUN: bot starting monitoreo loop", flush=True)
        while True:
            try:
                bot_p2p.loop_monitoreo()
            except Exception as e:
                print(f"RUN: BOT_LOOP_CRASH: {e}", flush=True)
                time.sleep(5)
    except Exception as e:
        print(f"RUN: BOT_INIT_CRASH: {e}", flush=True)
        import traceback
        traceback.print_exc()

threading.Thread(target=run_bot, daemon=True).start()
time.sleep(1)

print("RUN: health server starting main loop", flush=True)
server.serve_forever()
