from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import fitz

from .config import settings
from .llm import BaseLLMProvider, FakeLLM, get_llm_provider

ROMAN = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
    "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20
}

UNIT_RE = re.compile(r"^\s*UNITS?\s*(\d+|[IVX]+)\s*[:.]?\s*(.*?)\s*$", re.I)
AREA_NAMES = {
    "PHYSICAL CHEMISTRY": "physical",
    "INORGANIC CHEMISTRY": "inorganic",
    "ORGANIC CHEMISTRY": "organic",
}

U14_VERBATIM_NODES = [
    ("PHY.U14.T01", "topic", "Electromagnetic induction (Faraday, Lenz, eddy currents, self and mutual inductance)", "PHY.U14", None, []),
    ("PHY.U14.T02", "topic", "Peak and RMS values", "PHY.U14", None, []),
    ("PHY.U14.T02.S01", "subtopic", "RMS value of non-sinusoidal waveforms", "PHY.U14.T02",
     "Calculation of root mean square value for non-sinusoidal currents and periodic waveforms. Excludes standard sinusoidal AC RMS calculations.",
     ["The electric current in a circuit is given by i = i0(t/T). The r.m.s. current for the period from t=0 to t=T is ____.", "Calculate the rms value for a triangular current wave of peak value i0."]),
    ("PHY.U14.T03", "topic", "Reactance and impedance", "PHY.U14", None, []),
    ("PHY.U14.T03.S01", "subtopic", "Inductive reactance and inductor energy", "PHY.U14.T03",
     "Inductive reactance XL = omega L, magnetic energy stored in an inductor 1/2 L I^2, and power dissipation in resistive inductors. Excludes capacitive circuits.",
     ["An inductor stores 16 J of magnetic-field energy and dissipates 32 W of thermal energy when a.c. current of 2 A flows through it. Find XL/R.", "An alternating voltage is applied across a pure inductor of 0.05 H. Find inductive reactance at 50 Hz."]),
    ("PHY.U14.T03.S02", "subtopic", "Capacitive reactance", "PHY.U14.T03",
     "Capacitive reactance XC = 1/(omega C) and capacitor response in AC circuits. Excludes inductive circuits.",
     ["Find the capacitive reactance of a 10 microfarad capacitor connected to a 220 V, 50 Hz source.", "A capacitor blocks DC and offers reactance to AC; calculate reactance at 1 kHz."]),
    ("PHY.U14.T04", "topic", "LCR series circuit", "PHY.U14", None, []),
    ("PHY.U14.T04.S01", "subtopic", "Impedance and phase angle", "PHY.U14.T04",
     "Impedance Z = sqrt(R^2 + (XL-XC)^2) and phase angle phi in series LCR circuits. Excludes resonant condition and LC oscillations.",
     ["For the series LCR circuit connected with a 220 V source, XL=70, XC=150 and R=60. The power factor is alpha/10. Find alpha.", "Calculate the phase angle between voltage and current in an LCR circuit with given component values."]),
    ("PHY.U14.T04.S02", "subtopic", "LC oscillations (energy exchange)", "PHY.U14.T04",
     "LC oscillations, energy exchange between electric field of capacitor and magnetic field of inductor, oscillation frequency omega = 1/sqrt(LC). Excludes external damping or driving source.",
     ["A capacitor C is first charged fully with potential difference V0 and connected across inductor L. In t s, 25% energy is transferred to inductor. Find t.", "In an LC circuit, energy oscillates sinusoidally between capacitor and inductor; find the oscillation period."]),
    ("PHY.U14.T05", "topic", "Resonance", "PHY.U14", None, []),
    ("PHY.U14.T05.S01", "subtopic", "Resonance condition and maximum current", "PHY.U14.T05",
     "Series resonance condition omega L = 1/(omega C), resonant frequency, impedance minimum, and maximum current at resonance. Excludes off-resonance power factor.",
     ["Using a variable-frequency a.c. voltage source, the maximum current measured in the given LCR circuit is 50 mA for V=5 sin(100t). Find C.", "At series resonance in an LCR circuit, find the resonance frequency and maximum current."]),
    ("PHY.U14.T06", "topic", "Power in AC circuits and wattless current", "PHY.U14", None, []),
    ("PHY.U14.T06.S01", "subtopic", "Power factor", "PHY.U14.T06",
     "Average power in AC circuits P = Vrms Irms cos phi and power factor cos phi = R/Z. Excludes purely reactive wattless current.",
     ["An AC circuit has impedance 100 ohm and resistance 60 ohm; find the power factor.", "A circuit draws 5 A at 220 V with power factor 0.8; find the true power consumed."]),
    ("PHY.U14.T06.S02", "subtopic", "Wattless current", "PHY.U14.T06",
     "Wattless current Irms sin phi in purely reactive or low power factor AC circuits. Excludes active (wattful) power dissipation.",
     ["A current of 5 A flows in an AC circuit with a phase lag of 60 degrees. Find the wattless component of current.", "Show that in a purely inductive circuit the average power dissipated is zero and current is wattless."]),
    ("PHY.U14.T07", "topic", "AC generator and transformer", "PHY.U14", None, []),
]


def _clean_title(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" :.-\t")
    value = re.sub(r"\bDIFFRENTIAL\b", "DIFFERENTIAL", value, flags=re.I)
    value = re.sub(r"\bCALCULAS\b", "CALCULUS", value, flags=re.I)
    return value


def _to_unit_num(token: str) -> int:
    token = token.upper()
    return int(token) if token.isdigit() else ROMAN.get(token, 0)


def _collect_pages(pdf_path: Path) -> list[str]:
    with fitz.open(pdf_path) as pdf:
        return [p.get_text("text") for p in pdf]


def _extract_subject_page_ranges(pages: list[str]) -> dict[str, list[int]]:
    subject_pages: dict[str, list[int]] = {"mathematics": [], "physics": [], "chemistry": []}
    current: str | None = None
    for idx, text in enumerate(pages):
        upper = text.upper()
        if "PHYSICS" in upper[:500] and re.search(r"UNIT\s*1\s*:\s*UNITS AND MEASUREMENTS", upper):
            current = "physics"
        elif "CHEMISTRY" in upper[:700] and ("PHYSICAL CHEMISTRY" in upper or "UNIT I:" in upper):
            current = "chemistry"
        elif "MATHEMATICS" in upper[:700] and "SETS, RELATIONS" in upper:
            current = "mathematics"
        if current:
            subject_pages[current].append(idx)
    if not subject_pages["mathematics"]:
        subject_pages["mathematics"] = [0, 1]
    if not subject_pages["physics"]:
        subject_pages["physics"] = [2, 3, 4, 5]
    if not subject_pages["chemistry"]:
        subject_pages["chemistry"] = list(range(6, len(pages)))
    return subject_pages


def _extract_units_for_subject(pages: list[str], subject: str) -> list[dict[str, Any]]:
    joined = "\n".join(pages)
    lines = joined.splitlines()
    units: list[dict[str, Any]] = []
    current_area = None
    active: dict[str, Any] | None = None

    for line in lines:
        stripped = re.sub(r"\s+", " ", line).strip()
        if subject == "chemistry":
            for label, area in AREA_NAMES.items():
                if label in stripped.upper():
                    current_area = area
                    break
        match = UNIT_RE.match(stripped)
        if not match:
            embedded = re.search(r"\bUNITS?\s*(\d+|[IVX]+)\s*[:.]?\s*(.*?)\s*$", stripped, re.I)
            if embedded and stripped[:embedded.start()].strip().upper() in {"MATHEMATICS", "PHYSICS", "CHEMISTRY"}:
                match = embedded
        if match:
            n = _to_unit_num(match.group(1))
            title = _clean_title(match.group(2))
            if not n or n > 20 or len(title) < 2:
                continue
            if active:
                active["syllabus_text"] = " ".join(active["body"]).strip()
                units.append(active)
            active = {
                "unit_number": n,
                "name": title,
                "area": current_area if subject == "chemistry" else None,
                "body": [],
            }
        elif active:
            if "SYLLABUS FOR JEE" in stripped.upper():
                continue
            active["body"].append(stripped)

    if active:
        active["syllabus_text"] = " ".join(active["body"]).strip()
        units.append(active)

    unique: dict[int, dict[str, Any]] = {}
    for u in units:
        if u["unit_number"] not in unique:
            u.pop("body", None)
            unique[u["unit_number"]] = u
    return [unique[k] for k in sorted(unique)]


def load_taxonomy(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {node["code"]: node for node in raw["nodes"]}


def _truncate_words(text: str, max_words: int = 8) -> str:
    words = text.strip().split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


def _derive_fallback_topics_and_subtopics(unit_code: str, unit_name: str, syllabus_text: str) -> list[dict[str, Any]]:
    """Deterministic, curriculum-aligned topic & subtopic generator for JEE Main syllabus."""
    # Special cases: Physics U20 and Chemistry U20 generate topics only
    if unit_code in {"PHY.U20", "CHE.U20"}:
        chunks = re.split(r";|\.(?=\s+[A-Z])", syllabus_text)
        topics = []
        for c in chunks:
            c = c.strip(" ,.;:-")
            if len(c) > 8:
                topics.append({"name": _truncate_words(c, 8), "subtopics": []})
        if not topics:
            topics = [{"name": _truncate_words(unit_name, 8), "subtopics": []}]
        return topics[:10]

    # Split syllabus into topics
    raw_topics = re.split(r";|\.(?=\s+[A-Z])", syllabus_text)
    topics_out: list[dict[str, Any]] = []

    for rt in raw_topics:
        rt = rt.strip(" ,.;:-")
        if len(rt) < 8:
            continue
        # Split subtopics by comma
        clauses = [cl.strip(" ,.;:-") for cl in re.split(r"[,;]", rt) if len(cl.strip(" ,.;:-")) >= 5]
        topic_name = _truncate_words(clauses[0] if clauses else rt, 8)

        subtopics_out = []
        sub_candidates = clauses[1:] if len(clauses) > 1 else clauses
        if len(sub_candidates) < 2:
            # Generate at least 2 concrete subtopics from the topic
            sub_candidates = [
                f"{topic_name} theory and fundamental definitions",
                f"{topic_name} problem solving and applications",
            ]
        # Keep between 2 and 6 subtopics
        sub_candidates = sub_candidates[:6]
        if len(sub_candidates) < 2:
            sub_candidates.append(f"{topic_name} standard formulas and applications")

        for sc in sub_candidates:
            st_name = _truncate_words(sc, 8)
            subtopics_out.append({
                "name": st_name,
                "description": f"Includes problem-types on {st_name}. Excludes unrelated parts of {topic_name}.",
                "example_stems": [
                    f"Calculate the primary parameters for {st_name} given standard values.",
                    f"Which of the following statements is correct regarding {st_name}?",
                ],
            })

        topics_out.append({"name": topic_name, "subtopics": subtopics_out})

    if not topics_out:
        topics_out = [{
            "name": _truncate_words(unit_name, 8),
            "subtopics": [
                {
                    "name": f"{_truncate_words(unit_name, 6)} core concepts",
                    "description": f"Core concepts and principles of {unit_name}. Excludes advanced derivations.",
                    "example_stems": [
                        f"Find the primary quantity in {unit_name}.",
                        f"State the governing law for {unit_name}.",
                    ],
                },
                {
                    "name": f"{_truncate_words(unit_name, 6)} applications",
                    "description": f"Application and numerical problem solving for {unit_name}.",
                    "example_stems": [
                        f"Compute the resultant value in {unit_name}.",
                        f"A given setup in {unit_name} produces a measured output.",
                    ],
                },
            ],
        }]

    return topics_out[:12]


def build_taxonomy_v2(
    syllabus_pdf: Path,
    unit_filter: str | None = None,
    version: str | None = None,
    llm: BaseLLMProvider | None = None,
) -> dict[str, Any]:
    version = version or settings.taxonomy_version
    all_pages = _collect_pages(syllabus_pdf)
    ranges = _extract_subject_page_ranges(all_pages)
    data: list[dict[str, Any]] = []

    subjects = [
        ("MAT", "mathematics", "Mathematics"),
        ("PHY", "physics", "Physics"),
        ("CHE", "chemistry", "Chemistry"),
    ]
    for code, key, name in subjects:
        data.append({
            "code": code, "level": "subject", "name": name, "parent_code": None,
            "syllabus_text": None, "sort_order": 1, "is_reviewed": True,
            "description": None, "example_stems": [], "replaced_by": None,
        })

    for code, name in [
        ("CHE.PHYSICAL", "Physical Chemistry"),
        ("CHE.INORGANIC", "Inorganic Chemistry"),
        ("CHE.ORGANIC", "Organic Chemistry"),
    ]:
        data.append({
            "code": code, "level": "area", "name": name, "parent_code": "CHE",
            "syllabus_text": None, "sort_order": 1, "is_reviewed": True,
            "description": None, "example_stems": [], "replaced_by": None,
        })

    for _, key, subj_name in subjects:
        ptxt = [all_pages[i] for i in ranges[key] if i < len(all_pages)]
        units = _extract_units_for_subject(ptxt, key)
        prefix = {"mathematics": "MAT", "physics": "PHY", "chemistry": "CHE"}[key]

        for unit in units:
            n = unit["unit_number"]
            ucode = f"{prefix}.U{n:02d}"
            if unit_filter and ucode != unit_filter:
                continue

            parent = "MAT" if key == "mathematics" else "PHY"
            if key == "chemistry":
                area = unit.get("area")
                if area not in {"physical", "inorganic", "organic"}:
                    area = "physical" if n <= 8 else "inorganic" if n <= 12 else "organic"
                parent = f"CHE.{area.upper()}"

            unit_syl = unit.get("syllabus_text", "")
            data.append({
                "code": ucode, "level": "unit", "name": unit["name"],
                "parent_code": parent, "syllabus_text": unit_syl,
                "sort_order": n, "is_reviewed": True,
                "description": None, "example_stems": [], "replaced_by": None,
            })

            # Check if this is curated Physics Unit 14
            if ucode == "PHY.U14":
                for item in U14_VERBATIM_NODES:
                    code, level, name, parent_code, desc, examples = item
                    data.append({
                        "code": code,
                        "level": level,
                        "name": name,
                        "parent_code": parent_code,
                        "syllabus_text": name,
                        "sort_order": int(code.split(".")[-1][1:]),
                        "is_reviewed": False,
                        "description": desc,
                        "example_stems": examples,
                        "replaced_by": None,
                    })
                continue

            # LLM generation for topics and subtopics
            unit_topics = None
            if llm and not isinstance(llm, FakeLLM):
                try:
                    prompt = (
                        f"You are a JEE Main curriculum expert.\n"
                        f"Subject: {subj_name}\n"
                        f"Unit: {ucode} - {unit['name']}\n"
                        f"Syllabus: {unit_syl}\n\n"
                        f"Style example from Physics Unit 14:\n"
                        f"- Topic names stay close to syllabus clauses (max 8 words).\n"
                        f"- Subtopics are concrete problem-types a JEE coaching chapter teaches (max 8 words).\n"
                        f"- Subtopics MUST be mutually exclusive and cover the topic.\n"
                        f"- 2 to 6 subtopics per topic.\n"
                        f"- Each subtopic must have a 1-2 sentence description stating included and excluded types.\n"
                        f"- Each subtopic must have 2 short example stems.\n"
                        f"{'Note: For practical/experimental unit, produce topics only, no subtopics.' if ucode in {'PHY.U20', 'CHE.U20'} else ''}\n"
                        f"Return JSON matching: {{'topics': [{{'name': '...', 'subtopics': [{{'name': '...', 'description': '...', 'example_stems': ['...', '...']}}]}}]}}"
                    )
                    resp = llm.extract_json([], prompt)
                    if resp and "topics" in resp and resp["topics"]:
                        unit_topics = resp["topics"]
                except Exception:
                    unit_topics = None

            if not unit_topics:
                unit_topics = _derive_fallback_topics_and_subtopics(ucode, unit["name"], unit_syl)

            # Assign codes deterministically
            for t_idx, topic in enumerate(unit_topics, 1):
                t_code = f"{ucode}.T{t_idx:02d}"
                t_name = _truncate_words(topic["name"], 8)
                data.append({
                    "code": t_code, "level": "topic", "name": t_name,
                    "parent_code": ucode, "syllabus_text": t_name,
                    "sort_order": t_idx, "is_reviewed": False,
                    "description": None, "example_stems": [], "replaced_by": None,
                })
                if ucode in {"PHY.U20", "CHE.U20"}:
                    continue
                subtopics = topic.get("subtopics") or []
                for s_idx, sub in enumerate(subtopics, 1):
                    s_code = f"{t_code}.S{s_idx:02d}"
                    s_name = _truncate_words(sub["name"], 8)
                    desc = sub.get("description") or f"Problems involving {s_name}."
                    stems = sub.get("example_stems") or [
                        f"Compute the value for {s_name}.",
                        f"Which condition applies for {s_name}?",
                    ]
                    data.append({
                        "code": s_code, "level": "subtopic", "name": s_name,
                        "parent_code": t_code, "syllabus_text": s_name,
                        "sort_order": s_idx, "is_reviewed": False,
                        "description": desc, "example_stems": stems[:2], "replaced_by": None,
                    })

    return {"taxonomy_version": version, "source_file": str(syllabus_pdf), "nodes": data}


def write_taxonomy_review_csvs(nodes: list[dict[str, Any]], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    unit_nodes: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        code = node["code"]
        if "." in code:
            parts = code.split(".")
            unit_code = f"{parts[0]}.{parts[1]}"
            if parts[1].startswith("U"):
                unit_nodes.setdefault(unit_code, []).append(node)

    for unit_code, unodes in unit_nodes.items():
        csv_path = output_dir / f"{unit_code}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["code", "level", "name", "description", "example_stems", "action"])
            for n in unodes:
                examples_str = " | ".join(n.get("example_stems") or [])
                writer.writerow([
                    n["code"],
                    n["level"],
                    n["name"],
                    n.get("description") or "",
                    examples_str,
                    "keep",
                ])


def apply_taxonomy_review(
    csv_path: Path,
    seed_path: Path | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    seed_path = seed_path or Path("db/seeds/jee_main_2027_taxonomy_v2.json")
    if not seed_path.exists():
        raise FileNotFoundError(f"Taxonomy seed {seed_path} not found.")

    raw = json.loads(seed_path.read_text(encoding="utf-8"))
    nodes_by_code: dict[str, dict[str, Any]] = {n["code"]: n for n in raw["nodes"]}

    actions_applied: list[str] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = row["code"].strip()
            level = row["level"].strip()
            name = row["name"].strip()
            desc = row.get("description", "").strip()
            examples = [e.strip() for e in row.get("example_stems", "").split("|") if e.strip()]
            raw_action = row.get("action", "").strip()
            action_lower = raw_action.lower()

            if action_lower == "add" or (not code and action_lower):
                # Assign fresh code
                parent_code = ".".join(code.split(".")[:-1]) if ("." in code) else code
                if not parent_code or parent_code not in nodes_by_code:
                    unit_code = csv_path.stem
                    topics = [c for c, n in nodes_by_code.items() if n.get("level") == "topic" and n.get("parent_code") == unit_code]
                    parent_code = topics[-1] if topics else unit_code

                # Find maximum existing index for parent
                existing_nums = [
                    int(c.split(".")[-1][1:])
                    for c in nodes_by_code
                    if c.startswith(parent_code) and len(c.split(".")) == len(parent_code.split(".")) + 1 and c.split(".")[-1][1:].isdigit()
                ]
                next_num = (max(existing_nums) + 1) if existing_nums else 1
                prefix_letter = "S" if level == "subtopic" else "T"
                new_code = f"{parent_code}.{prefix_letter}{next_num:02d}"
                nodes_by_code[new_code] = {
                    "code": new_code,
                    "level": level,
                    "name": name,
                    "parent_code": parent_code,
                    "syllabus_text": name,
                    "sort_order": next_num,
                    "is_reviewed": True,
                    "is_active": True,
                    "description": desc,
                    "example_stems": examples,
                    "replaced_by": None,
                }
                actions_applied.append(f"Added {new_code}: {name}")
                continue

            if code not in nodes_by_code:
                continue

            node = nodes_by_code[code]
            if action_lower.startswith("merge_into:"):
                target_code = raw_action.split(":", 1)[1].strip()
                node["is_active"] = False
                node["replaced_by"] = target_code
                actions_applied.append(f"Merged {code} -> {target_code}")
            elif action_lower == "delete":
                node["is_active"] = False
                actions_applied.append(f"Deleted {code}")
            elif action_lower == "rename" or (name and name != node["name"]):
                node["name"] = name
                node["is_reviewed"] = True
                actions_applied.append(f"Renamed {code} -> {name}")
            elif action_lower == "keep":
                node["is_reviewed"] = True

            if desc:
                node["description"] = desc
            if examples:
                node["example_stems"] = examples

    # Write updated seed back
    raw["nodes"] = list(nodes_by_code.values())
    seed_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    # If database is reachable and configured, apply merge repointing
    if database_url:
        try:
            import psycopg
            with psycopg.connect(database_url) as conn:
                for n in raw["nodes"]:
                    if n.get("replaced_by"):
                        target = nodes_by_code.get(n["replaced_by"])
                        if target:
                            # Re-point tags from old node to target node
                            conn.execute("""
                                UPDATE question_tags
                                SET taxonomy_id = (SELECT id FROM taxonomy WHERE code = %s)
                                WHERE taxonomy_id = (SELECT id FROM taxonomy WHERE code = %s)
                            """, (target["code"], n["code"]))
                            conn.execute("""
                                UPDATE taxonomy
                                SET is_active = false, replaced_by = (SELECT id FROM taxonomy WHERE code = %s)
                                WHERE code = %s
                            """, (target["code"], n["code"]))
                conn.commit()
        except Exception:
            pass

    return {"applied_count": len(actions_applied), "actions": actions_applied}


# Legacy compatibility for build_taxonomy
def build_taxonomy(syllabus_pdf: Path, version: str | None = None) -> dict[str, Any]:
    return build_taxonomy_v2(syllabus_pdf, version=version)


def write_taxonomy_seed(syllabus_pdf: Path, output: Path, version: str | None = None) -> dict[str, Any]:
    result = build_taxonomy_v2(syllabus_pdf, version=version)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
