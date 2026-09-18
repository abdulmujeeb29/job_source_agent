import asyncio
import json

from app.schemas import now
from evaluation.run import execute_sample


async def test_parallel_batch_is_bounded_and_preserves_existing_attempts(tmp_path, settings):
    existing = tmp_path / "run-01.json"
    existing.write_text('{"status":"failed","original":true}')
    active = peak = 0
    started = []

    class ControllerFixture:
        def __init__(self, *args):
            pass

        async def execute(self, run):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            started.append(run.run_id)
            await asyncio.sleep(.01)
            run.status = "succeeded"
            run.finished_at = now()
            active -= 1

    urls = [f"https://www.linkedin.com/jobs/view/{5000000000+i}/" for i in range(20)]
    await execute_sample(urls, tmp_path, settings, None, 3, lambda: None, ControllerFixture)
    assert peak == 3
    assert len(started) == len(set(started)) == 19
    assert json.loads(existing.read_text()) == {"status": "failed", "original": True}
    assert len(list(tmp_path.glob("run-*.json"))) == 20
    assert all(json.loads((tmp_path / f"run-{i:02}.json").read_text())["finished_at"] for i in range(2, 21))
