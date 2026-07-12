import ast
from pathlib import Path


def test_domain_does_not_import_outer_layers() -> None:
    domain_path = Path("pjsk_core/domain")
    assert domain_path.is_dir(), "the domain package must exist"

    forbidden = ("pjsk_core.application", "pjsk_core.ports", "adapters", "plugin")
    for path in domain_path.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(name.startswith(forbidden) for name in imports), path
