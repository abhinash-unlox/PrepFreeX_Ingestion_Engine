import json
import re
from apps.api.db import get_db_cursor

def quarantine_defective_questions(dry_run: bool = False):
    with get_db_cursor() as cur:
        cur.execute("""
            SELECT id, question_uid, subject, unit_code, primary_topic_code,
                   question_text_latex, options, has_diagram, diagram_s3_key
            FROM public.completed_questions
            WHERE assessment_status = 'ELIGIBLE';
        """)
        rows = cur.fetchall()

    print(f"Auditing {len(rows)} currently eligible questions against strict academic OCR integrity rules...")

    quarantined = []

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

        # 1. Non-unique or incomplete options
        if len(clean_opts_stripped) < 4:
            reasons.append("Less than 4 non-empty options")
        elif len(set(clean_opts_stripped)) < 4:
            reasons.append(f"Duplicate options ({len(set(clean_opts_stripped))}/4 unique)")

        # 2. Options ending in trailing incomplete grammar ('is', 'field is', etc.)
        if any(re.search(r'\b(is|and the magnetic field is|field is|are)\s*$', o.strip(), re.I) for o in clean_opts):
            reasons.append("Option text cuts off with trailing verb ('is')")

        # 3. Missing chemical structures for comparative questions (I, II, III, IV)
        if re.search(r'\b(following (alkenes|compounds|structures|molecules|complexes|isomers))\b', stem, re.I):
            has_formulas_in_stem = bool(re.search(r'([A-Z][a-z]?\d|\bCH[0-9_]|\bstructure\b|\([I|V|X]+\)\s+[A-Za-z0-9])', stem))
            options_are_roman_only = any(re.match(r'^\s*\(?[I|V|X]+\)?\s*<?\s*\(?[I|V|X]+\)?', o.strip()) for o in clean_opts)
            if not r.get("has_diagram") and not has_formulas_in_stem and options_are_roman_only:
                reasons.append("Requires compound structures (I, II, III, IV) but none provided in stem or diagram")

        # 4. Stripped mathematical expressions / blank holes in sentences
        stripped_holes = [
            (r'\bfor\s*,\s*let\b', "Missing range/domain ('For , let')"),
            (r'\bwhere\s+and\s*\.', "Missing variable definitions ('where and .')"),
            (r'\b[Ss]uppose the cubic\s+has\b', "Missing equation ('Suppose the cubic has')"),
            (r'\bundergoes elastic strain of\s*\.', "Missing numerical value ('elastic strain of .')"),
            (r'\bbond angle is almost close to\s*\.', "Missing numerical value ('angle is close to .')"),
            (r'\bhigh solubility in water at\s*\.', "Missing numerical value ('solubility at .')"),
            (r'\bgiven by\s+P\s*$', "Stem abruptly ends with 'given by P'"),
            (r'\bstatements\s+is a contradiction\b', "Missing statement text ('statements is a contradiction')"),
            (r'\blet\s+and\s+be\b', "Missing variables ('let and be')"),
            (r'\bvalues of both dissolved\s*$', "Stem cut off at 'dissolved'"),
            (r'\bwhose eccentricity is 1 and the length\b', "Corrupted ellipse eccentricity ('eccentricity is 1')"),
            (r'\b(at|close to|of|is|equal to|with|from)\s+\.', "Blank value followed by period (' .')"),
            (r'\b2l2 equals\b', "Mangled exponent in vector length (2l2 instead of 2l^2)"),
            (r'f\(x\)\s*=\s*\+\s*\.', "Empty operator missing arguments ('f(x) = + .')")
        ]
        for pattern, desc in stripped_holes:
            if re.search(pattern, stem_clean, re.I):
                reasons.append(desc)

        # 5. Corrupted box drawing / unicode piecewise glyphs
        if re.search(r'[⎧⎪⎨⎩]', stem):
            reasons.append("Mangled OCR piecewise bracket symbols (⎧, ⎪, ⎨)")

        # 6. Severely broken fractions without fraction bars
        if re.search(r'x2\s+y2.*?\+\s*=\s*1', stem_clean) or re.search(r'a2\s+b2', stem_clean):
            reasons.append("Scrambled multi-line fraction without division bar")

        # 7. Mangled exponent notation making problem nonsensical
        if re.search(r'\b\d+\s+10\d+\s+V\s+m1\b', stem_clean) or re.search(r'\b3g\s+cm3\b', stem_clean):
            reasons.append("Stripped scientific exponents (e.g. 105 V m1, 3g cm3)")

        if reasons:
            quarantined.append((qid, reasons))

    print(f"\nTotal questions meeting strict quarantine criteria: {len(quarantined)}")

    if not dry_run and quarantined:
        with get_db_cursor() as cur:
            for qid, rsns in quarantined:
                rsn_str = "; ".join(rsns)
                cur.execute("""
                    UPDATE public.completed_questions
                    SET assessment_status = 'BROKEN',
                        academic_status = 'QUARANTINED',
                        tags = COALESCE(tags, '[]'::jsonb) || jsonb_build_array('BROKEN_REASON: ' || %s)
                    WHERE id = %s;
                """, (rsn_str, qid))
        print(f"Successfully quarantined {len(quarantined)} questions in public.completed_questions!")

    return len(quarantined)

if __name__ == "__main__":
    quarantine_defective_questions(dry_run=False)

