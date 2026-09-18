import asyncio
import json
from uuid import uuid4

from app.browser import BrowserSession
from app.config import Settings


async def main():
    async with BrowserSession(Settings(), "smoke-" + uuid4().hex[:8]) as browser:
        await browser.open("https://example.com")
        observation = await browser.observe()
        print(json.dumps({"url": observation.url, "title": observation.title,
                          "snapshot": observation.snapshot, "links": len(observation.links)}, indent=2))


asyncio.run(main())
