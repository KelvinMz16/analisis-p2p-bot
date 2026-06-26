import subprocess, sys, threading, socket, time

def _hc(c):
    try:
        c.recv(1024)
        c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
    except: pass
    finally:
        try: c.close()
        except: pass

def _hs(port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.listen(10)
        print(f"HEALTH_SERVER_PORT:{port}", flush=True)
        while True:
            c, _ = s.accept()
            threading.Thread(target=_hc, args=(c,), daemon=True).start()
    except Exception as e:
        print(f"HEALTH_SERVER_ERROR_PORT:{port}:{e}", flush=True)

for p in [8080, 7860]:
    threading.Thread(target=_hs, args=(p,), daemon=True).start()

print("RUN: health servers started", flush=True)

while True:
    print("RUN: starting bot_p2p.py", flush=True)
    r = subprocess.call([sys.executable, "-u", "bot_p2p.py"])
    print(f"RUN: bot_p2p.py EXIT_CODE={r} - restarting in 5s", flush=True)
    time.sleep(5)
