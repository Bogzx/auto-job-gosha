FROM python:3.11-slim

# openssh-client is needed for SSH SOCKS5 tunnels
RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --uid 1000 app

WORKDIR /app

COPY requirements.txt .
# Generous timeout/retries: torch (sentence-transformers) is a large wheel
RUN pip install --no-cache-dir --timeout 180 --retries 8 -r requirements.txt

COPY . .

# Ensure data directory exists and is owned by app user
RUN mkdir -p /app/data && chown -R app:app /app/data

USER app

# Run the bot (main.py shim delegates to gosha.main)
# Override CMD to run just the web: ["uvicorn", "gosha.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
CMD ["python", "main.py"]
