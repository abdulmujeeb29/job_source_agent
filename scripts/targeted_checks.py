"""Post-fix development checks on known failures; never modify baseline results."""
import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.controller import Controller
from app.schemas import Run
from app.storage import Store


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("indices", nargs="+", type=int)
    args = parser.parse_args()
    sample = json.loads(Path("evaluation/results/sample.json").read_text())["urls"]
    s = Settings()
    folder = s.data_dir / "targeted"
    folder.mkdir(parents=True, exist_ok=True)
    store = Store(s.data_dir / "runs.sqlite3")
    try:
        for index in args.indices:
            url = sample[index - 1]
            run = Run(run_id=uuid4().hex, input_url=url, normalized_input_url=url)
            await Controller(s, store).execute(run)
            (folder / f"{index:02}-{run.run_id}.json").write_text(run.model_dump_json(indent=2))
            print(json.dumps({"index": index, "company": run.company_name, "status": run.status,
                              "jobs_url": run.jobs_url, "reason": run.failure_reason,
                              "seconds": run.duration_ms / 1000, "run_id": run.run_id}), flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
