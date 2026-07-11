from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from aya.config import SECURITY_CONFIG

IGNORAR_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "data_local", "exports", "logs", "backups"}
EXTENSOES_INGESTAO = {
    ".cfg",
    ".csv",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
ARQUIVOS_BLOQUEADOS = {".env", ".env.local"}
EXTENSOES_BLOQUEADAS = {".db", ".sqlite", ".sqlite3", ".key", ".pem"}


@dataclass
class TextChunk:
    source_path: str
    index: int
    title: str
    content: str


class FileIngestor:
    def __init__(
        self,
        root: str | Path = SECURITY_CONFIG.allowed_file_root,
        max_file_chars: int = 120_000,
        chunk_chars: int = 1800,
        overlap: int = 220,
    ):
        self.root = Path(root).resolve()
        self.max_file_chars = max_file_chars
        self.chunk_chars = chunk_chars
        self.overlap = overlap

    def ingest_path(self, path_text: str, recursive: bool = True) -> list[TextChunk]:
        path = (self.root / (path_text or ".")).resolve()
        if not self._inside_root(path):
            raise ValueError("caminho fora da raiz do projeto")
        if self._blocked(path):
            raise ValueError("caminho bloqueado por seguranca")
        if not path.exists():
            raise FileNotFoundError(path_text)

        files = self._files_from_path(path, recursive=recursive)
        chunks: list[TextChunk] = []
        for file_path in files:
            chunks.extend(self._chunk_file(file_path))
        return chunks

    def _files_from_path(self, path: Path, recursive: bool) -> list[Path]:
        if path.is_file():
            return [path] if self._is_supported(path) else []

        iterator = path.rglob("*") if recursive else path.glob("*")
        files = []
        for item in iterator:
            if self._should_ignore(item):
                continue
            if item.is_file() and self._is_supported(item):
                files.append(item)
        return sorted(files)

    def _chunk_file(self, file_path: Path) -> list[TextChunk]:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return []
        if len(text) > self.max_file_chars:
            text = text[: self.max_file_chars]

        rel = str(file_path.relative_to(self.root)).replace("\\", "/")
        chunks: list[TextChunk] = []
        for section_title, section_text in self._split_sections(text, file_path.suffix.lower()):
            for content in self._split_text(section_text):
                index = len(chunks) + 1
                label = self._slug(section_title) if section_title else f"chunk-{index}"
                chunks.append(
                    TextChunk(
                        source_path=rel,
                        index=index,
                        title=f"{rel}#{label}-{index}",
                        content=content,
                    )
                )
        return chunks

    def _split_sections(self, text: str, suffix: str) -> list[tuple[str, str]]:
        if suffix in {".md", ".rst"}:
            pattern = re.compile(r"(?m)^(#{1,6}\s+.+|[^\n]+\n[=-]{3,})\s*$")
        elif suffix == ".py":
            pattern = re.compile(r"(?m)^(?:async\s+def|def|class)\s+[A-Za-z_]\w*[^\n]*")
        else:
            return [("", text)]

        matches = list(pattern.finditer(text))
        if not matches:
            return [("", text)]
        sections: list[tuple[str, str]] = []
        if matches[0].start() > 0 and text[: matches[0].start()].strip():
            sections.append(("introducao", text[: matches[0].start()]))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            title = match.group(0).splitlines()[0].lstrip("# ").strip()
            sections.append((title, text[match.start() : end]))
        return sections

    def _split_text(self, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + self.chunk_chars)
            if end < len(text):
                split_at = max(text.rfind("\n\n", start, end), text.rfind("\n", start, end))
                if split_at > start + self.chunk_chars // 2:
                    end = split_at
            content = text[start:end].strip()
            if content:
                chunks.append(content)
            if end >= len(text):
                break
            start = max(end - self.overlap, start + 1)
        return chunks

    @staticmethod
    def _slug(value: str) -> str:
        value = re.sub(r"[^\w.-]+", "-", (value or "").strip().lower()).strip("-")
        return value[:60] or "secao"

    def _is_supported(self, path: Path) -> bool:
        return path.suffix.lower() in EXTENSOES_INGESTAO and not self._blocked(path)

    def _should_ignore(self, path: Path) -> bool:
        return any(part in IGNORAR_DIRS for part in path.parts) or self._blocked(path)

    def _inside_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    def _blocked(self, path: Path) -> bool:
        parts = {part.lower() for part in path.parts}
        if parts & IGNORAR_DIRS:
            return True
        if path.name.lower() in ARQUIVOS_BLOQUEADOS:
            return True
        return path.suffix.lower() in EXTENSOES_BLOQUEADAS
