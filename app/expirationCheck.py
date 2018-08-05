import asyncio
import uvloop

from app import lib

if __name__ == '__main__':
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(lib.expirationCheck(loop))
