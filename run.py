import os, sys, threading, time, json
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.getenv("PORT", 7860))

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "VesArbitrajeP2P"}).encode())
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, *a): pass

def run_bot():
    print(f"RUN: starting bot on port {PORT}", flush=True)
    try:
        import bot_p2p
        bot_p2p.guardar_config_local()
        if bot_p2p.TELEGRAM_TOKEN:
            threading.Thread(target=bot_p2p.polling_telegram, daemon=True).start()
            threading.Thread(target=bot_p2p._loop_bcv_scrape, daemon=True).start()
            time.sleep(2)
        print("RUN: bot entering monitoreo loop", flush=True)
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

print(f"RUN: starting health server on port {PORT}", flush=True)
server = HTTPServer(("0.0.0.0", PORT), Handler)

threading.Thread(target=run_bot, daemon=True).start()

try:
    server.serve_forever()
except Exception as e:
    print(f"RUN: SERVER_CRASH: {e}", flush=True)
    # Keep process alive as fallback
    while True:
        time.sleep(60)
