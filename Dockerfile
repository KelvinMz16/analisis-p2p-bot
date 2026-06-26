FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot_p2p.py health.py .

EXPOSE 7860

CMD python -u health.py & exec python -u bot_p2p.py
