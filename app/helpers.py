import asyncio
import aioredis
import aiohttp
import os


async def getRedis(loop, redis=[]):
    if len(redis) == 0:
        redis.append(await aioredis.create_redis(
            os.environ.get("REDIS_HOST",'redis://redis'), loop=loop))
    return redis[0]


async def getSession(loop, session=[]):
    if len(session) == 0:
        session.append(aiohttp.ClientSession())
    return session[0]


async def call(specs, loop=None):
    loop = asyncio.get_event_loop() if loop is None else loop
    session = await getSession(loop)
    asyncio.ensure_future(session.get(specs))


