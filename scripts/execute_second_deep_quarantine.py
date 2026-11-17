import json
import re
from apps.api.db import get_db_cursor

def run_deep_quarantine():
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, question_uid, subject, unit_code, primary_topic_code,
                   question_text_latex, options, has_diagram, diagram_s3_key
            FROM public.completed_questions
            WHERE assessment_status = 'ELIGIBLE';
        """)
        rows = cur.fetchall()

    print(f"Auditing all {len(rows)} remaining eligible questions for deep OCR defects...")

    to_quarantine = []

    for r in rows:
        qid = r["id"]
        stem = r.get("question_text_latex") or ""
        stem_clean = " ".join(stem.split()).strip()

        opts = r.get("options") or []
        if isinstance(opts, str):
            try: opts = json.loads(opts)
            except: opts = []
        clean_opts = [o.get("text", "") if isinstance(o, dict) else str(o) for o in opts]
        clean_opts_stripped = [o.strip() for o in clean_opts if o.strip()]

        reasons = []

        # 1. Leaked watermarks & branding
        watermarks = [
            r'mathongo', r'#mathbole', r'question bank', r'jee main 202\d',
            r'www\.mathongo', r'vedantu', r'pw\.live'
        ]
        for w in watermarks:
            if re.search(w, stem, re.I):
                reasons.append(f"Watermark in stem ({w})")
            for o in clean_opts:
                if re.search(w, o, re.I):
                    reasons.append(f"Watermark in option ({w})")

        # 2. Leaked exam dates at top of stem
        if re.match(r'^\s*\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', stem_clean, re.I):
            reasons.append("Exam date banner leaked at start of stem")

        # 3. Leaked foreign question or multi-line OCR text in options
        for o in clean_opts:
            if len(o.splitlines()) >= 3 or len(o) > 150:
                if re.search(r'(Electrostatics|Questions|q1|q2|4πε0|Aldehydes and Ketones|MathonGo)', o, re.I):
                    reasons.append("Option contains leaked foreign question or OCR page text")
                elif len(o) > 220:
                    reasons.append(f"Option excessively long ({len(o)} chars), likely leaked text")

        # 4. Blank multi-choice lists in stem: (A) (B) (C) (D) without any chemical/entity names
        if re.search(r'\([A-E]\)\s*\n*\s*\([B-E]\)\s*\n*\s*\([C-E]\)', stem) or re.search(r'\bA\.\s*B\s*\n*\s*C\.\s*D\b', stem):
            reasons.append("Stem contains blank choice labels (A) (B) (C)... missing entity formulas")

        # 5. Missing reaction formula when stem explicitly references "following reaction"
        if re.search(r'\b(in the following reaction|rate of the reaction is the highest for|for the following reaction)\b', stem, re.I):
            has_rxn = bool(re.search(r'(->|\\rightarrow|\\to|-->|⇌|\\rightleftharpoons)', stem))
            if not has_rxn and not r.get("has_diagram"):
                reasons.append("Explicitly references 'following reaction' but has no reaction formula or diagram")

        # 6. Nuclear reaction missing equation before (energy) / -particle in option
        if re.search(r'as\s*:\s*\(energy\)', stem, re.I) or re.search(r'\bthree particles named x are produced\b', stem, re.I):
            if not re.search(r'(->|\\rightarrow|\+)', stem):
                reasons.append("Nuclear fission equation completely missing before '(energy)'")

        # 7. Broken options: cut off, scrambled OCR, stripped Greek letters, trailing conjunctions/prepositions
        for o in clean_opts:
            o_str = o.strip()
            if re.search(r'^-[a-z]+$', o_str) and len(o_str) > 1:
                reasons.append(f"Stripped Greek letter in option ('{o_str}')")
            if re.search(r'\([A-E]\)\s*\(?[A-E]\)?', o_str):
                reasons.append(f"Scrambled OCR choice labels merged inside option ('{o_str[:50]}...')")
            if re.search(r'\b(and|or|of|to|is|are|with|from|than|in|at)\s*$', o_str, re.I) and len(o_str) > 3:
                # exclude simple mathematical formulas that happen to end in a single variable
                reasons.append(f"Option cut off ending with preposition/conjunction ('{o_str}')")
            if re.match(r'^(is true but is false|is false but is true|Both and are true|Both and are false)', o_str, re.I):
                reasons.append("Assertion-reason option missing subjects ('is true but is false')")
            if re.search(r'\b(explanation of|maximum of|minimum of|correct option :)\s*$', o_str, re.I):
                reasons.append(f"Option cut off with trailing preposition ('{o_str[-25:]}')")
            if re.search(r'\ban\s+Pp\s*<', o_str):
                reasons.append("Typo in option ('an Pp <')")

        # 8. Missing math/physics formulas represented by blank drops or prepositions:
        stripped_patterns = [
            (r'\broots\s+of\s+in the interval\b', "Missing equation ('roots of in the interval')"),
            (r'\bof the equation,\s+in the interval\b', "Missing equation ('equation, in the interval')"),
            (r'\bhas two distinct real roots in\s*$', "Stem cut off ending with 'roots in'"),
            (r'\bthe equation,\s+has two distinct\b', "Missing equation ('the equation, has')"),
            (r'\bGiven\s+such that\s+is the only\b', "Missing function and variable ('Given such that is the only')"),
            (r'\breal root of\s+If\s+then\b', "Missing equation ('real root of If then')"),
            (r'\bgenerate\s*\.\s*$', "Stem/statement cut off at 'generate .'"),
            (r'\bStatements? II\s*:\s*The Lewis acid catalyst polarises the bromine to generate\s*\.', "Missing chemical species in Statement II"),
            (r'\bproduce\s+with aqueous\s+solution\b', "Missing chemical species ('produce with aqueous solution')"),
            (r'\bfrequency of electromagnetic wave is\s+and\b', "Missing frequency value in EM wave problem"),
            (r'\bwavelength of the wave \(in\s*\)\s*is', "Missing units in parentheses '(in ) is'"),
            (r'\bdenote the K\s*\.?\s*E\.\s*and\s*momentum\b', "Mangled 'K E. and momentum'"),
            (r'\bA\s+B\s+C\s+D\s+E\s+Choose the correct answer\b', "Blank items A B C D E before question prompt"),
            (r'\bx7 7x 2 = 0\b', "Mangled exponents and signs ('x7 7x 2 = 0')"),
            (r'\bx4 4x \+ 1 = 0\b', "Mangled exponents ('x4 4x + 1 = 0')"),
            (r'\bthe value of \. is\b', "Missing expression ('the value of . is')"),
            (r'\bequal to \.\b', "Missing expression ('equal to .')"),
            (r'\bwhere  and  are\b', "Missing variable definitions ('where and are')"),
            (r'\bLet  and  be\b', "Missing definitions ('Let and be')"),
            (r'\band  are roots of\b', "Missing root symbols ('and are roots of')"),
            (r'\bis given by\s*\.\s*$', "Cut off at 'is given by .'"),
            (r'\bis equal to\s*\.\s*$', "Cut off at 'is equal to .'"),
            (r'test are\s*:\s*\n*Choose the correct answer from the options given below', "Missing compounds in test prompt ('test are : Choose the correct answer')")
        ]
        for pat, desc in stripped_patterns:
            if re.search(pat, stem, re.I):
                reasons.append(desc)

        # 9. Stems ending abruptly in prepositions without terminal punctuation or object
        if re.search(r'\b(in the interval|of the form|equal to|given by|such that|value of|is equal to)\s*$', stem_clean, re.I):
            reasons.append(f"Stem abruptly ends with hanging preposition/operator: '{stem_clean[-30:]}'")

        if reasons:
            to_quarantine.append((qid, list(set(reasons))))

    print(f"\nTotal questions to quarantine in this deep pass: {len(to_quarantine)}")

    with get_db_cursor() as cur:
        for qid, rsns in to_quarantine:
            rsn_str = "; ".join(rsns)
            cur.execute("""
                UPDATE public.completed_questions
                SET assessment_status = 'BROKEN',
                    academic_status = 'QUARANTINED',
                    tags = COALESCE(tags, '[]'::jsonb) || jsonb_build_array('BROKEN_REASON: ' || %s)
                WHERE id = %s;
            """, (rsn_str, qid))

    print(f"Successfully quarantined {len(to_quarantine)} broken questions in public.completed_questions!")

if __name__ == "__main__":
    run_deep_quarantine()

