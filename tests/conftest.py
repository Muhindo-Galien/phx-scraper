import pytest

from config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        max_retries=2,
        backoff_base=0.001,
        backoff_max=0.002,
        batch_size=20,
        max_concurrency=20,
        max_pages=50,
    )
