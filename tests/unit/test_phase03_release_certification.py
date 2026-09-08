from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

from tomiris_agent_roles.builtin import create_builtin_role_registry
from tomiris_agent_roles.definitions import AgentDefinitionLoader

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "deploy" / "hf_space_template"
EXPECTED_TAG = "v0.3-pilot-agents-pass"
EXPECTED_REQUIREMENT = (
    f"tomiris @ git+https://github.com/nuxotetotmailsvoboden-lgtm/Tomiris.git@{EXPECTED_TAG}"
)


def test_phase03_template_has_exact_immutable_release_pin() -> None:
    lines = [
        line.strip()
        for line in (TEMPLATE / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lines == [EXPECTED_REQUIREMENT]
    parsed = Requirement(lines[0])
    assert parsed.name == "tomiris"
    assert parsed.url is not None and parsed.url.endswith(f"@{EXPECTED_TAG}")

    normalized = lines[0].lower()
    assert "@main" not in normalized
    assert re.search(r"@phase[-_/]", normalized) is None
    assert "@v0.2-orchestrator-pass" not in normalized


def test_hf_docker_image_contains_git_and_installs_the_pinned_requirement() -> None:
    dockerfile = (TEMPLATE / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"apt-get install[^\n]*", dockerfile)
    assert "git" in dockerfile
    assert "COPY requirements.txt ./" in dockerfile
    assert "pip install --no-cache-dir -r requirements.txt" in dockerfile


def test_hf_app_imports_the_universal_runtime() -> None:
    tree = ast.parse((TEMPLATE / "app.py").read_text(encoding="utf-8"))
    imports_runtime_app = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "tomiris_agent_runtime.main"
        and any(alias.name == "app" for alias in node.names)
        for node in ast.walk(tree)
    )
    assert imports_runtime_app


def test_phase03_template_documents_analytical_configuration_and_release_policy() -> None:
    documents = [
        TEMPLATE / "README.md",
        ROOT / "docs" / "HF_AGENT_RUNTIME.md",
        ROOT / "docs" / "operations.md",
        ROOT / "docs" / "AGENT_VERSIONING.md",
        ROOT / "docs" / "HOW_TO_ADD_AGENT.md",
        ROOT / "docs" / "HOW_TO_UPGRADE_AGENT.md",
    ]
    for path in documents:
        content = path.read_text(encoding="utf-8")
        assert EXPECTED_TAG in content, path
        assert "v0.2-orchestrator-pass" in content, path

    template_docs = (TEMPLATE / "README.md").read_text(encoding="utf-8")
    assert "TOMIRIS_RUNTIME_MODE=analytical" in template_docs
    assert "TOMIRIS_AGENT_DEFINITION_PATH" in template_docs
    assert "main" in template_docs and "feature branch" in template_docs


def test_current_phase03_codebase_packages_and_loads_every_pilot_role() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    packages = set(project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"])
    assert {
        "src/tomiris_agent_runtime",
        "src/tomiris_agent_roles",
        "src/tomiris_market_data",
        "src/tomiris_features",
    }.issubset(packages)

    registry = create_builtin_role_registry()
    definitions = AgentDefinitionLoader(registry).load_directory(ROOT / "agents" / "definitions")
    assert set(definitions) == {
        "BTC_CONTEXT_001",
        "ETH_TECHNICAL_001",
        "SOL_TECHNICAL_001",
    }
    assert all(registry.build(definition) for definition in definitions.values())
