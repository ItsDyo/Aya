from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Sequence
from typing import Protocol

from openai import OpenAI

from aya.config import MODEL_CONFIG, RAG_CONFIG
from aya.data.database import Database


logger = logging.getLogger(__name__)


class EmbeddingClient(Protocol):
    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        ...


class OllamaEmbeddingClient:
    def __init__(
        self,
        base_url: str = MODEL_CONFIG.ollama_base_url,
        api_key: str = MODEL_CONFIG.ollama_api_key,
    ):
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=RAG_CONFIG.embedding_timeout_seconds,
            max_retries=0,
        )

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=model, input=texts)
        return [list(item.embedding) for item in sorted(response.data, key=lambda item: item.index)]


class StaticEmbeddingClient:
    """Cliente deterministico usado nos testes do RAG semantico."""

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [list(self.vectors[text]) for text in texts]


class EmbeddingService:
    def __init__(
        self,
        db: Database,
        client: EmbeddingClient | None = None,
        enabled: bool | None = None,
        model: str | None = None,
    ):
        self.db = db
        self.enabled = RAG_CONFIG.embedding_enabled if enabled is None else bool(enabled)
        self.model = (model or RAG_CONFIG.embedding_model).strip()
        self.client = client or OllamaEmbeddingClient()
        self.available = self.enabled
        self.last_error = ""

    def index_knowledge(self, row, force: bool = False) -> bool:
        if not self.enabled or not self.available:
            return False
        text = self._document_text(row)
        content_hash = self._hash(text)
        cached = self.db.buscar_embedding_conhecimento(int(row["id"]), self.model)
        if cached and cached["content_hash"] == content_hash and not force:
            return False
        vectors = self._embed([text])
        if not vectors:
            return False
        self._save_vector(int(row["id"]), content_hash, vectors[0])
        return True

    def index_all(self, force: bool = False) -> tuple[int, int]:
        if not self.enabled:
            return 0, self.db.contar_conhecimentos()
        self.available = True
        self.last_error = ""
        indexed = 0
        skipped = 0
        pending: list[tuple[object, str, str]] = []
        for row in self.db.listar_todos_conhecimentos():
            text = self._document_text(row)
            content_hash = self._hash(text)
            cached = self.db.buscar_embedding_conhecimento(int(row["id"]), self.model)
            if cached and cached["content_hash"] == content_hash and not force:
                skipped += 1
                continue
            pending.append((row, text, content_hash))

        for start in range(0, len(pending), 16):
            batch = pending[start : start + 16]
            vectors = self._embed([item[1] for item in batch])
            if not vectors:
                break
            if len(vectors) != len(batch):
                self._fail("O modelo retornou quantidade incorreta de embeddings.")
                break
            for (row, _text, content_hash), vector in zip(batch, vectors, strict=True):
                self._save_vector(int(row["id"]), content_hash, vector)
                indexed += 1
        return indexed, skipped

    def semantic_scores(self, query: str, limit: int = 30) -> dict[int, float]:
        if not self.enabled or not self.available or not query.strip():
            return {}
        vectors = self._embed([query.strip()])
        if not vectors:
            return {}
        query_vector = vectors[0]
        scored: list[tuple[int, float]] = []
        for row in self.db.listar_embeddings_conhecimento(
            self.model,
            limite=RAG_CONFIG.embedding_scan_limit,
        ):
            try:
                vector = json.loads(row["vetor_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            score = self.cosine_similarity(query_vector, vector)
            if score > 0:
                scored.append((int(row["conhecimento_id"]), score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return dict(scored[: max(1, int(limit))])

    def status(self) -> str:
        if not self.enabled:
            return "Embeddings locais: desligados (RAG lexical ativo)."
        if not self.available:
            return f"Embeddings locais: indisponiveis ({self.last_error})."
        total = self.db.contar_embeddings_conhecimento(self.model)
        return f"Embeddings locais: ativos com {self.model} ({total} item(ns) indexado(s))."

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = self.client.embed(self.model, texts)
            for vector in vectors:
                self._validate_vector(vector)
            return vectors
        except Exception as exc:
            logger.exception("Falha no modelo local de embeddings")
            self._fail(str(exc).replace("\n", " ")[:180] or "falha desconhecida")
            return []

    def _save_vector(self, knowledge_id: int, content_hash: str, vector: list[float]):
        self.db.salvar_embedding_conhecimento(
            knowledge_id,
            self.model,
            content_hash,
            json.dumps(vector, separators=(",", ":")),
            len(vector),
        )

    def _fail(self, message: str):
        self.available = False
        self.last_error = message

    @staticmethod
    def _document_text(row) -> str:
        return "\n".join(
            part.strip()
            for part in (row["topico"], row["tags"], row["source_path"], row["conteudo"])
            if part and part.strip()
        )[:12_000]

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_vector(vector: Sequence[float]):
        if not vector or any(not math.isfinite(float(value)) for value in vector):
            raise ValueError("Embedding vazio ou com valor invalido.")

    @staticmethod
    def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
        if not left or len(left) != len(right):
            return 0.0
        dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
        right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return max(-1.0, min(1.0, dot / (left_norm * right_norm)))
