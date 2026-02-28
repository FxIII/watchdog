import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("watchdog")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
MAX_EXPIRE = int(os.getenv("MAX_EXPIRE_SECONDS", str(30 * 24 * 3600)))  # 1 month

redis: aioredis.Redis = None


# ── Models ────────────────────────────────────────────────────────────────────

class WatchdogConfig(BaseModel):
    timeout: int = 600                  # seconds, how often kick must come
    expire: int = MAX_EXPIRE            # seconds, lifetime of this watchdog
    alert_url: HttpUrl                  # called once when timeout is missed
    recover_url: HttpUrl                # called when kick resumes after alert


# ── Redis helpers ─────────────────────────────────────────────────────────────

def config_key(wid: str) -> str:
    return f"watchdog:{wid}:config"

def heartbeat_key(wid: str) -> str:
    return f"watchdog:{wid}:heartbeat"

async def save_config(wid: str, cfg: WatchdogConfig):
    expire = min(cfg.expire, MAX_EXPIRE)
    await redis.hset(config_key(wid), mapping={
        "timeout":     cfg.timeout,
        "expire":      expire,
        "alert_url":   str(cfg.alert_url),
        "recover_url": str(cfg.recover_url),
    })
    await redis.expire(config_key(wid), expire)

async def load_config(wid: str) -> dict | None:
    data = await redis.hgetall(config_key(wid))
    return {k.decode(): v.decode() for k, v in data.items()} if data else None

async def set_heartbeat(wid: str, timeout: int):
    await redis.set(heartbeat_key(wid), "1", ex=timeout)

async def heartbeat_exists(wid: str) -> bool:
    return await redis.exists(heartbeat_key(wid)) == 1


# ── HTTP caller ───────────────────────────────────────────────────────────────

async def call_url(url: str, label: str):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url)
            log.info(f"[{label}] GET {url} → {r.status_code}")
    except Exception as e:
        log.error(f"[{label}] GET {url} failed: {e}")


# ── Keyspace event listener ───────────────────────────────────────────────────

async def listen_for_expirations():
    """Subscribe to expired keyspace events and fire alert_url on heartbeat expiry."""
    pub = redis.pubsub()
    await pub.psubscribe("__keyevent@0__:expired")
    log.info("Listening for keyspace expiration events...")
    async for message in pub.listen():
        if message["type"] != "pmessage":
            continue
        key = message["data"].decode()
        # e.g. watchdog:abc123:heartbeat
        if not (key.startswith("watchdog:") and key.endswith(":heartbeat")):
            continue
        wid = key.split(":")[1]
        cfg = await load_config(wid)
        if cfg is None:
            log.info(f"[{wid}] heartbeat expired but config gone — watchdog dead.")
            continue
        log.info(f"[{wid}] heartbeat expired → calling alert_url")
        await call_url(cfg["alert_url"], f"{wid}/alert")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis
    redis = aioredis.from_url(REDIS_URL, decode_responses=False)
    task = asyncio.create_task(listen_for_expirations())
    log.info("Watchdog service started.")
    yield
    task.cancel()
    await redis.aclose()


# ── App ───────────────────────────────────────────────────────────────────────

from fastapi.responses import RedirectResponse

app = FastAPI(title="Watchdog", lifespan=lifespan)


@app.get("/")
async def root():
    return RedirectResponse(url="/ui")


@app.post("/watchdog/{wid}", status_code=201)
async def create_or_update(wid: str, cfg: WatchdogConfig):
    """Create or update a watchdog. Resets the heartbeat timer."""
    if cfg.expire > MAX_EXPIRE:
        raise HTTPException(400, f"expire must be ≤ {MAX_EXPIRE}s (1 month)")
    await save_config(wid, cfg)
    await set_heartbeat(wid, cfg.timeout)
    log.info(f"[{wid}] created/updated — timeout={cfg.timeout}s expire={cfg.expire}s")
    return {"id": wid, "timeout": cfg.timeout, "expire": cfg.expire}


@app.get("/watchdog/{wid}")
async def get_config(wid: str):
    """Return the current configuration and live TTL info for a watchdog."""
    cfg = await load_config(wid)
    if cfg is None:
        raise HTTPException(404, "Watchdog not found or expired")

    heartbeat_ttl = await redis.ttl(heartbeat_key(wid))
    expire_ttl = await redis.ttl(config_key(wid))
    status = "watching" if heartbeat_ttl > 0 else "alert"

    return {
        "id":            wid,
        "status":        status,
        "timeout":       int(cfg["timeout"]),
        "expire_in":     expire_ttl,
        "heartbeat_ttl": max(heartbeat_ttl, 0),
        "alert_url":     cfg["alert_url"],
        "recover_url":   cfg["recover_url"],
    }


@app.get("/watchdog/{wid}/ping")
async def ping(wid: str):
    """Kick the watchdog. If it was in alert state, recover_url is called."""
    cfg = await load_config(wid)
    if cfg is None:
        raise HTTPException(404, "Watchdog not found or expired")

    alive = await heartbeat_exists(wid)
    await set_heartbeat(wid, int(cfg["timeout"]))

    if not alive:
        log.info(f"[{wid}] recovered → calling recover_url")
        asyncio.create_task(call_url(cfg["recover_url"], f"{wid}/recover"))
        return {"id": wid, "status": "recovered"}

    return {"id": wid, "status": "ok"}


@app.delete("/watchdog/{wid}")
async def delete_watchdog(wid: str):
    """Remove a watchdog entirely."""
    deleted = await redis.delete(config_key(wid), heartbeat_key(wid))
    if deleted == 0:
        raise HTTPException(404, "Watchdog not found")
    log.info(f"[{wid}] deleted")
    return {"id": wid, "status": "deleted"}


if os.path.isdir("static"):
    app.mount("/ui", StaticFiles(directory="static", html=True), name="static")