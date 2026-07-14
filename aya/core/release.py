from __future__ import annotations

import subprocess
import sys
import time
import re
import hashlib
import json
import os
import platform
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
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
    timeout_seconds: int | None = None
    timeout_source: str = "nao_aplicavel"
    result_origin: str = "executado"
    validation_id: str = ""
    interpretation: str = ""

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


CHECK_STATES = {
    "APROVADO",
    "REPROVADO",
    "TIMEOUT",
    "INDISPONIVEL",
    "NAO_EXECUTADO",
    "CANCELADO",
    "ERRO_INTERNO",
}


@dataclass(frozen=True)
class ReleaseTimeoutConfig:
    pytest_related: int = 600
    pytest_complete: int = 3600
    tool: int = 300
    adaptive_factor: float = 1.5
    adaptive_minimum: int = 900
    adaptive_maximum: int = 3600
    reuse_window_seconds: int = 7200

    @classmethod
    def from_env(cls) -> "ReleaseTimeoutConfig":
        base = cls()
        return cls(
            pytest_related=_bounded_env_int("AYA_RELEASE_RELATED_PYTEST_TIMEOUT", base.pytest_related, 60, 2400),
            pytest_complete=_bounded_env_int("AYA_RELEASE_PYTEST_TIMEOUT", base.pytest_complete, 60, 5400),
            tool=_bounded_env_int("AYA_RELEASE_TOOL_TIMEOUT", base.tool, 30, 1200),
            adaptive_factor=float(os.getenv("AYA_RELEASE_ADAPTIVE_FACTOR", str(base.adaptive_factor))),
            adaptive_minimum=_bounded_env_int("AYA_RELEASE_ADAPTIVE_MINIMUM", base.adaptive_minimum, 60, 3600),
            adaptive_maximum=_bounded_env_int("AYA_RELEASE_ADAPTIVE_MAXIMUM", base.adaptive_maximum, 60, 5400),
            reuse_window_seconds=_bounded_env_int(
                "AYA_RELEASE_REUSE_WINDOW_SECONDS",
                base.reuse_window_seconds,
                60,
                24 * 3600,
            ),
        )


@dataclass(frozen=True)
class ReleaseEvidence:
    validation_id: str
    mode: str
    check_name: str
    command: str
    exit_code: int | None
    status: str
    started_at: str
    finished_at: str
    duration_ms: int
    project_head: str
    working_tree_clean: bool
    python_version: str
    executable_path: str
    environment_fingerprint: str
    test_scope: str
    output_sha256: str
    result_sha256: str
    created_by: str
    reused: bool = False
    timeout_seconds: int | None = None
    timeout_source: str = ""


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


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


class ReleaseReportService:
    """Gera um relatorio honesto de release sem inventar testes nao executados."""

    FAST_MARK_EXPR = "not integration and not slow and not ollama and not release_full"

    def __init__(
        self,
        db: Database,
        rag_status_provider,
        diagnostics_provider,
        releases_dir: Path | None = None,
        runner: CommandRunner = default_runner,
        timeout_config: ReleaseTimeoutConfig | None = None,
    ):
        self.db = db
        self.rag_status_provider = rag_status_provider
        self.diagnostics_provider = diagnostics_provider
        self.releases_dir = releases_dir or LOGS_DIR / "releases"
        self.evidence_dir = LOGS_DIR / "release_evidence"
        self.test_profiles_dir = LOGS_DIR / "test_profiles"
        self.runner = runner
        self.timeout_config = timeout_config or ReleaseTimeoutConfig.from_env()

    def build(self, salvar: bool = False) -> str:
        snapshot = self._snapshot()
        report = self._format(snapshot)
        if salvar:
            path = self._save(report, snapshot.created_at)
            report += f"\n\nRelatorio salvo em: {path}"
        return report

    def execute(self, mode: str = "completo", reuse: bool = False) -> str:
        mode = self._normalize_mode(mode)
        snapshot = self._snapshot()
        checks = self._run_checks(mode, reuse=reuse)
        report = self._format(snapshot, checks, mode=mode)
        path = self._save(report, snapshot.created_at)
        return report + f"\n\nRelatorio salvo em: {path}"

    def validar(self, mode: str = "completo", reuse: bool = False) -> str:
        return self.execute(mode=mode, reuse=reuse)

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

    def perfil_testes(self, action: str = "") -> str:
        action = (action or "").strip().lower()
        if "historico" in action:
            return self.perfil_testes_historico()
        if "ultimo" in action:
            return self.perfil_testes_ultimo()
        mode = "rapido" if "rapido" in action or "rápido" in action else "completo"
        created_at = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = self.test_profiles_dir / f"test_profile_{created_at}_{mode}.json"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "scripts.pytest_profile_plugin",
            "--aya-profile-output",
            str(json_path),
            *self._pytest_args_for_mode(mode),
        ]
        timeout, _source = self._timeout_for_check("pytest", mode)
        started = time.perf_counter()
        try:
            result = self.runner(command, timeout)
        except subprocess.TimeoutExpired:
            return f"Perfil de testes excedeu {timeout}s e ficou incompleto. Arquivo esperado: {json_path}"
        duration = time.perf_counter() - started
        if not json_path.exists():
            return f"Perfil de testes nao foi gerado. Codigo: {getattr(result, 'returncode', 'indisponivel')}"
        data = self._load_profile(json_path)
        markdown = self._profile_markdown(data)
        md_path = json_path.with_suffix(".md")
        md_path.write_text(markdown, encoding="utf-8")
        status = "APROVADO" if result.returncode == 0 else "REPROVADO"
        return "\n".join(
            [
                "Perfil de desempenho dos testes:",
                f"- Modo: {mode}",
                f"- Status: {status}",
                f"- Duracao observada pelo comando: {duration:.1f}s",
                f"- Testes coletados: {data.get('total_collected', 'indisponivel')}",
                f"- Testes aprovados: {data.get('total_passed', 'indisponivel')}",
                f"- JSON: {json_path}",
                f"- Markdown: {md_path}",
                "A suite rapida nao substitui o release completo.",
            ]
        )

    def perfil_testes_ultimo(self) -> str:
        latest = self._latest_profile()
        if not latest:
            return "Nenhum perfil de testes encontrado em logs/test_profiles/."
        md_path = latest.with_suffix(".md")
        if md_path.exists():
            return self._trim_output(md_path.read_text(encoding="utf-8", errors="replace"), limit=8000)
        return self._profile_markdown(self._load_profile(latest))

    def perfil_testes_historico(self, limite: int = 8) -> str:
        profiles = self._profile_files()
        if not profiles:
            return "Nenhum perfil de testes encontrado em logs/test_profiles/."
        lines = ["Historico de perfis de teste:"]
        for path in profiles[:limite]:
            data = self._load_profile(path)
            lines.append(
                f"- {path.name} | collected={data.get('total_collected')} | "
                f"passed={data.get('total_passed')} | duracao_ms={data.get('total_duration_ms')}"
            )
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

    def _format(
        self,
        snapshot: ReleaseSnapshot,
        checks: list[ReleaseCheck] | None = None,
        mode: str = "completo",
    ) -> str:
        mode = self._normalize_mode(mode)
        checks = checks or self._not_executed_checks(mode)
        complete = self._is_complete(checks, mode)
        overall = self._overall_status(checks)
        return "\n".join([
            "Relatorio tecnico de release da Aya",
            f"Gerado em: {snapshot.created_at}",
            f"Python: {sys.version.split()[0]}",
            f"Ambiente: {sys.prefix}",
            f"Modo: {mode}",
            f"HEAD: {self._project_head()}",
            f"Working tree limpo: {'sim' if self._working_tree_clean() else 'nao'}",
            f"Release completo: {'sim' if complete else 'nao'}",
            f"Release tipo: {'COMPLETO' if complete else 'PARCIAL'}",
            f"Status geral: {overall}",
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

    def _run_checks(self, mode: str, reuse: bool = False) -> list[ReleaseCheck]:
        checks: list[ReleaseCheck] = []
        for name, command, scope in self._checks_for_mode(mode):
            timeout, timeout_source = self._timeout_for_check(name, mode)
            if reuse:
                reused = self._find_reusable_evidence(name, command, mode, scope)
                if reused:
                    checks.append(self._check_from_evidence(reused))
                    continue
            started = time.perf_counter()
            started_at = datetime.now()
            executed_at = datetime.now().isoformat(timespec="seconds")
            try:
                result = self.runner(command, timeout)
                output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
                returncode = result.returncode
                state = self._classify_check(returncode, output)
            except subprocess.TimeoutExpired as exc:
                partial = self._decode_timeout_output(exc)
                output = (
                    f"O {name} excedeu o limite de {timeout} segundos. "
                    "A execucao ficou incompleta; isso nao comprova reprovacao da suite.\n"
                    "O processo foi encerrado.\n"
                    f"{partial}"
                ).strip()
                returncode = None
                state = "TIMEOUT"
            except (FileNotFoundError, ModuleNotFoundError) as exc:
                output = f"Falha ao executar comando: {exc}"
                returncode = None
                state = "INDISPONIVEL"
            except KeyboardInterrupt:
                output = "Execucao cancelada de forma controlada."
                returncode = None
                state = "CANCELADO"
            except Exception as exc:
                output = f"Falha interna do mecanismo de release: {exc}"
                returncode = None
                state = "ERRO_INTERNO"
            duration = time.perf_counter() - started
            sanitized_output = self._sanitize_output(output)
            evidence = self._save_evidence(
                name=name,
                command=command,
                mode=mode,
                scope=scope,
                returncode=returncode,
                state=state,
                started_at=started_at,
                duration_seconds=duration,
                output=sanitized_output,
                timeout_seconds=timeout,
                timeout_source=timeout_source,
            )
            checks.append(ReleaseCheck(
                name=name,
                command=command,
                returncode=returncode,
                duration_seconds=duration,
                output=sanitized_output,
                executed_at=executed_at,
                state=state,
                timeout_seconds=timeout,
                timeout_source=timeout_source,
                result_origin="executado",
                validation_id=evidence.validation_id,
                interpretation=self._interpretation(state, name, timeout),
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
            lines.append(f"  timeout_s: {check.timeout_seconds if check.timeout_seconds is not None else 'nao registrado'}")
            lines.append(f"  origem_timeout: {check.timeout_source}")
            lines.append(f"  origem_resultado: {check.result_origin}")
            lines.append(f"  evidencia_id: {check.validation_id or 'nao registrada'}")
            if check.name == "pytest" and " -m " in f" {check.command_text} ":
                self._append_pytest_scope(lines, check)
            if check.interpretation:
                lines.append(f"  interpretacao: {check.interpretation}")
            if check.output:
                lines.append("  saida:")
                lines.extend(f"    {line}" for line in self._trim_output(check.output).splitlines())
        return lines

    def _not_executed_checks(self, mode: str = "completo") -> list[ReleaseCheck]:
        return [
            ReleaseCheck(
                name=name,
                command=command,
                returncode=None,
                duration_seconds=0,
                output="",
                executed_at="",
                state="NAO_EXECUTADO",
                timeout_seconds=self._timeout_for_check(name, mode)[0],
                timeout_source=self._timeout_for_check(name, mode)[1],
            )
            for name, command, _scope in self._checks_for_mode(mode)
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

    def _is_complete(self, checks: list[ReleaseCheck], mode: str = "completo") -> bool:
        states = {check.name: check.state for check in checks}
        required = {name for name, _command, _scope in self._checks_for_mode(mode)}
        return required.issubset(states) and all(states[name] == "APROVADO" for name in required)

    def _overall_status(self, checks: list[ReleaseCheck]) -> str:
        states = {check.state for check in checks}
        if all(state == "APROVADO" for state in states):
            return "APROVADO"
        if "ERRO_INTERNO" in states:
            return "ERRO"
        if "REPROVADO" in states:
            return "REPROVADO"
        if states & {"TIMEOUT", "INDISPONIVEL", "CANCELADO", "NAO_EXECUTADO"}:
            return "PARCIAL"
        return "PARCIAL"

    def _checks_for_mode(self, mode: str) -> list[tuple[str, list[str], str]]:
        mode = self._normalize_mode(mode)
        pytest_command = [sys.executable, "-m", "pytest", *self._pytest_args_for_mode(mode)]
        return [
            ("pytest", pytest_command, "suite_completa" if mode == "completo" else "release_curto"),
            ("ruff", [sys.executable, "-m", "ruff", "check", "."], "codigo_estatico"),
            ("compileall", [sys.executable, "-m", "compileall", "."], "sintaxe"),
            ("pip check", [sys.executable, "-m", "pip", "check"], "dependencias"),
            ("smoke_test.py", [sys.executable, "scripts\\smoke_test.py"], "smoke"),
        ]

    def _pytest_args_for_mode(self, mode: str) -> list[str]:
        if self._normalize_mode(mode) == "rapido":
            return ["-m", self.FAST_MARK_EXPR]
        return []

    def _timeout_for_check(self, name: str, mode: str) -> tuple[int, str]:
        if name == "pytest" and self._normalize_mode(mode) == "completo":
            adaptive = self._adaptive_pytest_timeout()
            if adaptive:
                return adaptive, "adaptativo"
            return self.timeout_config.pytest_complete, "configuracao"
        if name == "pytest":
            return self.timeout_config.pytest_related, "configuracao"
        return self.timeout_config.tool, "configuracao"

    def _adaptive_pytest_timeout(self) -> int | None:
        evidence = self._latest_approved_evidence("pytest", mode="completo")
        if not evidence:
            return None
        observed = max(1, evidence.duration_ms / 1000)
        budget = int(observed * self.timeout_config.adaptive_factor)
        budget = max(self.timeout_config.adaptive_minimum, budget)
        return min(self.timeout_config.adaptive_maximum, budget)

    def _normalize_mode(self, mode: str) -> str:
        value = (mode or "").strip().lower()
        if value in {"rapido", "rápido", "quick"}:
            return "rapido"
        return "completo"

    def _decode_timeout_output(self, exc: subprocess.TimeoutExpired) -> str:
        parts: list[str] = []
        for value in (exc.stdout, exc.stderr):
            if not value:
                continue
            if isinstance(value, bytes):
                parts.append(value.decode("utf-8", errors="replace"))
            else:
                parts.append(str(value))
        return "\n".join(parts).strip()

    def _interpretation(self, state: str, name: str, timeout: int) -> str:
        if state == "TIMEOUT":
            return (
                f"O {name} excedeu o limite de {timeout} segundos. "
                "A execucao ficou incompleta; isso nao comprova reprovacao da suite."
            )
        if state == "INDISPONIVEL":
            return "Comando, modulo ou dependencia indisponivel no ambiente atual."
        if state == "NAO_EXECUTADO":
            return "Check registrado como nao executado."
        if state == "ERRO_INTERNO":
            return "Falha da infraestrutura de release, separada da suite do projeto."
        return ""

    def _project_head(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else "indisponivel"
        except Exception:
            return "indisponivel"

    def _working_tree_clean(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=PROJECT_ROOT,
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            return result.returncode == 0 and not result.stdout.strip()
        except Exception:
            return False

    def _environment_fingerprint(self) -> str:
        payload = {
            "python": platform.python_version(),
            "executable": sys.executable,
            "prefix": sys.prefix,
            "platform": platform.platform(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _output_hash(self, output: str) -> str:
        return hashlib.sha256((output or "").encode("utf-8", errors="replace")).hexdigest()

    def _result_hash(self, evidence: dict) -> str:
        relevant = {key: value for key, value in evidence.items() if key != "result_sha256"}
        return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode("utf-8")).hexdigest()

    def _save_evidence(
        self,
        *,
        name: str,
        command: list[str],
        mode: str,
        scope: str,
        returncode: int | None,
        state: str,
        started_at: datetime,
        duration_seconds: float,
        output: str,
        timeout_seconds: int,
        timeout_source: str,
    ) -> ReleaseEvidence:
        finished_at = datetime.now()
        validation_id = f"VAL-{finished_at.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        evidence = ReleaseEvidence(
            validation_id=validation_id,
            mode=mode,
            check_name=name,
            command=" ".join(command),
            exit_code=returncode,
            status=state,
            started_at=started_at.isoformat(timespec="seconds"),
            finished_at=finished_at.isoformat(timespec="seconds"),
            duration_ms=int(duration_seconds * 1000),
            project_head=self._project_head(),
            working_tree_clean=self._working_tree_clean(),
            python_version=platform.python_version(),
            executable_path=sys.executable,
            environment_fingerprint=self._environment_fingerprint(),
            test_scope=scope,
            output_sha256=self._output_hash(output),
            result_sha256="",
            created_by="release_service",
            reused=False,
            timeout_seconds=timeout_seconds,
            timeout_source=timeout_source,
        )
        payload = asdict(evidence)
        payload["result_sha256"] = self._result_hash(payload)
        evidence = ReleaseEvidence(**payload)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        (self.evidence_dir / f"{validation_id}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return evidence

    def _evidence_items(self) -> list[ReleaseEvidence]:
        if not self.evidence_dir.exists():
            return []
        items: list[ReleaseEvidence] = []
        for path in sorted(self.evidence_dir.glob("VAL-*.json"), key=lambda item: item.name, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                recorded_hash = payload.get("result_sha256", "")
                if recorded_hash != self._result_hash(payload):
                    continue
                items.append(ReleaseEvidence(**payload))
            except (OSError, TypeError, ValueError):
                continue
        return items

    def _latest_approved_evidence(self, check_name: str, mode: str) -> ReleaseEvidence | None:
        expected_command = ""
        for name, command, _scope in self._checks_for_mode(mode):
            if name == check_name:
                expected_command = " ".join(command)
                break
        current_head = self._project_head()
        for evidence in self._evidence_items():
            if (
                evidence.check_name == check_name
                and evidence.mode == mode
                and evidence.status == "APROVADO"
                and evidence.command == expected_command
                and evidence.project_head == current_head
                and evidence.working_tree_clean
                and (check_name != "pytest" or mode != "completo" or evidence.duration_ms >= 60_000)
            ):
                return evidence
        return None

    def _find_reusable_evidence(
        self,
        name: str,
        command: list[str],
        mode: str,
        scope: str,
    ) -> ReleaseEvidence | None:
        now = datetime.now()
        command_text = " ".join(command)
        if not self._working_tree_clean():
            return None
        for evidence in self._evidence_items():
            created = self._parse_created_at(evidence.finished_at)
            if not created or now - created > timedelta(seconds=self.timeout_config.reuse_window_seconds):
                continue
            if (
                evidence.check_name == name
                and evidence.mode == mode
                and evidence.command == command_text
                and evidence.status == "APROVADO"
                and evidence.project_head == self._project_head()
                and evidence.working_tree_clean
                and evidence.python_version == platform.python_version()
                and evidence.executable_path == sys.executable
                and evidence.environment_fingerprint == self._environment_fingerprint()
                and evidence.test_scope == scope
            ):
                return evidence
        return None

    def _check_from_evidence(self, evidence: ReleaseEvidence) -> ReleaseCheck:
        return ReleaseCheck(
            name=evidence.check_name,
            command=evidence.command.split(),
            returncode=evidence.exit_code,
            duration_seconds=evidence.duration_ms / 1000,
            output=(
                f"Resultado reutilizado de evidencia aprovada {evidence.validation_id}; "
                "os testes nao foram executados novamente neste release."
            ),
            executed_at=evidence.finished_at,
            state=evidence.status,
            timeout_seconds=evidence.timeout_seconds,
            timeout_source=evidence.timeout_source or "evidencia",
            result_origin="reutilizado",
            validation_id=evidence.validation_id,
        )

    def _append_pytest_scope(self, lines: list[str], check: ReleaseCheck) -> None:
        command = check.command_text
        if f"-m {self.FAST_MARK_EXPR}" in command:
            lines.append(f"  selecao: {self.FAST_MARK_EXPR}")
            lines.append("  aviso: A suite rapida nao substitui o release completo.")
        else:
            lines.append("  selecao: suite completa sem filtro de marcadores")
        collected, deselected = self._parse_pytest_counts(check.output)
        if collected is not None:
            lines.append(f"  testes_coletados: {collected}")
        if deselected is not None:
            lines.append(f"  testes_excluidos: {deselected}")
            lines.append(f"  testes_executados_estimados: {max(0, (collected or 0) - deselected)}")

    def _parse_pytest_counts(self, output: str) -> tuple[int | None, int | None]:
        collected = None
        deselected = None
        match = re.search(r"collected\s+(\d+)\s+items", output or "")
        if match:
            collected = int(match.group(1))
        match = re.search(r"(\d+)\s+deselected", output or "")
        if match:
            deselected = int(match.group(1))
        return collected, deselected

    def _load_profile(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def _profile_files(self) -> list[Path]:
        if not self.test_profiles_dir.exists():
            return []
        files = []
        for path in self.test_profiles_dir.glob("*.json"):
            try:
                if "profile_id" in self._load_profile(path):
                    files.append(path)
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)

    def _latest_profile(self) -> Path | None:
        profiles = self._profile_files()
        return profiles[0] if profiles else None

    def _profile_markdown(self, data: dict) -> str:
        tests = data.get("tests", [])
        commands = data.get("commands", [])
        by_file = defaultdict(int)
        by_marker = defaultdict(int)
        marker_counts = defaultdict(int)
        for test in tests:
            by_file[test.get("nodeid", "").split("::", 1)[0]] += int(test.get("total_ms", 0))
            markers = test.get("markers") or ["unit/inferido"]
            for marker in markers:
                by_marker[marker] += int(test.get("total_ms", 0))
                marker_counts[marker] += 1
        total = max(1, int(data.get("total_duration_ms", 0)))
        slowest = sorted(tests, key=lambda item: int(item.get("total_ms", 0)), reverse=True)
        top10_ms = sum(int(test.get("total_ms", 0)) for test in slowest[:10])
        lines = [
            "# Perfil de desempenho dos testes",
            "",
            f"- Perfil: {data.get('profile_id')}",
            f"- HEAD: {data.get('project_head')}",
            f"- Duracao total: {total} ms",
            f"- Coletados: {data.get('total_collected')}",
            f"- Aprovados: {data.get('total_passed')}",
            f"- Falhas: {data.get('total_failed')}",
            f"- Pulados: {data.get('total_skipped')}",
            f"- Python: {data.get('python_version')}",
            f"- Pytest: {data.get('pytest_version')}",
            f"- Top 10 testes: {top10_ms} ms de {total} ms ({(top10_ms / total) * 100:.1f}%)",
            "",
            "## 20 testes mais lentos",
            *self._format_profile_rows(slowest[:20], "total_ms"),
            "",
            "## 20 setups mais lentos",
            *self._format_profile_rows(sorted(tests, key=lambda item: int(item.get("setup_ms", 0)), reverse=True)[:20], "setup_ms"),
            "",
            "## 20 teardowns mais lentos",
            *self._format_profile_rows(sorted(tests, key=lambda item: int(item.get("teardown_ms", 0)), reverse=True)[:20], "teardown_ms"),
            "",
            "## Duracao acumulada por arquivo",
            *[f"- {value} ms | {name}" for name, value in sorted(by_file.items(), key=lambda item: item[1], reverse=True)[:20]],
            "",
            "## Duracao acumulada por marcador",
            *[f"- {value} ms | {name}" for name, value in sorted(by_marker.items(), key=lambda item: item[1], reverse=True)[:20]],
            "",
            "## Quantidade por categoria",
            *[f"- {name}: {count}" for name, count in sorted(marker_counts.items())],
            "",
            "## Limites",
            *self._threshold_lines(tests),
            "",
            "## Comandos externos mais caros",
            *[
                f"- {cmd.get('total_ms')} ms | {cmd.get('count')}x | {cmd.get('command')}"
                for cmd in sorted(commands, key=lambda item: int(item.get("total_ms", 0)), reverse=True)[:20]
            ],
            "",
            "## Comparacao com perfil anterior",
            *self._profile_comparison_lines(data),
        ]
        return "\n".join(lines)

    def _format_profile_rows(self, tests: list[dict], field: str) -> list[str]:
        if not tests:
            return ["- sem dados"]
        return [f"- {int(test.get(field, 0))} ms | {test.get('nodeid')}" for test in tests]

    def _threshold_lines(self, tests: list[dict]) -> list[str]:
        lines = []
        for seconds in (1, 5, 10, 30, 60):
            threshold = seconds * 1000
            count = sum(1 for test in tests if int(test.get("total_ms", 0)) >= threshold)
            lines.append(f"- >= {seconds}s: {count} teste(s)")
        return lines

    def _profile_comparison_lines(self, current: dict) -> list[str]:
        profiles = [path for path in self._profile_files() if path.name != self._profile_name(current)]
        if not profiles:
            return ["- Perfil anterior indisponivel."]
        previous = self._load_profile(profiles[0])
        before = int(previous.get("total_duration_ms", 0))
        after = int(current.get("total_duration_ms", 0))
        diff = after - before
        percent = (diff / before * 100) if before else 0
        tolerance_ms = 1000
        tolerance_percent = 5.0
        signal = "dentro da tolerancia" if abs(diff) < tolerance_ms or abs(percent) < tolerance_percent else "mudanca relevante"
        return [
            f"- Anterior: {previous.get('profile_id')} ({before} ms)",
            f"- Atual: {current.get('profile_id')} ({after} ms)",
            f"- Diferenca: {diff} ms ({percent:.1f}%) - {signal}",
            *self._profile_delta_lines(previous, current),
        ]

    def _profile_name(self, data: dict) -> str:
        profile_id = str(data.get("profile_id", ""))
        for path in self._profile_files():
            try:
                if self._load_profile(path).get("profile_id") == profile_id:
                    return path.name
            except Exception:
                continue
        return ""

    def _profile_delta_lines(self, previous: dict, current: dict) -> list[str]:
        previous_tests = {test.get("nodeid"): test for test in previous.get("tests", [])}
        current_tests = {test.get("nodeid"): test for test in current.get("tests", [])}
        added = sorted(set(current_tests) - set(previous_tests))
        removed = sorted(set(previous_tests) - set(current_tests))
        deltas = []
        for nodeid in sorted(set(previous_tests) & set(current_tests)):
            diff = int(current_tests[nodeid].get("total_ms", 0)) - int(previous_tests[nodeid].get("total_ms", 0))
            if abs(diff) >= 1000:
                deltas.append((diff, nodeid))
        slower = sorted([item for item in deltas if item[0] > 0], reverse=True)[:5]
        faster = sorted([item for item in deltas if item[0] < 0])[:5]
        lines = [f"- Testes adicionados: {len(added)}", f"- Testes removidos: {len(removed)}"]
        lines.extend(f"- Mais lento: +{diff} ms | {nodeid}" for diff, nodeid in slower)
        lines.extend(f"- Mais rapido: {diff} ms | {nodeid}" for diff, nodeid in faster)
        return lines

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
        states = "|".join(sorted(CHECK_STATES))
        checks = dict(re.findall(rf"^- ([\w ._]+):\s*({states})\b", text, flags=re.MULTILINE))
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
            "TIMEOUT": [],
            "INDISPONIVEL": [],
            "NAO_EXECUTADO": [],
            "CANCELADO": [],
            "ERRO_INTERNO": [],
        }
        for name, state in release.checks.items():
            states.setdefault(state, []).append(name)
        missing = self._missing_checks(release)
        states["NAO_EXECUTADO"].extend(missing)
        return [
            f"- Checks aprovados: {', '.join(states['APROVADO']) or 'nenhum'}",
            f"- Checks reprovados: {', '.join(states['REPROVADO']) or 'nenhum'}",
            f"- Checks com timeout: {', '.join(states['TIMEOUT']) or 'nenhum'}",
            f"- Checks indisponiveis: {', '.join(states['INDISPONIVEL']) or 'nenhum'}",
            f"- Checks nao executados: {', '.join(states['NAO_EXECUTADO']) or 'nenhum'}",
            f"- Checks cancelados: {', '.join(states['CANCELADO']) or 'nenhum'}",
            f"- Erros internos: {', '.join(states['ERRO_INTERNO']) or 'nenhum'}",
        ]

    def _missing_checks(self, release: SavedRelease) -> list[str]:
        required = [name for name, _command, _scope in self._checks_for_mode("completo")]
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
