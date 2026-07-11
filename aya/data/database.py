from __future__ import annotations

import sqlite3
import threading
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from aya.paths import DB_PATH as DEFAULT_DB_PATH
from aya.paths import ensure_runtime_dirs, migrate_legacy_file


@dataclass(frozen=True)
class MemoryWriteResult:
    memory_id: int
    action: str
    conflict_id: int | None = None


class Database:
    DB_PATH = DEFAULT_DB_PATH
    SCHEMA_VERSION = 10

    def __init__(self, db_path: str | Path | None = None):
        ensure_runtime_dirs()
        migrate_legacy_file("study_ai.db", self.DB_PATH)
        self.db_path = Path(db_path) if db_path else self.DB_PATH
        self.connection = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        self._criar_tabelas()

    def _criar_tabelas(self):
        with self._lock:
            cursor = self.connection.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_info (
                    chave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversas (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    role      TEXT    NOT NULL,
                    conteudo  TEXT    NOT NULL,
                    timestamp TEXT    NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessoes_estudo (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    materia            TEXT    NOT NULL,
                    duracao_minutos    INTEGER,
                    duracao_planejada  INTEGER,
                    notas              TEXT    DEFAULT '',
                    data               TEXT    NOT NULL,
                    concluida          INTEGER DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metas (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    descricao       TEXT    NOT NULL,
                    tipo            TEXT    NOT NULL,
                    concluida       INTEGER DEFAULT 0,
                    data_criacao    TEXT    NOT NULL,
                    data_conclusao  TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS perfil_usuario (
                    chave          TEXT PRIMARY KEY,
                    valor          TEXT NOT NULL,
                    atualizado_em  TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS dificuldades (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    materia        TEXT    NOT NULL,
                    topico         TEXT    NOT NULL,
                    descricao      TEXT    DEFAULT '',
                    registrado_em  TEXT    NOT NULL,
                    resolvido      INTEGER DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conhecimentos (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    topico        TEXT    NOT NULL,
                    conteudo      TEXT    NOT NULL,
                    tags          TEXT    DEFAULT '',
                    fonte         TEXT    DEFAULT 'manual',
                    source_path   TEXT    DEFAULT '',
                    criado_em     TEXT    NOT NULL,
                    atualizado_em TEXT    NOT NULL
                )
            """)
            self._garantir_coluna(cursor, "conhecimentos", "fonte", "TEXT DEFAULT 'manual'")
            self._garantir_coluna(cursor, "conhecimentos", "source_path", "TEXT DEFAULT ''")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memorias (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo         TEXT    NOT NULL,
                    chave        TEXT    NOT NULL,
                    valor        TEXT    NOT NULL,
                    origem       TEXT    DEFAULT '',
                    dominio      TEXT    DEFAULT 'geral',
                    confianca    REAL    DEFAULT 0.7,
                    status       TEXT    DEFAULT 'ativa',
                    uso_count    INTEGER DEFAULT 0,
                    ultimo_uso   TEXT,
                    criado_em    TEXT    NOT NULL,
                    atualizado_em TEXT   NOT NULL
                )
            """)
            self._garantir_coluna(cursor, "memorias", "status", "TEXT DEFAULT 'ativa'")
            self._garantir_coluna(cursor, "memorias", "uso_count", "INTEGER DEFAULT 0")
            self._garantir_coluna(cursor, "memorias", "ultimo_uso", "TEXT")
            self._garantir_coluna(cursor, "memorias", "dominio", "TEXT DEFAULT 'geral'")
            self._garantir_coluna(cursor, "memorias", "reforco_count", "INTEGER DEFAULT 0")
            self._garantir_coluna(cursor, "memorias", "ultima_confirmacao", "TEXT")
            self._garantir_coluna(cursor, "memorias", "fundida_em_id", "INTEGER")
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_memorias_tipo_chave
                ON memorias(tipo, chave)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS eventos_aprendizado (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo        TEXT    NOT NULL,
                    descricao   TEXT    NOT NULL,
                    metadata    TEXT    DEFAULT '',
                    criado_em   TEXT    NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memoria_historico (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    memoria_id     INTEGER NOT NULL,
                    acao           TEXT    NOT NULL,
                    valor_anterior TEXT    DEFAULT '',
                    valor_novo     TEXT    DEFAULT '',
                    origem         TEXT    DEFAULT '',
                    confianca      REAL    DEFAULT 0.0,
                    metadata       TEXT    DEFAULT '',
                    criado_em      TEXT    NOT NULL,
                    FOREIGN KEY (memoria_id) REFERENCES memorias(id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conflitos_memoria (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    memoria_id         INTEGER NOT NULL,
                    tipo               TEXT    NOT NULL,
                    chave              TEXT    NOT NULL,
                    valor_atual        TEXT    NOT NULL,
                    valor_proposto     TEXT    NOT NULL,
                    origem_proposta    TEXT    DEFAULT '',
                    dominio_proposto   TEXT    DEFAULT 'geral',
                    confianca_proposta REAL    DEFAULT 0.7,
                    reforco_count      INTEGER DEFAULT 1,
                    status             TEXT    DEFAULT 'pendente',
                    resolucao          TEXT    DEFAULT '',
                    criado_em          TEXT    NOT NULL,
                    resolvido_em       TEXT,
                    FOREIGN KEY (memoria_id) REFERENCES memorias(id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conhecimento_embeddings (
                    conhecimento_id INTEGER NOT NULL,
                    modelo          TEXT    NOT NULL,
                    content_hash    TEXT    NOT NULL,
                    vetor_json      TEXT    NOT NULL,
                    dimensoes       INTEGER NOT NULL,
                    atualizado_em   TEXT    NOT NULL,
                    PRIMARY KEY (conhecimento_id, modelo),
                    FOREIGN KEY (conhecimento_id) REFERENCES conhecimentos(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memoria_historico_memoria
                ON memoria_historico(memoria_id, id DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conflitos_memoria_status
                ON conflitos_memoria(status, memoria_id, id DESC)
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS aprendizados_pendentes (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    categoria   TEXT    NOT NULL,
                    tipo        TEXT    DEFAULT '',
                    chave       TEXT    NOT NULL,
                    valor       TEXT    NOT NULL,
                    origem      TEXT    DEFAULT '',
                    confianca   REAL    DEFAULT 0.5,
                    status      TEXT    DEFAULT 'pendente',
                    metadata    TEXT    DEFAULT '',
                    criado_em   TEXT    NOT NULL,
                    revisado_em TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS exercicios (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    topico            TEXT    NOT NULL,
                    pergunta          TEXT    NOT NULL,
                    resposta_esperada TEXT    DEFAULT '',
                    nivel             TEXT    DEFAULT 'medio',
                    status            TEXT    DEFAULT 'pendente',
                    resposta_usuario  TEXT    DEFAULT '',
                    feedback          TEXT    DEFAULT '',
                    nota              REAL,
                    criado_em         TEXT    NOT NULL,
                    respondido_em     TEXT,
                    revisar_em        TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS diario_companhia (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    tom         TEXT    DEFAULT 'companhia',
                    resumo      TEXT    NOT NULL,
                    mensagem    TEXT    DEFAULT '',
                    resposta    TEXT    DEFAULT '',
                    criado_em   TEXT    NOT NULL
                )
            """)
            cursor.execute("""
                DELETE FROM conhecimentos
                WHERE id NOT IN (
                    SELECT MIN(id)
                    FROM conhecimentos
                    GROUP BY topico, conteudo, tags, source_path
                )
            """)
            cursor.execute("DROP INDEX IF EXISTS idx_conhecimentos_unico")
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_conhecimentos_unico
                ON conhecimentos(topico, conteudo, tags, source_path)
            """)

            self._criar_fts_conhecimento(cursor)
            cursor.execute(
                "INSERT OR REPLACE INTO schema_info (chave, valor) VALUES (?, ?)",
                ("schema_version", str(self.SCHEMA_VERSION)),
            )
            self.connection.commit()

    def _criar_fts_conhecimento(self, cursor: sqlite3.Cursor):
        try:
            columns = {row["name"] for row in cursor.execute("PRAGMA table_info(conhecimentos_fts)").fetchall()}
            if columns and "source_path" not in columns:
                cursor.execute("DROP TABLE IF EXISTS conhecimentos_fts")
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS conhecimentos_fts
                USING fts5(topico, conteudo, tags, source_path, content='conhecimentos', content_rowid='id')
            """)
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass

    def _garantir_coluna(self, cursor: sqlite3.Cursor, table: str, column: str, definition: str):
        columns = {row["name"] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(sql, params)
            self.connection.commit()
            return cursor

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row:
        with self._lock:
            cursor = self.connection.cursor()
            cursor.execute(sql, params)
            return cursor.fetchone()

    def salvar_mensagem(self, role: str, conteudo: str):
        if role not in {"user", "assistant", "system"}:
            raise ValueError("role precisa ser user, assistant ou system")
        if not conteudo:
            return
        self._execute(
            "INSERT INTO conversas (role, conteudo, timestamp) VALUES (?, ?, ?)",
            (role, conteudo, datetime.now().isoformat()),
        )

    def carregar_historico(self, limite: int = 20) -> list[dict]:
        mensagens = self._fetchall(
            """SELECT role, conteudo
               FROM conversas
               ORDER BY id DESC
               LIMIT ?""",
            (limite,),
        )
        return [
            {"role": m["role"], "content": m["conteudo"]}
            for m in reversed(mensagens)
        ]

    def contar_mensagens_totais(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS total FROM conversas")
        return row["total"]

    def exportar_conversas(self, limite: int = 200) -> list[dict]:
        return self.carregar_historico(limite)

    def iniciar_sessao(self, materia: str, duracao_planejada: int) -> int:
        cursor = self._execute(
            """INSERT INTO sessoes_estudo
               (materia, duracao_planejada, data, concluida)
               VALUES (?, ?, ?, 0)""",
            (materia, duracao_planejada, datetime.now().isoformat()),
        )
        return cursor.lastrowid

    def concluir_sessao(self, sessao_id: int, duracao_real: int, notas: str = ""):
        self._execute(
            """UPDATE sessoes_estudo
               SET duracao_minutos = ?, notas = ?, concluida = 1
               WHERE id = ?""",
            (duracao_real, notas, sessao_id),
        )

    def buscar_sessoes_hoje(self) -> list[sqlite3.Row]:
        hoje = datetime.now().strftime("%Y-%m-%d")
        return self._fetchall(
            "SELECT * FROM sessoes_estudo WHERE data LIKE ? ORDER BY id DESC",
            (f"{hoje}%",),
        )

    def buscar_resumo_semanal(self) -> dict:
        row = self._fetchone(
            """SELECT
                COUNT(*)                AS total_sessoes,
                SUM(duracao_minutos)    AS total_minutos,
                COUNT(DISTINCT materia) AS materias_distintas
               FROM sessoes_estudo
               WHERE data >= date('now', '-7 days')
                 AND concluida = 1"""
        )
        return {
            "total_sessoes": row["total_sessoes"] or 0,
            "total_minutos": row["total_minutos"] or 0,
            "materias_distintas": row["materias_distintas"] or 0,
        }

    def buscar_historico_sessoes(self, limite: int = 10) -> list[sqlite3.Row]:
        return self._fetchall(
            """SELECT materia, duracao_minutos, duracao_planejada, data, concluida
               FROM sessoes_estudo
               ORDER BY id DESC
               LIMIT ?""",
            (limite,),
        )

    def criar_meta(self, descricao: str, tipo: str) -> int:
        cursor = self._execute(
            "INSERT INTO metas (descricao, tipo, data_criacao) VALUES (?, ?, ?)",
            (descricao, tipo, datetime.now().isoformat()),
        )
        return cursor.lastrowid

    def concluir_meta(self, meta_id: int):
        self._execute(
            "UPDATE metas SET concluida = 1, data_conclusao = ? WHERE id = ?",
            (datetime.now().isoformat(), meta_id),
        )

    def buscar_metas_ativas(self) -> list[sqlite3.Row]:
        return self._fetchall(
            "SELECT * FROM metas WHERE concluida = 0 ORDER BY data_criacao DESC"
        )

    def salvar_perfil(self, chave: str, valor: str):
        self._execute(
            """INSERT OR REPLACE INTO perfil_usuario
               (chave, valor, atualizado_em)
               VALUES (?, ?, ?)""",
            (chave.strip(), valor.strip(), datetime.now().isoformat()),
        )
        self.salvar_memoria("perfil", chave, valor, origem="perfil", confianca=0.9, dominio="pessoal")

    def carregar_perfil(self) -> dict:
        rows = self._fetchall("SELECT chave, valor FROM perfil_usuario")
        return {row["chave"]: row["valor"] for row in rows}

    def registrar_dificuldade(self, materia: str, topico: str, descricao: str = ""):
        self._execute(
            """INSERT INTO dificuldades
               (materia, topico, descricao, registrado_em)
               VALUES (?, ?, ?, ?)""",
            (materia, topico, descricao, datetime.now().isoformat()),
        )

    def buscar_dificuldades_abertas(self, limite: int = 5) -> list[sqlite3.Row]:
        return self._fetchall(
            """SELECT materia, topico, descricao
               FROM dificuldades
               WHERE resolvido = 0
               ORDER BY registrado_em DESC
               LIMIT ?""",
            (limite,),
        )

    def salvar_conhecimento(
        self,
        topico: str,
        conteudo: str,
        tags: str = "",
        fonte: str = "manual",
        source_path: str = "",
    ) -> int:
        agora = datetime.now().isoformat()
        cursor = self._execute(
            """INSERT OR IGNORE INTO conhecimentos
               (topico, conteudo, tags, fonte, source_path, criado_em, atualizado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (topico.strip(), conteudo.strip(), tags.strip(), fonte.strip(), source_path.strip(), agora, agora),
        )
        item_id = cursor.lastrowid or self._buscar_id_conhecimento(topico, conteudo, tags, source_path)
        self._sincronizar_fts_conhecimento(item_id, topico, conteudo, tags, source_path)
        return item_id

    def _buscar_id_conhecimento(self, topico: str, conteudo: str, tags: str, source_path: str = "") -> int:
        row = self._fetchone(
            """SELECT id FROM conhecimentos
               WHERE topico = ? AND conteudo = ? AND tags = ? AND source_path = ?""",
            (topico.strip(), conteudo.strip(), tags.strip(), source_path.strip()),
        )
        return row["id"]

    def substituir_conhecimentos_de_fonte(
        self,
        source_path: str,
        itens: list[tuple[str, str, str, str]],
    ) -> list[int]:
        source_path = (source_path or "").strip()
        preparados = [
            (topico.strip(), conteudo.strip(), tags.strip(), fonte.strip() or "arquivo")
            for topico, conteudo, tags, fonte in itens
            if topico.strip() and conteudo.strip()
        ]
        if not source_path or not preparados:
            return []
        agora = datetime.now().isoformat()
        ids: list[int] = []
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute("DELETE FROM conhecimentos WHERE source_path = ?", (source_path,))
                for topico, conteudo, tags, fonte in preparados:
                    cursor.execute(
                        """INSERT INTO conhecimentos
                           (topico, conteudo, tags, fonte, source_path, criado_em, atualizado_em)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (topico, conteudo, tags, fonte, source_path, agora, agora),
                    )
                    ids.append(int(cursor.lastrowid))
                self.connection.commit()
            except sqlite3.Error:
                self.connection.rollback()
                raise
        return ids

    def _sincronizar_fts_conhecimento(self, item_id: int, topico: str, conteudo: str, tags: str, source_path: str = ""):
        try:
            self._execute(
                """INSERT OR REPLACE INTO conhecimentos_fts(rowid, topico, conteudo, tags, source_path)
                   VALUES (?, ?, ?, ?, ?)""",
                (item_id, topico, conteudo, tags, source_path),
            )
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass

    def buscar_conhecimento(self, termo: str = "", limite: int = 5) -> list[sqlite3.Row]:
        termo = (termo or "").strip()
        if not termo:
            return self._fetchall(
                """SELECT id, topico, conteudo, tags, fonte, source_path, atualizado_em
                   FROM conhecimentos
                   ORDER BY atualizado_em DESC
                   LIMIT ?""",
                (limite,),
            )

        fts = self._buscar_conhecimento_fts(termo, limite)
        if fts:
            return fts

        like = f"%{termo}%"
        return self._fetchall(
            """SELECT id, topico, conteudo, tags, fonte, source_path, atualizado_em
               FROM conhecimentos
               WHERE topico LIKE ?
                  OR conteudo LIKE ?
                  OR tags LIKE ?
                  OR source_path LIKE ?
               ORDER BY atualizado_em DESC
               LIMIT ?""",
            (like, like, like, like, limite),
        )

    def buscar_conhecimento_rankeado(self, termo: str, limite: int = 30) -> list[sqlite3.Row]:
        tokens = self._tokens_busca_fts(termo)
        if not tokens:
            return []
        query = " OR ".join(
            f'"{token}"*' if token.replace("_", "").isalnum() else f'"{token}"'
            for token in tokens[:16]
        )
        try:
            rows = self._fetchall(
                """SELECT c.id, c.topico, c.conteudo, c.tags, c.fonte,
                          c.source_path, c.atualizado_em,
                          bm25(conhecimentos_fts, 5.0, 1.0, 2.0, 1.5) AS fts_rank
                   FROM conhecimentos_fts
                   JOIN conhecimentos c ON c.id = conhecimentos_fts.rowid
                   WHERE conhecimentos_fts MATCH ?
                   ORDER BY fts_rank ASC
                   LIMIT ?""",
                (query, max(1, min(200, int(limite)))),
            )
            if rows:
                return rows
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass

        encontrados: dict[int, sqlite3.Row] = {}
        for token in tokens[:8]:
            for row in self.buscar_conhecimento(token, limite=limite):
                encontrados.setdefault(int(row["id"]), row)
        return list(encontrados.values())[:limite]

    def listar_todos_conhecimentos(self, limite: int = 10_000) -> list[sqlite3.Row]:
        return self._fetchall(
            """SELECT id, topico, conteudo, tags, fonte, source_path, atualizado_em
               FROM conhecimentos ORDER BY id ASC LIMIT ?""",
            (max(1, min(100_000, int(limite))),),
        )

    def buscar_conhecimentos_por_ids(self, ids: list[int]) -> list[sqlite3.Row]:
        ids = list(dict.fromkeys(int(item_id) for item_id in ids if int(item_id) > 0))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        return self._fetchall(
            f"""SELECT id, topico, conteudo, tags, fonte, source_path, atualizado_em
                FROM conhecimentos WHERE id IN ({placeholders})""",
            tuple(ids),
        )

    def salvar_embedding_conhecimento(
        self,
        conhecimento_id: int,
        modelo: str,
        content_hash: str,
        vetor_json: str,
        dimensoes: int,
    ):
        self._execute(
            """INSERT INTO conhecimento_embeddings
               (conhecimento_id, modelo, content_hash, vetor_json, dimensoes, atualizado_em)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(conhecimento_id, modelo) DO UPDATE SET
                   content_hash = excluded.content_hash,
                   vetor_json = excluded.vetor_json,
                   dimensoes = excluded.dimensoes,
                   atualizado_em = excluded.atualizado_em""",
            (
                int(conhecimento_id),
                modelo.strip(),
                content_hash.strip(),
                vetor_json,
                int(dimensoes),
                datetime.now().isoformat(),
            ),
        )

    def buscar_embedding_conhecimento(self, conhecimento_id: int, modelo: str) -> sqlite3.Row | None:
        return self._fetchone(
            """SELECT conhecimento_id, modelo, content_hash, vetor_json, dimensoes, atualizado_em
               FROM conhecimento_embeddings WHERE conhecimento_id = ? AND modelo = ?""",
            (int(conhecimento_id), modelo.strip()),
        )

    def listar_embeddings_conhecimento(self, modelo: str, limite: int = 10_000) -> list[sqlite3.Row]:
        return self._fetchall(
            """SELECT conhecimento_id, modelo, content_hash, vetor_json, dimensoes, atualizado_em
               FROM conhecimento_embeddings
               WHERE modelo = ?
               ORDER BY conhecimento_id ASC
               LIMIT ?""",
            (modelo.strip(), max(1, min(100_000, int(limite)))),
        )

    def contar_embeddings_conhecimento(self, modelo: str = "") -> int:
        if modelo:
            row = self._fetchone(
                "SELECT COUNT(*) AS total FROM conhecimento_embeddings WHERE modelo = ?",
                (modelo.strip(),),
            )
        else:
            row = self._fetchone("SELECT COUNT(*) AS total FROM conhecimento_embeddings")
        return int(row["total"] if row else 0)

    @staticmethod
    def _tokens_busca_fts(termo: str) -> list[str]:
        normalized = unicodedata.normalize("NFKD", termo or "")
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        tokens = re.findall(r"[\w#+.-]{2,}", normalized.casefold())
        variants: list[str] = []
        for token in tokens:
            variants.append(token)
            if token.endswith("coes") and len(token) > 5:
                variants.append(token[:-4])
            elif token.endswith("ao") and len(token) > 4:
                variants.append(token[:-2])
            elif token.endswith("es") and len(token) > 6:
                variants.append(token[:-2])
            elif token.endswith("s") and len(token) > 5:
                variants.append(token[:-1])
        return list(dict.fromkeys(variant for variant in variants if len(variant) >= 2))

    def _buscar_conhecimento_fts(self, termo: str, limite: int) -> list[sqlite3.Row]:
        try:
            safe_query = " OR ".join(part for part in termo.split() if part)
            if not safe_query:
                return []
            return self._fetchall(
                """SELECT c.id, c.topico, c.conteudo, c.tags, c.fonte, c.source_path, c.atualizado_em
                   FROM conhecimentos_fts f
                   JOIN conhecimentos c ON c.id = f.rowid
                   WHERE conhecimentos_fts MATCH ?
                   LIMIT ?""",
                (safe_query, limite),
            )
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            return []

    def contar_conhecimentos(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS total FROM conhecimentos")
        return row["total"]

    def remover_conhecimento_por_source_path(self, source_path: str) -> int:
        source_path = (source_path or "").strip()
        if not source_path:
            return 0
        cursor = self._execute("DELETE FROM conhecimentos WHERE source_path = ?", (source_path,))
        try:
            self._execute("DELETE FROM conhecimentos_fts WHERE source_path = ?", (source_path,))
        except sqlite3.OperationalError:
            pass
        return cursor.rowcount

    def reconstruir_fts_conhecimento(self):
        try:
            self._execute("DELETE FROM conhecimentos_fts")
            rows = self._fetchall("SELECT id, topico, conteudo, tags, source_path FROM conhecimentos")
            for row in rows:
                self._sincronizar_fts_conhecimento(row["id"], row["topico"], row["conteudo"], row["tags"], row["source_path"])
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            self.reparar_fts_conhecimento()

    def reparar_fts_conhecimento(self):
        with self._lock:
            cursor = self.connection.cursor()
            try:
                cursor.execute("DROP TABLE IF EXISTS conhecimentos_fts")
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS conhecimentos_fts
                    USING fts5(topico, conteudo, tags, source_path, content='conhecimentos', content_rowid='id')
                """)
                rows = cursor.execute("SELECT id, topico, conteudo, tags, source_path FROM conhecimentos").fetchall()
                for row in rows:
                    cursor.execute(
                        """INSERT OR REPLACE INTO conhecimentos_fts(rowid, topico, conteudo, tags, source_path)
                           VALUES (?, ?, ?, ?, ?)""",
                        (row["id"], row["topico"], row["conteudo"], row["tags"], row["source_path"]),
                    )
                self.connection.commit()
            except sqlite3.Error:
                self.connection.rollback()

    def salvar_memoria(
        self,
        tipo: str,
        chave: str,
        valor: str,
        origem: str = "",
        confianca: float = 0.7,
        dominio: str = "geral",
    ) -> int:
        return self.salvar_memoria_avancada(
            tipo,
            chave,
            valor,
            origem=origem,
            confianca=confianca,
            dominio=dominio,
        ).memory_id

    def salvar_memoria_avancada(
        self,
        tipo: str,
        chave: str,
        valor: str,
        origem: str = "",
        confianca: float = 0.7,
        dominio: str = "geral",
    ) -> MemoryWriteResult:
        tipo = tipo.strip().lower()
        chave = chave.strip().lower()
        valor = valor.strip()
        origem = origem.strip()
        dominio = (dominio or "geral").strip().lower()
        if not tipo or not chave or not valor:
            return MemoryWriteResult(0, "ignored")

        agora = datetime.now().isoformat()
        confianca = max(0.0, min(1.0, float(confianca)))
        with self._lock:
            cursor = self.connection.cursor()
            atual = cursor.execute(
                "SELECT * FROM memorias WHERE tipo = ? AND chave = ?",
                (tipo, chave),
            ).fetchone()

            if not atual:
                cursor.execute(
                    """INSERT INTO memorias
                       (tipo, chave, valor, origem, dominio, confianca, status,
                        reforco_count, ultima_confirmacao, criado_em, atualizado_em)
                       VALUES (?, ?, ?, ?, ?, ?, 'ativa', 0, ?, ?, ?)""",
                    (tipo, chave, valor, origem, dominio, confianca, agora, agora, agora),
                )
                memoria_id = cursor.lastrowid
                self._registrar_historico_memoria(
                    cursor, memoria_id, "criada", "", valor, origem, confianca
                )
                self.connection.commit()
                return MemoryWriteResult(memoria_id, "created")

            memoria_id = int(atual["id"])
            mesmo_valor = self._normalizar_valor_memoria(atual["valor"]) == self._normalizar_valor_memoria(valor)
            substituicao_segura = tipo in {"assunto_atual", "reflexao"} or origem == "perfil" or atual["status"] != "ativa"

            if mesmo_valor:
                nova_confianca = min(0.99, max(float(atual["confianca"]), confianca) + 0.02)
                dominio_atual = atual["dominio"] or "geral"
                novo_dominio = dominio if dominio_atual in {"", "geral"} else dominio_atual
                cursor.execute(
                    """UPDATE memorias
                       SET origem = ?, dominio = ?, confianca = ?, status = 'ativa',
                           reforco_count = COALESCE(reforco_count, 0) + 1,
                           ultima_confirmacao = ?, atualizado_em = ?
                       WHERE id = ?""",
                    (origem or atual["origem"], novo_dominio, nova_confianca, agora, agora, memoria_id),
                )
                self._registrar_historico_memoria(
                    cursor, memoria_id, "reforcada", atual["valor"], valor, origem, nova_confianca
                )
                self.connection.commit()
                return MemoryWriteResult(memoria_id, "reinforced")

            if substituicao_segura:
                cursor.execute(
                    """UPDATE memorias
                       SET valor = ?, origem = ?, dominio = ?, confianca = ?, status = 'ativa',
                           fundida_em_id = NULL, atualizado_em = ?
                       WHERE id = ?""",
                    (valor, origem, dominio, confianca, agora, memoria_id),
                )
                self._registrar_historico_memoria(
                    cursor,
                    memoria_id,
                    "atualizada",
                    atual["valor"],
                    valor,
                    origem,
                    confianca,
                    metadata=f"tipo={tipo}",
                )
                self.connection.commit()
                return MemoryWriteResult(memoria_id, "updated")

            conflito = cursor.execute(
                """SELECT id, valor_proposto, reforco_count FROM conflitos_memoria
                   WHERE memoria_id = ? AND status = 'pendente'
                   ORDER BY id DESC""",
                (memoria_id,),
            ).fetchall()
            conflito_existente = next(
                (
                    item
                    for item in conflito
                    if self._normalizar_valor_memoria(item["valor_proposto"])
                    == self._normalizar_valor_memoria(valor)
                ),
                None,
            )
            if conflito_existente:
                conflito_id = int(conflito_existente["id"])
                cursor.execute(
                    """UPDATE conflitos_memoria
                       SET confianca_proposta = MAX(confianca_proposta, ?),
                           reforco_count = reforco_count + 1
                       WHERE id = ?""",
                    (confianca, conflito_id),
                )
                acao = "conflito_reforcado"
            else:
                cursor.execute(
                    """INSERT INTO conflitos_memoria
                       (memoria_id, tipo, chave, valor_atual, valor_proposto, origem_proposta,
                        dominio_proposto, confianca_proposta, criado_em)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (memoria_id, tipo, chave, atual["valor"], valor, origem, dominio, confianca, agora),
                )
                conflito_id = cursor.lastrowid
                acao = "conflito_criado"

            self._registrar_historico_memoria(
                cursor,
                memoria_id,
                acao,
                atual["valor"],
                valor,
                origem,
                confianca,
                metadata=f"conflito_id={conflito_id}",
            )
            self.connection.commit()
            return MemoryWriteResult(memoria_id, "conflict", conflito_id)

    def buscar_memorias(self, termo: str = "", limite: int = 10) -> list[sqlite3.Row]:
        termo = (termo or "").strip()
        if not termo:
            return self._fetchall(
                """SELECT id, tipo, chave, valor, origem, dominio, confianca, status, uso_count,
                          reforco_count, ultima_confirmacao, ultimo_uso, criado_em, atualizado_em
                   FROM memorias
                   WHERE status = 'ativa'
                   ORDER BY confianca DESC, uso_count DESC, atualizado_em DESC
                   LIMIT ?""",
                (limite,),
            )

        like = f"%{termo.lower()}%"
        return self._fetchall(
            """SELECT id, tipo, chave, valor, origem, dominio, confianca, status, uso_count,
                      reforco_count, ultima_confirmacao, ultimo_uso, criado_em, atualizado_em
               FROM memorias
               WHERE status = 'ativa'
                 AND (tipo LIKE ?
                  OR chave LIKE ?
                  OR valor LIKE ?
                  OR origem LIKE ?)
               ORDER BY confianca DESC, uso_count DESC, atualizado_em DESC
               LIMIT ?""",
            (like, like, like, like, limite),
        )

    def contar_memorias(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS total FROM memorias WHERE status = 'ativa'")
        return row["total"]

    def buscar_memorias_para_revisao(self, limite: int = 10) -> list[sqlite3.Row]:
        return self._fetchall(
            """SELECT id, tipo, chave, valor, origem, dominio, confianca, status, uso_count,
                      reforco_count, ultima_confirmacao, ultimo_uso, criado_em, atualizado_em
               FROM memorias
               WHERE status = 'ativa'
                 AND (
                    confianca < 0.85
                    OR tipo IN ('assunto_atual', 'reflexao')
                    OR EXISTS (
                        SELECT 1 FROM conflitos_memoria c
                        WHERE c.memoria_id = memorias.id AND c.status = 'pendente'
                    )
                 )
               ORDER BY confianca ASC, atualizado_em ASC
               LIMIT ?""",
            (limite,),
        )

    def buscar_memorias_por_dominio(self, dominio: str, limite: int = 50) -> list[sqlite3.Row]:
        dominio = (dominio or "geral").strip().lower()
        return self._fetchall(
            """SELECT id, tipo, chave, valor, origem, dominio, confianca, status, uso_count,
                      reforco_count, ultima_confirmacao, ultimo_uso, criado_em, atualizado_em
               FROM memorias
               WHERE status = 'ativa' AND dominio = ?
               ORDER BY atualizado_em DESC, confianca DESC
               LIMIT ?""",
            (dominio, max(1, min(100, int(limite)))),
        )

    def confirmar_memoria(self, memoria_id: int) -> bool:
        agora = datetime.now().isoformat()
        with self._lock:
            cursor = self.connection.cursor()
            memoria = cursor.execute("SELECT * FROM memorias WHERE id = ?", (memoria_id,)).fetchone()
            if not memoria or memoria["status"] == "fundida":
                return False
            nova_confianca = max(float(memoria["confianca"]), 0.95)
            cursor.execute(
                """UPDATE memorias
                   SET confianca = ?, status = 'ativa',
                       reforco_count = COALESCE(reforco_count, 0) + 1,
                       ultima_confirmacao = ?, atualizado_em = ?
                   WHERE id = ?""",
                (nova_confianca, agora, agora, memoria_id),
            )
            self._registrar_historico_memoria(
                cursor,
                memoria_id,
                "confirmada",
                memoria["valor"],
                memoria["valor"],
                "curadoria",
                nova_confianca,
            )
            self.connection.commit()
            return True

    def arquivar_memoria(self, memoria_id: int) -> bool:
        agora = datetime.now().isoformat()
        with self._lock:
            cursor = self.connection.cursor()
            memoria = cursor.execute("SELECT * FROM memorias WHERE id = ?", (memoria_id,)).fetchone()
            if not memoria:
                return False
            cursor.execute(
                "UPDATE memorias SET status = 'arquivada', atualizado_em = ? WHERE id = ?",
                (agora, memoria_id),
            )
            self._registrar_historico_memoria(
                cursor,
                memoria_id,
                "arquivada",
                memoria["valor"],
                memoria["valor"],
                "curadoria",
                float(memoria["confianca"]),
            )
            self.connection.commit()
            return True

    def restaurar_memoria(self, memoria_id: int) -> bool:
        agora = datetime.now().isoformat()
        with self._lock:
            cursor = self.connection.cursor()
            memoria = cursor.execute("SELECT * FROM memorias WHERE id = ?", (memoria_id,)).fetchone()
            if not memoria or memoria["status"] == "fundida":
                return False
            cursor.execute(
                "UPDATE memorias SET status = 'ativa', atualizado_em = ? WHERE id = ?",
                (agora, memoria_id),
            )
            self._registrar_historico_memoria(
                cursor,
                memoria_id,
                "restaurada",
                memoria["valor"],
                memoria["valor"],
                "curadoria",
                float(memoria["confianca"]),
            )
            self.connection.commit()
            return True

    def atualizar_memoria_controlada(self, memoria_id: int, novo_valor: str) -> bool:
        novo_valor = (novo_valor or "").strip()
        if not novo_valor:
            return False
        agora = datetime.now().isoformat()
        with self._lock:
            cursor = self.connection.cursor()
            memoria = cursor.execute("SELECT * FROM memorias WHERE id = ?", (memoria_id,)).fetchone()
            if not memoria or memoria["status"] == "fundida":
                return False
            cursor.execute(
                """UPDATE memorias
                   SET valor = ?, origem = ?, atualizado_em = ?
                   WHERE id = ?""",
                (novo_valor, f"editado:{memoria['origem'] or 'curadoria'}", agora, memoria_id),
            )
            self._registrar_historico_memoria(
                cursor,
                memoria_id,
                "editada",
                memoria["valor"],
                novo_valor,
                "curadoria",
                float(memoria["confianca"]),
            )
            self.connection.commit()
            return True

    def alterar_dominio_memoria(self, memoria_id: int, dominio: str) -> bool:
        dominio = (dominio or "geral").strip().lower()
        agora = datetime.now().isoformat()
        with self._lock:
            cursor = self.connection.cursor()
            memoria = cursor.execute("SELECT * FROM memorias WHERE id = ?", (memoria_id,)).fetchone()
            if not memoria or memoria["status"] == "fundida":
                return False
            cursor.execute(
                "UPDATE memorias SET dominio = ?, atualizado_em = ? WHERE id = ?",
                (dominio, agora, memoria_id),
            )
            self._registrar_historico_memoria(
                cursor,
                memoria_id,
                "dominio_alterado",
                memoria["dominio"] or "",
                dominio,
                "curadoria",
                float(memoria["confianca"]),
            )
            self.connection.commit()
            return True

    def registrar_revisao_memoria(self, memoria_id: int, acao: str, metadata: str = "") -> bool:
        agora = datetime.now().isoformat()
        with self._lock:
            cursor = self.connection.cursor()
            memoria = cursor.execute("SELECT * FROM memorias WHERE id = ?", (memoria_id,)).fetchone()
            if not memoria:
                return False
            self._registrar_historico_memoria(
                cursor,
                memoria_id,
                acao,
                memoria["valor"],
                memoria["valor"],
                "curadoria",
                float(memoria["confianca"]),
                metadata=metadata or f"registrado_em={agora}",
            )
            self.connection.commit()
            return True

    def buscar_memoria_por_id(self, memoria_id: int) -> sqlite3.Row | None:
        return self._fetchone(
            """SELECT id, tipo, chave, valor, origem, dominio, confianca, status,
                      uso_count, reforco_count, ultima_confirmacao, ultimo_uso,
                      fundida_em_id, criado_em, atualizado_em
               FROM memorias WHERE id = ?""",
            (memoria_id,),
        )

    def listar_conflitos_memoria(self, limite: int = 20, status: str = "pendente") -> list[sqlite3.Row]:
        return self._fetchall(
            """SELECT id, memoria_id, tipo, chave, valor_atual, valor_proposto,
                      origem_proposta, dominio_proposto, confianca_proposta,
                      reforco_count, status, resolucao, criado_em, resolvido_em
               FROM conflitos_memoria
               WHERE status = ?
               ORDER BY id DESC
               LIMIT ?""",
            ((status or "pendente").strip().lower(), max(1, min(100, int(limite)))),
        )

    def contar_conflitos_memoria(self, status: str = "pendente") -> int:
        row = self._fetchone(
            "SELECT COUNT(*) AS total FROM conflitos_memoria WHERE status = ?",
            ((status or "pendente").strip().lower(),),
        )
        return int(row["total"] if row else 0)

    def resolver_conflito_memoria(self, conflito_id: int, aceitar: bool) -> bool:
        agora = datetime.now().isoformat()
        with self._lock:
            cursor = self.connection.cursor()
            conflito = cursor.execute(
                "SELECT * FROM conflitos_memoria WHERE id = ? AND status = 'pendente'",
                (conflito_id,),
            ).fetchone()
            if not conflito:
                return False
            memoria = cursor.execute(
                "SELECT * FROM memorias WHERE id = ?",
                (conflito["memoria_id"],),
            ).fetchone()
            if not memoria:
                return False

            if aceitar:
                nova_confianca = min(0.99, max(float(conflito["confianca_proposta"]), 0.9))
                dominio_atual = memoria["dominio"] or "geral"
                dominio_proposto = conflito["dominio_proposto"] or "geral"
                novo_dominio = (
                    dominio_proposto
                    if dominio_proposto != "geral" or dominio_atual == "geral"
                    else dominio_atual
                )
                cursor.execute(
                    """UPDATE memorias
                       SET valor = ?, origem = ?, dominio = ?, confianca = ?, status = 'ativa',
                           reforco_count = COALESCE(reforco_count, 0) + 1,
                           ultima_confirmacao = ?, atualizado_em = ?
                       WHERE id = ?""",
                    (
                        conflito["valor_proposto"],
                        f"conflito_aceito:{conflito['origem_proposta']}",
                        novo_dominio,
                        nova_confianca,
                        agora,
                        agora,
                        memoria["id"],
                    ),
                )
                self._registrar_historico_memoria(
                    cursor,
                    memoria["id"],
                    "conflito_aceito",
                    memoria["valor"],
                    conflito["valor_proposto"],
                    conflito["origem_proposta"],
                    nova_confianca,
                    metadata=f"conflito_id={conflito_id}",
                )
                status = "aceito"
                resolucao = "valor_proposto_aplicado"
                cursor.execute(
                    """UPDATE conflitos_memoria
                       SET status = 'superado', resolucao = ?, resolvido_em = ?
                       WHERE memoria_id = ? AND status = 'pendente' AND id != ?""",
                    (f"superado_por={conflito_id}", agora, memoria["id"], conflito_id),
                )
            else:
                nova_confianca = min(0.99, float(memoria["confianca"]) + 0.01)
                cursor.execute(
                    """UPDATE memorias
                       SET confianca = ?, reforco_count = COALESCE(reforco_count, 0) + 1,
                           ultima_confirmacao = ?, atualizado_em = ?
                       WHERE id = ?""",
                    (nova_confianca, agora, agora, memoria["id"]),
                )
                self._registrar_historico_memoria(
                    cursor,
                    memoria["id"],
                    "conflito_rejeitado",
                    memoria["valor"],
                    conflito["valor_proposto"],
                    conflito["origem_proposta"],
                    nova_confianca,
                    metadata=f"conflito_id={conflito_id}",
                )
                status = "rejeitado"
                resolucao = "valor_atual_mantido"

            cursor.execute(
                """UPDATE conflitos_memoria
                   SET status = ?, resolucao = ?, resolvido_em = ?
                   WHERE id = ?""",
                (status, resolucao, agora, conflito_id),
            )
            self.connection.commit()
            return True

    def fundir_memorias(self, memoria_principal_id: int, memoria_duplicada_id: int) -> tuple[bool, str]:
        if memoria_principal_id == memoria_duplicada_id:
            return False, "As memorias precisam ter IDs diferentes."
        agora = datetime.now().isoformat()
        with self._lock:
            cursor = self.connection.cursor()
            principal = cursor.execute(
                "SELECT * FROM memorias WHERE id = ? AND status = 'ativa'",
                (memoria_principal_id,),
            ).fetchone()
            duplicada = cursor.execute(
                "SELECT * FROM memorias WHERE id = ? AND status = 'ativa'",
                (memoria_duplicada_id,),
            ).fetchone()
            if not principal or not duplicada:
                return False, "Nao encontrei as duas memorias ativas para fundir."
            if self._normalizar_valor_memoria(principal["valor"]) != self._normalizar_valor_memoria(duplicada["valor"]):
                return False, "Os valores sao diferentes; resolva como conflito em vez de fundir."

            nova_confianca = min(0.99, max(float(principal["confianca"]), float(duplicada["confianca"])) + 0.02)
            cursor.execute(
                """UPDATE memorias
                   SET confianca = ?, uso_count = COALESCE(uso_count, 0) + ?,
                       reforco_count = COALESCE(reforco_count, 0) + COALESCE(?, 0) + 1,
                       ultima_confirmacao = ?, atualizado_em = ?
                   WHERE id = ?""",
                (
                    nova_confianca,
                    int(duplicada["uso_count"] or 0),
                    int(duplicada["reforco_count"] or 0),
                    agora,
                    agora,
                    memoria_principal_id,
                ),
            )
            cursor.execute(
                """UPDATE memorias
                   SET status = 'fundida', fundida_em_id = ?, atualizado_em = ?
                   WHERE id = ?""",
                (memoria_principal_id, agora, memoria_duplicada_id),
            )
            cursor.execute(
                """UPDATE conflitos_memoria
                   SET status = 'superado', resolucao = ?, resolvido_em = ?
                   WHERE memoria_id = ? AND status = 'pendente'""",
                (f"memoria_fundida_em={memoria_principal_id}", agora, memoria_duplicada_id),
            )
            self._registrar_historico_memoria(
                cursor,
                memoria_principal_id,
                "fusao_recebida",
                principal["valor"],
                principal["valor"],
                "curadoria",
                nova_confianca,
                metadata=f"memoria_fundida_id={memoria_duplicada_id}",
            )
            self._registrar_historico_memoria(
                cursor,
                memoria_duplicada_id,
                "fundida",
                duplicada["valor"],
                principal["valor"],
                "curadoria",
                nova_confianca,
                metadata=f"memoria_principal_id={memoria_principal_id}",
            )
            self.connection.commit()
            return True, "Memorias fundidas com historico preservado."

    def buscar_historico_memoria(self, memoria_id: int, limite: int = 20) -> list[sqlite3.Row]:
        return self._fetchall(
            """SELECT id, memoria_id, acao, valor_anterior, valor_novo, origem,
                      confianca, metadata, criado_em
               FROM memoria_historico
               WHERE memoria_id = ?
               ORDER BY id DESC
               LIMIT ?""",
            (memoria_id, max(1, min(100, int(limite)))),
        )

    def arquivar_memorias_temporarias_antigas(self, dias: int = 45) -> list[int]:
        dias = max(7, min(3650, int(dias)))
        limite_data = (datetime.now() - timedelta(days=dias)).isoformat()
        agora = datetime.now().isoformat()
        arquivadas: list[int] = []
        with self._lock:
            cursor = self.connection.cursor()
            candidatas = cursor.execute(
                """SELECT * FROM memorias
                   WHERE status = 'ativa'
                     AND tipo IN ('assunto_atual', 'reflexao')
                     AND confianca < 0.85
                     AND atualizado_em < ?
                     AND (ultimo_uso IS NULL OR ultimo_uso < ?)
                     AND NOT EXISTS (
                         SELECT 1 FROM conflitos_memoria c
                         WHERE c.memoria_id = memorias.id AND c.status = 'pendente'
                     )""",
                (limite_data, limite_data),
            ).fetchall()
            for memoria in candidatas:
                cursor.execute(
                    "UPDATE memorias SET status = 'arquivada', atualizado_em = ? WHERE id = ?",
                    (agora, memoria["id"]),
                )
                self._registrar_historico_memoria(
                    cursor,
                    memoria["id"],
                    "arquivada_por_tempo",
                    memoria["valor"],
                    memoria["valor"],
                    "manutencao_automatica",
                    float(memoria["confianca"]),
                    metadata=f"ttl_dias={dias}",
                )
                arquivadas.append(int(memoria["id"]))
            self.connection.commit()
        return arquivadas

    @staticmethod
    def _normalizar_valor_memoria(valor: str) -> str:
        normalized = unicodedata.normalize("NFKD", valor or "")
        sem_acento = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", sem_acento.casefold()).strip()

    @staticmethod
    def _registrar_historico_memoria(
        cursor: sqlite3.Cursor,
        memoria_id: int,
        acao: str,
        valor_anterior: str,
        valor_novo: str,
        origem: str,
        confianca: float,
        metadata: str = "",
    ):
        cursor.execute(
            """INSERT INTO memoria_historico
               (memoria_id, acao, valor_anterior, valor_novo, origem,
                confianca, metadata, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                memoria_id,
                acao,
                valor_anterior or "",
                valor_novo or "",
                origem or "",
                float(confianca),
                metadata or "",
                datetime.now().isoformat(),
            ),
        )

    def registrar_uso_memorias(self, memoria_ids: list[int]):
        if not memoria_ids:
            return
        agora = datetime.now().isoformat()
        with self._lock:
            cursor = self.connection.cursor()
            cursor.executemany(
                """UPDATE memorias
                   SET uso_count = uso_count + 1,
                       ultimo_uso = ?
                   WHERE id = ? AND status = 'ativa'""",
                [(agora, memoria_id) for memoria_id in memoria_ids],
            )
            self.connection.commit()

    def registrar_evento_aprendizado(self, tipo: str, descricao: str, metadata: str = "") -> int:
        cursor = self._execute(
            """INSERT INTO eventos_aprendizado (tipo, descricao, metadata, criado_em)
               VALUES (?, ?, ?, ?)""",
            (tipo.strip(), descricao.strip(), metadata.strip(), datetime.now().isoformat()),
        )
        return cursor.lastrowid

    def buscar_eventos_aprendizado(self, limite: int = 10) -> list[sqlite3.Row]:
        return self._fetchall(
            """SELECT id, tipo, descricao, metadata, criado_em
               FROM eventos_aprendizado
               ORDER BY id DESC
               LIMIT ?""",
            (limite,),
        )

    def salvar_aprendizado_pendente(
        self,
        categoria: str,
        chave: str,
        valor: str,
        tipo: str = "",
        origem: str = "",
        confianca: float = 0.5,
        status: str = "pendente",
        metadata: str = "",
    ) -> int:
        categoria = categoria.strip().lower()
        status = status.strip().lower() or "pendente"
        chave = chave.strip()
        valor = valor.strip()
        if categoria not in {"memoria", "conhecimento"}:
            raise ValueError("categoria precisa ser memoria ou conhecimento")
        if status not in {"pendente", "aprovado", "rejeitado", "aplicado"}:
            raise ValueError("status de aprendizado invalido")
        if not chave or not valor:
            return 0

        cursor = self._execute(
            """INSERT INTO aprendizados_pendentes
               (categoria, tipo, chave, valor, origem, confianca, status, metadata, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                categoria,
                tipo.strip(),
                chave,
                valor,
                origem.strip(),
                confianca,
                status,
                metadata.strip(),
                datetime.now().isoformat(),
            ),
        )
        return cursor.lastrowid

    def buscar_aprendizado_pendente(self, aprendizado_id: int) -> sqlite3.Row | None:
        return self._fetchone(
            """SELECT id, categoria, tipo, chave, valor, origem, confianca, status, metadata, criado_em, revisado_em
               FROM aprendizados_pendentes
               WHERE id = ?""",
            (aprendizado_id,),
        )

    def listar_aprendizados_pendentes(self, limite: int = 20, status: str = "pendente") -> list[sqlite3.Row]:
        status = (status or "pendente").strip().lower()
        return self._fetchall(
            """SELECT id, categoria, tipo, chave, valor, origem, confianca, status, metadata, criado_em
               FROM aprendizados_pendentes
               WHERE status = ?
               ORDER BY id DESC
               LIMIT ?""",
            (status, limite),
        )

    def contar_aprendizados_pendentes(self) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) AS total FROM aprendizados_pendentes WHERE status = 'pendente'"
        )
        return row["total"]

    def atualizar_status_aprendizado(self, aprendizado_id: int, status: str) -> bool:
        status = status.strip().lower()
        if status not in {"aprovado", "rejeitado", "aplicado"}:
            raise ValueError("status de aprendizado invalido")
        cursor = self._execute(
            """UPDATE aprendizados_pendentes
               SET status = ?, revisado_em = ?
               WHERE id = ? AND status = 'pendente'""",
            (status, datetime.now().isoformat(), aprendizado_id),
        )
        return cursor.rowcount > 0

    def atualizar_metadata_aprendizado(self, aprendizado_id: int, metadata: str) -> bool:
        cursor = self._execute(
            """UPDATE aprendizados_pendentes
               SET metadata = ?
               WHERE id = ? AND status = 'pendente'""",
            (metadata.strip(), aprendizado_id),
        )
        return cursor.rowcount > 0

    def criar_exercicio(
        self,
        topico: str,
        pergunta: str,
        resposta_esperada: str = "",
        nivel: str = "medio",
    ) -> int:
        topico = topico.strip()
        pergunta = pergunta.strip()
        if not topico or not pergunta:
            return 0
        cursor = self._execute(
            """INSERT INTO exercicios
               (topico, pergunta, resposta_esperada, nivel, status, criado_em)
               VALUES (?, ?, ?, ?, 'pendente', ?)""",
            (topico, pergunta, resposta_esperada.strip(), nivel.strip() or "medio", datetime.now().isoformat()),
        )
        return cursor.lastrowid

    def buscar_exercicio(self, exercicio_id: int) -> sqlite3.Row | None:
        return self._fetchone(
            """SELECT id, topico, pergunta, resposta_esperada, nivel, status,
                      resposta_usuario, feedback, nota, criado_em, respondido_em, revisar_em
               FROM exercicios
               WHERE id = ?""",
            (exercicio_id,),
        )

    def listar_exercicios(self, status: str = "pendente", limite: int = 10) -> list[sqlite3.Row]:
        status = (status or "pendente").strip().lower()
        return self._fetchall(
            """SELECT id, topico, pergunta, nivel, status, nota, revisar_em, criado_em
               FROM exercicios
               WHERE status = ?
               ORDER BY id DESC
               LIMIT ?""",
            (status, limite),
        )

    def contar_exercicios_pendentes(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS total FROM exercicios WHERE status = 'pendente'")
        return row["total"]

    def registrar_resposta_exercicio(
        self,
        exercicio_id: int,
        resposta_usuario: str,
        feedback: str,
        nota: float,
        dias_revisao: int,
    ) -> bool:
        nota = max(0.0, min(10.0, float(nota)))
        status = "revisar" if nota < 7 else "concluido"
        revisar_em = (datetime.now() + timedelta(days=max(1, dias_revisao))).date().isoformat()
        cursor = self._execute(
            """UPDATE exercicios
               SET status = ?, resposta_usuario = ?, feedback = ?, nota = ?,
                   respondido_em = ?, revisar_em = ?
               WHERE id = ? AND status = 'pendente'""",
            (
                status,
                resposta_usuario.strip(),
                feedback.strip(),
                nota,
                datetime.now().isoformat(),
                revisar_em,
                exercicio_id,
            ),
        )
        return cursor.rowcount > 0

    def buscar_revisoes_pendentes(self, limite: int = 10) -> list[sqlite3.Row]:
        hoje = datetime.now().date().isoformat()
        return self._fetchall(
            """SELECT id, topico, pergunta, feedback, nota, revisar_em
               FROM exercicios
               WHERE revisar_em IS NOT NULL
                 AND revisar_em <= ?
               ORDER BY revisar_em ASC, id DESC
               LIMIT ?""",
            (hoje, limite),
        )

    def registrar_diario_companhia(
        self,
        tom: str,
        resumo: str,
        mensagem: str = "",
        resposta: str = "",
    ) -> int:
        resumo = resumo.strip()
        if not resumo:
            return 0
        cursor = self._execute(
            """INSERT INTO diario_companhia
               (tom, resumo, mensagem, resposta, criado_em)
               VALUES (?, ?, ?, ?, ?)""",
            (
                (tom or "companhia").strip(),
                resumo,
                (mensagem or "").strip(),
                (resposta or "").strip(),
                datetime.now().isoformat(),
            ),
        )
        return cursor.lastrowid

    def buscar_diario_companhia(self, limite: int = 10) -> list[sqlite3.Row]:
        return self._fetchall(
            """SELECT id, tom, resumo, criado_em
               FROM diario_companhia
               ORDER BY id DESC
               LIMIT ?""",
            (limite,),
        )

    def contar_diario_companhia(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS total FROM diario_companhia")
        return row["total"]

    def fechar(self):
        with self._lock:
            self.connection.close()
