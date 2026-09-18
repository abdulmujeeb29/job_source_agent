"""Run a real discovery from the terminal with the same controller used by the UI."""
import argparse
import asyncio
from uuid import uuid4

from app.config import Settings
from app.controller import Controller
from app.schemas import Run
from app.storage import Store
from app.urls import normalize_job_url


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    args = parser.parse_args()
    s = Settings()
    store = Store(s.data_dir / "runs.sqlite3")
    run = Run(run_id=uuid4().hex, input_url=args.url, normalized_input_url=normalize_job_url(args.url))
    try:
        await Controller(s, store).execute(run)
        print(run.model_dump_json(indent=2))
    finally:
        store.close()


asyncio.run(main())
