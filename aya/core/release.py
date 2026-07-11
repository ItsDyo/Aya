from __future__ import annotations

import subprocess
import sys
import time
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from aya.data.database import Database
from aya.paths import LOGS_DIR, PROJECT_ROOT


@dataclass(frozen=True)
class ReleaseSnapshot:
    created_at: str
    quick_check: str
    conversations: int
    knowledge: int
    memories: int
    conflicts: int
    pending_learning: int
    pending_exercises: int
    rag_status: str
    diagnostics: str


@dataclass(frozen=True)
class ReleaseCheck:
    name: str
    command: list[str]
    returncode: int | None
    duration_seconds: float
    output: str
    executed_at: str
    state: str = "NAO_EXECUTADO"

    @property
    def passed(self) -> bool:
        return self.state == "APROVADO"

    @property
    def command_text(self) -> str:
        return " ".join(self.command)


@dataclass(frozen=True)
class SavedRelease:
    path: Path
    created_at: str
    checks: dict[str, str]
    quick_check: str
    knowledge: int | None
    memories: int | None
    conflicts: int | None
    complete: bool = False

    @property
    def all_checks_passed(self) -> bool:
        return self.complete or (bool(self.checks) and self._has_required_checks() and all(status == "APROVADO" for status in self.checks.values()))

    def _has_required_checks(self) -> bool:
        required = {"pytest", "ruff", "compileall", "pip check", "smoke_test.py"}
        return required.issubset(set(self.checks))


class CommandRunner(Protocol):
    def __call__(self, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        ...


def default_runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


class ReleaseReportService:
    """Gera um relatorio honesto de release sem inventar testes nao executados."""

    REQUIRED_CHECKS = [
        ("pytest", [sys.executable, "-m", "pytest"], 600),
        ("ruff", [sys.executable, "-m", "ruff", "check", "."], 180),
        ("compileall", [sys.executable, "-m", "compileall", "."], 180),
        ("pip check", [sys.executable, "-m", "pip", "check"], 180),
        ("smoke_test.py", [sys.executable, "scripts\\smoke_test.py"], 180),
    ]

    def __init__(
        self,
        db: Database,
        rag_status_provider,
        diagnostics_provider,
        releases_dir: Path | None = None,
        runner: CommandRunner = default_runner,
    ):
        self.db = db
        self.rag_status_provider = rag_status_provider
        self.diagnostics_provider = diagnostics_provider
        self.releases_dir = releases_dir or LOGS_DIR / "releases"
        self.runner = runner

    def build(self, salvar: bool = False) -> str:
        snapshot = self._snapshot()
        report = self._format(snapshot)
        if salvar:
            path = self._save(report, snapshot.created_at)
            report += f"\n\nRelatorio salvo em: {path}"
        return report

    def execute(self) -> str:
        snapshot = self._snapshot()
        checks = self._run_checks()
        report = self._format(snapshot, checks)
        path = self._save(report, snapshot.created_at)
        return report + f"\n\nRelatorio salvo em: {path}"

    def validar(self) -> str:
        return self.execute()

    def status(self) -> str:
        releases = self._saved_releases()
        if not releases:
            return "Status de release:\n- Nenhum relatorio de release encontrado em logs/releases/."
        latest = releases[0]
        complete = self._latest_complete_release(releases)
        lines = [
            "Status de release:",
            f"- Ultimo release: {latest.path.name}",
            f"- Gerado em: {latest.created_at}",
            f"- Tipo: {'completo' if latest.all_checks_passed else 'parcial'}",
            *self._status_counts(latest),
            f"- Idade do relatorio: {self._age_text(latest.created_at)}",
            f"- Estado temporal: {self._freshness_text(latest)}",
            f"- Arquivos alterados desde a validacao: {len(self._changed_files_since(latest.path.stat().st_mtime))}",
        ]
        missing = self._missing_checks(latest)
        if missing:
            lines.append(f"- Checks que precisam ser executados novamente: {', '.join(missing)}")
        if complete:
            lines.append(f"- Ultimo release completo: {complete.path.name} ({complete.created_at})")
        else:
            lines.append("- Ultimo release completo: nenhum encontrado")
        return "\n".join(lines)

    def listar(self, limite: int = 8) -> str:
        releases = self._saved_releases()
        if not releases:
            return "Nenhum relatorio de release encontrado em logs/releases/."
        lines = ["Historico tecnico de releases:"]
        for release in releases[:limite]:
            status = "COMPLETO" if release.all_checks_passed else "PARCIAL"
            lines.append(
                f"- {release.path.name} | {release.created_at} | {status} | "
                f"checks={len(release.checks)} | quick_check={release.quick_check}"
            )
        return "\n".join(lines)

    def ultimo(self) -> str:
        releases = self._saved_releases()
        if not releases:
            return "Nenhum relatorio de release encontrado em logs/releases/."
        release = releases[0]
        text = release.path.read_text(encoding="utf-8", errors="replace")
        return self._trim_output(text, limit=6000)

    def ultimo_completo(self) -> str:
        release = self._latest_complete_release()
        if not release:
            return "Nenhum release completo encontrado em logs/releases/."
        text = release.path.read_text(encoding="utf-8", errors="replace")
        return self._trim_output(text, limit=6000)

    def comparar(self) -> str:
        releases = self._saved_releases()
        if len(releases) < 2:
            return "Preciso de pelo menos dois relatorios em logs/releases/ para comparar."
        atual, anterior = releases[0], releases[1]
        lines = [
            "Comparacao de releases:",
            f"- Atual: {atual.path.name} ({atual.created_at})",
            f"- Anterior: {anterior.path.name} ({anterior.created_at})",
            "",
            "Checks:",
        ]
        all_names = sorted(set(atual.checks) | set(anterior.checks))
        for name in all_names:
            before = anterior.checks.get(name, "ausente")
            after = atual.checks.get(name, "ausente")
            marker = "igual" if before == after else "mudou"
            lines.append(f"- {name}: {before} -> {after} ({marker})")
        lines.extend([
            "",
            "Dados:",
            f"- Conhecimentos: {anterior.knowledge} -> {atual.knowledge}",
            f"- Memorias: {anterior.memories} -> {atual.memories}",
            f"- Conflitos: {anterior.conflicts} -> {atual.conflicts}",
            f"- SQLite quick_check: {anterior.quick_check} -> {atual.quick_check}",
        ])
        return "\n".join(lines)

    def _snapshot(self) -> ReleaseSnapshot:
        try:
            quick_check = self.db.connection.execute("PRAGMA quick_check").fetchone()[0]
        except Exception as exc:
            quick_check = f"erro: {exc}"
        return ReleaseSnapshot(
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            quick_check=quick_check,
            conversations=self.db.contar_mensagens_totais(),
            knowledge=self.db.contar_conhecimentos(),
            memories=self.db.contar_memorias(),
            conflicts=self.db.contar_conflitos_memoria(),
            pending_learning=self.db.contar_aprendizados_pendentes(),
            pending_exercises=self.db.contar_exercicios_pendentes(),
            rag_status=self.rag_status_provider(),
            diagnostics=self.diagnostics_provider(),
        )

    def _format(self, snapshot: ReleaseSnapshot, checks: list[ReleaseCheck] | None = None) -> str:
        checks = checks or self._not_executed_checks()
        complete = self._is_complete(checks)
        return "\n".join([
            "Relatorio tecnico de release da Aya",
            f"Gerado em: {snapshot.created_at}",
            f"Python: {sys.version.split()[0]}",
            f"Ambiente: {sys.prefix}",
            f"Release completo: {'sim' if complete else 'nao'}",
            f"Release tipo: {'COMPLETO' if complete else 'PARCIAL'}",
            "",
            "Estado verificado agora:",
            f"- Banco SQLite: quick_check={snapshot.quick_check}",
            f"- Conversas salvas: {snapshot.conversations}",
            f"- Conhecimentos: {snapshot.knowledge}",
            f"- Memorias persistentes: {snapshot.memories}",
            f"- Conflitos de memoria: {snapshot.conflicts}",
            f"- Aprendizados pendentes: {snapshot.pending_learning}",
            f"- Exercicios pendentes: {snapshot.pending_exercises}",
            f"- {snapshot.rag_status}",
            "",
            "Checklist de release:",
            f"- Banco integro: {'APROVADO' if snapshot.quick_check == 'ok' else 'REPROVADO'}",
            *self._format_checks(checks),
            "",
            "Diagnostico resumido:",
            self._trim_diagnostics(snapshot.diagnostics),
            "",
            "Riscos para fechar 1.0:",
            *self._risks(snapshot),
            "",
            "Comandos recomendados antes de declarar release:",
            "python -m pytest",
            "python -m ruff check .",
            "python -m compileall .",
            "python -m pip check",
            "python scripts\\smoke_test.py",
        ])

    def _run_checks(self) -> list[ReleaseCheck]:
        checks: list[ReleaseCheck] = []
        for name, command, timeout in self.REQUIRED_CHECKS:
            started = time.perf_counter()
            executed_at = datetime.now().isoformat(timespec="seconds")
            try:
                result = self.runner(command, timeout)
                output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
                returncode = result.returncode
                state = self._classify_check(returncode, output)
            except subprocess.TimeoutExpired as exc:
                output = f"Tempo esgotado apos {timeout}s.\n{exc.stdout or ''}\n{exc.stderr or ''}".strip()
                returncode = 124
                state = "REPROVADO"
            except Exception as exc:
                output = f"Falha ao executar comando: {exc}"
                returncode = None
                state = "INDISPONIVEL"
            checks.append(ReleaseCheck(
                name=name,
                command=command,
                returncode=returncode,
                duration_seconds=time.perf_counter() - started,
                output=self._sanitize_output(output),
                executed_at=executed_at,
                state=state,
            ))
        return checks

    def _format_checks(self, checks: list[ReleaseCheck]) -> list[str]:
        lines: list[str] = []
        for check in checks:
            lines.append(f"- {check.name}: {check.state} ({check.duration_seconds:.1f}s)")
            lines.append(f"  estado: {check.state}")
            lines.append(f"  comando: {check.command_text}")
            lines.append(f"  codigo_saida: {check.returncode if check.returncode is not None else 'indisponivel'}")
            lines.append(f"  executado_em: {check.executed_at if check.state != 'NAO_EXECUTADO' else 'nao executado'}")
            lines.append(f"  duracao_ms: {int(check.duration_seconds * 1000)}")
            if check.output:
                lines.append("  saida:")
                lines.extend(f"    {line}" for line in self._trim_output(check.output).splitlines())
        return lines

    def _not_executed_checks(self) -> list[ReleaseCheck]:
        return [
            ReleaseCheck(
                name=name,
                command=command,
                returncode=None,
                duration_seconds=0,
                output="",
                executed_at="",
                state="NAO_EXECUTADO",
            )
            for name, command, _timeout in self.REQUIRED_CHECKS
        ]

    def _classify_check(self, returncode: int, output: str) -> str:
        lower = output.lower()
        unavailable_markers = (
            "no module named",
            "is not recognized",
            "not found",
            "cannot find",
            "no such file",
        )
        if any(marker in lower for marker in unavailable_markers):
            return "INDISPONIVEL"
        return "APROVADO" if returncode == 0 else "REPROVADO"

    def _is_complete(self, checks: list[ReleaseCheck]) -> bool:
        states = {check.name: check.state for check in checks}
        required = {name for name, _command, _timeout in self.REQUIRED_CHECKS}
        return required.issubset(states) and all(states[name] == "APROVADO" for name in required)

    def _risks(self, snapshot: ReleaseSnapshot) -> list[str]:
        risks: list[str] = []
        if snapshot.quick_check != "ok":
            risks.append("- Banco SQLite precisa ser corrigido antes de release.")
        if snapshot.conflicts:
            risks.append("- Existem conflitos de memoria pendentes.")
        if snapshot.pending_learning:
            risks.append("- Existem aprendizados pendentes de curadoria.")
        if "Embeddings locais: ativos" not in snapshot.rag_status:
            risks.append("- RAG semantico nao esta ativo.")
        if not risks:
            risks.append("- Nenhum risco critico detectado nos dados verificados agora.")
        return risks

    def _trim_output(self, output: str, limit: int = 2400) -> str:
        text = output.strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "\n... [saida truncada]"

    def _sanitize_output(self, output: str) -> str:
        sanitized = []
        patterns = [
            (r"(?i)(api[_-]?key|token|secret|password|senha)\s*[:=]\s*\S+", r"\1=[segredo ocultado]"),
            (r"sk-[A-Za-z0-9_-]{8,}", "[segredo ocultado]"),
        ]
        for line in (output or "").splitlines():
            clean = line
            for pattern, replacement in patterns:
                clean = re.sub(pattern, replacement, clean)
            sanitized.append(clean)
        return "\n".join(sanitized).strip()

    def _trim_diagnostics(self, diagnostics: str, limit: int = 5000) -> str:
        text = diagnostics.strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "\n... [diagnostico truncado]"

    def _save(self, report: str, created_at: str) -> Path:
        self.releases_dir.mkdir(parents=True, exist_ok=True)
        slug = created_at.replace(":", "").replace("-", "").replace(" ", "_")
        path = self.releases_dir / f"release_{slug}.md"
        index = 2
        while path.exists():
            path = self.releases_dir / f"release_{slug}_{index}.md"
            index += 1
        path.write_text(report, encoding="utf-8")
        return path

    def _saved_releases(self) -> list[SavedRelease]:
        if not self.releases_dir.exists():
            return []
        items: list[SavedRelease] = []
        for path in sorted(self.releases_dir.glob("release_*.md"), key=lambda item: item.name, reverse=True):
            items.append(self._parse_saved_release(path))
        return items

    def _parse_saved_release(self, path: Path) -> SavedRelease:
        text = path.read_text(encoding="utf-8", errors="replace")
        created = self._match_text(text, r"Gerado em:\s*(.+)") or "desconhecido"
        quick = self._match_text(text, r"Banco SQLite:\s*quick_check=([^\n]+)") or "desconhecido"
        checks = dict(re.findall(r"^- ([\w ._]+):\s*(APROVADO|REPROVADO|INDISPONIVEL|NAO_EXECUTADO)\b", text, flags=re.MULTILINE))
        complete_text = self._match_text(text, r"Release completo:\s*(sim|nao)")
        complete = complete_text == "sim"
        return SavedRelease(
            path=path,
            created_at=created,
            checks=checks,
            quick_check=quick,
            knowledge=self._match_int(text, r"Conhecimentos:\s*(\d+)"),
            memories=self._match_int(text, r"Memorias persistentes:\s*(\d+)"),
            conflicts=self._match_int(text, r"Conflitos de memoria:\s*(\d+)"),
            complete=complete,
        )

    def _match_text(self, text: str, pattern: str) -> str | None:
        match = re.search(pattern, text)
        return match.group(1).strip() if match else None

    def _match_int(self, text: str, pattern: str) -> int | None:
        value = self._match_text(text, pattern)
        return int(value) if value is not None else None

    def _latest_complete_release(self, releases: list[SavedRelease] | None = None) -> SavedRelease | None:
        releases = releases if releases is not None else self._saved_releases()
        for release in releases:
            if release.all_checks_passed:
                return release
        return None

    def _status_counts(self, release: SavedRelease) -> list[str]:
        states = {
            "APROVADO": [],
            "REPROVADO": [],
            "INDISPONIVEL": [],
            "NAO_EXECUTADO": [],
        }
        for name, state in release.checks.items():
            states.setdefault(state, []).append(name)
        missing = self._missing_checks(release)
        states["NAO_EXECUTADO"].extend(missing)
        return [
            f"- Checks aprovados: {', '.join(states['APROVADO']) or 'nenhum'}",
            f"- Checks reprovados: {', '.join(states['REPROVADO']) or 'nenhum'}",
            f"- Checks indisponiveis: {', '.join(states['INDISPONIVEL']) or 'nenhum'}",
            f"- Checks nao executados: {', '.join(states['NAO_EXECUTADO']) or 'nenhum'}",
        ]

    def _missing_checks(self, release: SavedRelease) -> list[str]:
        required = [name for name, _command, _timeout in self.REQUIRED_CHECKS]
        return [name for name in required if name not in release.checks]

    def _age_text(self, created_at: str) -> str:
        created = self._parse_created_at(created_at)
        if not created:
            return "desconhecida"
        seconds = max(0, int((datetime.now() - created).total_seconds()))
        if seconds < 60:
            return f"{seconds} segundo(s)"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minuto(s)"
        hours = minutes // 60
        if hours < 48:
            return f"{hours} hora(s)"
        return f"{hours // 24} dia(s)"

    def _freshness_text(self, release: SavedRelease) -> str:
        created = self._parse_created_at(release.created_at)
        if not created:
            return "desconhecido"
        changed = self._changed_files_since(release.path.stat().st_mtime)
        if changed:
            return f"desatualizado; {len(changed)} arquivo(s) do projeto mudaram depois da validacao"
        hours = (datetime.now() - created).total_seconds() / 3600
        if hours > 24:
            return "desatualizado pela idade do relatorio"
        return "atual"

    def _changed_files_since(self, timestamp: float) -> list[Path]:
        ignored_parts = {".git", ".pytest_cache", ".ruff_cache", "__pycache__", "logs", "data_local", "backups", "exports", "voices"}
        extensions = {".py", ".md", ".txt", ".toml", ".json", ".ps1"}
        changed: list[Path] = []
        for path in PROJECT_ROOT.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(PROJECT_ROOT)
            if any(part in ignored_parts for part in relative.parts):
                continue
            if path.suffix.lower() not in extensions:
                continue
            try:
                if path.stat().st_mtime > timestamp:
                    changed.append(relative)
            except OSError:
                continue
        return changed[:20]

    def _parse_created_at(self, value: str) -> datetime | None:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(value.strip(), fmt)
            except ValueError:
                continue
        return None
