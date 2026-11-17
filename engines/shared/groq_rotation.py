from __future__ import annotations

import itertools
import os
import time
from typing import Any
import httpx

from engines.shared.config import settings

# Load keys from environment (.env) or fallback to predefined list
def _load_keys() -> list[str]:
    raw = os.getenv("GROQ_API_KEYS", "")
    if raw:
        return [k.strip() for k in raw.replace("\n", ",").split(",") if k.strip()]
    single = os.getenv("GROQ_API_KEY", "")
    return [single] if single else []


DEFAULT_KEYS = _load_keys() or [
    # Fallback placeholders if not in .env
    "gsk_xxxxxxxx1",
    "gsk_xxxxxxxx2",
    "gsk_xxxxxxxx3",
    "gsk_xxxxxxxx4",
]

_key_cycle = itertools.cycle(DEFAULT_KEYS)
current_key = next(_key_cycle) if DEFAULT_KEYS else ""


def set_api_keys(keys: list[str]):
    """Update active API keys list and reset round-robin cycle."""
    global DEFAULT_KEYS, _key_cycle, current_key
    DEFAULT_KEYS = [k.strip() for k in keys if k and k.strip()]
    if DEFAULT_KEYS:
        _key_cycle = itertools.cycle(DEFAULT_KEYS)
        current_key = next(_key_cycle)


def get_current_key() -> str:
    global current_key
    return current_key


def rotate_key() -> str:
    global current_key, _key_cycle
    current_key = next(_key_cycle)
    return current_key


def chat_with_rotation(
    messages: list[dict[str, Any]],
    model: str = settings.groq_model,  # Uses the project's configured model: qwen/qwen3.8-27b
    temperature: float = 0.0,
    response_format: dict[str, Any] | None = None,
    api_keys: list[str] | None = None,
    max_retries: int | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Execute chat completion with automatic round-robin key rotation on rate limits (HTTP 429).
    
    Compatible with Groq REST API (supports qwen/qwen3.8-27b and other Groq models).
    """
    global current_key, _key_cycle

    keys = api_keys or DEFAULT_KEYS
    if not keys:
        raise ValueError("No Groq API keys configured. Set GROQ_API_KEYS in .env or pass api_keys list.")

    retries = max_retries or (len(keys) * 4)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if response_format:
        payload["response_format"] = response_format

    last_error = None

    for attempt in range(retries):
        key = current_key
        key_hint = key[-4:] if len(key) >= 4 else "key"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(f"{settings.groq_base_url}/chat/completions", headers=headers, json=payload)

                # HTTP 429: Rate limit hit
                if resp.status_code == 429:
                    # Adaptive backoff: fast rotation between keys, then wait for 60s sliding window
                    cooldown = 1 if attempt < len(keys) else min(15, 5 * (attempt // len(keys) + 1))
                    print(f"Key limit hit (429) on ...{key_hint} -> switching to next key... (attempt {attempt+1}/{retries}, cooling {cooldown}s)")
                    rotate_key()
                    time.sleep(cooldown)
                    continue

                resp.raise_for_status()
                data = resp.json()
                return data

        except httpx.HTTPStatusError as e:
            last_error = e
            if e.response.status_code == 429:
                cooldown = 1 if attempt < len(keys) else min(15, 5 * (attempt // len(keys) + 1))
                print(f"Key limit hit (429) on ...{key_hint} -> switching to next key... (attempt {attempt+1}/{retries}, cooling {cooldown}s)")
                rotate_key()
                time.sleep(cooldown)
                continue
            print(f"HTTP error {e.response.status_code}: {e.response.text}")
            raise e

        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            if "429" in err_str or "rate limit" in err_str:
                cooldown = 1 if attempt < len(keys) else min(15, 5 * (attempt // len(keys) + 1))
                print(f"Key limit hit -> switching to next key... (attempt {attempt+1}/{retries}, cooling {cooldown}s)")
                rotate_key()
                time.sleep(cooldown)
                continue
            raise e

    raise RuntimeError(f"Saari keys limit pe pahunch gayi after {retries} attempts: {last_error}")

