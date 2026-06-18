"""Shared contract parsing for the metadata gate and verification generator."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

TAG_RE = re.compile(r"@(\w+)\b")


@dataclass(frozen=True)
class FunctionContract:
    rel_path: str
    lineno: int
    qualname: str
    module: str  # import path, e.g. linkshort.shorten
    name: str
    intent: str
    params: tuple[str, ...]
    returns: str | None
    raises: tuple[str, ...]
    feature: str | None
    flag: str | None
    entity_id: str  # src/linkshort/shorten.py#create_short_link

    @property
    def loc(self) -> str:
        return f"{self.rel_path}:{self.lineno} {self.qualname}()"


def parse_tags(docstring: str) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {}
    current = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if current is not None:
            tags.setdefault(current, []).append(" ".join(buffer).strip())
        buffer = []

    for raw in docstring.splitlines():
        line = raw.strip()
        m = TAG_RE.match(line)
        if m:
            flush()
            current = m.group(1)
            buffer = [line[m.end():].strip()]
        elif current is not None:
            buffer.append(line)
    flush()
    return tags


def signature_params(fn) -> set[str]:
    a = fn.args
    names = [arg.arg for arg in (a.posonlyargs + a.args + a.kwonlyargs)]
    if a.vararg:
        names.append(a.vararg.arg)
    if a.kwarg:
        names.append(a.kwarg.arg)
    return {n for n in names if n not in ("self", "cls")}


def documented_params(tags) -> set[str]:
    return {e.split()[0].rstrip(":") for e in tags.get("param", []) if e.split()}


def raised_types(fn) -> set[str]:
    types: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Raise) and node.exc is not None:
            exc = node.exc
            if isinstance(exc, ast.Call):
                exc = exc.func
            if isinstance(exc, ast.Name):
                types.add(exc.id)
            elif isinstance(exc, ast.Attribute):
                types.add(exc.attr)
    return types


def returns_value(fn) -> bool:
    if fn.returns is not None:
        ann = fn.returns
        if isinstance(ann, ast.Constant) and ann.value is None:
            return False
        if isinstance(ann, ast.Name) and ann.id == "None":
            return False
        return True
    return any(isinstance(n, ast.Return) and n.value is not None for n in ast.walk(fn))


def first_tag(tags, key: str) -> str | None:
    vals = tags.get(key)
    if not vals or not vals[0].split():
        return None
    return vals[0].split()[0]


def module_import_path(rel_path: Path) -> str:
    parts = list(rel_path.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts)


def collect_contracts(src_root: Path, root: Path) -> list[FunctionContract]:
    contracts: list[FunctionContract] = []
    for path in sorted(src_root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        rel_s = rel.as_posix()
        tree = ast.parse(path.read_text(), filename=str(path))
        mod = module_import_path(rel)
        funcs: list[tuple[ast.AST, str]] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append((node, node.name))
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        funcs.append((sub, f"{node.name}.{sub.name}"))
        for fn, qual in funcs:
            if fn.name.startswith("_"):
                continue
            doc = ast.get_docstring(fn)
            if not doc:
                continue
            tags = parse_tags(doc)
            contracts.append(FunctionContract(
                rel_path=rel_s,
                lineno=fn.lineno,
                qualname=qual,
                module=mod,
                name=fn.name,
                intent=(tags.get("intent") or [""])[0],
                params=tuple(sorted(signature_params(fn))),
                returns=(tags.get("returns") or [None])[0],
                raises=tuple(e.split()[0] for e in tags.get("raises", []) if e.split()),
                feature=first_tag(tags, "feature"),
                flag=first_tag(tags, "flag"),
                entity_id=f"{rel_s}#{fn.name}",
            ))
    return contracts