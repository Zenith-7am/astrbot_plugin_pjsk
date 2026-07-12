import ast
from pathlib import Path


FORBIDDEN_IMPORTS = (
    "pjsk_core.application",
    "pjsk_core.ports",
    "pjsk_core.adapters",
    "pjsk_core.plugin",
    "adapters",
    "plugin",
)


def _import_from_names(node: ast.ImportFrom, package: list[str]) -> list[str]:
    if node.level:
        package = package[: max(0, len(package) - node.level + 1)]
        module = ".".join((*package, *((node.module or "").split("."))))
        module = module.rstrip(".")
    else:
        module = node.module or ""
    if node.module in {None, "pjsk_core"}:
        return [".".join(filter(None, (module, alias.name))) for alias in node.names]
    return [module]


def find_forbidden_imports(domain: Path) -> list[tuple[Path, str]]:
    violations: list[tuple[Path, str]] = []
    for path in domain.rglob("*.py"):
        package = ["pjsk_core", "domain", *path.parent.relative_to(domain).parts]
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = _import_from_names(node, package)
            violations.extend(
                (path, name)
                for name in names
                if any(
                    name == forbidden or name.startswith(f"{forbidden}.")
                    for forbidden in FORBIDDEN_IMPORTS
                )
            )
    return violations


def test_finds_forbidden_imports_in_nested_modules(tmp_path: Path) -> None:
    domain = tmp_path / "pjsk_core" / "domain"
    nested = domain / "nested"
    nested.mkdir(parents=True)
    (nested / "rule.py").write_text(
        "from pjsk_core.application import service\n", encoding="utf-8"
    )

    assert find_forbidden_imports(domain) == [
        (nested / "rule.py", "pjsk_core.application")
    ]


def test_resolves_relative_import_from_nested_module_package(tmp_path: Path) -> None:
    domain = tmp_path / "pjsk_core" / "domain"
    nested = domain / "nested"
    nested.mkdir(parents=True)
    source = nested / "rule.py"
    source.write_text(
        "from ...application import service\n", encoding="utf-8"
    )

    assert find_forbidden_imports(domain) == [
        (source, "pjsk_core.application")
    ]


def test_normalizes_absolute_and_relative_forbidden_imports(tmp_path: Path) -> None:
    domain = tmp_path / "pjsk_core" / "domain"
    domain.mkdir(parents=True)
    source = domain / "rule.py"
    source.write_text(
        "import adapters.sqlite\n"
        "from pjsk_core import ports\n"
        "from pjsk_core.adapters import cache\n"
        "from ..application import submit_score\n"
        "from .. import ports\n"
        "from .. import adapters\n"
        "from .. import plugin\n"
        "from ...plugin import presenter\n",
        encoding="utf-8",
    )

    assert find_forbidden_imports(domain) == [
        (source, "adapters.sqlite"),
        (source, "pjsk_core.ports"),
        (source, "pjsk_core.adapters"),
        (source, "pjsk_core.application"),
        (source, "pjsk_core.ports"),
        (source, "pjsk_core.adapters"),
        (source, "pjsk_core.plugin"),
        (source, "plugin"),
    ]


def test_domain_does_not_import_outer_layers() -> None:
    domain_path = Path("pjsk_core/domain")
    assert domain_path.is_dir(), "the domain package must exist"
    assert find_forbidden_imports(domain_path) == []
