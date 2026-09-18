from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings,
                                   dotenv_settings, file_secret_settings):
        # Local .env is the explicitly selected project configuration. Docker has
        # no .env in its image and therefore uses injected environment variables.
        return init_settings, dotenv_settings, env_settings, file_secret_settings

    azure_openai_base_url: str = ""
    azure_openai_model: str = "gpt-6-astra"
    azure_openai_api_key: SecretStr = SecretStr("")
    apify_api_token: SecretStr = SecretStr("")
    apify_job_actor: str = "piotrv1001/linkedin-job-details-scraper"
    apify_company_actor: str = "harvestapi/linkedin-company"
    apify_company_fallback_actor: str = "piotrv1001/linkedin-company-scraper"
    data_dir: Path = Path("data")
    chromium_executable: str = ""
    chromium_no_sandbox: bool = False
    agent_browser_binary: str = "agent-browser"
    run_timeout_seconds: int = Field(default=300, ge=10, le=900)
    max_actions: int = Field(default=20, ge=1, le=50)
    max_model_calls: int = Field(default=24, ge=1, le=60)
    max_queue_size: int = Field(default=10, ge=1, le=100)
    requests_per_hour: int = Field(default=30, ge=1, le=1000)

    def missing(self) -> list[str]:
        return [name.upper() for name in (
            "azure_openai_base_url", "azure_openai_api_key", "apify_api_token"
        ) if not (getattr(self, name).get_secret_value() if isinstance(
            getattr(self, name), SecretStr
        ) else getattr(self, name))]

    @property
    def model_base_url(self) -> str:
        return self.azure_openai_base_url.rstrip("/").removesuffix("/responses") + "/"
