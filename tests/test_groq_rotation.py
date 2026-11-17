from __future__ import annotations

from unittest.mock import patch, MagicMock
import httpx
import pytest

from engines.shared.config import settings
from engines.ingestion.llm import GroqKeyRotator, GroqProvider
from engines.shared.groq_rotation import chat_with_rotation, set_api_keys, rotate_key, get_current_key


def test_key_rotator_cycle():
    """Verify round-robin rotation across multiple keys."""
    keys = ["key_1", "key_2", "key_3", "key_4"]
    rotator = GroqKeyRotator(keys)

    assert rotator.total_keys == 4
    assert rotator.current_key() == "key_1"
    assert rotator.rotate() == "key_2"
    assert rotator.rotate() == "key_3"
    assert rotator.rotate() == "key_4"
    # Cycles back to key_1
    assert rotator.rotate() == "key_1"


def test_groq_provider_default_model():
    """Verify GroqProvider preserves the configured model qwen/qwen3.8-27b."""
    provider = GroqProvider(api_keys=["mock_key_1", "mock_key_2"])
    assert provider.model_name == "qwen/qwen3.8-27b"
    assert provider.rotator.total_keys == 2


def test_chat_with_rotation_success_on_first_try():
    """Verify normal completion without rate limit."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "Hello!"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    }

    set_api_keys(["mock_key_1", "mock_key_2", "mock_key_3", "mock_key_4"])

    with patch("httpx.Client.post", return_value=mock_resp):
        res = chat_with_rotation([{"role": "user", "content": "hi"}], model=settings.groq_model)
        assert res["choices"][0]["message"]["content"] == "Hello!"


def test_chat_with_rotation_failover_on_429():
    """Verify automatic key rotation when HTTP 429 RateLimit occurs."""
    keys = ["rate_limited_key_1", "working_key_2"]
    set_api_keys(keys)

    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.text = "Rate limit exceeded"

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {
        "choices": [{"message": {"content": "Success after rotation"}}],
        "usage": {"total_tokens": 20}
    }

    # First call returns 429, second call returns 200
    with patch("httpx.Client.post", side_effect=[resp_429, resp_200]):
        res = chat_with_rotation(
            [{"role": "user", "content": "test"}],
            model=settings.groq_model,
            api_keys=keys,
            max_retries=2
        )
        assert res["choices"][0]["message"]["content"] == "Success after rotation"

