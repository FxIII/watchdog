import asyncio
import json
import sys
import traceback
from uuid import uuid4 as uuid

from app import helpers

OneMonth = 60 * 60 * 24 * 30


class WatchdogDog:
    def __init__(self, dogId, redis):
        self.dog = dogId
        self.redis = redis

    async def ping(self):
        watchdog = await Watchdog.fromDog(self.dog, self.redis)
        wasEmpty = not (await self.redis.exists("dog:%s" % self.dog))
        print("wasEmpty? %s" % wasEmpty)
        doc = await watchdog.refresh(dogToo=True)
        print("doc: %r" % doc)
        if wasEmpty and doc.get("creationCallback"):
            print("calling creation callback")
            print(str(doc["creationCallback"]))
            await helpers.call(doc["creationCallback"])
        return doc


class Watchdog:
    def __init__(self, id, redis):
        self.id = id
        self.redis = redis

    @staticmethod
    async def fromDog(dog, loop=None):
        loop = asyncio.get_event_loop() if loop is None else loop
        redis = await helpers.getRedis(loop)
        watchdogId = (await redis.get("findDog:%s" % dog)).decode()
        return Watchdog(watchdogId, redis)

    @staticmethod
    async def mkWatchdog(data, loop=None):
        doc = {
            "_id": uuid().hex,
            "dog": uuid().hex,
            "timeout": data.get("timeout", 600),
            "callback": data.get("callback"),
            "creationCallback": data.get("creationCallback")
        }
        loop = asyncio.get_event_loop() if loop is None else loop
        redis = await helpers.getRedis(loop)
        await redis.set("watchdog:%s" % doc["_id"], json.dumps(doc), expire=OneMonth)
        await redis.set("findDog:%s" % doc["dog"], doc["_id"], expire=OneMonth)
        await redis.set("dog:%s" % doc["dog"], "watchdog:%s" % doc["_id"], expire=int(doc["timeout"]))
        return Watchdog(doc["_id"], redis), doc

    async def refresh(self, dogToo=False):
        doc = await self.getDoc()
        print("got document %r" % doc)
        dogId = doc["dog"]
        res = await self.redis.expire("watchdog:%s" % self.id, OneMonth)
        print("reset TTL for watchdog:%s (%s)" % (self.id, res))
        res = await self.redis.expire("findDog:%s" % dogId, OneMonth)
        print("reset TTL for findDog:%s (%s)" % (dogId, res))
        if dogToo:
            print("reset TTL for dog too")
            res = await self.redis.set("dog:%s" % dogId, "watchdog:%s" % self.id, expire=int(doc["timeout"]))
            print("ensure exists dog:%s (%s)" % (dogId, res))
            res = await self.redis.expire("dog:%s" % dogId, int(doc["timeout"]))
            print("reset TTL for dog:%s (%s)" % (dogId, res))
            return doc

    async def update(self, data):
        # todo  update document
        _ = data
        self.refresh()

    async def getDoc(self):
        doc = await self.redis.get("watchdog:%s" % self.id)
        return json.loads(doc)

    async def timeout(self, loop=None):
        doc = await self.getDoc()
        callback = doc["callback"]
        await helpers.call(callback, loop)


async def expirationCheck(loop=None):
    loop = asyncio.get_event_loop() if loop is None else loop
    redis = await helpers.getRedis(loop, [])
    await redis.config_set("notify-keyspace-events", "Ex")  # enable expiration events
    channel, = await redis.psubscribe('__keyevent@0__:expired')  # wait for expirations
    while True:
        while await channel.wait_message():
            try:
                event, expiredKey = await channel.get(encoding='utf-8')
                print("expired %s, notify." % expiredKey)
                dogId = expiredKey[len("dog:"):]
                watchdog = await Watchdog.fromDog(dogId, loop)
                await watchdog.timeout(loop)
            except Exception as e:
                traceback.print_exc(file=sys.stdout)
