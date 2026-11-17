from pathlib import Path
from engines.shared.stage_cache import StageCache


def test_stage_cache_invalidation_isolation(tmp_path: Path):
    cache = StageCache(cache_dir=tmp_path)

    # Put Stage 5 (Question Extraction)
    cache.put(
        stage="stage5_questions",
        content_hash="page_sha_123",
        model_id="qwen3.8-27b",
        prompt_version="q_v1",
        result={"stem": "What is momentum?"},
    )

    # Put Stage 9 (Taxonomy Tagging)
    cache.put(
        stage="stage9_tagging",
        content_hash="q_hash_abc",
        model_id="qwen3.8-27b",
        prompt_version="tag_v1",
        result={"primary": "PHY.U07.T01.S01"},
        extra_scope="tax_v1",
    )

    # Verify both present
    assert cache.get("stage5_questions", "page_sha_123", "qwen3.8-27b", "q_v1") is not None
    assert cache.get("stage9_tagging", "q_hash_abc", "qwen3.8-27b", "tag_v1", extra_scope="tax_v1") is not None

    # Invalidate ONLY Stage 9 (e.g. taxonomy updated)
    cache.invalidate_stage("stage9_tagging")

    # Stage 9 is invalidated, Stage 5 remains untouched
    assert cache.get("stage9_tagging", "q_hash_abc", "qwen3.8-27b", "tag_v1", extra_scope="tax_v1") is None
    assert cache.get("stage5_questions", "page_sha_123", "qwen3.8-27b", "q_v1") == {"stem": "What is momentum?"}

