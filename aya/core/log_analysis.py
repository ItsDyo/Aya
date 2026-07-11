from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import re


@dataclass(frozen=True)
class LogIssue:
    module: str
    message: str
    exception_type: str
    count: int
    first_seen: str
    last_seen: str
    status: str
    severity: str


@dataclass(frozen=True)
class LogSummary:
    total_error_records: int
    unique_errors: int
    duplicated_records: int
    active_errors: int
    recovered_errors: int
    old_errors: int
    warnings: int
    normal_ignored: int
    sensitive_findings: int
    issues: list[LogIssue]


def analyze_logs(logs_dir: Path) -> LogSummary:
    try:
        if not logs_dir.exists():
            return empty_log_summary()
        records = []
        warnings = 0
        sensitive = 0
        for path in logs_dir.glob("*.log"):
            text = path.read_text(encoding="utf-8", errors="replace")
            sensitive += count_sensitive_lines(text)
            parsed = parse_log_records(text)
            records.extend(parsed)
            warnings += sum(1 for item in parsed if item["level"] == "WARNING")
        error_records = [item for item in records if is_error_record(item)]
        issues = group_log_issues(error_records)
        active = sum(1 for issue in issues if issue.status == "ativo")
        recovered = sum(1 for issue in issues if issue.status in {"recuperado", "falha recuperada"})
        old = sum(1 for issue in issues if issue.status == "antigo")
        total_errors = sum(issue.count for issue in issues)
        return LogSummary(
            total_error_records=total_errors,
            unique_errors=len(issues),
            duplicated_records=max(0, total_errors - len(issues)),
            active_errors=active,
            recovered_errors=recovered,
            old_errors=old,
            warnings=warnings,
            normal_ignored=max(0, len(records) - len(error_records) - warnings),
            sensitive_findings=sensitive,
            issues=issues,
        )
    except OSError:
        return empty_log_summary()


def empty_log_summary() -> LogSummary:
    return LogSummary(0, 0, 0, 0, 0, 0, 0, 0, 0, [])


def parse_log_records(text: str) -> list[dict]:
    start_re = re.compile(
        r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) "
        r"\[(?P<level>\w+)\] (?P<module>[^:]+): (?P<message>.*)$"
    )
    records: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        match = start_re.match(line)
        if match:
            if current:
                records.append(current)
            current = {**match.groupdict(), "lines": [line]}
        elif current:
            current["lines"].append(line)
    if current:
        records.append(current)
    return records


def is_error_record(record: dict) -> bool:
    block = "\n".join(record.get("lines", []))
    return record.get("level") in {"ERROR", "CRITICAL"} or "Traceback" in block


def group_log_issues(records: list[dict]) -> list[LogIssue]:
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for record in records:
        exception_type = exception_type_from_record(record)
        key = (record.get("module", ""), record.get("message", ""), exception_type)
        grouped.setdefault(key, []).append(record)

    issues: list[LogIssue] = []
    for (module, message, exception_type), items in grouped.items():
        times = sorted(str(item.get("ts", "")) for item in items)
        status = issue_status(items, exception_type)
        severity = issue_severity(status, exception_type, len(items))
        issues.append(LogIssue(
            module=module,
            message=message,
            exception_type=exception_type,
            count=len(items),
            first_seen=times[0] if times else "indisponivel",
            last_seen=times[-1] if times else "indisponivel",
            status=status,
            severity=severity,
        ))
    return sorted(issues, key=lambda item: (item.status != "ativo", -item.count, item.last_seen), reverse=False)


def exception_type_from_record(record: dict) -> str:
    for line in reversed(record.get("lines", [])):
        stripped = line.strip()
        match = re.match(
            r"^(?:(?:[A-Za-z_][\w.]*\.)?([A-Za-z_][\w.]*?(?:Error|Exception))|RuntimeError|ConnectionResetError|PermissionError|re\.PatternError):",
            stripped,
        )
        if match:
            return stripped.split(":", 1)[0]
    return "sem excecao"


def issue_status(items: list[dict], exception_type: str) -> str:
    last_seen = max(str(item.get("ts", "")) for item in items)
    last_dt = parse_ts(last_seen)
    block = "\n".join("\n".join(item.get("lines", [])) for item in items)
    if "\\tests\\" in block or "/tests/" in block or "tests\\test_" in block:
        return "falha recuperada"
    if "modelo de embedding ausente" in block:
        return "falha recuperada"
    if exception_type == "ConnectionResetError":
        return "antigo" if older_than(last_dt, days=1) else "recuperado"
    if older_than(last_dt, days=1):
        return "antigo"
    return "ativo"


def issue_severity(status: str, exception_type: str, count: int) -> str:
    if status == "ativo":
        return "alta" if count > 1 else "media"
    if status == "falha recuperada":
        return "baixa"
    if exception_type in {"PermissionError", "ConnectionResetError"}:
        return "media"
    return "baixa"


def parse_ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S,%f")
    except ValueError:
        return None


def older_than(value: datetime | None, days: int) -> bool:
    if not value:
        return False
    return datetime.now() - value > timedelta(days=days)


def count_sensitive_lines(text: str) -> int:
    patterns = [
        r"(?i)(api[_-]?key|token|secret|password|senha)\s*[:=]",
        r"sk-[A-Za-z0-9_-]{10,}",
    ]
    return sum(1 for line in text.splitlines() if any(re.search(pattern, line) for pattern in patterns))
