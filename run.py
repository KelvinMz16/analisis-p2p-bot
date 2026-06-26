import os, sys, threading, time, json
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.getenv("PORT", 7860))
STARTED = time.time()

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "uptime": int(time.time()-STARTED)}).encode())
    def log_message(self, *a): pass

def run_bot():
    try:
        print("STEP: importing bot_p2p", flush=True)
        import bot_p2p
        print("STEP: guardar_config_local", flush=True)
        bot_p2p.guardar_config_local()
        print("STEP: starting telegram threads", flush=True)
        if bot_p2p.TELEGRAM_TOKEN:
            threading.Thread(target=bot_p2p.polling_telegram, daemon=True).start()
            threading.Thread(target=bot_p2p._loop_bcv_scrape, daemon=True).start()
        print("STEP: entering loop_monitoreo", flush=True)
        bot_p2p.loop_monitoreo()
        print("STEP: loop_monitoreo EXITED (unexpected)", flush=True)
    except Exception as e:
        print(f"FATAL: {e}", flush=True)
        import traceback
        traceback.print_exc()

threading.Thread(target=run_bot, daemon=True).start()

print(f"RUN: server on port {PORT}", flush=True)
HTTPServer(("0.0.0.0", PORT), H).serve_forever()
