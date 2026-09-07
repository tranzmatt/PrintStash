"""Static import contracts for product modules, including deferred imports.

This tool reads source only: importing the application would construct runtime
dependencies and would miss imports hidden inside functions. TYPE_CHECKING-only
edges are excluded from cycles but still checked for private implementation use.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class Dependency:
    source: str
    target: str
    symbol: str = ""
    runtime: bool = True

    @property
    def key(self) -> str:
        return f"{self.source} -> {self.target}"

    @property
    def private_key(self) -> str:
        return f"{self.key}.{self.symbol}"


def module_name(path: Path, root: Path) -> str:
    parts = path.relative_to(root).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports(source: str, name: str, *, package: bool = False) -> set[Dependency]:
    result: set[Dependency] = set()

    class Visitor(ast.NodeVisitor):
        runtime = True

        def __init__(self) -> None:
            self.aliases: dict[str, str] = {}

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            previous = self.aliases.copy()
            self.generic_visit(node)
            self.aliases = previous

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_If(self, node: ast.If) -> None:
            if ast.unparse(node.test) not in {"TYPE_CHECKING", "typing.TYPE_CHECKING"}:
                self.generic_visit(node)
                return
            previous = self.runtime
            self.runtime = False
            for child in node.body:
                self.visit(child)
            self.runtime = previous
            for child in node.orelse:
                self.visit(child)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                result.add(Dependency(name, alias.name, runtime=self.runtime))
                self.aliases[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            target = node.module or ""
            if node.level:
                parent = name if package else name.rpartition(".")[0]
                prefix = parent.split(".")[: len(parent.split(".")) - node.level + 1]
                target = ".".join([*prefix, *([target] if target else [])])
            for alias in node.names:
                result.add(Dependency(name, target, alias.name, self.runtime))
                self.aliases[alias.asname or alias.name] = f"{target}.{alias.name}"

        def visit_Attribute(self, node: ast.Attribute) -> None:
            parts = []
            value = node
            while isinstance(value, ast.Attribute):
                parts.append(value.attr)
                value = value.value
            if (
                isinstance(value, ast.Name)
                and value.id in self.aliases
                and (
                    (node.attr.startswith("_") and not node.attr.startswith("__"))
                    or (
                        name.startswith("app.api.")
                        and self.aliases[value.id].startswith("app.")
                    )
                )
            ):
                target = ".".join([self.aliases[value.id], *reversed(parts[1:])])
                result.add(Dependency(name, target, node.attr, self.runtime))
            self.generic_visit(node)

    Visitor().visit(ast.parse(source))
    return result


def graph_for(dependencies: set[Dependency], modules: set[str]) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {name: set() for name in modules}
    for dependency in dependencies:
        if not dependency.runtime:
            continue
        target = f"{dependency.target}.{dependency.symbol}"
        if target not in modules:
            target = dependency.target
        if target in modules and target != dependency.source:
            graph[dependency.source].add(target)
    return graph


def cyclic_edges(graph: dict[str, set[str]]) -> set[str]:
    """Return edges within strongly connected groups, not downstream dependents."""
    counter = 0
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    edges: set[str] = set()

    def visit(source: str) -> None:
        nonlocal counter
        indices[source] = low[source] = counter
        counter += 1
        stack.append(source)
        active.add(source)
        for target in graph[source]:
            if target not in indices:
                visit(target)
                low[source] = min(low[source], low[target])
            elif target in active:
                low[source] = min(low[source], indices[target])
        if low[source] != indices[source]:
            return
        group: set[str] = set()
        while True:
            target = stack.pop()
            active.remove(target)
            group.add(target)
            if target == source:
                break
        if len(group) > 1:
            edges.update(
                f"{member} -> {target}"
                for member in group
                for target in graph[member]
                if target in group
            )

    for name in graph:
        if name not in indices:
            visit(name)
    return edges


def owner(name: str) -> str:
    parts = name.split(".")
    if len(parts) >= 3 and parts[:2] == ["app", "modules"]:
        return ".".join(parts[:3])
    return ".".join(parts[:2])


def violations(dependencies: set[Dependency]) -> set[str]:
    return {
        dependency.private_key
        for dependency in dependencies
        if dependency.target.startswith("app.modules.")
        and owner(dependency.source) != owner(dependency.target)
        and (
            dependency.symbol.startswith("_")
            or any(part.startswith("_") for part in dependency.target.split(".")[3:])
        )
    }


def implicit_api_exports(
    dependencies: set[Dependency], sources: dict[str, str]
) -> set[str]:
    """Imported dependencies are not operation APIs unless explicitly exported."""
    hidden: dict[str, set[str]] = {}
    for name, source in sources.items():
        if not name.startswith("app.modules."):
            continue
        imported: set[str] = set()
        exported: set[str] = set()
        for node in ast.parse(source).body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imported.update(
                    alias.asname or alias.name.split(".")[0] for alias in node.names
                )
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                exported.update(ast.literal_eval(node.value))
        hidden[name] = imported - exported

    result: set[str] = set()
    for dependency in dependencies:
        if not dependency.source.startswith("app.api."):
            continue
        reference = f"{dependency.target}.{dependency.symbol}".rstrip(".")
        parts = reference.split(".")
        for boundary in range(len(parts) - 1, 2, -1):
            module = ".".join(parts[:boundary])
            if module in hidden:
                member = parts[boundary]
                if member in hidden[module]:
                    result.add(f"{dependency.source} -> {module}.{member}")
                break
    return result


def inspect(root: Path) -> dict[str, list[str]]:
    paths = list((root / "app").rglob("*.py"))
    sources = {module_name(path, root): path.read_text() for path in paths}
    modules = {module_name(path, root) for path in paths}
    dependencies = set().union(
        *(
            imports(
                path.read_text(),
                module_name(path, root),
                package=path.name == "__init__.py",
            )
            for path in paths
        )
    )
    return {
        "cyclic_dependencies": sorted(cyclic_edges(graph_for(dependencies, modules))),
        "private_dependencies": sorted(
            violations(dependencies) | implicit_api_exports(dependencies, sources)
        ),
        "legacy_imports": sorted(
            {
                dependency.key
                for dependency in dependencies
                if dependency.target == "app.services"
                or dependency.target.startswith("app.services.")
            }
        ),
        "transport_dependencies": sorted(
            {
                dependency.key
                for dependency in dependencies
                if dependency.source.startswith(("app.modules.", "app.runtime."))
                and (
                    dependency.target.startswith(("app.api", "app.bootstrap"))
                    or dependency.target == "fastapi"
                    or dependency.target.startswith("fastapi.")
                    or dependency.target
                    in {
                        "starlette.requests",
                        "starlette.responses",
                        "starlette.exceptions",
                        "starlette.websockets",
                    }
                )
            }
        ),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    current = inspect(root)
    baseline = json.loads((root / "architecture-debt.json").read_text())
    if any(baseline.values()):
        raise SystemExit(
            "Architecture debt is resolved; new exceptions are prohibited."
        )
    errors = {
        kind: {
            "new": sorted(set(values) - set(baseline.get(kind, []))),
            "resolved": sorted(set(baseline.get(kind, [])) - set(values)),
        }
        for kind, values in current.items()
        if set(values) != set(baseline.get(kind, []))
    }
    if errors:
        raise SystemExit(json.dumps(errors, indent=2))
    print(
        "Architecture contracts hold; recorded debt:",
        {key: len(value) for key, value in current.items()},
    )


if __name__ == "__main__":
    main()
