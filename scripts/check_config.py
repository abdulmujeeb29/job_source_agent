"""Report presence/variable names only, never credential contents."""
import json

from dotenv import dotenv_values

from app.config import Settings

s = Settings()
print(json.dumps({
    "env_variable_names": list(dotenv_values(".env")),
    "missing_required": s.missing(),
    "deployment": s.azure_openai_model,
    "endpoint_configured": bool(s.azure_openai_base_url),
}, indent=2))
