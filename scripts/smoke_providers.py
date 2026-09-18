import argparse
import asyncio
import json

from app.config import Settings
from app.providers import ApifyProvider, Astra
from app.schemas import DiscoveryError


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-url")
    args = parser.parse_args()
    settings = Settings()
    if settings.missing():
        raise SystemExit("Missing variables: " + ", ".join(settings.missing()))
    model, provider = Astra(settings), ApifyProvider(settings)
    try:
        decision = await model.decide({"task": "Configuration smoke test. No browser page is available. Return stop with page_kind other and no listings."})
        print(json.dumps({"azure": "ok", "action": decision.action, "usage": model.usage}))
        await provider.request("GET", "users/me")
        print(json.dumps({"apify_auth": "ok"}))
        if args.job_url:
            company = await provider.extract(args.job_url)
            print(company.model_dump_json(indent=2))
            print(json.dumps({"provider_usage": provider.usage}))
    except DiscoveryError as exc:
        print(json.dumps({"error": exc.code, "reason": exc.reason}))
        raise SystemExit(1) from None
    finally:
        await model.close()
        await provider.close()


asyncio.run(main())
