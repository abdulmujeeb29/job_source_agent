"""Inspect live website mechanics without Astra. Not an agent success/evaluation."""
import argparse
import asyncio
import json
from uuid import uuid4

from app.browser import BrowserSession
from app.config import Settings


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--follow-text", action="append", default=[])
    parser.add_argument("--settle-seconds", type=int, default=0)
    args = parser.parse_args()
    async with BrowserSession(Settings(), "probe-" + uuid4().hex[:8]) as browser:
        await browser.open(args.url)
        for text in [None] + args.follow_text:
            if args.settle_seconds:
                await asyncio.sleep(args.settle_seconds)
            observation = await browser.observe()
            if text:
                candidates = [link for link in observation.links if text.casefold() in link.text.casefold()]
                if not candidates:
                    print(json.dumps({"missing_link_text": text, "snapshot": observation.snapshot}))
                    return
                await browser.open(candidates[0].url)
                if args.settle_seconds:
                    await asyncio.sleep(args.settle_seconds)
                observation = await browser.observe()
            print(json.dumps({"url": observation.url, "title": observation.title,
                              "snapshot": observation.snapshot[:16000], "frames": observation.frames}, ensure_ascii=False))


asyncio.run(main())
