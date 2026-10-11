"""Project Bootstrap (Mission #0) domain contracts and event mappings.

Specification source: Docs/AETP-设计方案.md §§15.5, 5.2, 17.2, INV-019.
"""

from __future__ import annotations

from typing import Dict, FrozenSet

AGGREGATES: Dict[str, str] = {
    "bootstrap": "project",
}

COMMAND_AGGREGATES: Dict[str, str] = {
    "project.bootstrap.finalize": "project",
}

DOMAIN_EVENTS: FrozenSet[str] = frozenset({"project.bootstrap_verified"})

