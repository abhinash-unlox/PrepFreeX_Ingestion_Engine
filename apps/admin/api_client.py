from __future__ import annotations

import os
import time
from typing import Any
import requests


class AdminAPIClient:
    """Pure HTTP REST client for PrepFreeX Core API.
    
    STRICT RULE: This module communicates ONLY over HTTP REST and NEVER connects
    directly to PostgreSQL. No database drivers (psycopg, sqlite, etc.) are imported.
    """

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or os.getenv("API_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
        self.last_diagnostic: dict[str, Any] = {
            "endpoint": "None",
            "response_time_ms": 0.0,
            "status_code": 0,
            "record_count": 0,
            "error": None,
        }

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None
    ) -> tuple[Any, float, int, str | None]:
        url = f"{self.base_url}{path}"
        t0 = time.time()
        try:
            resp = requests.request(method, url, params=params, json=json_data, timeout=12.0)
            elapsed_ms = (time.time() - t0) * 1000.0
            status_code = resp.status_code

            is_ok = getattr(resp, "ok", 200 <= resp.status_code < 300)
            if is_ok:
                # Check content type for binary/image
                content_type = resp.headers.get("content-type", "")
                if "image" in content_type:
                    return resp.content, elapsed_ms, status_code, None

                data = resp.json()
                count = len(data.get("items", [])) if isinstance(data, dict) and "items" in data else 1
                self.last_diagnostic = {
                    "endpoint": path,
                    "response_time_ms": round(elapsed_ms, 2),
                    "status_code": status_code,
                    "record_count": count,
                    "error": None,
                }
                return data, elapsed_ms, status_code, None
            else:
                err = f"HTTP {status_code}: {resp.text}"
                self.last_diagnostic = {
                    "endpoint": path,
                    "response_time_ms": round(elapsed_ms, 2),
                    "status_code": status_code,
                    "record_count": 0,
                    "error": err,
                }
                return None, elapsed_ms, status_code, err
        except requests.exceptions.RequestException as e:
            elapsed_ms = (time.time() - t0) * 1000.0
            err_msg = f"Connection error: {e}"
            self.last_diagnostic = {
                "endpoint": path,
                "response_time_ms": round(elapsed_ms, 2),
                "status_code": 0,
                "record_count": 0,
                "error": err_msg,
            }
            return None, elapsed_ms, 0, err_msg

    def get_health(self) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", "/api/v1/health")

    def get_summary(self) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", "/api/v1/admin/summary")

    def get_questions(self, params: dict[str, Any]) -> tuple[dict[str, Any] | None, float, int, str | None]:
        clean_params = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", "/api/v1/admin/questions", params=clean_params)

    def get_question_detail(self, public_id: str) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", f"/api/v1/admin/questions/{public_id}")

    def get_taxonomy(self) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", "/api/v1/admin/taxonomy")

    # =========================================================================
    # TAXONOMY REVIEW AUDIT WORKFLOW METHODS
    # =========================================================================

    def get_taxonomy_review_summary(self) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", "/api/v1/admin/taxonomy-review/summary")

    def get_taxonomy_tree(self) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", "/api/v1/admin/taxonomy-review/taxonomy-tree")

    def get_taxonomy_review_questions(self, params: dict[str, Any]) -> tuple[dict[str, Any] | None, float, int, str | None]:
        clean_params = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", "/api/v1/admin/taxonomy-review/questions", params=clean_params)

    def get_taxonomy_review_question_detail(self, public_id: str) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", f"/api/v1/admin/taxonomy-review/question/{public_id}")

    def get_source_page_preview(self, public_id: str) -> tuple[bytes | None, float, int, str | None]:
        return self._request("GET", f"/api/v1/admin/taxonomy-review/source-page/{public_id}")

    def get_next_unreviewed_question(
        self,
        subject: str | None = None,
        unit_code: str | None = None
    ) -> tuple[dict[str, Any] | None, float, int, str | None]:
        params = {}
        if subject and subject.lower() != "all":
            params["subject"] = subject
        if unit_code and unit_code.lower() != "all":
            params["unit_code"] = unit_code
        return self._request("GET", "/api/v1/admin/taxonomy-review/next-unreviewed", params=params)

    def submit_taxonomy_decision(
        self,
        public_id: str,
        reviewer_decision: str,
        proposed_subtopic_id: int | None = None,
        proposal_details: str | None = None,
        reviewer_notes: str | None = None,
        reviewer_id: str = "internal_reviewer",
        apply_immediately: bool = True
    ) -> tuple[dict[str, Any] | None, float, int, str | None]:
        payload = {
            "public_id": public_id,
            "reviewer_decision": reviewer_decision,
            "proposed_subtopic_id": proposed_subtopic_id,
            "proposal_details": proposal_details,
            "reviewer_notes": reviewer_notes,
            "reviewer_id": reviewer_id,
            "apply_immediately": apply_immediately
        }
        return self._request("POST", "/api/v1/admin/taxonomy-review/decision", json_data=payload)

    def apply_taxonomy_correction(
        self,
        audit_id: int,
        reviewer_id: str = "internal_reviewer"
    ) -> tuple[dict[str, Any] | None, float, int, str | None]:
        payload = {
            "audit_id": audit_id,
            "reviewer_id": reviewer_id
        }
        return self._request("POST", "/api/v1/admin/taxonomy-review/apply-correction", json_data=payload)

    def get_taxonomy_suggestion(self, public_id: str) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", f"/api/v1/admin/taxonomy-review/suggest/{public_id}")

    # ==========================================
    # Question Variation Playground Endpoints
    # ==========================================
    def get_variation_filters(self) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", "/api/v1/admin/question-variation/filters")

    def list_variation_questions(
        self,
        subject: str | None = None,
        unit_code: str | None = None,
        topic_code: str | None = None,
        search: str | None = None,
        limit: int = 25,
        offset: int = 0
    ) -> tuple[dict[str, Any] | None, float, int, str | None]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if subject and subject.lower() != "all":
            params["subject"] = subject
        if unit_code and unit_code.lower() != "all":
            params["unit_code"] = unit_code
        if topic_code and topic_code.lower() != "all":
            params["topic_code"] = topic_code
        if search and search.strip():
            params["search"] = search.strip()
        return self._request("GET", "/api/v1/admin/question-variation/questions", params=params)

    def get_variation_question_detail(self, public_id: str) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", f"/api/v1/admin/question-variation/questions/{public_id}")

    def generate_question_variant(
        self,
        public_id: str,
        custom_guidance: str | None = None,
        run_llm_review: bool = True
    ) -> tuple[dict[str, Any] | None, float, int, str | None]:
        payload = {
            "public_id": public_id,
            "custom_guidance": custom_guidance,
            "run_llm_review": run_llm_review
        }
        # Generation with Groq may take ~10-25 seconds; request has custom timeout if needed
        url = f"{self.base_url}/api/v1/admin/question-variation/generate"
        t0 = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=60.0)
            elapsed_ms = (time.time() - t0) * 1000.0
            if resp.ok:
                return resp.json(), elapsed_ms, resp.status_code, None
            return None, elapsed_ms, resp.status_code, f"HTTP {resp.status_code}: {resp.text}"
        except Exception as e:
            return None, (time.time() - t0) * 1000.0, 0, str(e)

    def list_variation_experiments(self, limit: int = 20, offset: int = 0) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", "/api/v1/admin/question-variation/experiments", params={"limit": limit, "offset": offset})

    def get_variation_experiment_detail(self, experiment_id: int) -> tuple[dict[str, Any] | None, float, int, str | None]:
        return self._request("GET", f"/api/v1/admin/question-variation/experiments/{experiment_id}")

    def review_variation_experiment(
        self,
        experiment_id: int,
        human_verdict: str,
        reviewer_feedback: str | None = None
    ) -> tuple[dict[str, Any] | None, float, int, str | None]:
        payload = {
            "human_verdict": human_verdict,
            "reviewer_feedback": reviewer_feedback
        }
        return self._request("POST", f"/api/v1/admin/question-variation/experiments/{experiment_id}/review", json_data=payload)

