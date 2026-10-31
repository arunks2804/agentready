"""Static readiness checks. These only read files; they never execute repo code."""
import os
import re
from pathlib import Path

DIMENSIONS = [
    ("discovery", "Discovery"),
    ("code_understanding", "Code understanding"),
    ("api_context", "API context"),
    ("build_environment", "Build environment"),
    ("testing", "Testing"),
    ("debugging", "Debugging and observability"),
    ("delivery", "Delivery workflow"),
    ("task_context", "Task context"),
]
SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}
MAX_FILES = 5000
MAX_BYTES = 1_000_000
TEST_COMMAND = re.compile(
    r"(python3? -m (?:unittest|pytest)[^\n`]*|pytest[^\n`]*|npm (?:run )?test[^\n`]*)"
)


class Repo:
    def __init__(self, path):
        self.root = Path(path)
        self.files = []
        for base, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in names:
                full = Path(base) / name
                if not full.is_symlink():
                    self.files.append(full.relative_to(self.root).as_posix())
            if len(self.files) >= MAX_FILES:
                break
        self.files.sort()

    def has(self, *candidates):
        lowered = {f.lower(): f for f in self.files}
        for candidate in candidates:
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]
        return None

    def read(self, rel):
        path = self.root / rel
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def source_files(self):
        return [
            f for f in self.files
            if f.endswith((".py", ".js", ".ts", ".go", ".java"))
            and not f.startswith(("tests/", "test/")) and "/tests/" not in f
        ]

    def docs_text(self):
        names = [f for f in self.files if f.lower().endswith(".md")]
        return "\n".join(self.read(f) for f in names)


def file_evidence(rel, detail, line=None):
    return {"kind": "file", "provenance": "measured", "ref": rel, "line": line, "detail": detail}


def absent_evidence(detail):
    return {"kind": "absent", "provenance": "measured", "ref": None, "line": None, "detail": detail}


def find_test_command(repo):
    for name in ("AGENTS.md", "CLAUDE.md", "README.md", "CONTRIBUTING.md"):
        rel = repo.has(name)
        if rel:
            match = TEST_COMMAND.search(repo.read(rel))
            if match:
                return rel, match.group(1).strip()
    return None, None


def parse_catalog(repo):
    rel = repo.has("catalog-info.yaml", "catalog-info.yml")
    if not rel:
        return None, {}
    fields = {}
    for line in repo.read(rel).splitlines():
        match = re.match(r"^(name|owner|description):\s*(.+)$", line.strip())
        if match:
            fields[match.group(1)] = match.group(2).strip()
    return rel, fields


def env_vars_used(repo):
    used = {}
    pattern = re.compile(r"""(?:os\.environ\[|os\.environ\.get\(|os\.getenv\(|process\.env\.)["']?(\w+)""")
    for rel in repo.source_files():
        for number, line in enumerate(repo.read(rel).splitlines(), 1):
            for name in pattern.findall(line):
                used.setdefault(name, (rel, number))
    return used


def _exists_check(repo, candidates, found, missing):
    rel = repo.has(*candidates)
    return (True, [file_evidence(rel, found)]) if rel else (False, [absent_evidence(missing)])


def check_catalog(repo):
    rel, fields = parse_catalog(repo)
    if not rel:
        return False, [absent_evidence("No catalog-info.yaml, so an agent cannot find this service by what it does.")]
    gaps = [k for k in ("name", "owner", "description") if k not in fields]
    if gaps:
        return False, [file_evidence(rel, f"Catalog entry is missing: {', '.join(gaps)}.")]
    return True, [file_evidence(rel, f"Registered as {fields['name']}, owned by {fields['owner']}.")]


def check_codeowners(repo):
    return _exists_check(repo, ["CODEOWNERS", ".github/CODEOWNERS"],
                         "Code ownership is declared.", "No CODEOWNERS file.")


def check_readme(repo):
    rel = repo.has("README.md")
    if not rel:
        return False, [absent_evidence("No README.md.")]
    words = len(repo.read(rel).split())
    detail = f"README has {words} words."
    return words >= 30, [file_evidence(rel, detail if words >= 30 else f"{detail} Too short to explain the service.")]


def check_architecture(repo):
    return _exists_check(repo, ["docs/architecture.md", "ARCHITECTURE.md"],
                         "Architecture overview present.", "No architecture overview.")


def check_agent_guide(repo):
    return _exists_check(repo, ["AGENTS.md", "CLAUDE.md"],
                         "Agent instructions present.", "No AGENTS.md or CLAUDE.md.")


def check_api_spec(repo):
    return _exists_check(repo, ["openapi.yaml", "openapi.yml", "openapi.json", "docs/openapi.yaml"],
                         "API contract published.", "No OpenAPI contract found.")


def check_api_examples(repo):
    rel = repo.has("openapi.yaml", "openapi.yml", "openapi.json", "docs/openapi.yaml")
    if not rel:
        return False, [absent_evidence("No API contract, so no usage examples.")]
    has_example = "example" in repo.read(rel)
    return has_example, [file_evidence(rel, "Contract includes examples." if has_example else "Contract has no examples.")]


def check_dependencies(repo):
    return _exists_check(repo, ["requirements.txt", "pyproject.toml", "package.json", "go.mod"],
                         "Dependency manifest present.", "No dependency manifest.")


def check_setup_docs(repo):
    text = repo.docs_text()
    match = re.search(r"^#+\s*(setup|getting started|install\w*)", text, re.I | re.M)
    if match:
        return True, [file_evidence(repo.has("README.md") or "docs", f"Found section “{match.group(1)}”.")]
    return False, [absent_evidence("No setup section in any Markdown file.")]


def check_env_vars(repo):
    used = env_vars_used(repo)
    documented = repo.read(repo.has(".env.example") or "") + repo.docs_text()
    missing = [(name, where) for name, where in used.items() if name not in documented]
    if missing:
        return False, [
            file_evidence(where[0], f"{name} is read here but not documented anywhere.", where[1])
            for name, where in missing
        ]
    if not used:
        return True, [absent_evidence("Source reads no environment variables.")]
    return True, [file_evidence(repo.has(".env.example") or "docs", f"All {len(used)} variable(s) are documented.")]


def check_tests_exist(repo):
    tests = [f for f in repo.files if re.search(r"(^|/)(tests?/|test_[^/]+\.py$)", f)]
    if tests:
        return True, [file_evidence(tests[0], f"{len(tests)} test file(s) found.")]
    return False, [absent_evidence("No tests found.")]


def check_test_command(repo):
    rel, command = find_test_command(repo)
    if rel:
        return True, [file_evidence(rel, f"Documented command: {command}")]
    return False, [absent_evidence("No test command in AGENTS.md, CLAUDE.md, README.md or CONTRIBUTING.md.")]


def check_logging(repo):
    prints = []
    for rel in repo.source_files():
        for number, line in enumerate(repo.read(rel).splitlines(), 1):
            if re.match(r"\s*print\(", line):
                prints.append((rel, number))
    if prints:
        return False, [file_evidence(r, "Uses print() instead of structured logging.", n) for r, n in prints[:3]]
    return True, [absent_evidence("No print() calls in service source.")]


def check_runbook(repo):
    return _exists_check(repo, ["docs/runbook.md", "RUNBOOK.md"], "Runbook present.", "No runbook.")


def check_ci(repo):
    workflows = [f for f in repo.files if f.startswith(".github/workflows/")]
    if workflows or repo.has(".gitlab-ci.yml", "Jenkinsfile"):
        return True, [file_evidence(workflows[0] if workflows else "CI config", "CI pipeline defined in the repo.")]
    return False, [absent_evidence("No CI configuration, so required checks are invisible to an agent.")]


def check_definition_of_done(repo):
    if re.search(r"definition of done", repo.docs_text(), re.I):
        return True, [file_evidence(repo.has("CONTRIBUTING.md") or "docs", "Definition of done is written down.")]
    return False, [absent_evidence("No written definition of done.")]


def check_issue_template(repo):
    templates = [f for f in repo.files if f.startswith(".github/ISSUE_TEMPLATE/")]
    if not templates:
        return False, [absent_evidence("No issue template, so tickets arrive without acceptance criteria.")]
    has_criteria = any("acceptance criteria" in repo.read(f).lower() for f in templates)
    detail = "Template asks for acceptance criteria." if has_criteria else "Template omits acceptance criteria."
    return has_criteria, [file_evidence(templates[0], detail)]


CHECKS = [
    ("catalog_entry", "discovery", "high", "Service is registered in the catalog", check_catalog,
     "Add catalog-info.yaml with name, owner and a description of what the service does."),
    ("codeowners", "discovery", "medium", "Code ownership is declared", check_codeowners,
     "Add a CODEOWNERS file naming the owning team."),
    ("readme_overview", "code_understanding", "medium", "README explains the service", check_readme,
     "Describe what the service owns, its boundaries and its key conventions."),
    ("architecture_doc", "code_understanding", "low", "Architecture is documented", check_architecture,
     "Add docs/architecture.md covering components and dependencies."),
    ("agent_guide", "code_understanding", "low", "Agent instructions exist", check_agent_guide,
     "Add AGENTS.md with commands, layout and conventions."),
    ("api_spec", "api_context", "high", "API contract is published", check_api_spec,
     "Publish an OpenAPI contract in the repository."),
    ("api_examples", "api_context", "low", "API contract has examples", check_api_examples,
     "Add request and response examples to the contract."),
    ("dependency_manifest", "build_environment", "medium", "Dependencies are declared", check_dependencies,
     "Declare dependencies in a manifest."),
    ("setup_documented", "build_environment", "medium", "Setup is documented", check_setup_docs,
     "Add a setup section with the steps to run the service."),
    ("env_vars_documented", "build_environment", "high", "Required settings work", check_env_vars,
     "Add a working sample settings file, including any files it points to."),
    ("tests_exist", "testing", "high", "Tests exist", check_tests_exist,
     "Add automated tests covering core behaviour."),
    ("test_command_documented", "testing", "high", "Test command is documented", check_test_command,
     "State the exact test command in AGENTS.md or the README."),
    ("structured_logging", "debugging", "medium", "Service uses structured logging", check_logging,
     "Replace print() with the logging module."),
    ("runbook", "debugging", "low", "Runbook exists", check_runbook,
     "Add docs/runbook.md with error codes and where to find logs and traces."),
    ("ci_config", "delivery", "medium", "CI is defined in the repo", check_ci,
     "Add a CI workflow so required checks are visible."),
    ("definition_of_done", "delivery", "low", "Definition of done is written", check_definition_of_done,
     "State review and release requirements in CONTRIBUTING.md."),
    ("issue_template", "task_context", "medium", "Tickets capture acceptance criteria", check_issue_template,
     "Add an issue template with an acceptance criteria section."),
]
CHECK_INDEX = {c[0]: c for c in CHECKS}


def run_checks(path):
    repo = Repo(path)
    results = []
    for check_id, dimension, severity, title, fn, recommendation in CHECKS:
        passed, evidence = fn(repo)
        results.append({
            "check_id": check_id, "dimension": dimension, "severity": severity, "title": title,
            "passed": passed, "evidence": evidence, "recommendation": recommendation,
        })
    return results


def score(results):
    """Weighted share of passing checks per dimension, then an unweighted mean."""
    by_dimension = {}
    for key, _ in DIMENSIONS:
        rows = [r for r in results if r["dimension"] == key]
        total = sum(SEVERITY_WEIGHT[r["severity"]] for r in rows)
        passed = sum(SEVERITY_WEIGHT[r["severity"]] for r in rows if r["passed"])
        by_dimension[key] = round(100 * passed / total) if total else 0
    overall = round(sum(by_dimension.values()) / len(by_dimension))
    return overall, by_dimension
