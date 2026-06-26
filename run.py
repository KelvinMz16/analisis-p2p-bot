import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone, timedelta

# Global state for the status page
bot_status = {"started": None, "last_restart": None, "restarts": 0, "running": False}

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VesArbitrajeP2P - Bot Status</title>
    <meta http-equiv="refresh" content="30">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', system-ui, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .card { background: #1e293b; border-radius: 16px; padding: 2rem; max-width: 480px; width: 90%%; box-shadow: 0 4px 30px rgba(0,0,0,0.4); border: 1px solid #334155; }
        h1 { font-size: 1.4rem; color: #22c55e; margin-bottom: 1rem; }
        .status { display: flex; align-items: center; gap: 8px; margin-bottom: 1.5rem; }
        .dot { width: 12px; height: 12px; border-radius: 50%%; background: #22c55e; animation: pulse 2s infinite; }
        @keyframes pulse { 0%%,100%% { opacity:1; } 50%% { opacity:0.4; } }
        .info { background: #0f172a; border-radius: 8px; padding: 1rem; }
        .row { display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid #1e293b; }
        .row:last-child { border: none; }
        .label { color: #94a3b8; }
        .value { color: #f1f5f9; font-weight: 500; }
    </style>
</head>
<body>
    <div class="card">
        <h1>💰 VesArbitrajeP2P</h1>
        <div class="status"><div class="dot"></div><span>Bot activo</span></div>
        <div class="info">
            <div class="row"><span class="label">Inicio</span><span class="value">%s</span></div>
            <div class="row"><span class="label">Uptime</span><span class="value">%s</span></div>
            <div class="row"><span class="label">Reinicios</span><span class="value">%d</span></div>
            <div class="row"><span class="label">Estado</span><span class="value">%s</span></div>
        </div>
    </div>
</body>
</html>"""

def get_uptime():
    if not bot_status["started"]:
        return "Iniciando..."
    delta = datetime.now(timezone.utc) - bot_status["started"]
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    return f"{minutes}m {seconds}s"

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

def start_health_server(port):
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
        print(f"HEALTH_SERVER: Listening on port {port}", flush=True)
        server.serve_forever()
    except Exception as e:
        print(f"HEALTH_SERVER_ERROR:{port}:{e}", flush=True)

# Start health/status server on port 7860 in a daemon thread
threading.Thread(target=start_health_server, args=(7860,), daemon=True).start()
time.sleep(1.0)  # Give the health server time to bind before main loop starts
bot_status["started"] = datetime.now(timezone.utc)

print("RUN: health server started on port 7860", flush=True)

while True:
    try:
        bot_status["running"] = True
        print("RUN: starting bot_p2p.py", flush=True)
        r = subprocess.call([sys.executable, "-u", "bot_p2p.py"])
        bot_status["running"] = False
        bot_status["restarts"] += 1
        bot_status["last_restart"] = datetime.now(timezone.utc)
        print(f"RUN: bot_p2p.py EXIT_CODE={r} - restarting in 5s", flush=True)
        time.sleep(5)
    except Exception as e:
        print(f"RUN: WHILE_LOOP_CRASH: {e}", flush=True)
        time.sleep(5)

