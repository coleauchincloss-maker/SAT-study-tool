# Match server + static app. Everything is standard library except `anthropic`,
# which is only needed if you want question generation on the deployed server.
FROM python:3.12-slim

WORKDIR /app

# Install first so the layer caches independently of app changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hosts inject PORT; server.py reads it.
ENV PORT=8080
EXPOSE 8080

# 0.0.0.0 so the platform's proxy can reach it.
CMD ["sh", "-c", "python3 server.py --host 0.0.0.0 --port ${PORT}"]
