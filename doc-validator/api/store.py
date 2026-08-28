import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .buildinfo import current_build
from .pipeline import Judgement, ProcessStep

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "judgements.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS judgements (
    id                TEXT PRIMARY KEY,
    ticker            TEXT NOT NULL,
    normalized_ticker TEXT NOT NULL,
    market            TEXT NOT NULL,
    result            INTEGER NOT NULL,
    ruleset_version   TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    duration_ms       REAL NOT NULL,
    commit_hash       TEXT NOT NULL,
    commit_short      TEXT NOT NULL,
    branch            TEXT NOT NULL,
    dirty             INTEGER NOT NULL,
    response_json     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS judgement_steps (
    judgement_id TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    name         TEXT NOT NULL,
    title        TEXT NOT NULL,
    description  TEXT NOT NULL,
    status       TEXT NOT NULL,
    input_json   TEXT NOT NULL,
    output_json  TEXT NOT NULL,
    duration_ms  REAL NOT NULL,
    PRIMARY KEY (judgement_id, seq),
    FOREIGN KEY (judgement_id) REFERENCES judgements(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_judgements_created_at
    ON judgements (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_judgements_ticker
    ON judgements (normalized_ticker, created_at DESC);
"""


class JudgementStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = Path(db_path or os.getenv("JUDGEMENT_DB_PATH") or _DEFAULT_DB)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save(self, judgement: Judgement) -> Dict[str, Any]:
        """판정 결과와 실행 기록을 저장하고, 저장된 응답 본문을 그대로 돌려준다.

        응답 JSON을 통째로 한 번 더 저장한다. 나중에 스키마가 바뀌어도
        '그 당시 반환한 데이터'는 원문 그대로 남아 있어야 하기 때문이다.
        """
        payload = judgement.to_dict()
        build = current_build()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO judgements (
                    id, ticker, normalized_ticker, market, result, ruleset_version,
                    created_at, duration_ms, commit_hash, commit_short, branch, dirty,
                    response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    judgement.id,
                    judgement.ticker,
                    judgement.normalized_ticker,
                    judgement.market,
                    int(judgement.result),
                    judgement.ruleset_version,
                    judgement.created_at.isoformat(),
                    judgement.duration_ms,
                    build.commit,
                    build.commit_short,
                    build.branch,
                    int(build.dirty),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.executemany(
                """
                INSERT INTO judgement_steps (
                    judgement_id, seq, name, title, description, status,
                    input_json, output_json, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        judgement.id, s.seq, s.name, s.title, s.description, s.status,
                        json.dumps(s.input, ensure_ascii=False),
                        json.dumps(s.output, ensure_ascii=False),
                        s.duration_ms,
                    )
                    for s in judgement.steps
                ],
            )
        return payload

    def get(self, judgement_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM judgements WHERE id = ?", (judgement_id,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["response_json"])

    def get_steps(self, judgement_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM judgement_steps WHERE judgement_id = ? ORDER BY seq",
                (judgement_id,),
            ).fetchall()
        return [
            {
                "seq": r["seq"],
                "name": r["name"],
                "title": r["title"],
                "description": r["description"],
                "status": r["status"],
                "input": json.loads(r["input_json"]),
                "output": json.loads(r["output_json"]),
                "duration_ms": r["duration_ms"],
            }
            for r in rows
        ]

    def get_summary(self, judgement_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM judgements WHERE id = ?", (judgement_id,)
            ).fetchone()
        if row is None:
            return None
        return self._summary_row(row)

    def list(self, limit: int = 50, offset: int = 0,
             ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM judgements"
        params: List[Any] = []
        if ticker:
            sql += " WHERE normalized_ticker = ?"
            params.append(ticker.strip().upper())
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._summary_row(r) for r in rows]

    def count(self, ticker: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM judgements"
        params: List[Any] = []
        if ticker:
            sql += " WHERE normalized_ticker = ?"
            params.append(ticker.strip().upper())
        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()["n"]

    @staticmethod
    def _summary_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "ticker": row["ticker"],
            "normalized_ticker": row["normalized_ticker"],
            "market": row["market"],
            "result": bool(row["result"]),
            "ruleset_version": row["ruleset_version"],
            "created_at": row["created_at"],
            "duration_ms": row["duration_ms"],
            "build": {
                "commit": row["commit_hash"],
                "commit_short": row["commit_short"],
                "branch": row["branch"],
                "dirty": bool(row["dirty"]),
            },
        }
