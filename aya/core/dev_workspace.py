from __future__ import annotations

import re
import shutil
import subprocess
import time
from math import ceil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


FULL_VALIDATION_PYTEST_TIMEOUT_SECONDS = 1200
VALIDATION_COMMANDS = (
    ("pytest", ("python", "-m", "pytest"), FULL_VALIDATION_PYTEST_TIMEOUT_SECONDS),
    ("ruff", ("python", "-m", "ruff", "check", "."), 180),
    ("compileall", ("python", "-m", "compileall", "."), 180),
    ("pip check", ("python", "-m", "pip", "check"), 180),
    ("smoke", ("python", "scripts/smoke_test.py"), 180),
)
RELATED_TEST_TIMEOUT_POLICY_VERSION = "related_tests_timeout_v1"
RELATED_TEST_TIMEOUT_MINIMUM_SECONDS = 900
RELATED_TEST_TIMEOUT_MAXIMUM_SECONDS = 1800
RELATED_TEST_TIMEOUT_FALLBACK_SECONDS = 1200
FULL_BASELINE_TIMEOUT_POLICY_VERSION = "baseline_full_timeout_v1"
FULL_BASELINE_TIMEOUT_MINIMUM_SECONDS = 1200
FULL_BASELINE_TIMEOUT_MAXIMUM_SECONDS = 3600
FULL_BASELINE_TIMEOUT_FALLBACK_SECONDS = 2400
PROTECTED_NAMES = {".env", ".env.local", ".env.example"}
PROTECTED_PARTS = {"data_local", "logs", "backups", ".git", "voices"}
PROTECTED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".key", ".pem", ".onnx"}
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*([^\s'\"]+|['\"][^'\"]+['\"])",
)


@dataclass(frozen=True)
class GitState:
    valid: bool
    clean: bool
    message: str
    changed_files: tuple[str, ...] = ()

    @property
    def safe(self) -> bool:
        return self.valid and self.clean


@dataclass(frozen=True)
class CheckResult:
    name: str
    command: str
    exit_code: int
    duration_ms: int
    output: str
    started_at: str = ""
    timeout_seconds: int | None = None
    result: str = ""
    failure_category: str = ""
    evidence_source: str = "executed"

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass(frozen=True)
class PatchInspection:
    valid: bool
    message: str
    files: tuple[str, ...]
    changed_lines: int
    diff_created: bool = False


class DevWorkspace:
    """Worktree isolada com comandos fixos e patches limitados."""

    def __init__(self, root: str | Path, workspace_root: str | Path | None = None):
        self.root = Path(root).resolve()
        self.workspace_root = Path(workspace_root or self.root.parent / "aya_dev_workspaces").resolve()

    def git_state(self) -> GitState:
        top = self._run(("git", "rev-parse", "--show-toplevel"), self.root, 15)
        if top.returncode != 0:
            return GitState(False, False, "Git indisponivel ou repositorio invalido.")
        try:
            recognized_root = Path(top.stdout.strip()).resolve()
        except OSError:
            return GitState(False, False, "A raiz informada pelo Git e invalida.")
        if recognized_root != self.root:
            return GitState(False, False, "A raiz do Git nao corresponde a raiz configurada da Aya.")
        status = self._run(("git", "status", "--porcelain"), self.root, 15)
        if status.returncode != 0:
            return GitState(False, False, "Nao foi possivel consultar git status.")
        changed = tuple(line[3:] for line in status.stdout.splitlines() if len(line) >= 4)
        if changed:
            return GitState(True, False, f"Repositorio possui {len(changed)} alteracao(oes) nao salvas.", changed)
        return GitState(True, True, "Repositorio Git valido e limpo.")

    def head(self) -> str:
        result = self._run(("git", "rev-parse", "HEAD"), self.root, 15)
        if result.returncode != 0:
            raise RuntimeError("Nao foi possivel consultar HEAD.")
        return result.stdout.strip()

    def create(self, proposal_id: str) -> Path:
        state = self.git_state()
        if not state.safe:
            raise RuntimeError(state.message)
        target = self.workspace_root / self._safe_id(proposal_id)
        if target.exists():
            raise RuntimeError("O workspace isolado dessa proposta ja existe.")
        target.parent.mkdir(parents=True, exist_ok=True)
        result = self._run(("git", "worktree", "add", "--detach", str(target), "HEAD"), self.root, 90)
        if result.returncode != 0:
            raise RuntimeError(f"Nao foi possivel criar Git worktree: {self.sanitize(result.stderr or result.stdout)}")
        return target

    def discard(self, workspace: str | Path) -> str:
        path = self._workspace_path(workspace)
        status = self._run(("git", "status", "--porcelain"), path, 30)
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else True
        command = ("git", "worktree", "remove", str(path))
        if dirty:
            command = ("git", "worktree", "remove", "--force", str(path))
        result = self._run(command, self.root, 90)
        if result.returncode != 0 and path.exists():
            shutil.rmtree(path)
        prune = self._run(("git", "worktree", "prune"), self.root, 90)
        if result.returncode != 0:
            return f"Worktree removido por fallback; prune codigo={prune.returncode}."
        return f"Worktree removido {'com --force apos preservar diff' if dirty else 'sem --force'}; prune codigo={prune.returncode}."

    def inspect_patch(
        self,
        patch: str,
        max_files: int = 4,
        max_lines: int = 250,
        allowed_files: list[str] | tuple[str, ...] | None = None,
    ) -> PatchInspection:
        if not self._looks_like_pure_unified_diff(patch):
            return PatchInspection(False, "O modelo deve retornar somente diff unificado puro.", (), 0, False)
        allowed = set(allowed_files or ())
        files: list[str] = []
        changed_lines = 0
        has_hunk = False
        for line in patch.splitlines():
            if line.startswith("@@ "):
                has_hunk = True
            if line.startswith(("+++ ", "--- ")):
                raw = line[4:].split("\t", 1)[0].strip()
                if raw == "/dev/null":
                    continue
                rel = raw[2:] if raw.startswith(("a/", "b/")) else raw
                error = self._path_error(rel)
                if error:
                    return PatchInspection(False, error, tuple(files), changed_lines, True)
                if allowed and rel not in allowed:
                    return PatchInspection(False, f"Arquivo fora do escopo autorizado: {rel}.", tuple(files), changed_lines, True)
                if line.startswith("+++ ") and rel not in files:
                    files.append(rel)
            elif line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                changed_lines += 1
        if not files:
            return PatchInspection(False, "O modelo nao produziu um diff unificado verificavel.", (), changed_lines, False)
        if not has_hunk:
            return PatchInspection(False, "Diff unificado sem hunk verificavel.", tuple(files), changed_lines, True)
        if len(files) > max_files:
            return PatchInspection(False, f"Patch excede o limite de {max_files} arquivos.", tuple(files), changed_lines, True)
        if changed_lines > max_lines:
            return PatchInspection(False, f"Patch excede o limite de {max_lines} linhas modificadas.", tuple(files), changed_lines, True)
        return PatchInspection(True, "Patch dentro dos limites.", tuple(files), changed_lines, True)

    def apply_patch(
        self,
        workspace: str | Path,
        patch: str,
        max_files: int = 4,
        max_lines: int = 250,
        allowed_files: list[str] | tuple[str, ...] | None = None,
    ) -> PatchInspection:
        path = self._workspace_path(workspace)
        inspection = self.inspect_patch(patch, max_files, max_lines, allowed_files)
        if not inspection.valid:
            return inspection
        check = self._run(("git", "apply", "--check", "-"), path, 30, input_text=patch)
        if check.returncode != 0:
            return PatchInspection(False, f"Patch recusado pelo Git: {self.sanitize(check.stderr)}", inspection.files, inspection.changed_lines, True)
        applied = self._run(("git", "apply", "-"), path, 30, input_text=patch)
        if applied.returncode != 0:
            return PatchInspection(False, f"Falha ao aplicar no workspace: {self.sanitize(applied.stderr)}", inspection.files, inspection.changed_lines, True)
        return inspection

    def diff(self, workspace: str | Path) -> str:
        path = self._workspace_path(workspace)
        result = self._run(("git", "diff", "--no-ext-diff", "--"), path, 30)
        return self.sanitize(result.stdout) if result.returncode == 0 else "Diff indisponivel."

    def diff_check(self, workspace: str | Path) -> CheckResult:
        path = self._workspace_path(workspace)
        return self._check("git diff --check", ("git", "diff", "--check"), 30, path)

    def validate(
        self,
        workspace: str | Path,
        related_tests: list[str] | None = None,
        *,
        related_test_timeout: int | None = None,
    ) -> list[CheckResult]:
        path = self._workspace_path(workspace)
        results: list[CheckResult] = []
        if related_tests:
            safe_tests = [test for test in related_tests if not self._path_error(test) and test.endswith(".py")]
            if safe_tests:
                timeout = related_test_timeout or calculate_related_test_timeout(None)
                results.append(
                    self._check(
                        "testes relacionados",
                        ("python", "-m", "pytest", *safe_tests),
                        timeout,
                        path,
                    )
                )
                if not results[-1].passed:
                    return results
        for name, command, timeout in VALIDATION_COMMANDS:
            results.append(self._check(name, command, timeout, path))
        return results

    def baseline(self, workspace: str | Path, related_tests: list[str] | None = None) -> list[CheckResult]:
        return self.validate(workspace, related_tests)

    def sanitize(self, text: str, limit: int = 5000) -> str:
        """Redact sensitive values and truncate technical command output."""
        redacted = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[PROTEGIDO]", text or "")
        return redacted[:limit] + ("\n... [saida truncada]" if len(redacted) > limit else "")

    def _check(self, name: str, command: tuple[str, ...], timeout: int, cwd: Path) -> CheckResult:
        started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        started = time.perf_counter()
        try:
            result = self._run(command, cwd, timeout)
            code = result.returncode
            output = self.sanitize("\n".join(value for value in (result.stdout, result.stderr) if value))
        except subprocess.TimeoutExpired:
            code = 124
            output = "Tempo limite excedido."
        return CheckResult(
            name,
            " ".join(command),
            code,
            int((time.perf_counter() - started) * 1000),
            output,
            started_at=started_at,
            timeout_seconds=timeout,
        )

    def _run(
        self,
        command: tuple[str, ...],
        cwd: Path,
        timeout: int,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )

    def _workspace_path(self, workspace: str | Path) -> Path:
        path = Path(workspace).resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("Workspace fora da area isolada da Aya.") from exc
        if not path.exists() or not path.is_dir():
            raise ValueError("Workspace isolado nao encontrado.")
        return path

    def _path_error(self, value: str) -> str:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or not normalized or ":" in normalized:
            return "Patch contem caminho fora da raiz permitida."
        lowered = {part.lower() for part in path.parts}
        if path.name.lower() in PROTECTED_NAMES or lowered & PROTECTED_PARTS or path.suffix.lower() in PROTECTED_SUFFIXES:
            return f"Arquivo protegido no patch: {normalized}."
        target = self.root.joinpath(*path.parts)
        if target.is_symlink():
            try:
                target.resolve().relative_to(self.root)
            except ValueError:
                return "Patch aponta para link simbolico externo."
        return ""

    def _looks_like_pure_unified_diff(self, patch: str) -> bool:
        text = patch.strip()
        if not text or "```" in text:
            return False
        lines = text.splitlines()
        allowed_prefixes = ("diff --git ", "index ", "--- ", "+++ ", "@@ ", "+", "-", " ")
        for line in lines:
            if line.startswith(allowed_prefixes) or line == r"\ No newline at end of file":
                continue
            return False
        return any(line.startswith("--- ") for line in lines) and any(line.startswith("+++ ") for line in lines)

    def _safe_id(self, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("Identificador de proposta invalido.")
        return value


def calculate_related_test_timeout(baseline_duration_seconds: float | None) -> int:
    if baseline_duration_seconds is None:
        return RELATED_TEST_TIMEOUT_FALLBACK_SECONDS
    calculated = ceil((baseline_duration_seconds * 1.5) + 60)
    return max(RELATED_TEST_TIMEOUT_MINIMUM_SECONDS, min(RELATED_TEST_TIMEOUT_MAXIMUM_SECONDS, calculated))


def calculate_full_baseline_timeout(duration_seconds: float | None) -> int:
    if duration_seconds is None:
        return FULL_BASELINE_TIMEOUT_FALLBACK_SECONDS
    calculated = ceil((duration_seconds * 1.5) + 120)
    return max(FULL_BASELINE_TIMEOUT_MINIMUM_SECONDS, min(FULL_BASELINE_TIMEOUT_MAXIMUM_SECONDS, calculated))
