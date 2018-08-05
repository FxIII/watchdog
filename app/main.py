import json
from quart import Quart, jsonify, request, make_response
import uvicorn
import uvicorn.loops.auto
import asyncio

from uvicorn.loops import uvloop

from app import helpers
from app.lib import Watchdog, WatchdogDog, expirationCheck

app = Quart(__name__)

OneMonth = 60 * 60 * 24 * 30
expirationCheck_isSetup = False


async def Error(code, message):
    ret = await make_response(jsonify({
        "status": "error",
        "message": str(message)}))
    ret.status_code = code
    return ret


@app.route('/')
async def hello():
    return await Error(401, "no-no")


@app.route("/ping/<dogId>", methods=["GET"])
async def resetTimeout(dogId):
    loop = asyncio.get_event_loop()
    redis = await helpers.getRedis(loop)
    watchdog = WatchdogDog(dogId, redis)
    doc = await watchdog.ping()
    return jsonify({
        "status": "ok",
        "repeat_within": int(doc["timeout"])
    })


@app.route('/watchdogs', methods=["POST"])
async def createWatchdog():
    data = await request.data
    data = json.loads(data.decode("utf-8"))
    loop = asyncio.get_event_loop()
    try:
        watchdog, doc = await Watchdog.mkWatchdog(data, loop)
        return jsonify({
            "status": "ok",
            "watchdog": "/watchdogs/%s" % doc["_id"],
            "ping": "/ping/%s" % doc["dog"],
            "data": doc})
    except Exception as e:
        print(e)
        return await Error(500, e)


@app.route('/watchdogs/<id>/timeout', methods=["GET"])
async def timeout(id):
    loop = asyncio.get_event_loop()
    redis = await helpers.getRedis(loop)
    watchdog = Watchdog(id, redis)
    await watchdog.timeout()
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    uvicorn.run(app, "0.0.0.0", 5000, log_level="info")
