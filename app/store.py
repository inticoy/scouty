"""올린 소식·시간대 기록 (SQLite). 같은 소식을 며칠 안에 다시 올리지 않으려고."""
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DB_PATH = Path("data/scoot.db")
KST = ZoneInfo("Asia/Seoul")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS posted (
  destination TEXT NOT NULL,
  key         TEXT NOT NULL,
  posted_at   TEXT NOT NULL,
  PRIMARY KEY (destination, key)
);
CREATE TABLE IF NOT EXISTS meta (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str = DB_PATH):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)

    def posted_keys(self, destination: str, days: int = 14) -> set:
        since = (datetime.now(KST) - timedelta(days=days)).isoformat()
        return {r["key"] for r in self.db.execute(
            "SELECT key FROM posted WHERE destination = ? AND posted_at >= ?", (destination, since))}

    def mark_posted(self, destination: str, keys: list):
        self.db.executemany("INSERT OR REPLACE INTO posted (destination, key, posted_at) VALUES (?, ?, ?)",
                            [(destination, key, _now()) for key in keys])
        self.db.commit()

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str):
        self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
        self.db.commit()

    def get_delivery(self, destination: str, date: str) -> dict | None:
        value = self.get_meta(f"delivery:{destination}:{date}")
        return json.loads(value) if value else None

    def save_delivery(self, destination: str, date: str, delivery: dict, keys: list[str] = ()):
        # 메시지 진행 상태와 해당 소식의 중복 방지 기록을 함께 저장한다
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                            (f"delivery:{destination}:{date}", json.dumps(delivery, ensure_ascii=False)))
            self.db.executemany("INSERT OR REPLACE INTO posted (destination, key, posted_at) VALUES (?, ?, ?)",
                                [(destination, key, _now()) for key in keys])
