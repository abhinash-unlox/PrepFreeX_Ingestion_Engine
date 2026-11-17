"""
PDF Question Extractor using PyMuPDF and Qwen
Extracts raw page text & diagram assets from PDF and parses structured JEE questions with token tracking.
"""

from __future__ import annotations
import os
import io
import json
import uuid
import itertools
from typing import Optional, Generator
import requests
import fitz  # PyMuPDF
from PIL import Image
import boto3
from engines.shared.config import settings

class PDFQuestionExtractor:
    def __init__(self, api_keys: Optional[list[str]] = None):
        raw_keys = api_keys or list(settings.groq_api_keys) or ([settings.groq_api_key] if settings.groq_api_key else [])
        self.api_keys = [k for k in raw_keys if k]
        self.key_cycle = itertools.cycle(self.api_keys) if self.api_keys else None
        self.model = "qwen/qwen3.8-27b"
        self._s3 = None

    @property
    def s3_client(self):
        if self._s3 is None and settings.minio_endpoint:
            try:
                self._s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.minio_endpoint,
                    aws_access_key_id=settings.minio_access_key,
                    aws_secret_access_key=settings.minio_secret_key,
                    region_name=settings.minio_region
                )
            except Exception:
                pass
        return self._s3

    def extract_from_pdf(self, pdf_path: str, max_pages: Optional[int] = None) -> Generator[dict, None, None]:
        """
        Iterates over pages in the PDF, extracts question candidates, and yields structured question dicts.
        """
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        pages_to_process = min(total_pages, max_pages) if max_pages else total_pages

        for page_num in range(pages_to_process):
            page = doc[page_num]
            text = page.get_text("text").strip()

            if len(text) < 50:
                continue

            # Check for embedded diagrams on this page
            image_list = page.get_images(full=True)
            diagram_s3_key = None
            if image_list and self.s3_client:
                diagram_s3_key = self._upload_page_diagram(doc, image_list[0], page_num, pdf_path)

            # Send page text to Qwen to segment and structure into individual questions
            parsed_questions, tokens = self._qwen_parse_page(text, page_num + 1, diagram_s3_key)

            for q in parsed_questions:
                q["page_number"] = page_num + 1
                q["tokens_used"] = tokens
                q["source_pdf"] = os.path.basename(pdf_path)
                yield q

    def _upload_page_diagram(self, doc, img_info, page_num: int, pdf_path: str) -> Optional[str]:
        try:
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            ext = base_image["ext"]

            # Filter out tiny icon images (less than 60x60)
            img = Image.open(io.BytesIO(image_bytes))
            if img.width < 60 or img.height < 60:
                return None

            s3_key = f"staged-diagrams/{uuid.uuid4().hex[:12]}_p{page_num}.{ext}"
            self.s3_client.put_object(
                Bucket=settings.minio_bucket,
                Key=s3_key,
                Body=image_bytes,
                ContentType=f"image/{ext}"
            )
            return s3_key
        except Exception:
            return None

    def _qwen_parse_page(self, page_text: str, page_num: int, diagram_s3_key: Optional[str]) -> tuple[list[dict], dict]:
        tokens_used = {"prompt": 0, "completion": 0, "total": 0}
        if not self.key_cycle:
            return [], tokens_used

        api_key = next(self.key_cycle)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        prompt = f"""You are a high-precision JEE Main OCR and mathematical transcription engine.
Extract and parse all complete examination questions from this page text.

PAGE TEXT:
\"\"\"
{page_text[:4000]}
\"\"\"

RULES:
1. Maintain exact mathematical expressions in LaTeX $...$ notation. Do NOT drop variables or numbers.
2. Ensure options are in a list of exactly 4 strings for Multiple Choice questions.
3. If an answer key or solution is given for a question on this page, extract correct_option ('A', 'B', 'C', or 'D').
4. If a figure or diagram is mentioned, set has_diagram = true.
5. Return JSON format with a list named 'questions':

{{
  "questions": [
    {{
      "question_type": "SINGLE_CHOICE",
      "question_text_latex": "Complete stem with formulas in $...$",
      "options": ["Option A text", "Option B text", "Option C text", "Option D text"],
      "correct_option": "A",
      "numerical_target": null,
      "solution_text_latex": "Explanation if present, else empty string",
      "has_diagram": false
    }}
  ]
}}"""

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        }

        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                usage = data.get("usage", {})
                tokens_used = {
                    "prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0)
                }
                parsed = json.loads(data["choices"][0]["message"]["content"])
                raw_qs = parsed.get("questions", [])

                for q in raw_qs:
                    if diagram_s3_key and q.get("has_diagram"):
                        q["diagram_s3_key"] = diagram_s3_key
                    else:
                        q["diagram_s3_key"] = None

                return raw_qs, tokens_used
        except Exception:
            pass

        return [], tokens_used
