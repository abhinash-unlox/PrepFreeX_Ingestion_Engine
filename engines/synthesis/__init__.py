"""Embibe-style Parametric Variant Synthesis & Blind-Solver Verification Engine."""
from engines.synthesis.embibe_variant_engine import (
    generate_variant_candidate,
    blind_solve_candidate,
    verify_and_ingest_variant,
)

__all__ = [
    "generate_variant_candidate",
    "blind_solve_candidate",
    "verify_and_ingest_variant",
]

