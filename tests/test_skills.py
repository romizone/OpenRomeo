"""Agents (Code/Chat) + SKILL.md loader (catalog + load_skill)."""

from __future__ import annotations

from coworker.agent import build_engine
from coworker.agents import AgentContext, chat_agent, code_agent, get_agent
from coworker.providers import ModelCapabilities
from coworker.skills import SkillLoader, skill_catalog_text, skill_tools
from coworker.tools import ToolRegistry
from coworker.tools.shell import LocalExecutor
from coworker.tools.todo import TodoList


class _Stub:
    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()


# -- agents ---------------------------------------------------------------------


def test_code_agent_tools(tmp_path):
    ex = LocalExecutor(cwd=tmp_path, default_timeout=5)
    try:
        ctx = AgentContext(workspace=tmp_path, executor=ex, todo=TodoList())
        names = {getattr(t, "__name__", "?") for t in code_agent().build_tools(ctx)}
        assert {
            "read_file",
            "write_file",
            "git_status",
            "run_shell",
            "todo_write",
        } <= names
    finally:
        ex.close()


def test_chat_agent_has_no_workspace_tools():
    assert chat_agent().build_tools(AgentContext()) == []
    assert chat_agent().needs_workspace is False
    assert code_agent().needs_workspace is True


def test_get_agent_fallback():
    assert get_agent("chat").name == "chat"
    # Unknown ids fall back to the default persona (Cowork), per the persona registry.
    assert get_agent("nope").name == "cowork"


# -- SKILL.md loader ------------------------------------------------------------


def _make_skill(skills_dir, name, desc, body):
    d = skills_dir / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n{body}", encoding="utf-8"
    )


def test_skill_frontmatter_parses_yaml_folded_and_block_list(tmp_path):
    """Claude Desktop / Claude Code skills commonly use folded (`>`) descriptions and
    YAML block-list allowed-tools — the parser must read real YAML, not split lines."""
    d = tmp_path / "skills" / "fancy"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\n"
        "name: fancy\n"
        "description: >\n"
        "  A multi-line description that folds\n"
        "  across two source lines: with a colon.\n"
        "allowed-tools:\n"
        "  - Bash\n"
        "  - Read\n"
        "---\n"
        "Body.",
        encoding="utf-8",
    )
    skill = SkillLoader([tmp_path / "skills"]).get("fancy")
    assert "folds across two source lines: with a colon." in skill.description
    assert skill.allowed_tools == ["Bash", "Read"]


def test_skill_loader_catalog_and_load(tmp_path):
    skills_dir = tmp_path / "skills"
    _make_skill(
        skills_dir, "pdf", "extract text from PDFs", "Use pdfplumber to extract text."
    )
    loader = SkillLoader([skills_dir])

    assert loader.catalog() == [
        {"name": "pdf", "description": "extract text from PDFs"}
    ]
    assert "pdf: extract text from PDFs" in skill_catalog_text(loader)

    reg = ToolRegistry()
    reg.register_all(skill_tools(loader))
    loaded = reg.execute("load_skill", {"name": "pdf"})
    assert "pdfplumber" in loaded["instructions"]
    assert reg.execute("load_skill", {"name": "missing"})["error"]


# -- builtin document skills (docx / pptx / pdf) ---------------------------------


def test_builtin_document_skills_ship_with_every_workspace_engine(tmp_path):
    engine = build_engine(agent=code_agent(), workspace=tmp_path, provider=_Stub())
    try:
        names = {c["name"] for c in engine.skill_loader.catalog()}
        assert {"docx", "pptx", "xlsx", "pdf"} <= names
        loaded = engine.registry.execute("load_skill", {"name": "docx"})
        assert "python-docx" in loaded["instructions"]
        assert loaded["resources_path"]
        assert (
            "openpyxl"
            in engine.registry.execute("load_skill", {"name": "xlsx"})["instructions"]
        )
    finally:
        engine.executor.close()


def test_workspace_skill_overrides_builtin(tmp_path):
    ws_skills = tmp_path / ".coworker" / "skills"
    _make_skill(ws_skills, "pdf", "custom pdf flow", "Use my in-house pdf pipeline.")
    engine = build_engine(agent=code_agent(), workspace=tmp_path, provider=_Stub())
    try:
        loaded = engine.registry.execute("load_skill", {"name": "pdf"})
        assert "in-house" in loaded["instructions"]
    finally:
        engine.executor.close()


# -- engine assembly per agent --------------------------------------------------


def test_build_engine_chat_without_a_workspace_is_pure_chat(tmp_path):
    """Direct callers (TUI, /v1/chat/completions) that hand Chat no workspace still get the
    old workspace-less surface: `expand` skips every capability whose context is missing, so
    nothing advertises a tool the session can't run."""
    engine = build_engine(agent=chat_agent(), provider=_Stub())
    assert "load_skill" not in engine.registry.names()
    assert "read_file" not in engine.registry.names()
    assert engine.skill_loader is None
    assert engine.executor is None
    assert engine.agent_name == "chat"
    # What it DOES keep: the Claude-Chat-style basics (web + memory arrive via the
    # manager's memory_store wiring; web tools register unconditionally).
    assert "web_search" in engine.registry.names()
    assert "web_fetch" in engine.registry.names()


def test_build_engine_chat_with_scratch_can_produce_documents(tmp_path):
    """Given the scratch dir the manager provisions, Chat gets the full deliverable loop:
    files + shell to run python-docx/openpyxl, the skill catalog that teaches it how, and
    view_file to look at what it produced."""
    engine = build_engine(agent=chat_agent(), workspace=tmp_path, provider=_Stub())
    try:
        names = set(engine.registry.names())
        assert {
            "read_file",
            "write_file",
            "run_shell",
            "load_skill",
            "view_file",
        } <= names
        assert engine.skill_loader is not None
        assert engine.executor is not None
        catalog = engine.messages[0]["content"]
        for skill in ("docx", "xlsx", "pptx", "pdf"):
            assert skill in catalog
    finally:
        engine.executor.close()


def test_build_engine_code_has_agents_md_and_skills(tmp_path):
    (tmp_path / "AGENTS.md").write_text("PROJECT RULE: prefer pathlib.")
    engine = build_engine(agent=code_agent(), workspace=tmp_path, provider=_Stub())
    try:
        assert "prefer pathlib" in engine.messages[0]["content"]
        assert "todo_write" in engine.registry.names()
        assert "load_skill" in engine.registry.names()
        assert engine.agent_name == "code"
    finally:
        engine.executor.close()
