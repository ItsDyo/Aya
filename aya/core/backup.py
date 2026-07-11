from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aya.data.database import Database
from aya.paths import BACKUPS_DIR, DATA_DIR, EXPORTS_DIR, LOGS_DIR, ensure_runtime_dirs


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    created_at: str
    size_bytes: int


class BackupService:
    """Cria backups portaveis dos dados persistentes da Aya."""

    def __init__(
        self,
        db: Database,
        backups_dir: Path = BACKUPS_DIR,
        data_dir: Path = DATA_DIR,
        exports_dir: Path = EXPORTS_DIR,
        logs_dir: Path = LOGS_DIR,
    ):
        self.db = db
        self.backups_dir = backups_dir
        self.data_dir = data_dir
        self.exports_dir = exports_dir
        self.logs_dir = logs_dir

    def criar_backup(self, label: str = "") -> str:
        ensure_runtime_dirs()
        self.backups_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = self._safe_label(label)
        backup_name = f"aya_backup_{timestamp}{suffix}.zip"
        backup_path = self.backups_dir / backup_name
        temp_db = self.backups_dir / f"study_ai_{timestamp}.db"

        try:
            self._backup_sqlite(temp_db)
            manifest = self._manifest(backup_name, label)
            with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(temp_db, "data_local/study_ai.db")
                self._add_optional_tree(
                    archive,
                    self.data_dir,
                    "data_local",
                    exclude={self.db.db_path.name, f"{self.db.db_path.name}-wal", f"{self.db.db_path.name}-shm"},
                )
                self._add_optional_tree(archive, self.exports_dir, "exports")
                self._add_optional_tree(archive, self.logs_dir, "logs", patterns=("*.log",))
                archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        finally:
            self._safe_unlink(temp_db)

        return (
            "Backup criado com sucesso.\n"
            f"- Arquivo: {backup_path}\n"
            f"- Tamanho: {self._format_size(backup_path.stat().st_size)}\n"
            "- Inclui banco SQLite, historico local, exports e logs."
        )

    def listar_backups(self, limite: int = 10) -> str:
        backups = self._listar_infos(limite)
        if not backups:
            return "Ainda nao existem backups da Aya."
        linhas = ["Backups encontrados:"]
        for item in backups:
            linhas.append(f"- {item.path.name} | {self._format_size(item.size_bytes)} | {item.created_at}")
        return "\n".join(linhas)

    def verificar_backup(self, caminho: str = "") -> str:
        backup_path = self._resolver_backup(caminho)
        if not backup_path:
            return "Use assim: `/backup verificar nome_do_backup.zip` ou gere um backup primeiro."
        if not backup_path.exists():
            return f"Backup nao encontrado: {backup_path}"

        try:
            with zipfile.ZipFile(backup_path) as archive:
                bad_file = archive.testzip()
                names = set(archive.namelist())
                required = {"manifest.json", "data_local/study_ai.db"}
                missing = sorted(required - names)
                db_status = self._verificar_sqlite_no_zip(archive) if not missing else "incompleto"
        except zipfile.BadZipFile:
            return f"Backup invalido ou corrompido: {backup_path}"
        except sqlite3.DatabaseError as exc:
            return f"Backup contem banco SQLite invalido: {exc}"

        if bad_file:
            return f"Backup corrompido. Primeiro arquivo com erro: {bad_file}"
        if missing:
            return f"Backup incompleto. Itens ausentes: {', '.join(missing)}"
        return f"Backup verificado com sucesso: {backup_path.name} (SQLite quick_check={db_status})"

    def extrair_backup(self, caminho: str = "") -> str:
        backup_path = self._resolver_backup(caminho)
        if not backup_path:
            return "Use assim: `/backup extrair nome_do_backup.zip` ou gere um backup primeiro."
        verificacao = self.verificar_backup(str(backup_path))
        if "Backup verificado com sucesso" not in verificacao:
            return verificacao

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destino = self.backups_dir / f"restaurado_{timestamp}"
        destino.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(backup_path) as archive:
            archive.extractall(destino)
        return (
            "Backup extraido com seguranca.\n"
            f"- Origem: {backup_path.name}\n"
            f"- Pasta: {destino}\n"
            "- A Aya atual nao foi sobrescrita."
        )

    def resumo(self) -> str:
        backups = self._listar_infos(5)
        if not backups:
            return "Backups: nenhum backup encontrado."
        ultimo = backups[0]
        return f"Backups: ultimo em {ultimo.created_at} ({self._format_size(ultimo.size_bytes)})."

    def _backup_sqlite(self, target: Path):
        destination = sqlite3.connect(target)
        try:
            with self.db._lock:
                self.db.connection.commit()
                self.db.connection.backup(destination)
            destination.commit()
        finally:
            destination.close()

    def _safe_unlink(self, path: Path):
        for _ in range(5):
            try:
                path.unlink(missing_ok=True)
                return
            except PermissionError:
                time.sleep(0.1)
        path.unlink(missing_ok=True)

    def _verificar_sqlite_no_zip(self, archive: zipfile.ZipFile) -> str:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_db = Path(temp_dir) / "study_ai.db"
            temp_db.write_bytes(archive.read("data_local/study_ai.db"))
            connection = sqlite3.connect(temp_db)
            try:
                row = connection.execute("PRAGMA quick_check").fetchone()
                return str(row[0] if row else "sem resposta")
            finally:
                connection.close()

    def _manifest(self, backup_name: str, label: str) -> dict[str, object]:
        return {
            "name": backup_name,
            "label": label.strip(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "schema_version": Database.SCHEMA_VERSION,
            "database_path": str(self.db.db_path),
            "contents": ["data_local/study_ai.db", "data_local/*", "exports/*", "logs/*.log"],
        }

    def _add_optional_tree(
        self,
        archive: zipfile.ZipFile,
        source: Path,
        archive_root: str,
        exclude: set[str] | None = None,
        patterns: tuple[str, ...] = ("*",),
    ):
        if not source.exists():
            return
        exclude = exclude or set()
        seen: set[Path] = set()
        for pattern in patterns:
            for path in source.rglob(pattern):
                if path in seen or path.is_dir() or path.name in exclude:
                    continue
                seen.add(path)
                relative = path.relative_to(source)
                archive.write(path, str(Path(archive_root) / relative))

    def _listar_infos(self, limite: int) -> list[BackupInfo]:
        if not self.backups_dir.exists():
            return []
        backups = sorted(self.backups_dir.glob("aya_backup_*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
        infos = []
        for path in backups[:limite]:
            created_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
            infos.append(BackupInfo(path=path, created_at=created_at, size_bytes=path.stat().st_size))
        return infos

    def _resolver_backup(self, caminho: str) -> Path | None:
        value = (caminho or "").strip().strip('"')
        if value:
            path = Path(value)
            if not path.is_absolute():
                path = self.backups_dir / path
            return path
        backups = self._listar_infos(1)
        return backups[0].path if backups else None

    def _safe_label(self, label: str) -> str:
        value = "".join(ch for ch in (label or "").strip().lower().replace(" ", "_") if ch.isalnum() or ch in "_-")
        return f"_{value[:40]}" if value else ""

    def _format_size(self, size: int) -> str:
        units = ["B", "KB", "MB", "GB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"
