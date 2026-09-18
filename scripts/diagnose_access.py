"""Minimal auth diagnostics; never print credentials."""
import argparse
import asyncio
import json
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

from app.config import Settings
from app.providers import ApifyProvider
from app.schemas import DiscoveryError


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--azure-only", action="store_true")
    args = parser.parse_args()
    s = Settings()
    key = s.azure_openai_api_key.get_secret_value()
    local = dotenv_values(".env")
    print(json.dumps({"azure_host": urlsplit(s.model_base_url).hostname,
                      "azure_path": urlsplit(s.model_base_url).path,
                      "key_matches_dotenv": key == local.get("AZURE_OPENAI_API_KEY"),
                      "base_url_matches_dotenv": s.azure_openai_base_url == local.get("AZURE_OPENAI_BASE_URL"),
                      "key_has_outer_whitespace": key != key.strip(),
                      "key_contains_newline": "\n" in key}))
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        for label, headers in [("bearer", {"Authorization": f"Bearer {key.strip()}"}),
                               ("api-key", {"api-key": key.strip()})]:
            r = await client.post(s.model_base_url + "responses", headers=headers,
                                  json={"model": s.azure_openai_model, "input": "Reply OK.", "max_output_tokens": 32, "store": False})
            result = {"auth_style": label, "status": r.status_code}
            if not r.is_success:
                try:
                    message = r.json().get("error", {}).get("message", "")
                    if isinstance(message, str):
                        for secret in (key, s.apify_api_token.get_secret_value()):
                            if secret:
                                message = message.replace(secret, "[REDACTED]")
                        result["azure_message"] = message[:500]
                except (ValueError, AttributeError):
                    pass
            print(json.dumps(result))
    if args.azure_only:
        return
    p = ApifyProvider(s)
    try:
        await p.request("GET", "users/me")
        print(json.dumps({"apify_auth": "ok"}))
        identity = await p.extract("https://www.linkedin.com/jobs/view/4427787182/")
        print(identity.model_dump_json(indent=2))
        print(json.dumps({"provider_usage": p.usage}))
    except DiscoveryError as e:
        print(json.dumps({"apify_error": e.code, "reason": e.reason, "usage": p.usage}))
    finally:
        await p.close()


asyncio.run(main())
