from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data_local"
EXPORTS_DIR = PROJECT_ROOT / "exports"
LOGS_DIR = PROJECT_ROOT / "logs"
BACKUPS_DIR = PROJECT_ROOT / "backups"

DB_PATH = DATA_DIR / "study_ai.db"
HISTORY_PATH = DATA_DIR / "historico_aya.json"
FINE_TUNING_DATASET_PATH = EXPORTS_DIR / "fine_tuning_dataset.jsonl"
LOG_PATH = LOGS_DIR / "aya.log"


def ensure_runtime_dirs():
    DATA_DIR.mkdir(exist_ok=True)
    EXPORTS_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)
    BACKUPS_DIR.mkdir(exist_ok=True)


def migrate_legacy_file(old_name: str, new_path: Path):
    old_path = PROJECT_ROOT / old_name
    if old_path.exists() and not new_path.exists():
        ensure_runtime_dirs()
        old_path.replace(new_path)
