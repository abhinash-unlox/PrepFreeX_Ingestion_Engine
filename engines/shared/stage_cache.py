from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class StageCache:
    """Stage-specific persistent caching system for LLM and compute operations.
    
    Guarantees stage-specific invalidation:
    - Modifying taxonomy only invalidates subtopic tagging (Stage 9).
    - Modifying metadata prompts only invalidates metadata enrichment (Stage 10).
    - PDF page extraction and question boundary detection are never rerun unnecessarily.
    """

    def __init__(self, cache_dir: Path | str = Path("data/cache")):
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _compute_key(
        self,
        stage: str,
        content_hash: str,
        model_id: str,
        prompt_version: str,
        schema_version: str = "1.0",
        extra_scope: str = "",
    ) -> str:
        components = [
            f"stage={stage}",
            f"content={content_hash}",
            f"model={model_id}",
            f"prompt_v={prompt_version}",
            f"schema_v={schema_version}",
            f"scope={extra_scope}",
        ]
        raw = "|".join(components)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(
        self,
        stage: str,
        content_hash: str,
        model_id: str,
        prompt_version: str,
        schema_version: str = "1.0",
        extra_scope: str = "",
    ) -> dict[str, Any] | None:
        key = self._compute_key(stage, content_hash, model_id, prompt_version, schema_version, extra_scope)
        path = self.cache_dir / f"{stage}_{key}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data.get("result")
            except Exception:
                pass
        return None

    def put(
        self,
        stage: str,
        content_hash: str,
        model_id: str,
        prompt_version: str,
        result: dict[str, Any] | list[Any],
        schema_version: str = "1.0",
        extra_scope: str = "",
    ) -> str:
        key = self._compute_key(stage, content_hash, model_id, prompt_version, schema_version, extra_scope)
        path = self.cache_dir / f"{stage}_{key}.json"
        payload = {
            "stage": stage,
            "content_hash": content_hash,
            "model_id": model_id,
            "prompt_version": prompt_version,
            "schema_version": schema_version,
            "extra_scope": extra_scope,
            "result": result,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return key

    def invalidate_stage(self, stage: str):
        """Invalidates all cached entries for a specific stage without touching other stages."""
        for p in self.cache_dir.glob(f"{stage}_*.json"):
            p.unlink()


_GLOBAL_STAGE_CACHE: StageCache | None = None


def get_stage_cache(cache_dir: Path | str | None = None) -> StageCache:
    global _GLOBAL_STAGE_CACHE
    if _GLOBAL_STAGE_CACHE is None or cache_dir is not None:
        _GLOBAL_STAGE_CACHE = StageCache(cache_dir=cache_dir or Path("data/cache"))
    return _GLOBAL_STAGE_CACHE

