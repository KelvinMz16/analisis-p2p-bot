import socket

hosts = [
    ("proxy2.wynd.network", 4650),
    ("proxy2.wynd.network", 4444),
    ("proxy3.wynd.network", 4650),
    ("proxy3.wynd.network", 4444),
]

for host, port in hosts:
    try:
        s = socket.socket()
        s.settimeout(10)
        s.connect((host, port))
        print(f"OK: {host}:{port}")
        s.close()
    except Exception as e:
        print(f"FAIL: {host}:{port} - {e}")
