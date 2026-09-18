"""Frozen local evaluation runner. Does not deploy, publish, or modify the sample."""
import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.controller import Controller
from app.providers import ApifyProvider, Astra
from app.schemas import Run, now
from app.storage import Store


def fingerprint():
    files = sorted([*Path("app").rglob("*.py"), *Path("app/static").glob("*"), *Path("evaluation").glob("*.py"),
                    Path("pyproject.toml"), Path("uv.lock"), Path("Dockerfile")])
    return hashlib.sha256(b"".join(str(p).encode() + p.read_bytes() for p in files)).hexdigest()


async def execute_sample(urls, folder, settings, store, concurrency, check_source, controller_factory=Controller):
    gate = asyncio.Semaphore(concurrency)

    async def execute_one(index, url):
        async with gate:
            check_source()
            output = folder / f"run-{index:02}.json"
            if output.exists():
                print(f"{index}/20: preserving existing attempt", flush=True)
                return
            run = Run(run_id=uuid4().hex, input_url=url, normalized_input_url=url)
            output.write_text(json.dumps({"input_url": url, "status": "interrupted", "run_id": run.run_id,
                                          "failure_reason": "Attempt started; final result not yet written."}, indent=2))
            await controller_factory(settings, store).execute(run)
            output.write_text(run.model_dump_json(indent=2))
            print(f"{index}/20: {run.status} — {run.company_name or run.failure_code}", flush=True)

    async with asyncio.TaskGroup() as group:
        for index, url in enumerate(urls, 1):
            group.create_task(execute_one(index, url))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/results"))
    parser.add_argument("--sample", type=Path, default=Path("evaluation/results/sample.json"))
    parser.add_argument("--kind", choices=["baseline", "post-fix", "fresh"], default="baseline")
    parser.add_argument("--run-protocol", type=Path)
    parser.add_argument("--selection-protocol", type=Path, default=Path("evaluation/PROTOCOL.md"))
    parser.add_argument("--concurrency", type=int, choices=[1, 2, 3], default=1)
    args = parser.parse_args()
    folder = args.output_dir
    if args.kind != "baseline" and folder.resolve() == Path("evaluation/results").resolve():
        raise SystemExit("Post-fix results must use a separate output directory.")
    sample_bytes = args.sample.read_bytes()
    sample = json.loads(sample_bytes)
    if len(sample["urls"]) != 20 or len(set(sample["urls"])) != 20:
        raise SystemExit("Exactly 20 distinct sampled URLs required.")
    if hashlib.sha256(args.selection_protocol.read_bytes()).hexdigest() != sample["protocol_sha256"]:
        raise SystemExit("Protocol changed after sampling. Preserve and explain the revision before evaluating.")
    folder.mkdir(parents=True, exist_ok=True)
    sample_copy = folder / "sample.json"
    if sample_copy.exists() and sample_copy.read_bytes() != sample_bytes:
        raise SystemExit("Output directory already contains a different sample.")
    if not sample_copy.exists():
        sample_copy.write_bytes(sample_bytes)
    s = Settings()
    model, provider = Astra(s), ApifyProvider(s)
    try:
        await model.decide({"task": "Preflight only; no page available. Stop with no listings."})
        await provider.request("GET", "users/me")
    finally:
        await model.close()
        await provider.close()
    frozen = {"source_sha256": fingerprint(), "sample_sha256": hashlib.sha256((folder / "sample.json").read_bytes()).hexdigest(),
              "app_version": Run.model_fields["config_version"].default,
              "concurrency": args.concurrency,
              "selection_protocol_sha256": sample["protocol_sha256"],
              "run_protocol_sha256": hashlib.sha256(args.run_protocol.read_bytes()).hexdigest() if args.run_protocol else None,
              "environment": "local", "python": platform.python_version(), "model": s.azure_openai_model,
              "evaluation_kind": args.kind,
              "azure_base_url": s.model_base_url,
              "agent_browser": subprocess.check_output([s.agent_browser_binary, "--version"], text=True).strip(),
              "max_actions": s.max_actions, "deadline_seconds": s.run_timeout_seconds,
              "max_model_calls": s.max_model_calls, "job_actor": s.apify_job_actor,
              "company_actor": s.apify_company_actor, "company_fallback_actor": s.apify_company_fallback_actor}
    freeze_file = folder / "freeze.json"
    if freeze_file.exists():
        if json.loads(freeze_file.read_text())["configuration"] != frozen:
            raise SystemExit("Build/configuration changed since freeze. Preserve the original evaluation.")
    else:
        freeze_file.write_text(json.dumps({"frozen_at": now(), "configuration": frozen}, indent=2))
    store = Store(s.data_dir / "runs.sqlite3")
    try:
        def check_source():
            if fingerprint() != frozen["source_sha256"]:
                raise RuntimeError("Source changed during evaluation; stopping.")
            if args.run_protocol and hashlib.sha256(args.run_protocol.read_bytes()).hexdigest() != frozen["run_protocol_sha256"]:
                raise RuntimeError("Run protocol changed during evaluation; stopping.")
        await execute_sample(sample["urls"], folder, s, store, args.concurrency, check_source)
    finally:
        store.close()


if __name__ == "__main__":
    asyncio.run(main())
