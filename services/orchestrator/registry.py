"""Loads + Pydantic-validates every services/agents/*/manifest.yaml.

An invalid manifest makes that agent UNAVAILABLE — it is never rendered
partially (spec.md §1). Dirs whose name starts with '_' or '.' are hidden
(e.g. the `_echo` test agent) and skipped unless `include_hidden=True`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from agents.manifest import Manifest
from pydantic import ValidationError

_AGENTS_DIR = Path(__file__).resolve().parents[1] / "agents"


@dataclass(frozen=True)
class AgentEntry:
    id: str
    dir: Path
    manifest: Manifest | None
    available: bool
    error: str | None


def _load_one(mf_path: Path) -> AgentEntry:
    d = mf_path.parent
    try:
        raw = yaml.safe_load(mf_path.read_text()) or {}
    except yaml.YAMLError as e:
        return AgentEntry(d.name, d, None, False, f"yaml error: {e}")

    rid = str(raw.get("id") or d.name)
    try:
        m = Manifest.model_validate(raw)
    except ValidationError as e:
        return AgentEntry(rid, d, None, False, f"invalid manifest: {e}")
    return AgentEntry(m.id, d, m, True, None)


def load_registry(
    agents_dir: Path | None = None, *, include_hidden: bool = False
) -> dict[str, AgentEntry]:
    base = agents_dir or _AGENTS_DIR
    out: dict[str, AgentEntry] = {}
    for mf in sorted(base.glob("*/manifest.yaml")):
        if not include_hidden and mf.parent.name.startswith(("_", ".")):
            continue
        entry = _load_one(mf)
        out[entry.id] = entry
    return out


@lru_cache
def registry() -> dict[str, AgentEntry]:
    return load_registry()


def available_manifests() -> list[Manifest]:
    return [e.manifest for e in registry().values() if e.available and e.manifest]


def get(agent_id: str) -> AgentEntry:
    r = registry()
    if agent_id not in r:
        raise KeyError(f"no agent {agent_id!r}")
    return r[agent_id]
