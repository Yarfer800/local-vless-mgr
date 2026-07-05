FROM python:3.12-slim

WORKDIR /app

# Для curl (ожидание Marzban) и минимальной диагностики
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY main.py .

# Ждём Marzban API, потом запускаем демон
CMD ["sh", "-c", "\
    MARZBAN_CHECK=\"${MARZBAN_URL:-http://marzban:8000}\"; \
    echo \"Waiting for Marzban at $MARZBAN_CHECK ...\"; \
    until curl -s \"${MARZBAN_CHECK}/api/inbounds\" > /dev/null 2>&1; do \
        sleep 3; \
    done; \
    echo 'Marzban is ready, starting collector...'; \
    python main.py --daemon \
"]
