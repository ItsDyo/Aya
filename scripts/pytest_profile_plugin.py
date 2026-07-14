from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


SENSITIVE_PATTERN = re.compile(
    r"(?i)(token|secret|password|senha|api[_-]?key|authorization|bearer)[=:\s]+[^\s]+|sk-[A-Za-z0-9_-]{8,}"
)
ACTIVE_PROFILE = None


def pytest_addoption(parser):
    group = parser.getgroup("aya-profile")
    group.addoption("--aya-profile-output", action="store", default="", help="Write Aya test profile JSON here.")


def pytest_configure(config):
    global ACTIVE_PROFILE
    output = config.getoption("--aya-profile-output")
    config._aya_profile = AyaProfile(output) if output else None
    if config._aya_profile:
        ACTIVE_PROFILE = config._aya_profile
        config._aya_profile.install()


def pytest_unconfigure(config):
    global ACTIVE_PROFILE
    profile = getattr(config, "_aya_profile", None)
    if profile:
        profile.uninstall()
    ACTIVE_PROFILE = None


def pytest_collection_finish(session):
    profile = getattr(session.config, "_aya_profile", None)
    if not profile:
        return
    profile.total_collected = len(session.items)
    for item in session.items:
        profile.register_item(item)


def pytest_runtest_protocol(item, nextitem):
    profile = getattr(item.config, "_aya_profile", None)
    if profile:
        profile.current_nodeid = item.nodeid
    return None


def pytest_runtest_logreport(report):
    profile = ACTIVE_PROFILE
    if profile:
        profile.record_report(report)


def pytest_sessionfinish(session, exitstatus):
    profile = getattr(session.config, "_aya_profile", None)
    if profile:
        profile.finish(exitstatus)


class AyaProfile:
    def __init__(self, output: str):
        self.output = Path(output)
        self.profile_id = f"TP-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
        self.started_at = datetime.now()
        self.started_perf = time.perf_counter()
        self.current_nodeid = ""
        self.total_collected = 0
        self.tests: dict[str, dict[str, Any]] = {}
        self.command_stats: dict[str, dict[str, Any]] = {}
        self._original_run = subprocess.run

    def install(self) -> None:
        subprocess.run = self._run_wrapper

    def uninstall(self) -> None:
        subprocess.run = self._original_run

    def register_item(self, item) -> None:
        markers = sorted(marker.name for marker in item.iter_markers())
        self.tests.setdefault(
            item.nodeid,
            {
                "nodeid": item.nodeid,
                "arquivo": str(Path(str(item.fspath))).replace("\\", "/"),
                "classe": item.cls.__name__ if item.cls else "",
                "funcao": item.name,
                "outcome": "notrun",
                "setup_ms": 0,
                "call_ms": 0,
                "teardown_ms": 0,
                "total_ms": 0,
                "markers": markers,
            },
        )

    def record_report(self, report) -> None:
        item = self.tests.setdefault(
            report.nodeid,
            {
                "nodeid": report.nodeid,
                "arquivo": report.nodeid.split("::", 1)[0],
                "classe": "",
                "funcao": report.nodeid.split("::")[-1],
                "outcome": "notrun",
                "setup_ms": 0,
                "call_ms": 0,
                "teardown_ms": 0,
                "total_ms": 0,
                "markers": [],
            },
        )
        duration_ms = int(report.duration * 1000)
        item[f"{report.when}_ms"] = duration_ms
        item["total_ms"] = int(item.get("setup_ms", 0) + item.get("call_ms", 0) + item.get("teardown_ms", 0))
        if report.when == "call" or report.failed or report.skipped:
            item["outcome"] = report.outcome

    def finish(self, exitstatus: int) -> None:
        finished = datetime.now()
        tests = list(self.tests.values())
        payload = {
            "profile_id": self.profile_id,
            "project_head": self._project_head(),
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "total_duration_ms": int((time.perf_counter() - self.started_perf) * 1000),
            "python_version": platform.python_version(),
            "pytest_version": self._pytest_version(),
            "environment_fingerprint": self._environment_fingerprint(),
            "exitstatus": exitstatus,
            "total_collected": self.total_collected,
            "total_passed": sum(1 for item in tests if item["outcome"] == "passed"),
            "total_failed": sum(1 for item in tests if item["outcome"] == "failed"),
            "total_skipped": sum(1 for item in tests if item["outcome"] == "skipped"),
            "tests": tests,
            "commands": sorted(self.command_stats.values(), key=lambda item: item["total_ms"], reverse=True),
        }
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _run_wrapper(self, command, *args, **kwargs):
        started = time.perf_counter()
        try:
            return self._original_run(command, *args, **kwargs)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            normalized = self._normalize_command(command)
            stat = self.command_stats.setdefault(
                normalized,
                {"command": normalized, "count": 0, "total_ms": 0, "tests": []},
            )
            stat["count"] += 1
            stat["total_ms"] += duration_ms
            if self.current_nodeid and self.current_nodeid not in stat["tests"]:
                stat["tests"].append(self.current_nodeid)

    def _normalize_command(self, command) -> str:
        if isinstance(command, (list, tuple)):
            parts = [str(part) for part in command]
        else:
            parts = str(command).split()
        safe = []
        redact_next = False
        for part in parts:
            if redact_next:
                safe.append("[segredo ocultado]")
                redact_next = False
            elif SENSITIVE_PATTERN.search(part):
                safe.append("[segredo ocultado]")
            elif part.lower() in {"--token", "--password", "--senha", "--secret", "--api-key"}:
                safe.append(part)
                redact_next = True
            else:
                safe.append(part)
        return " ".join(safe)

    def _project_head(self) -> str:
        try:
            result = self._original_run(
                ["git", "rev-parse", "HEAD"],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else "indisponivel"
        except Exception:
            return "indisponivel"

    def _environment_fingerprint(self) -> str:
        payload = {
            "python": platform.python_version(),
            "executable": sys.executable,
            "prefix": sys.prefix,
            "platform": platform.platform(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _pytest_version(self) -> str:
        try:
            import pytest

            return pytest.__version__
        except Exception:
            return "indisponivel"
