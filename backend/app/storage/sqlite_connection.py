import os
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    path = Path(
        os.getenv("STUDYCLOUD_DATA_DIR", PROJECT_ROOT / "data")
    ).resolve()

    path.mkdir(parents=True, exist_ok=True)
    (path / "uploads").mkdir(parents=True, exist_ok=True)

    return path


def connect_sqlite() -> sqlite3.Connection:
    connection = sqlite3.connect(data_dir() / "studycloud.db")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    return connection
