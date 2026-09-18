from app.config import Settings


def test_project_dotenv_overrides_stale_shell_credential(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("AZURE_OPENAI_API_KEY=new-local-key\nAZURE_OPENAI_BASE_URL=https://new.example/openai/v1/\n")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "stale-shell-key")
    settings = Settings(_env_file=path)
    assert settings.azure_openai_api_key.get_secret_value() == "new-local-key"


def test_production_uses_injected_environment_without_dotenv(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "injected-production-key")
    settings = Settings(_env_file=None)
    assert settings.azure_openai_api_key.get_secret_value() == "injected-production-key"
