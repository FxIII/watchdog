# 🐕 watchdog

> A tiny Redis-backed dead man's switch as a microservice.

You call it regularly. If you stop — it calls someone.

---

## How it works

Post a watchdog with a timeout and two URLs. From that moment on, call the `/ping` endpoint more often than the timeout. As long as you do, nothing happens.

Miss the deadline → `alert_url` is called once.  
Start pinging again → `recover_url` is called, watchdog goes back to watching.

The whole thing is stateless by design. No database, no state machine. Just two Redis keys per watchdog:

- `watchdog:{id}:config` — stores configuration, expires after `expire` seconds (max 1 month)
- `watchdog:{id}:heartbeat` — a key with TTL equal to `timeout`. Recreated on every ping. When it expires, Redis fires a keyspace event and the service calls `alert_url`. When a ping comes in and the key is gone, the service calls `recover_url`.

Redis key presence **is** the state.

---

## API

### `POST /watchdog/{id}`
Create or update a watchdog.

```json
{
  "timeout": 600,
  "expire": 2592000,
  "alert_url": "https://example.com/alert",
  "recover_url": "https://example.com/recover"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `timeout` | int | `600` | Seconds between required pings |
| `expire` | int | `2592000` | Watchdog lifetime in seconds (max 1 month) |
| `alert_url` | string | required | Called once when timeout is missed |
| `recover_url` | string | required | Called once when pinging resumes after an alert |

---

### `GET /watchdog/{id}`
Returns current configuration and live TTL info.

```json
{
  "id": "my-service",
  "status": "watching",
  "timeout": 600,
  "expire_in": 2591483,
  "heartbeat_ttl": 423,
  "alert_url": "https://example.com/alert",
  "recover_url": "https://example.com/recover"
}
```

`status` is either `watching` or `alert` — derived from heartbeat key presence, no extra storage needed.

---

### `GET /watchdog/{id}/ping`
Kicks the watchdog. Resets the heartbeat TTL. If the watchdog was in `alert` state (heartbeat had expired), `recover_url` is called and the watchdog returns to `watching`.

```json
{ "id": "my-service", "status": "ok" }
// or, if recovering:
{ "id": "my-service", "status": "recovered" }
```

---

### `DELETE /watchdog/{id}`
Removes the watchdog entirely (both config and heartbeat keys).

---

## Running

### With Docker Compose

```bash
docker compose up
```

This starts Redis (with keyspace notifications enabled) and the watchdog service on port `8000`.

```bash
# or build locally during development
docker compose up --build
```

The web UI is available at [http://localhost:8000](http://localhost:8000).  
The API docs are at [http://localhost:8000/docs](http://localhost:8000/docs).

---

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection string |
| `MAX_EXPIRE_SECONDS` | `2592000` | Maximum allowed expire value (1 month) |

---

## Docker image

Pre-built images are published to GitHub Container Registry on every push to `main`.

```bash
docker pull ghcr.io/fxiii/watchdog:latest
```

---

## Quick example

```bash
# Create a watchdog with a 1 minute timeout
curl -X POST http://localhost:8000/watchdog/my-service \
  -H "Content-Type: application/json" \
  -d '{
    "timeout": 60,
    "alert_url": "https://ntfy.sh/my-alerts",
    "recover_url": "https://ntfy.sh/my-alerts"
  }'

# Ping it (call this more often than every 60 seconds)
curl http://localhost:8000/watchdog/my-service/ping

# Check status
curl http://localhost:8000/watchdog/my-service

# Remove it
curl -X DELETE http://localhost:8000/watchdog/my-service
```

---

## Web UI

A minimal single-page UI is served at `/`. It uses `localStorage` to track watchdog IDs known to the browser, fetches live state from the API every 5 seconds, and lets you create, ping, edit and delete watchdogs without touching the terminal.

---

## Stack

| | |
|---|---|
| **Runtime** | Python 3.12 |
| **Framework** | FastAPI + Uvicorn |
| **Store** | Redis 7 (keyspace notifications) |
| **HTTP client** | httpx (async) |
| **CI/CD** | GitHub Actions → ghcr.io |

---

## Project structure

```
watchdog/
├── .github/
│   └── workflows/
│       └── docker.yml      # builds and pushes to ghcr.io on every push to main
├── static/
│   └── index.html          # single-page UI
├── app.py                  # everything — FastAPI app, Redis helpers, keyspace listener
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## License

MIT