import socket
import threading

def handle_client(conn):
    try:
        conn.recv(1024)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
    except:
        pass
    finally:
        try:
            conn.close()
        except:
            pass

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("0.0.0.0", 7860))
s.listen(20)
print("Health server listo en puerto 7860", flush=True)

while True:
    conn, addr = s.accept()
    threading.Thread(target=handle_client, args=(conn,), daemon=True).start()
