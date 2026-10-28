"""MITRE ATLAS technique ids for findings in AI systems (LLM apps, agents, RAG).

The catalog is a pinned snapshot of the ATLAS techniques, generated from
MITRE's ``atlas-data`` release.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib.resources import files
from typing import Any


_TECHNIQUE_ID = re.compile(r"\bAML\.T\d{4}(?:\.\d{3})?\b", re.IGNORECASE)


@cache
def _catalog() -> dict[str, Any]:
    raw = files("strix.report").joinpath("atlas_catalog.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(raw)
    return data


def atlas_version() -> str:
    return str(_catalog()["version"])


def technique(technique_id: str) -> dict[str, Any] | None:
    entry = _catalog()["techniques"].get(technique_id)
    return entry if isinstance(entry, dict) else None


def technique_url(technique_id: str) -> str:
    return f"https://atlas.mitre.org/techniques/{technique_id}"


def normalize_atlas_techniques(raw: Any) -> tuple[list[str], list[str]]:
    """Parse ATLAS ids from a list or string and check them against the catalog.

    Returns the ids in first-seen order and one error per id that is not a
    known ATLAS technique.
    """
    if raw is None:
        return [], []
    items = raw if isinstance(raw, list) else [raw]
    techniques: list[str] = []
    errors: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        found = [match.upper() for match in _TECHNIQUE_ID.findall(text)]
        if not found:
            errors.append(f"invalid ATLAS technique: '{text}' (expected an id like 'AML.T0051')")
            continue
        for technique_id in found:
            if technique_id in techniques:
                continue
            if technique(technique_id) is None:
                errors.append(
                    f"unknown ATLAS technique: '{technique_id}' is not a "
                    f"MITRE ATLAS v{atlas_version()} technique"
                )
                continue
            techniques.append(technique_id)
    return techniques, errors
