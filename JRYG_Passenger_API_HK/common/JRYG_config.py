"""香港接口自动化的文件与产物路径。"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
CASES_DIR = BASE_DIR / "cases"
REPORT_DIR = BASE_DIR / "report"
LOGS_DIR = BASE_DIR / "logs"
LOG_FILE = LOGS_DIR / "JRYG_api_run.log"
CAPTURE_DIR = Path(os.environ.get("HK_CAPTURE_DIR", BASE_DIR / "data" / "captures")).expanduser().resolve()


def init_all_dirs():
    for directory in (REPORT_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
