import os, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.getenv("PORT", 7860))

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass

def run_bot():
    import bot_p2p
    print("  Bot P2P Binance - Venezuela", flush=True)
    print(f"  Capital: ${bot_p2p.CONFIG['capital']} | Umbral: {bot_p2p.CONFIG['margen_objetivo']}%", flush=True)
    if bot_p2p.TELEGRAM_TOKEN:
        threading.Thread(target=bot_p2p.polling_telegram, daemon=True).start()
        threading.Thread(target=bot_p2p._loop_bcv_scrape, daemon=True).start()
        time.sleep(2)
        extra = ""
        if not bot_p2p.en_horario():
            extra = " (modo silencioso)"
        print(f"Iniciando monitoreo{extra}...", flush=True)
        bot_p2p.loop_monitoreo()
    else:
        print("Telegram token no configurado. Solo modo monitoreo", flush=True)
        bot_p2p.loop_monitoreo()

threading.Thread(target=run_bot, daemon=True).start()
print("SERVER: on port " + str(PORT), flush=True)
HTTPServer(("0.0.0.0", PORT), H).serve_forever()
