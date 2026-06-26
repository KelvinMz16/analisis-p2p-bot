FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot_p2p.py .

CMD python -u -c "
import subprocess,sys,threading,socket,time,os
def hs():
 s=socket.socket()
 s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 s.bind(('0.0.0.0',int(os.environ.get('PORT',8888))))
 s.listen(20)
 while True:
  c,_=s.accept()
  try:
   c.recv(1024)
   c.sendall(b'HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n')
  except:
   pass
  finally:
   c.close()
threading.Thread(target=hs,daemon=True).start()
print('Health ON',flush=True)
while True:
 print('Starting bot...',flush=True)
 r=subprocess.call([sys.executable,'-u','bot_p2p.py'])
 print(f'Bot exit({r}), restart in 5s',flush=True)
 time.sleep(5)
"
