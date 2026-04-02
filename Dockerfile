FROM python:3.11-slim

# openssh-client is needed for SSH SOCKS5 tunnels
RUN apt-get update && \
    apt-get install -y --no-install-recommends openssh-client && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the data directory exists for the SQLite database
RUN mkdir -p /app/data

# Run the bot (main.py shim delegates to gosha.main)
# Override CMD to run just the web: ["uvicorn", "gosha.web.app:app", "--host", "0.0.0.0", "--port", "8080"]
CMD ["python", "main.py"]
