from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from aya.core.project_tools import IGNORAR_DIRS


@dataclass(frozen=True)
class TechnicalFile:
    path: str
    sha256: str
    modified_at: float
    imports: list[str]
    classes: list[str]
    functions: list[str]
    methods: list[str]
    signatures: list[str]
    lines: int
    calls: list[str]
    related_tests: list[str]
    markers: list[str]


class TechnicalIndex:
    """Indice AST deterministico para selecionar contexto tecnico pequeno."""

    def __init__(self, root: str | Path, cache_path: str | Path):
        self.root = Path(root).resolve()
        self.cache_path = Path(cache_path)

    def build(self) -> list[TechnicalFile]:
        previous = {item["path"]: item for item in self._load_cache()}
        paths = self._python_files()
        test_paths = [
            self._relative(path)
            for path in paths
            if self._is_test(path) and path.name != "__init__.py"
        ]
        entries: list[TechnicalFile] = []
        for path in paths:
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            rel = self._relative(path)
            cached = previous.get(rel)
            if cached and cached.get("sha256") == digest:
                entries.append(TechnicalFile(**cached))
                continue
            entries.append(self._analyze(path, content, digest, test_paths))
        self._save(entries)
        return entries

    def select(self, query: str, limit: int = 6) -> list[TechnicalFile]:
        entries = self.build()
        terms = {term for term in re.findall(r"[a-zA-Z_][\w.]+", query.lower()) if len(term) >= 3}
        ranked: list[tuple[int, TechnicalFile]] = []
        for entry in entries:
            fields = " ".join([
                entry.path,
                *entry.imports,
                *entry.classes,
                *entry.functions,
                *entry.methods,
                *entry.calls,
                *entry.markers,
            ]).lower()
            score = sum(3 if term in entry.path.lower() else 1 for term in terms if term in fields)
            if score:
                ranked.append((score, entry))
        ranked.sort(key=lambda item: (-item[0], item[1].path))
        return [entry for _, entry in ranked[:limit]]

    def summary(self, entries: list[TechnicalFile] | None = None) -> str:
        entries = entries if entries is not None else self.build()
        markers = sum(len(item.markers) for item in entries)
        symbols = sum(len(item.classes) + len(item.functions) + len(item.methods) for item in entries)
        return (
            "Indice tecnico da Aya:\n"
            f"- Arquivos Python indexados: {len(entries)}\n"
            f"- Simbolos identificados: {symbols}\n"
            f"- TODOs/FIXMEs: {markers}\n"
            f"- Cache: {self.cache_path}"
        )

    def _python_files(self) -> list[Path]:
        files: list[Path] = []
        for path in self.root.rglob("*.py"):
            if path.is_symlink():
                try:
                    path.resolve().relative_to(self.root)
                except ValueError:
                    continue
            relative_parts = path.relative_to(self.root).parts
            if any(part in IGNORAR_DIRS for part in relative_parts):
                continue
            if path.is_file():
                files.append(path)
        return sorted(files)

    def _analyze(
        self,
        path: Path,
        content: bytes,
        digest: str,
        test_paths: list[str],
    ) -> TechnicalFile:
        text = content.decode("utf-8-sig", errors="replace")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = ast.Module(body=[], type_ignores=[])
        imports: set[str] = set()
        classes: list[str] = []
        functions: list[str] = []
        methods: list[str] = []
        signatures: list[str] = []
        calls: set[str] = set()

        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                signature = self._signature(node)
                signatures.append(signature)
                if isinstance(parents.get(node), ast.ClassDef):
                    methods.append(node.name)
                else:
                    functions.append(node.name)
            elif isinstance(node, ast.Call):
                name = self._call_name(node.func)
                if name:
                    calls.add(name)
        markers = [
            f"{number}: {line.strip()}"
            for number, line in enumerate(text.splitlines(), start=1)
            if re.search(r"\b(?:TODO|FIXME)\b", line, re.IGNORECASE)
        ]
        rel = self._relative(path)
        symbols = {
            value
            for value in {Path(rel).stem, *classes, *functions, *methods}
            if not value.startswith("__")
        }
        related = [test for test in test_paths if any(symbol.lower() in test.lower() for symbol in symbols)]
        if not related and not self._is_test(path):
            module = rel.removesuffix(".py").replace("\\", ".").replace("/", ".")
            related = self._tests_mentioning(module, symbols, test_paths)
        return TechnicalFile(
            path=rel,
            sha256=digest,
            modified_at=path.stat().st_mtime,
            imports=sorted(value for value in imports if value),
            classes=classes,
            functions=functions,
            methods=methods,
            signatures=signatures,
            lines=len(text.splitlines()),
            calls=sorted(calls),
            related_tests=sorted(set(related)),
            markers=markers,
        )

    def _tests_mentioning(self, module: str, symbols: set[str], tests: list[str]) -> list[str]:
        matches: list[str] = []
        needles = {module.lower(), *(symbol.lower() for symbol in symbols if len(symbol) >= 4)}
        for rel in tests:
            text = (self.root / rel).read_text(encoding="utf-8", errors="replace").lower()
            if any(needle in text for needle in needles):
                matches.append(rel)
        return matches

    def _signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args = [arg.arg for arg in [*node.args.posonlyargs, *node.args.args]]
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        args.extend(arg.arg for arg in node.args.kwonlyargs)
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")
        return f"{node.name}({', '.join(args)})"

    def _call_name(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            owner = self._call_name(node.value)
            return f"{owner}.{node.attr}" if owner else node.attr
        return ""

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _is_test(self, path: Path) -> bool:
        parts = {part.lower() for part in path.relative_to(self.root).parts}
        return "tests" in parts or path.name.lower().startswith("test_")

    def _load_cache(self) -> list[dict]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return []
        return data if isinstance(data, list) else []

    def _save(self, entries: list[TechnicalFile]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps([asdict(item) for item in entries], ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.cache_path)
