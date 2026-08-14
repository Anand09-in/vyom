import pytest
from pydantic import ValidationError
from vyom.config import Settings


def test_defaults():
    s = Settings()
    assert s.provider == "local"
    assert s.embedding_dim == 512
    assert s.top_k == 20


def test_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        Settings(provider="openai")


def test_sources_property():
    s = Settings(enabled_sources="bse,rbi")
    assert s.sources == ["bse", "rbi"]