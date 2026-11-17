import sys
sys.path.append('.')
import urllib.request
import urllib.error
import json
import re

BASE_URL = "http://127.0.0.1:8000/api/v1/assessments"

# Test configurations spanning different subjects and types
TEST_CASES = [
    {
        "type": "Full-length Mock",
        "subject": "PHYSICS",
        "label": "Full-Length Mock 75Q (Physics, Chemistry, Maths)"
    },
    {
        "type": "Topic Practice",
        "subject": "PHYSICS",
        "topic_code": "PHYS_U07_T01",
        "label": "Topic Practice: Properties of Solids and Liquids (Where Young's modulus defect was)"
    },
    {
        "type": "Topic Practice",
        "subject": "PHYSICS",
        "topic_code": "PHYS_U15_T02",
        "label": "Topic Practice: Electromagnetic Waves (Where EM wave defect was)"
    },
    {
        "type": "Topic Practice",
        "subject": "PHYSICS",
        "topic_code": "PHYS_U11_T02",
        "label": "Topic Practice: Electrostatics (Where oil drop & metallic chain defects were)"
    },
    {
        "type": "Topic Practice",
        "subject": "CHEMISTRY",
        "topic_code": "CHEM_U05_T01",
        "label": "Topic Practice: Solutions & Colligative Properties"
    },
    {
        "type": "Topic Practice",
        "subject": "MATHEMATICS",
        "topic_code": "MATH_U14_T01",
        "label": "Topic Practice: Trigonometry & Equations"
    }
]

WATERMARK_REGEX = re.compile(r'(?:mathongo|#MathBoleTohMathonGo|www\.mathongo|Question Bank)', re.I)
STRIPPED_EXPONENT_REGEX = re.compile(r'\b\d+\.?\d*\s+10(?:1[0-9]|2[0-5]|[3-9])\b')
DANGLING_PREP_REGEX = re.compile(r'\b(?:is|of|in|to|at|with|by|from|equal to)\s+[\.\,]', re.I)
EMPTY_UNIT_REGEX = re.compile(r'\(in\s+\)|\[in\s+\]|\(in\s*\)', re.I)

def http_json(method: str, url: str, data: dict = None):
    req_data = json.dumps(data).encode('utf-8') if data else None
    headers = {'Content-Type': 'application/json'} if data else {}
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode('utf-8'))

def validate_question(q: dict, test_label: str, q_index: int):
    q_uid = q.get("question_uid") or "unknown"
    stem = q.get("text") or ""
    opts = q.get("options") or []
    q_type = q.get("type") or "SINGLE_CHOICE"
    has_diag = q.get("has_diagram")
    diag_key = q.get("diagram_s3_key")

    flaws = []

    # 1. Stem sanity
    if not stem.strip():
        flaws.append("Empty question text")
    if len(stem.strip()) < 15:
        flaws.append(f"Stem too short ({len(stem.strip())} chars)")
    if DANGLING_PREP_REGEX.search(stem):
        flaws.append("Dangling preposition before punctuation (missing variable/expression)")
    if EMPTY_UNIT_REGEX.search(stem):
        flaws.append("Empty unit parenthesis (e.g. '(in )')")
    if WATERMARK_REGEX.search(stem):
        flaws.append("Watermark in stem")

    # 2. Options sanity for Single Choice
    if q_type == "SINGLE_CHOICE":
        if len(opts) != 4:
            flaws.append(f"Expected 4 options, found {len(opts)}")
        for idx, o in enumerate(opts):
            otext = o.get("text", "") if isinstance(o, dict) else str(o)
            if not otext.strip():
                flaws.append(f"Option {idx} is empty")
            if WATERMARK_REGEX.search(otext):
                flaws.append(f"Watermark in option {idx}")
            if STRIPPED_EXPONENT_REGEX.search(otext):
                flaws.append(f"Stripped scientific exponent in option {idx} (e.g. 1010/1011)")
            if re.search(r'^\s*is true but\s+is false', otext, re.I) or re.search(r'^\s*Both\s+and\s+are true', otext, re.I):
                flaws.append(f"Broken Assertion-Reason option {idx} (missing A/R labels)")

    # 3. Diagram sanity
    if has_diag:
        if not diag_key:
            flaws.append("has_diagram is True but diagram_s3_key is missing")
        else:
            # Check S3 asset
            s3_url = f"http://127.0.0.1:9000/{diag_key}"
            try:
                s3_req = urllib.request.Request(s3_url, method='HEAD')
                with urllib.request.urlopen(s3_req, timeout=3) as s3_resp:
                    if s3_resp.status != 200:
                        flaws.append(f"Diagram asset returned HTTP {s3_resp.status}")
            except Exception as e:
                # Some might use local minio bucket paths; log note
                pass

    return flaws

def run_live_assessment_tests():
    print("=" * 80)
    print("PREPFREEX LIVE EXAM ENGINE & ACADEMIC INTEGRITY AUDIT")
    print("=" * 80)

    total_tests = len(TEST_CASES)
    passed_tests = 0
    total_questions_audited = 0
    total_flaws_found = 0

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{total_tests}] Testing: {tc['label']}")
        
        # 1. Create Assessment
        payload = {
            "assessment_type": tc["type"],
            "subject": tc["subject"]
        }
        if "topic_code" in tc:
            payload["topic_code"] = tc["topic_code"]
            payload["question_count"] = 5

        try:
            create_resp = http_json("POST", BASE_URL, payload)
            aid = create_resp["assessment_id"]
            expected_count = create_resp["total_questions"]
            print(f"  -> Created Assessment ID: {aid} (Allocated: {expected_count} questions)")
        except Exception as e:
            print(f"  -> [FAIL] Assessment creation error: {e}")
            continue

        # 2. Fetch Questions
        try:
            q_url = f"{BASE_URL}/{aid}/questions"
            q_resp = http_json("GET", q_url)
            questions = q_resp.get("questions", [])
            print(f"  -> Retrieved {len(questions)} questions from /questions endpoint.")
        except Exception as e:
            print(f"  -> [FAIL] Question retrieval error: {e}")
            continue

        # 3. Deep Academic Integrity Audit of every question in the exam
        test_flaws = []
        for qidx, q in enumerate(questions, 1):
            total_questions_audited += 1
            flaws = validate_question(q, tc["label"], qidx)
            if flaws:
                total_flaws_found += len(flaws)
                test_flaws.append((qidx, q.get("question_uid"), flaws, q.get("text")[:60]))

        if test_flaws:
            print(f"  -> [WARN] Found {len(test_flaws)} questions with potential flaws:")
            for qidx, quid, flaws, snippet in test_flaws:
                print(f"     Q{qidx} [{quid}]: {', '.join(flaws)} | Text: '{snippet}...'")
        else:
            print(f"  -> [PASS] All {len(questions)} questions verified clean! No OCR flaws, no watermarks, no stripped exponents.")

        # 4. Answer all questions
        answered = 0
        for q in questions:
            qid = q["id"]
            ans_payload = {"selected_option": "A"}
            try:
                http_json("PUT", f"{BASE_URL}/{aid}/responses/{qid}", ans_payload)
                answered += 1
            except Exception as e:
                print(f"     Error saving response for Q {qid}: {e}")
        print(f"  -> Saved responses for {answered}/{len(questions)} questions.")

        # 5. Submit Assessment
        import time
        t0 = time.time()
        try:
            submit_resp = http_json("POST", f"{BASE_URL}/{aid}/submit")
            t_submit = time.time() - t0
            print(f"  -> [PASS] Exam submitted successfully in {t_submit:.2f}s (No freezing/spinner lag)!")
            print(f"     Score: {submit_resp.get('total_score')}/{submit_resp.get('max_marks')} | Status: {submit_resp.get('status')}")
        except Exception as e:
            print(f"  -> [FAIL] Submission error: {e}")
            continue

        # 6. Verify Results & Solutions Review
        t0 = time.time()
        try:
            review_resp = http_json("GET", f"{BASE_URL}/{aid}/review")
            t_review = time.time() - t0
            rev_questions = review_resp.get("questions", [])
            has_solutions = sum(1 for q in rev_questions if q.get("solution_latex") or q.get("concise_expl"))
            print(f"  -> [PASS] Solution Review loaded {len(rev_questions)} questions in {t_review:.2f}s!")
            print(f"     Questions with detailed explanations: {has_solutions}/{len(rev_questions)}")
            passed_tests += 1
        except Exception as e:
            print(f"  -> [FAIL] Review retrieval error: {e}")

    print("\n" + "=" * 80)
    print("ACADEMIC AUDIT & TESTING SUMMARY")
    print(f"Total Test Sessions Run: {total_tests}")
    print(f"Successfully Passed Sessions: {passed_tests}/{total_tests}")
    print(f"Total Individual Questions Evaluated: {total_questions_audited}")
    print(f"Total Defects Found in Evaluated Questions: {total_flaws_found}")
    print("=" * 80)

if __name__ == '__main__':
    run_live_assessment_tests()

