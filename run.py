import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone, timedelta

bot_status = {"started": None, "last_restart": None, "restarts": 0, "running": False}

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

def run_bot():
    import bot_p2p
    bot_p2p.guardar_config_local()
    if bot_p2p.TELEGRAM_TOKEN:
        threading.Thread(target=bot_p2p.polling_telegram, daemon=True).start()
        threading.Thread(target=bot_p2p._loop_bcv_scrape, daemon=True).start()
        time.sleep(2)
    while True:
        try:
            bot_p2p.loop_monitoreo()
        except Exception as e:
            print(f"RUN: BOT_CRASH: {e}", flush=True)
            bot_status["restarts"] += 1
            bot_status["last_restart"] = datetime.now(timezone.utc)
            time.sleep(5)

bot_status["started"] = datetime.now(timezone.utc)
bot_status["running"] = True

# Bot in daemon thread
threading.Thread(target=run_bot, daemon=True).start()
time.sleep(1)

# Health server in MAIN thread (no CPU competition)
server = ThreadingHTTPServer(("0.0.0.0", 7860), HealthHandler)
print("HEALTH_SERVER: Main thread on port 7860", flush=True)
server.serve_forever()
