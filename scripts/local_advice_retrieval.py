"""Offline retrieval-only experiment over allowlisted Pomona operational docs.

No LLM, web access, embeddings, dataset downloads, doses, or actuator commands.
Returns exact source excerpts, not synthesized agronomic recommendations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "calibration-provenance": ("docs/CALIBRATION_PROVENANCE.md", "Non-negotiable rules", {"ph", "ec", "calibration", "calibrate", "probe", "corrected"}),
    "sensor-temporal": ("docs/SENSOR_TEMPORAL_CHECKS.md", "Normal controls (required before enabling)", {"stuck", "flatline", "drift", "sensor", "plateau"}),
    "advice-boundary": ("docs/ADVICE_CARDS.md", "Allowed tools (if agentic later)", {"advice", "pump", "valve", "dosing", "irrigation", "control"}),
    "twin-calibration": ("docs/DIGITAL_TWIN.md", "Calibration of the twin (not probe calibration)", {"twin", "forecast", "rmse", "simulation"}),
}


def section(text: str, heading: str) -> str:
    match = re.search(r"^#{1,6} " + re.escape(heading) + r"\s*$", text, re.M)
    if not match: raise ValueError(f"Missing approved section: {heading}")
    start = match.end()
    end = re.search(r"^#{1,6} ", text[start:], re.M)
    return text[start:start + end.start() if end else len(text)].strip()


def retrieve(query: str, *, root: Path = ROOT) -> dict:
    tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    citations = []
    for source_id, (relative, heading, keywords) in SOURCES.items():
        score = len(tokens & keywords)
        if not score: continue
        raw = (root / relative).read_bytes()
        excerpt = section(raw.decode(), heading)
        citations.append({"source_id": source_id, "path": relative, "section": heading,
                          "document_sha256": hashlib.sha256(raw).hexdigest(),
                          "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                          "excerpt": excerpt, "keyword_score": score})
    citations.sort(key=lambda c: (-c["keyword_score"], c["source_id"]))
    return {"status": "source_excerpts_only" if citations else "insufficient_evidence",
            "citations": citations[:3], "human_review_required": True,
            "limitations": ["Keyword relevance is not claim entailment",
                "Internal operational documentation, not validated crop-treatment guidance",
                "No answer generation or changes to live advice cards"]}


def verify_citation(citation: dict, *, root: Path = ROOT) -> bool:
    """Accept only exact excerpts from an allowlisted section and document version."""
    try:
        path, heading, _ = SOURCES[citation["source_id"]]
        raw = (root / path).read_bytes()
        excerpt = section(raw.decode(), heading)
        return (citation["path"] == path and citation["section"] == heading
                and citation["document_sha256"] == hashlib.sha256(raw).hexdigest()
                and citation["excerpt"] == excerpt
                and citation["excerpt_sha256"] == hashlib.sha256(excerpt.encode()).hexdigest())
    except (KeyError, ValueError, OSError, UnicodeError, TypeError):
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(retrieve(args.query), indent=2))
