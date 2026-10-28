"""MITRE ATT&CK Enterprise technique ids for findings.

The catalog is a pinned snapshot of the active (not revoked, not deprecated)
Enterprise techniques, generated from MITRE's ``attack-stix-data`` release.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib.resources import files
from typing import Any


_TECHNIQUE_ID = re.compile(r"\bT\d{4}(?:\.\d{3})?\b", re.IGNORECASE)


@cache
def _catalog() -> dict[str, Any]:
    raw = files("strix.report").joinpath("attack_catalog.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(raw)
    return data


def attack_version() -> str:
    return str(_catalog()["version"])


def technique(technique_id: str) -> dict[str, Any] | None:
    entry = _catalog()["techniques"].get(technique_id)
    return entry if isinstance(entry, dict) else None


def technique_url(technique_id: str) -> str:
    return f"https://attack.mitre.org/techniques/{technique_id.replace('.', '/')}/"


def normalize_attack_techniques(raw: Any) -> tuple[list[str], list[str]]:
    """Parse technique ids from a list or string and check them against the catalog.

    Returns the ids in first-seen order and one error per id that is not an
    active Enterprise technique.
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
            errors.append(
                f"invalid ATT&CK technique: '{text}' (expected an id like 'T1190' or 'T1059.007')"
            )
            continue
        for technique_id in found:
            if technique_id in techniques:
                continue
            if technique(technique_id) is None:
                errors.append(
                    f"unknown ATT&CK technique: '{technique_id}' is not an active "
                    f"MITRE ATT&CK Enterprise v{attack_version()} technique"
                )
                continue
            techniques.append(technique_id)
    return techniques, errors
