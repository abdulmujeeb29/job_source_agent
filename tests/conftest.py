import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, azure_openai_base_url="https://example.azure.com/openai/v1/",
                    azure_openai_api_key="test-key", apify_api_token="test-token", data_dir=tmp_path)
