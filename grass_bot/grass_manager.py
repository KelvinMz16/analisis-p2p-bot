#!/usr/bin/env python3

import json
import os
import threading
import time
import uuid
import socket
import sys
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import requests
import socks as socks_mod

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

WEBSOCKET_URLS = [
    "wss://proxy2.wynd.network:4650",
    "wss://proxy2.wynd.network:4444",
]

NAMESPACE = uuid.UUID("bfeb71b6-06b8-5e07-87b2-c461c20d9ff6")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
ORIGIN = "chrome-extension://lkbnfiajjmbhnfledhphioinpickokdi"

PING_INTERVAL = 20
RECONNECT_DELAY = 5
TELEGRAM_REPORT_INTERVAL = 3600

VENEZUELA_TZ = timezone(timedelta(hours=-4))
SLEEP_START = 0
SLEEP_END = 7

FREE_PROXY_URLS = [
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&protocol=socks5",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/ebrasha/abdal-proxy-hub/main/socks5-proxy-list-by-EbraSha.txt",
    "https://sockslist.us/Api?request=display&country=all&level=all&token=free",
    "https://api.socks5proxies.com/api/proxies?protocol=socks5&limit=500",
]

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"[ERROR] No se encuentra {CONFIG_PATH}")
        print("Copia config.json.example a config.json y editalo")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    if os.getenv("TELEGRAM_TOKEN"):
        cfg["telegram_token"] = os.getenv("TELEGRAM_TOKEN")
    if os.getenv("TELEGRAM_CHAT_ID"):
        cfg["telegram_chat_id"] = os.getenv("TELEGRAM_CHAT_ID")
    return cfg

CONFIG = load_config()
TELEGRAM_TOKEN = CONFIG.get("telegram_token", "")
TELEGRAM_CHAT_ID = CONFIG.get("telegram_chat_id", "")

def _tg_call(method, payload=None, timeout=15):
    if not TELEGRAM_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        return resp.json()
    except:
        return None

def enviar_telegram(texto):
    _tg_call("sendMessage", {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown"
    })

def get_unix_ts():
    return int(time.time())

def en_horario():
    return not (SLEEP_START <= datetime.now(VENEZUELA_TZ).hour < SLEEP_END)

def make_browser_id(seed):
    return str(uuid.uuid5(NAMESPACE, seed))

def parse_proxy(proxy_str):
    if not proxy_str:
        return None
    match = re.match(r'(socks5|socks4|http)://(?:([^:]+):([^@]+)@)?([^:]+):(\d+)', proxy_str)
    if match:
        proto = match.group(1)
        user = match.group(2)
        passwd = match.group(3)
        host = match.group(4)
        port = int(match.group(5))
        return {"type": proto, "host": host, "port": port, "user": user, "pass": passwd}
    match = re.match(r'(?:socks5://)?([^:]+):(\d+)', proxy_str)
    if match:
        return {"type": "socks5", "host": match.group(1), "port": int(match.group(2)), "user": None, "pass": None}
    return None

def fetch_free_proxies():
    proxies = []
    print("[PROXY] Buscando proxies SOCKS5 gratuitos...", flush=True)
    for url in FREE_PROXY_URLS:
        try:
            resp = requests.get(url, timeout=15)
            if not resp.ok:
                continue
            ct = resp.headers.get("Content-Type", "")
            if "json" in ct:
                data = resp.json()
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            ip = item.get("ip") or item.get("proxy")
                            port = item.get("port")
                            if ip and port:
                                proxies.append(f"socks5://{ip}:{port}")
                        elif isinstance(item, str) and re.match(r'^[^:]+:\d+', item):
                            proxies.append(f"socks5://{item}")
                elif isinstance(data, dict) and "data" in data:
                    for item in data["data"]:
                        ip = item.get("ip") or item.get("proxy")
                        port = item.get("port")
                        if ip and port:
                            proxies.append(f"socks5://{ip}:{port}")
            else:
                for line in resp.text.strip().split("\n"):
                    line = line.strip()
                    parts = line.split(":")
                    if len(parts) >= 2 and parts[0].count(".") == 3:
                        ip = parts[0]
                        port_match = re.search(r'\d+', parts[1])
                        if port_match:
                            port = port_match.group()
                            if ip and port.isdigit():
                                proxy_str = f"socks5://{ip}:{port}"
                                if proxy_str not in proxies:
                                    proxies.append(proxy_str)
        except:
            pass
    proxies = list(dict.fromkeys(proxies))
    print(f"[PROXY] {len(proxies)} proxies encontrados", flush=True)
    return proxies

class GrassAccount:
    def __init__(self, user_id, proxy_str, label=None):
        self.user_id = user_id
        self.proxy_str = proxy_str
        self.proxy = parse_proxy(proxy_str) if proxy_str else None
        self.label = label or (f"cuenta_{proxy_str.split(':')[0]}" if proxy_str else "cuenta_1")
        seed = proxy_str or f"direct_{user_id}"
        self.browser_id = make_browser_id(seed)
        self.ws = None
        self.running = False
        self.thread = None
        self.last_pong = 0
        self.last_live = 0
        self.connected_since = 0
        self.retry_count = 0
        self.url_index = 0
        self.disconnect_expected = False

    def _create_socket(self, host, port):
        if self.proxy:
            st = socks_mod.SOCKS5 if self.proxy["type"] == "socks5" else socks_mod.SOCKS4
            sock = socks_mod.socksocket()
            sock.set_proxy(st, self.proxy["host"], self.proxy["port"],
                           username=self.proxy["user"], password=self.proxy["pass"])
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect((host, port))
        return sock

    def _send(self, data):
        if not self.ws:
            return
        try:
            self.ws.send(json.dumps(data))
        except Exception as e:
            print(f"[{self.label}] Send error: {e}", flush=True)

    def _recv(self):
        try:
            raw = self.ws.recv()
            if raw:
                return json.loads(raw)
        except:
            pass
        return None

    def _handle_auth(self, data):
        return {
            "browser_id": self.browser_id,
            "user_id": self.user_id,
            "user_agent": USER_AGENT,
            "timestamp": get_unix_ts(),
            "device_type": "extension",
            "version": "4.3.2",
            "extension_id": "lkbnfiajjmbhnfledhphioinpickokdi",
        }

    def _handle_http_request(self, data):
        url = data.get("url", "")
        method = data.get("method", "GET")
        headers = data.get("headers", {})
        body = data.get("body")
        try:
            req_headers = {}
            for k, v in headers.items():
                if isinstance(v, list):
                    req_headers[k] = "; ".join(v)
                else:
                    req_headers[k] = str(v)
            sess = requests.Session()
            resp = sess.request(method, url, headers=req_headers, data=body, timeout=30)
            import base64
            resp_body = base64.b64encode(resp.content).decode() if resp.content else ""
            return {
                "url": resp.url,
                "status": resp.status_code,
                "status_text": resp.reason,
                "headers": dict(resp.headers),
                "body": resp_body,
            }
        except Exception as e:
            print(f"[{self.label}] HTTP Request error: {e}", flush=True)
            return None

    def _run_forever(self):
        import websocket as ws_lib
        self.last_live = get_unix_ts()
        while self.running and not self.disconnect_expected:
            try:
                url = WEBSOCKET_URLS[self.url_index % len(WEBSOCKET_URLS)]
                parsed = urlparse(url)
                host = parsed.hostname
                port = parsed.port or (443 if parsed.scheme == "wss" else 80)

                proxy_info = f" via {self.proxy_str}" if self.proxy_str else " (directo)"
                print(f"[{self.label}] Conectando a {url}{proxy_info}...", flush=True)
                raw_sock = self._create_socket(host, port)

                self.ws = ws_lib.WebSocket()
                self.ws.connect(url, sock=raw_sock, skip_utf8_validation=True,
                                header={"User-Agent": USER_AGENT, "Origin": ORIGIN})
                self.connected_since = get_unix_ts()
                self.retry_count = 0
                print(f"[{self.label}] Conectado! id={self.user_id[:8]}... browser={self.browser_id[:8]}...", flush=True)

                last_ping = 0
                while self.running and not self.disconnect_expected:
                    now = get_unix_ts()
                    if now - last_ping >= PING_INTERVAL:
                        self._send({"id": str(uuid.uuid4()), "version": "1.0.0", "action": "PING", "data": {}})
                        last_ping = now
                    if now - self.last_live > 35:
                        print(f"[{self.label}] Conexion muerta ({now - self.last_live}s), reconectando...", flush=True)
                        break
                    self.ws.settimeout(5)
                    msg = self._recv()
                    if msg is None:
                        continue
                    action = msg.get("action", "")
                    msg_id = msg.get("id")
                    data = msg.get("data", {})
                    origin_action = msg.get("origin_action")
                    self.last_live = now
                    if action == "AUTH":
                        result = self._handle_auth(data)
                        self._send({"id": msg_id, "origin_action": "AUTH", "result": result})
                        print(f"[{self.label}] Autenticado", flush=True)
                    elif action == "PING":
                        self._send({"id": msg_id, "origin_action": "PING", "result": {}})
                        self.last_pong = now
                    elif action == "PONG":
                        self.last_pong = now
                    elif action == "HTTP_REQUEST":
                        result = self._handle_http_request(data)
                        if result is not None:
                            self._send({"id": msg_id, "origin_action": "HTTP_REQUEST", "result": result})
                    elif origin_action:
                        pass
            except Exception as e:
                err = str(e)
                if "timed out" in err and self.ws and self.ws.connected:
                    continue
                if not self.disconnect_expected:
                    print(f"[{self.label}] Error: {err[:120]}", flush=True)
            finally:
                try:
                    if self.ws:
                        self.ws.close()
                except:
                    pass
                self.ws = None
            if self.running and not self.disconnect_expected:
                self.retry_count += 1
                delay = min(RECONNECT_DELAY * (1 + self.retry_count * 0.5), 60)
                print(f"[{self.label}] Reconectando en {delay:.0f}s (intento #{self.retry_count})...", flush=True)
                time.sleep(delay)
                self.url_index += 1

    def start(self):
        if self.running:
            return
        self.running = True
        self.disconnect_expected = False
        self.thread = threading.Thread(target=self._run_forever, daemon=True)
        self.thread.start()
        print(f"[{self.label}] Iniciada", flush=True)

    def stop(self):
        self.disconnect_expected = True
        self.running = False
        try:
            if self.ws:
                self.ws.close()
        except:
            pass
        print(f"[{self.label}] Detenida", flush=True)

    @property
    def status(self):
        uptime = get_unix_ts() - self.connected_since if self.connected_since else 0
        return {
            "label": self.label,
            "proxy": self.proxy_str or "directo",
            "connected": self.ws is not None and self.running,
            "uptime": uptime,
            "retries": self.retry_count,
        }

class GrassManager:
    def __init__(self, config):
        self.config = config
        self.accounts = []
        self.running = False
        self.main_thread = None

        for acc_cfg in config.get("accounts", []):
            account = GrassAccount(
                user_id=acc_cfg["user_id"],
                proxy_str=acc_cfg.get("proxy", ""),
                label=acc_cfg.get("label"),
            )
            self.accounts.append(account)

    def start_all(self):
        for acc in self.accounts:
            acc.start()
            time.sleep(1)
        print(f"\n[*] {len(self.accounts)} cuenta(s) iniciada(s)", flush=True)

    def stop_all(self):
        for acc in self.accounts:
            acc.stop()

    def get_status_text(self):
        lines = ["\U0001F4BF *Grass Bot - Estado*"]
        connected = 0
        for acc in self.accounts:
            s = acc.status
            icon = "\U0001F7E2" if s["connected"] else "\U0001F534"
            uptime = s["uptime"]
            uptime_str = f"{uptime//3600}h {(uptime%3600)//60}m" if uptime > 0 else "0m"
            lines.append(f"{icon} {s['label']}: {'Conectada' if s['connected'] else 'Desconectada'} ({uptime_str})")
            lines.append(f"     \u21B3 Proxy: {s['proxy']}")
            if s["connected"]:
                connected += 1
        lines.append(f"\n{connected}/{len(self.accounts)} conectadas")
        return "\n".join(lines)

    def _monitor_loop(self):
        last_report = 0
        while self.running:
            try:
                now = get_unix_ts()
                if now - last_report >= TELEGRAM_REPORT_INTERVAL:
                    enviar_telegram(self.get_status_text())
                    last_report = now
                time.sleep(30)
            except:
                time.sleep(10)

    def start_monitor(self):
        self.running = True
        self.main_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.main_thread.start()

    def stop_monitor(self):
        self.running = False

    def send_status(self):
        enviar_telegram(self.get_status_text())

def telegram_polling(manager):
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            resp = requests.post(url, json={"offset": offset, "timeout": 10}, timeout=20)
            if not resp.ok:
                time.sleep(3)
                continue
            for update in resp.json().get("result", []):
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    cq = update["callback_query"]
                    chat_id = cq["message"]["chat"]["id"]
                    msg_id = cq["message"]["message_id"]
                    data = cq["data"]
                    requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": cq["id"]},
                    )
                    if data == "status":
                        text = manager.get_status_text()
                        kb = json.dumps({"inline_keyboard": [
                            [{"text": "\U0001F504 Actualizar", "callback_data": "status"},
                             {"text": "\U0001F4E1 Menu", "callback_data": "menu"}]
                        ]})
                        requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
                            json={"chat_id": chat_id, "message_id": msg_id,
                                  "text": text, "parse_mode": "Markdown", "reply_markup": kb},
                        )
                    elif data == "menu":
                        text = ("\U0001F4BF *Grass Multi-Account Bot*\n\n"
                                "Farming automatico con proxies SOCKS5.\n"
                                "Usa /status para ver estado.")
                        kb = json.dumps({"inline_keyboard": [
                            [{"text": "\U0001F4CB Estado", "callback_data": "status"}]
                        ]})
                        requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText",
                            json={"chat_id": chat_id, "message_id": msg_id,
                                  "text": text, "parse_mode": "Markdown", "reply_markup": kb},
                        )
                elif "message" in update:
                    msg = update["message"]
                    txt = msg.get("text", "")
                    chat_id = msg["chat"]["id"]
                    if txt in ("/start", "/menu"):
                        text = ("\U0001F4BF *Grass Multi-Account Bot*\n\n"
                                "Farming automatico con proxies SOCKS5.\n"
                                "Usa /status para ver estado.")
                        kb = json.dumps({"inline_keyboard": [
                            [{"text": "\U0001F4CB Estado", "callback_data": "status"}]
                        ]})
                        requests.post(
                            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                            json={"chat_id": chat_id, "text": text,
                                  "parse_mode": "Markdown", "reply_markup": kb},
                        )
                    elif txt == "/status":
                        manager.send_status()
        except:
            pass
        time.sleep(3)

def main():
    auto_proxies = CONFIG.get("auto_proxies", False)
    if auto_proxies:
        proxies = fetch_free_proxies()
        user_id = CONFIG.get("accounts", [{}])[0].get("user_id", "")
        if not user_id:
            print("[ERROR] No hay user_id en config.json")
            sys.exit(1)
        manager = GrassManager.__new__(GrassManager)
        manager.config = CONFIG
        manager.accounts = []
        manager.running = False
        manager.main_thread = None
        for i, proxy_str in enumerate(proxies[:CONFIG.get("max_accounts", 50)]):
            acc = GrassAccount(user_id=user_id, proxy_str=proxy_str, label=f"proxy_{i+1}")
            manager.accounts.append(acc)
    else:
        manager = GrassManager(CONFIG)

    if not manager.accounts:
        print("[ERROR] No hay cuentas configuradas")
        sys.exit(1)

    print("=" * 50, flush=True)
    print(f"  Grass Multi-Account Bot ({len(manager.accounts)} cuentas)", flush=True)
    print("=" * 50, flush=True)

    if TELEGRAM_TOKEN:
        t = threading.Thread(target=telegram_polling, args=(manager,), daemon=True)
        t.start()
        time.sleep(2)
        enviar_telegram(
            f"\U0001F4E1 *Grass Bot Iniciado*\n"
            f"{len(manager.accounts)} cuenta(s) configurada(s)\n"
            f"Usa /status para ver estado"
        )

    manager.start_all()
    manager.start_monitor()

    try:
        while True:
            time.sleep(60)
            connected = sum(1 for a in manager.accounts if a.status["connected"])
            total = len(manager.accounts)
            print(f"[LATIDO] {connected}/{total} conectadas", flush=True)
    except KeyboardInterrupt:
        print("\nDeteniendo...", flush=True)
        manager.stop_all()
        manager.stop_monitor()
        enviar_telegram("\U0001F534 *Grass Bot Detenido*")
        print("Detenido.", flush=True)

if __name__ == "__main__":
    main()
