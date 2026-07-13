from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from aya.core.dev_workspace import DevWorkspace


PATCH_MANIFEST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["version", "proposal_id", "base_commit", "operations", "tests"],
    "properties": {
        "version": {"const": 1},
        "proposal_id": {"type": "string", "pattern": "^DEV-[0-9]{8}-[A-F0-9]{6}$"},
        "base_commit": {"type": "string", "minLength": 7},
        "operations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "file", "expected_sha256"],
                "properties": {
                    "type": {"enum": ["insert_docstring", "replace_exact"]},
                    "file": {"type": "string"},
                    "symbol": {"type": "string"},
                    "expected_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
                    "content": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
            },
        },
        "tests": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
    },
}


@dataclass(frozen=True)
class ManifestResult:
    ok: bool
    message: str
    changed_files: tuple[str, ...] = ()
    changed_lines: int = 0


class StructuredPatchError(ValueError):
    pass


class StructuredPatchApplier:
    """Aplica manifestos pequenos de patch sem executar comandos do modelo."""

    def __init__(
        self,
        root: str | Path,
        workspace: DevWorkspace,
        max_files: int = 4,
        max_changed_lines: int = 250,
        max_operations: int = 4,
    ):
        self.root = Path(root).resolve()
        self.workspace = workspace
        self.max_files = max_files
        self.max_changed_lines = max_changed_lines
        self.max_operations = max_operations

    def parse(self, raw: object) -> dict:
        if isinstance(raw, str):
            text = raw.strip()
            if text.startswith("```"):
                raise StructuredPatchError("Manifesto em Markdown recusado.")
            try:
                raw = json.loads(text)
            except json.JSONDecodeError as exc:
                raise StructuredPatchError(f"JSON invalido: {exc.msg}.") from exc
        if not isinstance(raw, dict):
            raise StructuredPatchError("Manifesto deve ser um objeto JSON.")
        self._validate_shape(raw)
        return raw

    def apply(
        self,
        workspace_path: str | Path,
        manifest: dict,
        proposal_id: str,
        base_commit: str,
        allowed_files: list[str],
        allowed_symbols: list[str],
    ) -> ManifestResult:
        if manifest["proposal_id"] != proposal_id:
            raise StructuredPatchError("proposal_id do manifesto nao corresponde a proposta.")
        if manifest["base_commit"] != base_commit:
            raise StructuredPatchError("base_commit do manifesto nao corresponde ao HEAD esperado.")
        operations = manifest["operations"]
        if len(operations) > self.max_operations:
            raise StructuredPatchError(f"Manifesto excede o limite de {self.max_operations} operacoes.")

        workspace_root = Path(workspace_path).resolve()
        changed: set[str] = set()
        changed_lines = 0
        allowed = set(allowed_files)
        allowed_symbol_set = set(allowed_symbols)

        for operation in operations:
            rel = operation["file"]
            if rel not in allowed:
                raise StructuredPatchError(f"Arquivo fora da proposta: {rel}.")
            error = self.workspace._path_error(rel)
            if error:
                raise StructuredPatchError(error)
            path = (workspace_root / rel).resolve()
            try:
                path.relative_to(workspace_root)
            except ValueError as exc:
                raise StructuredPatchError("Arquivo fora do worktree.") from exc
            if not path.is_file():
                raise StructuredPatchError(f"Arquivo nao encontrado: {rel}.")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != operation["expected_sha256"]:
                raise StructuredPatchError(f"Hash diferente para {rel}.")

            before = path.read_text(encoding="utf-8-sig", errors="replace")
            if operation["type"] == "insert_docstring":
                symbol = operation.get("symbol", "")
                if symbol not in allowed_symbol_set:
                    raise StructuredPatchError(f"Simbolo fora da proposta: {symbol}.")
                after = self._insert_docstring(before, symbol, operation.get("content", ""))
            elif operation["type"] == "replace_exact":
                after = self._replace_exact(before, operation.get("old", ""), operation.get("new", ""))
            else:
                raise StructuredPatchError(f"Operacao desconhecida: {operation['type']}.")

            path.write_text(after, encoding="utf-8")
            changed.add(rel)
            changed_lines += self._line_delta(before, after)

        if len(changed) > self.max_files:
            raise StructuredPatchError(f"Manifesto excede o limite de {self.max_files} arquivos.")
        if changed_lines > self.max_changed_lines:
            raise StructuredPatchError(f"Manifesto excede o limite de {self.max_changed_lines} linhas modificadas.")
        return ManifestResult(True, "Manifesto aplicado deterministicamente.", tuple(sorted(changed)), changed_lines)

    def _validate_shape(self, manifest: dict) -> None:
        if manifest.get("version") != 1:
            raise StructuredPatchError("Versao de manifesto invalida.")
        for key in ("proposal_id", "base_commit", "operations", "tests"):
            if key not in manifest:
                raise StructuredPatchError(f"Campo obrigatorio ausente: {key}.")
        if not isinstance(manifest["operations"], list) or not manifest["operations"]:
            raise StructuredPatchError("Manifesto sem operacoes.")
        if len(manifest["operations"]) > self.max_operations:
            raise StructuredPatchError(f"Manifesto excede o limite de {self.max_operations} operacoes.")
        for operation in manifest["operations"]:
            if not isinstance(operation, dict):
                raise StructuredPatchError("Operacao deve ser objeto JSON.")
            if operation.get("type") not in {"insert_docstring", "replace_exact"}:
                raise StructuredPatchError(f"Operacao desconhecida: {operation.get('type')}.")
            if not all(operation.get(key) for key in ("file", "expected_sha256")):
                raise StructuredPatchError("Operacao sem arquivo ou hash esperado.")
            if operation["type"] == "insert_docstring" and not all(operation.get(key) for key in ("symbol", "content")):
                raise StructuredPatchError("insert_docstring exige symbol e content.")
            if operation["type"] == "replace_exact" and not all(key in operation for key in ("old", "new")):
                raise StructuredPatchError("replace_exact exige old e new.")

    def _insert_docstring(self, text: str, symbol: str, content: str) -> str:
        tree = ast.parse(text)
        matches = self._find_symbol(tree, symbol)
        if not matches:
            raise StructuredPatchError(f"Simbolo inexistente: {symbol}.")
        if len(matches) > 1:
            raise StructuredPatchError(f"Simbolo ambiguo: {symbol}.")
        node = matches[0]
        existing = ast.get_docstring(node, clean=False)
        if existing is not None:
            if existing.strip() == content.strip():
                raise StructuredPatchError("Docstring equivalente ja existe.")
            raise StructuredPatchError("Simbolo ja possui docstring.")

        lines = text.splitlines(keepends=True)
        insert_index = node.body[0].lineno - 1
        indent = self._indent_of(lines[insert_index])
        quote = '"""'
        docline = f"{indent}{quote}{content.strip()}{quote}\n"
        lines.insert(insert_index, docline)
        return "".join(lines)

    def _replace_exact(self, text: str, old: str, new: str) -> str:
        count = text.count(old)
        if count == 0:
            raise StructuredPatchError("Texto antigo nao encontrado.")
        if count > 1:
            raise StructuredPatchError("Texto antigo aparece mais de uma vez.")
        return text.replace(old, new, 1)

    def _find_symbol(self, tree: ast.AST, symbol: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef]:
        parts = symbol.split(".")
        matches: list[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef] = []

        def visit(body: list[ast.stmt], remaining: list[str]) -> None:
            for node in body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == remaining[0]:
                    if len(remaining) == 1:
                        matches.append(node)
                    elif isinstance(node, ast.ClassDef):
                        visit(node.body, remaining[1:])

        visit(tree.body, parts)
        if len(parts) == 1:
            direct = [item for item in matches if item.name == symbol]
            nested = [
                node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol
            ]
            return nested if len(nested) != len(direct) else direct
        return matches

    def _indent_of(self, line: str) -> str:
        return line[: len(line) - len(line.lstrip(" "))]

    def _line_delta(self, before: str, after: str) -> int:
        return abs(len(after.splitlines()) - len(before.splitlines())) or (1 if before != after else 0)
