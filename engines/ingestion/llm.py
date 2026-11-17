from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Type

from pydantic import BaseModel, ValidationError

from .config import settings

CACHE_DIR = Path("data/cache/llm_cache")


class LLMError(Exception):
    """Base exception for LLM errors."""
    pass


class LLMQuotaExceeded(LLMError):
    """Raised when rate limit or request budget is exceeded."""
    pass


class LLMValidationError(LLMError):
    """Raised when LLM output repeatedly fails validation."""
    pass


class RateLimiter:
    """Sliding-window rate limiter for LLM requests."""

    def __init__(self, requests_per_minute: int = 15):
        self.rpm = requests_per_minute
        self.timestamps: list[float] = []

    def acquire(self):
        if self.rpm <= 0:
            return
        now = time.time()
        # Drop timestamps older than 60 seconds
        self.timestamps = [t for t in self.timestamps if now - t < 60.0]
        if len(self.timestamps) >= self.rpm:
            sleep_time = 60.0 - (now - self.timestamps[0]) + 0.1
            if sleep_time > 0:
                time.sleep(sleep_time)
            now = time.time()
            self.timestamps = [t for t in self.timestamps if now - t < 60.0]
        self.timestamps.append(now)


class BaseLLMProvider:
    def extract_json(
        self,
        images: list[Path | bytes],
        prompt: str,
        json_schema: dict[str, Any] | Type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class FakeLLM(BaseLLMProvider):
    """In-memory or fixture-backed fake LLM for testing without API keys."""

    def __init__(self, responses: dict[str, Any] | Callable[[str], dict[str, Any]] | None = None):
        self.responses = responses or {}
        self.calls: list[dict[str, Any]] = []

    def extract_json(
        self,
        images: list[Path | bytes],
        prompt: str,
        json_schema: dict[str, Any] | Type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, "image_count": len(images)})
        if callable(self.responses):
            return self.responses(prompt)
        # Match prompt substrings or exact keys
        for key, res in self.responses.items():
            if key in prompt or prompt in key:
                if isinstance(res, (dict, list)):
                    return res
                if isinstance(res, str):
                    return json.loads(res)
        # Default empty dict
        return {}


class GeminiProvider(BaseLLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        rpm: int = 15,
        max_requests: int = 100,
    ):
        self.api_key = api_key or settings.gemini_api_key
        self.model_name = model_name or settings.gemini_model or "gemini-2.5-flash"
        self.rate_limiter = RateLimiter(rpm)
        self.max_requests = max_requests
        self.requests_made = 0
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise LLMError("GEMINI_API_KEY is not set. Add it to .env or use FakeLLM / --dry-run.")
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                raise LLMError(f"Failed to initialize Google Gen AI client: {e}")
        return self._client

    def _call_raw(self, image_bytes_list: list[bytes], prompt: str) -> str:
        if self.requests_made >= self.max_requests:
            raise LLMQuotaExceeded(f"Per-run LLM budget of {self.max_requests} requests reached.")

        client = self._get_client()
        from google.genai import types

        parts: list[Any] = []
        for b in image_bytes_list:
            parts.append(types.Part.from_bytes(data=b, mime_type="image/png"))
        parts.append(prompt)

        backoff = 2.0
        last_exc = None
        for attempt in range(4):
            try:
                self.rate_limiter.acquire()
                self.requests_made += 1
                resp = client.models.generate_content(
                    model=self.model_name,
                    contents=parts,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                    ),
                )
                return resp.text or "{}"
            except Exception as e:
                last_exc = e
                err_str = str(e).lower()
                if "429" in err_str or "quota" in err_str or "500" in err_str or "503" in err_str:
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue
                raise LLMError(f"Gemini API error: {e}") from e
        raise LLMError(f"Gemini call failed after retries: {last_exc}") from last_exc

    def extract_json(
        self,
        images: list[Path | bytes],
        prompt: str,
        json_schema: dict[str, Any] | Type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        return _cached_extract_json(self, self.model_name, images, prompt, json_schema)


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model_name: str | None = None,
        rpm: int = 30,
        max_requests: int = 100,
    ):
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model_name = model_name or settings.llm_model or "gpt-4o-mini"
        self.rate_limiter = RateLimiter(rpm)
        self.max_requests = max_requests
        self.requests_made = 0

    def _call_raw(self, image_bytes_list: list[bytes], prompt: str) -> str:
        if self.requests_made >= self.max_requests:
            raise LLMQuotaExceeded(f"Per-run LLM budget of {self.max_requests} requests reached.")

        import httpx

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        content_items: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for b in image_bytes_list:
            b64 = base64.b64encode(b).decode("utf-8")
            content_items.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})

        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": content_items}],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        backoff = 2.0
        last_exc = None
        for attempt in range(4):
            try:
                self.rate_limiter.acquire()
                self.requests_made += 1
                with httpx.Client(timeout=90.0) as client:
                    resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    return data["choices"][0]["message"]["content"]
            except Exception as e:
                last_exc = e
                err_str = str(e).lower()
                if "429" in err_str or "500" in err_str or "503" in err_str:
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue
                raise LLMError(f"OpenAI compatible API error: {e}") from e
        raise LLMError(f"OpenAI compatible call failed after retries: {last_exc}") from last_exc

    def extract_json(
        self,
        images: list[Path | bytes],
        prompt: str,
        json_schema: dict[str, Any] | Type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        return _cached_extract_json(self, self.model_name, images, prompt, json_schema)


def _load_image_bytes(item: Path | bytes) -> bytes:
    if isinstance(item, bytes):
        return item
    if isinstance(item, (str, Path)):
        return Path(item).read_bytes()
    raise ValueError(f"Unsupported image type: {type(item)}")


def _compute_cache_key(prompt: str, image_bytes_list: list[bytes], model_name: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(prompt.encode("utf-8"))
    for b in image_bytes_list:
        hasher.update(b)
    hasher.update(model_name.encode("utf-8"))
    return hasher.hexdigest()


def _cached_extract_json(
    provider: Any,
    model_name: str,
    images: list[Path | bytes],
    prompt: str,
    json_schema: dict[str, Any] | Type[BaseModel] | None = None,
) -> dict[str, Any]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    img_bytes = [_load_image_bytes(img) for img in images]
    cache_key = _compute_cache_key(prompt, img_bytes, model_name)
    cache_file = CACHE_DIR / f"{cache_key}.json"

    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Call provider with validation & single retry
    current_prompt = prompt
    for attempt in range(2):
        raw_text = provider._call_raw(img_bytes, current_prompt)
        try:
            parsed = _clean_and_parse_json(raw_text)
            if json_schema is not None:
                parsed = _validate_schema(parsed, json_schema)
            # Store in disk cache
            cache_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
            return parsed
        except (json.JSONDecodeError, ValidationError, ValueError) as err:
            if attempt == 0:
                current_prompt = (
                    f"{prompt}\n\n"
                    f"CRITICAL: The previous output failed validation: {err}. "
                    "Output ONLY valid JSON matching the exact schema."
                )
            else:
                raise LLMValidationError(f"Invalid LLM output after retry: {err}")


def _clean_and_parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    return json.loads(text)


def _validate_schema(data: Any, schema: dict[str, Any] | Type[BaseModel]) -> Any:
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        obj = schema.model_validate(data)
        return obj.model_dump()
    if isinstance(schema, dict):
        import jsonschema
        jsonschema.validate(instance=data, schema=schema)
    return data


_GLOBAL_PROVIDER: BaseLLMProvider | None = None



class GroqQuotaExceeded(LLMQuotaExceeded):
    """Raised when Groq daily or minute quota is exhausted."""
    pass


class GroqLedger:
    """Persistent daily usage ledger stored at data/cache/groq_ledger.json."""

    def __init__(self, ledger_path: Path = Path("data/cache/groq_ledger.json")):
        self.path = ledger_path

    def _today(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def read(self) -> dict[str, Any]:
        from datetime import datetime, timezone
        today = self._today()
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if data.get("date") == today:
                    return data
            except Exception:
                pass
        # Reset for new day
        data = {
            "date": today,
            "total_requests": 0,
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        self.write(data)
        return data

    def write(self, data: dict[str, Any]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def can_spend(self, estimated_tokens: int, max_requests: int = 850, max_tokens: int = 150000) -> tuple[bool, str]:
        usage = self.read()
        if usage["total_requests"] + 1 > max_requests:
            return False, f"Daily request limit reached ({usage['total_requests']}/{max_requests})"
        if usage["total_tokens"] + estimated_tokens > max_tokens:
            return False, f"Daily token limit reached ({usage['total_tokens']} + {estimated_tokens} > {max_tokens})"
        return True, ""

    def record(self, prompt_tokens: int, completion_tokens: int, total_tokens: int):
        from datetime import datetime, timezone
        usage = self.read()
        usage["total_requests"] += 1
        usage["prompt_tokens"] += prompt_tokens
        usage["completion_tokens"] += completion_tokens
        usage["total_tokens"] += total_tokens
        usage["last_updated"] = datetime.now(timezone.utc).isoformat()
        self.write(usage)


class GroqRateLimiter:
    """Sliding-window limiter enforcing requests/min (25) and tokens/min (7000)."""

    def __init__(self, rpm: int = 25, tpm: int = 7000):
        self.rpm = rpm
        self.tpm = tpm
        self.window: list[tuple[float, int]] = []  # (timestamp, token_count)

    def acquire(self, estimated_tokens: int = 500):
        now = time.time()
        # Evict older than 60s
        self.window = [(t, tok) for t, tok in self.window if now - t < 60.0]

        # Check RPM
        while len(self.window) >= self.rpm:
            sleep_for = 60.0 - (now - self.window[0][0]) + 0.1
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.time()
            self.window = [(t, tok) for t, tok in self.window if now - t < 60.0]

        # Check TPM
        while sum(tok for _, tok in self.window) + estimated_tokens > self.tpm and self.window:
            sleep_for = 60.0 - (now - self.window[0][0]) + 0.1
            if sleep_for > 0:
                time.sleep(sleep_for)
            now = time.time()
            self.window = [(t, tok) for t, tok in self.window if now - t < 60.0]

        self.window.append((now, estimated_tokens))


class GroqKeyRotator:
    """Round-robin rotator for multiple Groq API keys with automatic failover."""

    def __init__(self, keys: list[str] | tuple[str, ...]):
        self.keys = [k.strip() for k in keys if k and k.strip()]
        self._index = 0

    @property
    def total_keys(self) -> int:
        return len(self.keys)

    def current_key(self) -> str:
        if not self.keys:
            return ""
        return self.keys[self._index % len(self.keys)]

    def rotate(self) -> str:
        if not self.keys:
            return ""
        self._index = (self._index + 1) % len(self.keys)
        return self.current_key()


class GroqProvider(BaseLLMProvider):
    """LLM provider for Groq with multi-key round-robin rotation and quota safeguards."""

    def __init__(
        self,
        api_keys: list[str] | tuple[str, ...] | str | None = None,
        model_name: str | None = None,
        base_url: str | None = None,
        rpm: int = 25,
        tpm: int = 7000,
        max_daily_requests: int = 850,
        max_daily_tokens: int = 150000,
    ):
        if isinstance(api_keys, str):
            raw_keys = [k.strip() for k in api_keys.replace("\n", ",").split(",") if k.strip()]
        elif isinstance(api_keys, (list, tuple)):
            raw_keys = list(api_keys)
        else:
            raw_keys = list(settings.groq_api_keys) if settings.groq_api_keys else ([settings.groq_api_key] if settings.groq_api_key else [])

        self.rotator = GroqKeyRotator(raw_keys)
        self.model_name = model_name or settings.groq_model or "qwen/qwen3.8-27b"
        self.base_url = (base_url or settings.groq_base_url).rstrip("/")
        total_keys = max(1, self.rotator.total_keys)
        self.rate_limiter = GroqRateLimiter(rpm=rpm * total_keys, tpm=tpm * total_keys)
        self.ledger = GroqLedger()
        self.max_daily_requests = max_daily_requests
        self.max_daily_tokens = max_daily_tokens

    @property
    def api_key(self) -> str:
        return self.rotator.current_key()

    def _estimate_tokens(self, image_bytes_list: list[bytes], prompt: str) -> int:
        img_tokens = len(image_bytes_list) * 2048
        text_tokens = (len(prompt) // 4) + 100
        return img_tokens + text_tokens

    def _call_raw(self, image_bytes_list: list[bytes], prompt: str) -> str:
        if self.rotator.total_keys == 0:
            raise LLMError("GROQ_API_KEY (or GROQ_API_KEYS) is not set. Add your key(s) to .env or use FakeLLM / --dry-run.")

        estimated = self._estimate_tokens(image_bytes_list, prompt)
        total_keys = max(1, self.rotator.total_keys)
        can_spend, reason = self.ledger.can_spend(estimated, self.max_daily_requests * total_keys, self.max_daily_tokens * total_keys)
        if not can_spend:
            raise GroqQuotaExceeded(f"Groq daily quota limit reached: {reason}")

        import httpx

        # Build message content
        if image_bytes_list:
            content_items: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            for b in image_bytes_list:
                b64 = base64.b64encode(b).decode("utf-8")
                content_items.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
            messages = [{"role": "user", "content": content_items}]
        else:
            messages = [{"role": "user", "content": prompt}]

        payload = {
            "model": self.model_name,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

        # Retry across all rotated keys
        max_attempts = max(4, self.rotator.total_keys * 2)
        last_exc = None

        for attempt in range(max_attempts):
            cur_key = self.rotator.current_key()
            headers = {
                "Authorization": f"Bearer {cur_key}",
                "Content-Type": "application/json",
            }
            try:
                self.rate_limiter.acquire(estimated)
                with httpx.Client(timeout=90.0) as client:
                    resp = client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)

                    if resp.status_code == 429:
                        key_hint = cur_key[-4:] if len(cur_key) >= 4 else "key"
                        print(f"Key limit hit (429) on ...{key_hint} -> rotating to next key (attempt {attempt+1}/{max_attempts})...")
                        self.rotator.rotate()
                        time.sleep(1.0)
                        continue

                    resp.raise_for_status()
                    data = resp.json()

                    # Record usage in ledger
                    usage = data.get("usage", {})
                    p_tok = usage.get("prompt_tokens", estimated)
                    c_tok = usage.get("completion_tokens", 50)
                    t_tok = usage.get("total_tokens", p_tok + c_tok)
                    self.ledger.record(p_tok, c_tok, t_tok)

                    return data["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                last_exc = e
                if e.response.status_code == 429:
                    self.rotator.rotate()
                    time.sleep(1.0)
                    continue
                raise LLMError(f"Groq API error ({e.response.status_code}): {e.response.text}") from e
            except Exception as e:
                last_exc = e
                err_str = str(e).lower()
                if "429" in err_str or "rate limit" in err_str:
                    self.rotator.rotate()
                    time.sleep(1.0)
                    continue
                if "500" in err_str or "503" in err_str:
                    time.sleep(2.0)
                    continue
                raise LLMError(f"Groq API error: {e}") from e

        raise LLMError(f"All Groq API keys rate-limited or failed after {max_attempts} attempts: {last_exc}") from last_exc

    def extract_json(
        self,
        images: list[Path | bytes],
        prompt: str,
        json_schema: dict[str, Any] | Type[BaseModel] | None = None,
    ) -> dict[str, Any]:
        return _cached_extract_json(self, self.model_name, images, prompt, json_schema)


def get_llm_provider(provider_type: str | None = None) -> BaseLLMProvider:
    global _GLOBAL_PROVIDER
    if _GLOBAL_PROVIDER is not None:
        return _GLOBAL_PROVIDER

    p_type = (provider_type or settings.llm_provider or "groq").lower()
    if p_type == "fake":
        _GLOBAL_PROVIDER = FakeLLM()
    elif p_type == "groq":
        _GLOBAL_PROVIDER = GroqProvider(
            api_keys=settings.groq_api_keys or settings.groq_api_key,
            model_name=settings.groq_model,
            base_url=settings.groq_base_url,
            rpm=settings.llm_requests_per_minute,
            tpm=settings.max_llm_tokens_per_minute,
            max_daily_requests=settings.max_llm_requests_per_day,
            max_daily_tokens=settings.max_llm_tokens_per_day,
        )
    elif p_type == "openai_compatible":
        _GLOBAL_PROVIDER = OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model_name=settings.llm_model,
            rpm=settings.llm_requests_per_minute,
            max_requests=settings.max_llm_requests,
        )
    else:
        _GLOBAL_PROVIDER = GeminiProvider(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            rpm=settings.llm_requests_per_minute,
            max_requests=settings.max_llm_requests,
        )
    return _GLOBAL_PROVIDER


def set_llm_provider(provider: BaseLLMProvider | None):
    global _GLOBAL_PROVIDER
    _GLOBAL_PROVIDER = provider

