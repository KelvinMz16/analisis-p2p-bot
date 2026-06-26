import os, threading, time
from flask import Flask, jsonify

PORT = int(os.getenv("PORT", 7860))
STARTED = time.time()
app = Flask(__name__)

@app.route("/")
@app.route("/health")
def health():
    return jsonify({"status": "ok", "uptime": int(time.time() - STARTED)})

def run_bot():
    try:
        print("STEP: importing bot_p2p", flush=True)
        import bot_p2p
        print("STEP: guardar_config_local", flush=True)
        bot_p2p.guardar_config_local()
        if bot_p2p.TELEGRAM_TOKEN:
            print("STEP: starting telegram threads", flush=True)
            threading.Thread(target=bot_p2p.polling_telegram, daemon=True).start()
            threading.Thread(target=bot_p2p._loop_bcv_scrape, daemon=True).start()
        print("STEP: entering loop_monitoreo", flush=True)
        bot_p2p.loop_monitoreo()
        print("STEP: loop_monitoreo EXITED", flush=True)
    except Exception as e:
        print(f"FATAL: {e}", flush=True)
        import traceback
        traceback.print_exc()

threading.Thread(target=run_bot, daemon=True).start()
print(f"FLASK: on port {PORT}", flush=True)
app.run(host="0.0.0.0", port=PORT, debug=False)
