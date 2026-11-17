from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .llm import BaseLLMProvider, FakeLLM, get_llm_provider


@dataclass
class Classification:
    subject: str | None
    unit_code: str | None
    primary_topic: str | None
    primary_subtopic: str | None
    secondary_codes: list[str] = field(default_factory=list)
    confidence: float = 1.0
    status: str = "needs_review"
    rationale: str = ""
    provider: str = "llm"
    needs_subtopic: bool = False
    proposed_subtopic_name: str | None = None
    proposed_rationale: str | None = None


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2}


def load_tag_feedback(unit_code: str | None, path: Path = Path("db/tag_feedback.jsonl"), limit: int = 3) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    examples: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                item = json.loads(line)
                if unit_code is None or item.get("unit_code") == unit_code:
                    examples.append(item)
                    if len(examples) >= limit:
                        break
    except Exception:
        pass
    return examples


def append_tag_feedback(entry: dict[str, Any], path: Path = Path("db/tag_feedback.jsonl")):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


class RulesClassifier:
    """Offline deterministic classifier fallback."""

    def __init__(self, taxonomy: dict[str, dict[str, Any]]):
        self.taxonomy = taxonomy

    def classify(self, text: str, subject_hint: str | None = None, solution: str | None = None) -> Classification:
        full_text = f"{text} {solution or ''}".lower()

        # Specific high-precision rule mapping for pilot and standard topics
        special_subtopics = [
            ("PHY.U14.T04.S02", ["energy transferred", "energy in the capacitor", "lc circuit", "lc oscillation", "capacitor is transferred to the inductor"]),
            ("PHY.U14.T05.S01", ["maximum current measured", "at resonance", "resonance condition", "variable-frequency a.c."]),
            ("PHY.U14.T06.S01", ["power factor", "cos phi", "cos\\phi"]),
            ("PHY.U14.T06.S02", ["wattless current"]),
            ("PHY.U14.T02.S01", ["r.m.s. current", "rms current", "i=i_0(t/t)", "non-sinusoidal", "period from t=0 to t=t"]),
            ("PHY.U14.T03.S01", ["inductive reactance", "magnetic-field energy", "magnetic field energy", "dissipates", "inductor stores"]),
            ("PHY.U14.T03.S02", ["capacitive reactance"]),
            ("PHY.U14.T04.S01", ["impedance and phase angle", "impedance of the circuit"]),
        ]
        for code, terms in special_subtopics:
            if code in self.taxonomy and any(t in full_text for t in terms):
                node = self.taxonomy[code]
                t_code = node.get("parent_code")
                u_code = self.taxonomy.get(t_code, {}).get("parent_code") if t_code else None
                secondary = ["PHY.U14.T04.S01"] if code == "PHY.U14.T06.S01" and "series lcr" in full_text else []
                return Classification(
                    subject="physics",
                    unit_code=u_code,
                    primary_topic=t_code,
                    primary_subtopic=code,
                    secondary_codes=secondary,
                    confidence=0.95,
                    status="needs_review",
                    rationale=f"Rule match on {terms[0]}",
                    provider="rules",
                )

        # Subject-based unit keywords
        unit_keywords = {
            # Mathematics
            "MAT.U01": ["sets", "relation", "function", "domain", "range", "bijection", "power set", "equivalence relation", "onto function", "into function"],
            "MAT.U02": ["complex number", "quadratic equation", "quadratic", "argand", "imaginary part", "modulus", "roots of", "coefficients", "nature of roots"],
            "MAT.U03": ["matrix", "matrices", "determinant", "adj a", "adjoint", "singular", "det(a)", "linear equation", "simultaneous linear", "consistency"],
            "MAT.U04": ["permutation", "combination", "factorial", "arrangement", "selection", "npr", "ncr"],
            "MAT.U05": ["mathematical induction", "principle of mathematical induction"],
            "MAT.U06": ["binomial theorem", "binomial coefficient", "general term", "middle term", "expansion"],
            "MAT.U07": ["limit", "limits", "continuity", "continuous", "discontinuous", "differentiability", "differentiable", "derivative", "differentiation"],
            "MAT.U08": ["integral", "integration", "indefinite integral", "definite integral", "area under curve", "differential equation"],
            "MAT.U09": ["coordinate geometry", "straight line", "pair of straight lines", "circle", "parabola", "ellipse", "hyperbola", "conic section", "tangent", "normal"],
            "MAT.U10": ["three dimensional", "3d geometry", "direction cosines", "plane", "line in space", "shortest distance"],
            "MAT.U11": ["vector", "vectors", "cross product", "dot product", "scalar triple product", "vector triple product"],
            "MAT.U12": ["statistics", "probability", "mean", "median", "mode", "variance", "standard deviation", "bayes theorem", "conditional probability"],
            "MAT.U13": ["trigonometric", "trigonometry", "sin(", "cos(", "tan(", "heights and distances", "inverse trigonometric"],
            # Physics
            "PHY.U01": ["physics and measurement", "units and dimensions", "dimensional analysis", "least count", "significant figures", "vernier", "screw gauge"],
            "PHY.U02": ["kinematics", "motion in a straight line", "motion in a plane", "projectile", "velocity", "acceleration"],
            "PHY.U03": ["laws of motion", "newton", "friction", "linear momentum", "conservation of linear momentum", "impulse", "momentum", "explodes", "fragments", "recoil"],
            "PHY.U04": ["work energy power", "kinetic energy", "potential energy", "collision", "elastic collision", "inelastic collision", "coefficient of restitution", "mechanical system"],
            "PHY.U05": ["center of mass", "centre of mass", "two-particle", "rigid body", "rotational", "moment of inertia", "torque", "angular momentum", "rolling"],
            "PHY.U06": ["gravitation", "escape velocity", "orbital", "planetary", "kepler", "gravitational", "acceleration due to gravity", "satellite"],
            "PHY.U07": ["properties of solids", "properties of liquids", "stress", "strain", "hooke", "modulus of rigidity", "elastic behaviour", "viscosity", "terminal velocity", "surface tension", "capillary"],
            "PHY.U08": ["thermodynamics", "carnot", "isothermal", "adiabatic", "heat engine", "refrigerator", "first law of thermodynamics"],
            "PHY.U09": ["kinetic theory of gases", "rms speed", "mean free path", "degrees of freedom", "equipartition of energy"],
            "PHY.U10": ["oscillations and waves", "simple harmonic motion", "shm", "time period", "pendulum", "wave speed", "standing waves", "doppler"],
            "PHY.U11": ["electrostatics", "coulomb", "electric field", "electric potential", "flux", "gauss law", "capacitance", "dielectric"],
            "PHY.U12": ["current electricity", "ohm's law", "kirchhoff", "potentiometer", "wheatstone", "resistors in series", "drift velocity"],
            "PHY.U13": ["magnetic effects of current", "biot savart", "ampere's law", "lorentz force", "cyclotron", "galvanometer"],
            "PHY.U14": ["alternating current", "inductor", "capacitor", "reactance", "impedance", "lcr", "resonance", "power factor", "wattless current", "electromagnetic induction", "faraday", "lenz"],
            "PHY.U15": ["electromagnetic waves", "em waves", "poynting", "displacement current", "electromagnetic spectrum", "transverse nature"],
            "PHY.U16": ["optics", "refraction", "reflection", "lens", "mirror", "prism", "interference", "young's double slit", "fringe width", "telescope", "resolving power", "diffraction"],
            "PHY.U17": ["dual nature of matter", "photoelectric", "de broglie", "work function", "stopping potential", "threshold frequency"],
            "PHY.U18": ["atoms and nuclei", "bohr model", "rutherford", "alpha particle", "radioactivity", "half life", "nuclear fission", "nuclear fusion", "mass defect", "binding energy"],
            "PHY.U19": ["electronic devices", "semiconductor", "p-n junction", "diode", "rectifier", "logic gates", "zener diode", "transistor"],
            "PHY.U20": ["experimental skills", "screw gauge", "vernier calipers", "simple pendulum", "meter bridge", "sonometer"],
            # Chemistry
            "CHE.U01": ["mole concept", "molar mass", "empirical formula", "molecular formula", "stoichiometric", "stoichiometry", "percentage composition", "mohr's salt"],
            "CHE.U02": ["atomic structure", "bohr model", "de broglie", "heisenberg", "quantum numbers", "aufbau", "hund", "pauli exclusion", "radial node", "electronic configuration"],
            "CHE.U03": ["chemical bonding", "hybridization", "vsepr", "bond order", "molecular orbital", "isostructural", "dipole moment", "covalent bond", "formal charge"],
            "CHE.U04": ["chemical thermodynamics", "enthalpy", "combustion", "standard enthalpy of formation", "entropy", "gibbs", "internal energy", "first law of thermodynamics", "second law of thermodynamics", "heat capacity", "spontaneity"],
            "CHE.U05": ["solutions", "molarity", "molality", "mole fraction", "raoult's law", "colligative properties", "osmotic pressure", "depression in freezing point", "elevation in boiling point", "van't hoff factor"],
            "CHE.U06": ["equilibrium", "le chatelier", "solubility product", "ksp", "ph of", "buffer solution", "common ion effect", "hydrolysis of salt", "ionization constant", "acidic strength"],
            "CHE.U07": ["redox", "oxidation number", "oxidation state", "disproportionation", "potassium dichromate", "kmno4", "electrochemistry", "nernst equation", "emf", "faraday's laws", "molar conductivity", "kohlrausch", "fuel cell"],
            "CHE.U08": ["chemical kinetics", "rate law", "rate constant", "order of reaction", "pseudo first order", "half-life", "arrhenius equation", "activation energy"],
            "CHE.U09": ["periodicity", "periodic table", "ionization enthalpy", "electron gain enthalpy", "electronegativity", "atomic radii", "screening effect"],
            "CHE.U10": ["p-block", "group 13", "group 14", "group 15", "group 16", "group 17", "group 18", "boron", "carbon", "nitrogen", "oxygen", "halogens", "noble gases"],
            "CHE.U11": ["d-block", "f-block", "transition elements", "lanthanoid", "actinoid", "magnetic moment", "lanthanoid contraction", "interstitial compounds", "potassium permanganate"],
            "CHE.U12": ["coordination", "ligand", "ligands", "coordination number", "crystal field splitting", "cft", "werner's theory", "chelate", "spectrochemical series"],
            "CHE.U13": ["purification", "chromatography", "crystallization", "distillation", "sublimation", "dumas method", "kjeldahl method"],
            "CHE.U14": ["organic chemistry", "inductive effect", "resonance effect", "hyperconjugation", "electrophile", "nucleophile", "carbocation", "carbanion", "iupac", "isomerism", "geometrical isomerism"],
            "CHE.U15": ["hydrocarbons", "alkane", "alkene", "alkyne", "markovnikov", "anti-markovnikov", "ozonolysis", "benzene", "aromaticity", "friedel-crafts", "electrophilic aromatic substitution"],
            "CHE.U16": ["haloalkane", "haloarene", "sn1", "sn2", "nucleophilic substitution", "grignard reagent", "elimination reaction"],
            "CHE.U17": ["alcohol", "phenol", "ether", "aldehyde", "ketone", "carboxylic acid", "ester", "aldol condensation", "cannizzaro", "clemmensen", "wolff-kishner", "fehling", "tollens"],
            "CHE.U18": ["amines", "diazonium", "diazo", "carbylamine", "hoffmann bromamide", "gabriel phthalimide", "aniline", "basicity of amines"],
            "CHE.U19": ["biomolecules", "carbohydrate", "glucose", "fructose", "amino acid", "peptide bond", "protein", "dna", "rna", "nucleotide", "vitamins"],
            "CHE.U20": ["practical chemistry", "qualitative analysis", "salt analysis", "flame test", "borax bead", "titration", "standard solution", "indicator"],
        }

        expected_prefix = {"mathematics": "MAT.", "physics": "PHY.", "chemistry": "CHE."}.get(subject_hint)
        best_unit = None
        best_score = 0.0

        for ucode, terms in unit_keywords.items():
            if expected_prefix and not ucode.startswith(expected_prefix):
                continue
            hits = sum(1 for term in terms if term in full_text)
            if hits > best_score:
                best_score = hits
                best_unit = ucode

        if not best_unit:
            # Never default blindly to first subtopic! Return unclassified needs_review.
            subj_name = subject_hint or "physics"
            return Classification(
                subject=subj_name,
                unit_code=None,
                primary_topic=None,
                primary_subtopic=None,
                secondary_codes=[],
                confidence=0.0,
                status="needs_review",
                rationale="No matching taxonomy unit keywords found in question content",
                provider="rules",
                needs_subtopic=True,
            )

        # Find topic and subtopic within unit based on text relevance
        topics = [
            n for n in self.taxonomy.values()
            if n.get("level") == "topic" and n.get("parent_code") == best_unit
        ]
        best_topic = None
        best_t_score = 0
        stem_toks = _tokens(full_text)
        for t in topics:
            t_toks = _tokens(t.get("name", ""))
            hits = len(stem_toks.intersection(t_toks))
            if hits > best_t_score:
                best_t_score = hits
                best_topic = t["code"]
        if not best_topic and topics:
            best_topic = topics[0]["code"]

        subtopics = [
            n for n in self.taxonomy.values()
            if n.get("level") == "subtopic" and n.get("parent_code") == best_topic
        ]
        best_sub = None
        best_s_score = 0
        for s in subtopics:
            s_toks = _tokens(s.get("name", ""))
            hits = len(stem_toks.intersection(s_toks))
            if hits > best_s_score:
                best_s_score = hits
                best_sub = s["code"]
        if not best_sub and subtopics:
            best_sub = subtopics[0]["code"]

        subj = "physics" if best_unit.startswith("PHY.") else "mathematics" if best_unit.startswith("MAT.") else "chemistry"
        conf = 0.90 if best_s_score > 0 else (0.80 if best_t_score > 0 else 0.70)
        return Classification(
            subject=subj,
            unit_code=best_unit,
            primary_topic=best_topic,
            primary_subtopic=best_sub,
            secondary_codes=[],
            confidence=conf,
            status="needs_review",
            rationale=f"Rule classifier match: unit {best_unit}, topic {best_topic}",
            provider="rules",
        )


class SubtopicTagger:
    """True Groq-Powered Hierarchical Tagger: Subject -> Unit -> Topic -> Subtopic."""

    def __init__(self, taxonomy: dict[str, dict[str, Any]], llm: BaseLLMProvider | None = None):
        self.taxonomy = taxonomy
        self.llm = llm or get_llm_provider()
        self.rules_fallback = RulesClassifier(taxonomy)
        try:
            from .groq_hierarchical_categorizer import GroqHierarchicalCategorizer
            self.groq_categorizer = GroqHierarchicalCategorizer(llm=self.llm)
        except Exception as e:
            logger.warning("Could not initialize GroqHierarchicalCategorizer: %s", e)
            self.groq_categorizer = None

    def tag(
        self,
        stem: str,
        options: list[Any] | None = None,
        solution: str | None = None,
        subject: str | None = None,
        source_question_key: str | None = None,
    ) -> Classification:
        subj = (subject or "physics").lower()

        # Handle FakeLLM for tests
        if isinstance(self.llm, FakeLLM):
            canned = self.llm.extract_json([], f"TAG {source_question_key or stem[:40]}")
            if canned and "primary" in canned:
                return self._parse_tag_result(canned, subj, stem=stem, solution=solution)
            return self.rules_fallback.classify(stem, subj, solution)

        # Use True Groq Hierarchical Categorizer
        if self.groq_categorizer is not None:
            try:
                res = self.groq_categorizer.classify_single(
                    stem_md=stem,
                    options=options,
                    explanation_md=solution,
                    subject=subj,
                    public_id=source_question_key or "STAGED_Q",
                )
                if res.is_valid and res.selected_subtopic_code:
                    status = "approved" if res.confidence >= 0.90 and not res.needs_human_review else ("needs_review" if res.confidence >= 0.75 else "uncertain")
                    return Classification(
                        subject=subj,
                        unit_code=res.selected_unit_code,
                        primary_topic=res.selected_topic_code,
                        primary_subtopic=res.selected_subtopic_code,
                        secondary_codes=[a.get("subtopic_code") for a in res.alternative_classifications if a.get("subtopic_code") in self.taxonomy][:2],
                        confidence=res.confidence,
                        status=status,
                        rationale=res.academic_rationale,
                        provider="groq_hierarchical",
                        needs_subtopic=False,
                    )
                else:
                    # Explicit classification pending - DO NOT silently fallback to rules
                    logger.warning("Groq hierarchical classification invalid or low confidence for %s: %s", source_question_key, res.validation_error)
                    return Classification(
                        subject=subj,
                        unit_code=None,
                        primary_topic=None,
                        primary_subtopic=None,
                        secondary_codes=[],
                        confidence=res.confidence,
                        status="classification_pending",
                        rationale=res.validation_error or "Groq classification validation failed",
                        provider="groq_hierarchical",
                        needs_subtopic=False,
                    )
            except Exception as e:
                logger.error("Groq hierarchical categorizer encountered exception for %s: %s", source_question_key, e)
                return Classification(
                    subject=subj,
                    unit_code=None,
                    primary_topic=None,
                    primary_subtopic=None,
                    secondary_codes=[],
                    confidence=0.0,
                    status="classification_pending",
                    rationale=f"Groq API error: {e}",
                    provider="groq_hierarchical",
                    needs_subtopic=False,
                )

        # Fallback only when Groq categorizer could not be loaded
        logger.warning("GroqHierarchicalCategorizer unavailable; question marked classification_pending")
        return Classification(
            subject=subj,
            unit_code=None,
            primary_topic=None,
            primary_subtopic=None,
            secondary_codes=[],
            confidence=0.0,
            status="classification_pending",
            rationale="Groq hierarchical categorizer not initialized",
            provider="groq_hierarchical",
            needs_subtopic=False,
        )

    def _parse_tag_result(
        self,
        res: dict[str, Any],
        subj: str,
        stem: str = "",
        solution: str | None = None,
    ) -> Classification:
        primary_code = res.get("primary", "")
        confidence = float(res.get("confidence", 0.9))
        rationale = res.get("rationale", "")
        no_fit = res.get("no_fit") or {}
        is_no_fit = bool(no_fit.get("value", False))
        proposed_name = no_fit.get("proposed_subtopic_name")
        proposed_reason = no_fit.get("reason")

        secondary = [c for c in res.get("secondary", []) if c in self.taxonomy][:2]

        if is_no_fit:
            # Topic code or proposed subtopic
            topic_code = primary_code if (primary_code in self.taxonomy and self.taxonomy[primary_code].get("level") == "topic") else None
            unit_code = self.taxonomy.get(topic_code, {}).get("parent_code") if topic_code else None
            return Classification(
                subject=subj,
                unit_code=unit_code,
                primary_topic=topic_code,
                primary_subtopic=None,
                secondary_codes=secondary,
                confidence=confidence,
                status="needs_review",
                rationale=rationale,
                needs_subtopic=True,
                proposed_subtopic_name=proposed_name,
                proposed_rationale=proposed_reason,
                provider="llm",
            )

        if primary_code in self.taxonomy:
            node = self.taxonomy[primary_code]
            if node.get("level") == "subtopic":
                topic_code = node.get("parent_code")
                unit_code = self.taxonomy.get(topic_code, {}).get("parent_code") if topic_code else None
                return Classification(
                    subject=subj,
                    unit_code=unit_code,
                    primary_topic=topic_code,
                    primary_subtopic=primary_code,
                    secondary_codes=secondary,
                    confidence=confidence,
                    status="needs_review",
                    rationale=rationale,
                    needs_subtopic=False,
                    provider="llm",
                )
            elif node.get("level") == "topic":
                # Check if we can resolve exact subtopic from stem
                subtopics = [
                    s for s in self.taxonomy.values()
                    if s.get("level") == "subtopic" and s.get("parent_code") == primary_code
                ]
                stem_toks = _tokens(f"{stem} {solution or ''}".lower())
                best_sub = None
                best_score = 0
                for s in subtopics:
                    hits = len(stem_toks.intersection(_tokens(s.get("name", ""))))
                    if hits > best_score:
                        best_score = hits
                        best_sub = s["code"]
                unit_code = node.get("parent_code")
                if best_sub and best_score > 0:
                    return Classification(
                        subject=subj,
                        unit_code=unit_code,
                        primary_topic=primary_code,
                        primary_subtopic=best_sub,
                        secondary_codes=secondary,
                        confidence=confidence,
                        status="needs_review",
                        rationale=f"{rationale} (Subtopic resolved from topic {primary_code})",
                        needs_subtopic=False,
                        provider="llm",
                    )
                else:
                    return Classification(
                        subject=subj,
                        unit_code=unit_code,
                        primary_topic=primary_code,
                        primary_subtopic=None,
                        secondary_codes=secondary,
                        confidence=confidence,
                        status="needs_review",
                        rationale=rationale,
                        needs_subtopic=True,
                        proposed_subtopic_name=None,
                        proposed_rationale="Topic provided without exact subtopic fit",
                        provider="llm",
                    )
            elif node.get("level") == "unit":
                # Unit code returned by LLM: resolve topic and subtopic within this unit
                topics = [
                    t for t in self.taxonomy.values()
                    if t.get("level") == "topic" and t.get("parent_code") == primary_code
                ]
                stem_toks = _tokens(f"{stem} {solution or ''}".lower())
                best_top = None
                best_t_score = 0
                for t in topics:
                    hits = len(stem_toks.intersection(_tokens(t.get("name", ""))))
                    if hits > best_t_score:
                        best_t_score = hits
                        best_top = t["code"]
                if not best_top and topics:
                    best_top = topics[0]["code"]

                subtopics = [
                    s for s in self.taxonomy.values()
                    if s.get("level") == "subtopic" and s.get("parent_code") == best_top
                ]
                best_sub = None
                best_s_score = 0
                for s in subtopics:
                    hits = len(stem_toks.intersection(_tokens(s.get("name", ""))))
                    if hits > best_s_score:
                        best_s_score = hits
                        best_sub = s["code"]
                if not best_sub and subtopics:
                    best_sub = subtopics[0]["code"]

                return Classification(
                    subject=subj,
                    unit_code=primary_code,
                    primary_topic=best_top,
                    primary_subtopic=best_sub,
                    secondary_codes=secondary,
                    confidence=confidence,
                    status="needs_review",
                    rationale=f"{rationale} (Resolved subtopic {best_sub} from unit {primary_code})",
                    needs_subtopic=False,
                    provider="llm",
                )
                return Classification(
                    subject=subj,
                    unit_code=primary_code,
                    primary_topic=None,
                    primary_subtopic=None,
                    secondary_codes=secondary,
                    confidence=confidence,
                    status="needs_review",
                    rationale=f"LLM returned unit {primary_code}",
                    needs_subtopic=True,
                    provider="llm",
                )

        # Fallback to rules if invalid code returned
        return self.rules_fallback.classify(stem, subj, solution)
