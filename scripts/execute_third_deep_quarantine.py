import sys
sys.path.append('.')
import json
import re
from apps.api.db import get_db_cursor

WATERMARK_RE = re.compile(r'(?:mathongo|#MathBoleTohMathonGo|www\.mathongo|Question Bank|JEE Main 202\d\s+April|JEE Main 202\d\s+January)', re.I)

BROKEN_GRAMMAR_RE = [
    (re.compile(r',\s*\.', re.I), "Comma immediately followed by period (missing equation/variable)"),
    (re.compile(r'\b(?:is|of|in|to|at|with|by|from|equal to)\s+\.', re.I), "Dangling preposition before period (missing value/equation)"),
    (re.compile(r'\(in\s+\)|\[in\s+\]|\(in\s*\)', re.I), "Empty unit parenthesis e.g. (in )"),
    (re.compile(r'electric field is\s+and|magnetic field is\s+and', re.I), "Missing field equation ('field is and')"),
    (re.compile(r'is\s+and it travels', re.I), "Missing frequency/velocity value ('is and it travels')"),
    (re.compile(r'written as\s*:\s*\(energy\)', re.I), "Missing nuclear reaction equation"),
    (re.compile(r'coefficient\s+(?:between\s+.*?\s+)?is\s+then\b', re.I), "Missing coefficient value ('is then')"),
    (re.compile(r'produces\s+and\s+water', re.I), "Missing reaction products ('produces and water')"),
    (re.compile(r'combustion of\s+of\b', re.I), "Missing amount before 'of'"),
    (re.compile(r'compounds\s+[A-Za-z0-9]+\s+and\s+\.', re.I), "Missing compound formula before period"),
    (re.compile(r'When\s+1\s*g\s+of\s+is\s+dissolved', re.I), "Missing substance name ('1 g of is dissolved')"),
]

BROKEN_AR_OPTS_RE = [
    re.compile(r'^\s*is true but\s+is false', re.I),
    re.compile(r'^\s*is false but\s+is true', re.I),
    re.compile(r'^\s*Both\s+and\s+are true', re.I),
    re.compile(r'^\s*Both\s+and\s+are false', re.I),
]

STRIPPED_EXPONENT_RE = re.compile(r'\b\d+\.?\d*\s+10(?:1[0-9]|2[0-5]|[3-9])\b')

FIGURE_RE = re.compile(r'\b(?:see figure|given figure|shown in figure|as shown in the figure|shown below|in the circuit shown)\b', re.I)

def run_pass3_quarantine():
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, question_uid, subject, unit_code, primary_topic_code,
                   question_text_latex, options, has_diagram, diagram_s3_key
            FROM completed_questions
            WHERE assessment_status = 'ELIGIBLE';
        """)
        rows = cur.fetchall()

    print(f"Auditing {len(rows)} currently ELIGIBLE questions for Pass 3 deep forensic quarantine...")

    to_quarantine = []

    for r in rows:
        qid = r['id']
        stem = r.get('question_text_latex') or ''
        has_diag = bool(r.get('has_diagram')) and bool(r.get('diagram_s3_key'))
        
        opts = r.get('options') or []
        if isinstance(opts, str):
            try: opts = json.loads(opts)
            except: opts = []
        clean_opts = [o.get("text", "") if isinstance(o, dict) else str(o) for o in opts]
        
        issues = []
        
        # 1. Watermarks
        if WATERMARK_RE.search(stem):
            issues.append("Watermark in stem")
        for o in clean_opts:
            if WATERMARK_RE.search(o):
                issues.append("Watermark in option")
                break
                
        # 2. Broken grammar / missing values in stem
        for pattern, desc in BROKEN_GRAMMAR_RE:
            if pattern.search(stem):
                if 'x50 are' in stem and '...' in stem and desc.startswith('Comma immediately'):
                    continue
                issues.append(f"Stem: {desc}")
                break
                
        # 3. Missing diagrams
        if FIGURE_RE.search(stem) and not has_diag:
            issues.append("Figure referenced in stem but diagram missing")
            
        # 4. Broken AR options
        for o in clean_opts:
            for p in BROKEN_AR_OPTS_RE:
                if p.search(o):
                    issues.append("Broken Assertion-Reason option (missing A/R labels)")
                    break
                    
        # 5. Stripped exponents in options
        for o in clean_opts:
            if STRIPPED_EXPONENT_RE.search(o):
                issues.append("Stripped scientific exponent notation (e.g. 1010/1011)")
                break
                
        # 6. Multi-line OCR dump in options
        for o in clean_opts:
            lines = [line.strip() for line in o.splitlines() if line.strip()]
            if len(lines) >= 4 and any("q" in line or "E" in line or "V" in line or "m" in line for line in lines):
                issues.append("Multi-line OCR spillover in option")
                break

        if issues:
            to_quarantine.append((qid, "; ".join(issues)))

    print(f"Identified {len(to_quarantine)} defective questions to quarantine.")

    if not to_quarantine:
        print("No questions to quarantine.")
        return

    with get_db_cursor() as cur:
        for qid, reason in to_quarantine:
            cur.execute("""
                UPDATE completed_questions
                SET assessment_status = 'BROKEN',
                    academic_status = 'QUARANTINED',
                    tags = COALESCE(tags, '[]'::jsonb) || jsonb_build_array('PASS3_BROKEN: ' || %s)
                WHERE id = %s;
            """, (reason, qid))

    print(f"Successfully quarantined {len(to_quarantine)} questions in database!")

    # Verify remaining count
    with get_db_cursor() as cur:
        cur.execute("SELECT count(*) as cnt FROM completed_questions WHERE assessment_status = 'ELIGIBLE';")
        remaining = cur.fetchone()["cnt"]
        cur.execute("SELECT count(*) as cnt FROM completed_questions WHERE assessment_status = 'BROKEN';")
        total_quarantined = cur.fetchone()["cnt"]

    print(f"New Database State:")
    print(f"  - Clean ELIGIBLE Questions: {remaining}")
    print(f"  - Total QUARANTINED Questions: {total_quarantined}")

if __name__ == '__main__':
    run_pass3_quarantine()
