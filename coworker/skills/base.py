"""Skill loading — Anthropic SKILL.md format with progressive disclosure.

A skill is a folder containing `SKILL.md` (YAML frontmatter: name, description,
optional allowed-tools) + a markdown body of instructions + optional resources/scripts.

Progressive disclosure: at session start only the catalog (name + description) is injected
into the agent's context; the full body is loaded on demand via the `load_skill` tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import aisuite as ai


@dataclass
class Skill:
    name: str
    description: str
    instructions: str = ""  # full body — loaded on demand
    path: Optional[str] = None
    allowed_tools: list[str] = field(default_factory=list)


class SkillLoader:
    def __init__(self, dirs: list[str | Path]) -> None:
        self._skills: dict[str, Skill] = {}
        for directory in dirs:
            self._discover(Path(directory))

    def _discover(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for sub in sorted(directory.iterdir()):
            md = sub / "SKILL.md"
            if md.is_file():
                skill = _parse_skill(md)
                self._skills[skill.name] = skill

    def names(self) -> list[str]:
        return list(self._skills)

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def catalog(self) -> list[dict]:
        return [
            {"name": s.name, "description": s.description}
            for s in self._skills.values()
        ]


def _parse_skill(md: Path) -> Skill:
    text = md.read_text(encoding="utf-8")
    name, description, allowed, body = md.parent.name, "", [], text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            frontmatter = text[3:end]
            body = text[end + 4 :].lstrip("\n")
            fm = _parse_frontmatter(frontmatter)
            name = str(fm.get("name") or name)
            description = str(fm.get("description") or "")
            allowed = _as_tool_list(fm.get("allowed-tools") or fm.get("allowed_tools"))
    return Skill(
        name=name,
        description=description,
        instructions=body.strip(),
        path=str(md.parent),
        allowed_tools=allowed,
    )


def _parse_frontmatter(frontmatter: str) -> dict:
    """Parse SKILL.md YAML frontmatter. Real YAML (via pyyaml) so folded/blocked
    descriptions (`description: >` + indented lines) and block-list `allowed-tools`
    — both common in Claude Desktop / Claude Code skills — are read correctly, not
    mangled by a line splitter. Falls back to a tolerant line parser if pyyaml is
    absent or the block isn't a mapping."""
    try:
        import yaml

        data = yaml.safe_load(frontmatter)
        if isinstance(data, dict):
            return {str(k).strip().lower(): v for k, v in data.items()}
    except Exception:
        pass
    out: dict = {}
    for line in frontmatter.splitlines():
        if ":" not in line or line[:1] in (" ", "\t", "-"):
            continue  # skip continuation/list lines a flat parser can't place
        key, value = line.split(":", 1)
        out[key.strip().lower()] = value.strip()
    return out


def _as_tool_list(value) -> list[str]:
    """Normalize allowed-tools from YAML (a block/flow list) or a comma string."""
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return []


def skill_catalog_text(loader: SkillLoader) -> str:
    catalog = loader.catalog()
    if not catalog:
        return ""
    lines = [f"- {c['name']}: {c['description']}" for c in catalog]
    return (
        "Available skills — call load_skill(name) to load one's full instructions when "
        "it's relevant to the task:\n" + "\n".join(lines)
    )


def skill_tools(loader: SkillLoader) -> list:
    def load_skill(name: str) -> dict:
        """Load a skill's full instructions + resources path by name. Call this when a
        skill from the catalog is relevant to the current task."""
        skill = loader.get(name)
        if skill is None:
            return {"error": f"unknown skill: {name}", "available": loader.names()}
        return {
            "name": skill.name,
            "instructions": skill.instructions,
            "resources_path": skill.path,
        }

    return [
        ai.tool(
            load_skill,
            metadata=ai.ToolMetadata(
                category="skills", risk_level="low", capabilities=["load_skill"]
            ),
        )
    ]
