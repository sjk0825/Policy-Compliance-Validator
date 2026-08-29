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
    weight            REAL,
    ruleset_version   TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    as_of_date        TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS outcomes (
    judgement_id TEXT NOT NULL,
    horizon_days INTEGER NOT NULL,
    status       TEXT NOT NULL,          -- pending | scored | unavailable
    entry_date   TEXT,
    entry_price  REAL,
    exit_date    TEXT,
    exit_price   REAL,
    return_pct   REAL,
    hit          INTEGER,                -- 판정 방향이 맞았는가
    price_source TEXT,
    note         TEXT,
    evaluated_at TEXT,
    PRIMARY KEY (judgement_id, horizon_days),
    FOREIGN KEY (judgement_id) REFERENCES judgements(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_outcomes_pending
    ON outcomes (status, horizon_days);

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
                    id, ticker, normalized_ticker, market, result, weight, ruleset_version,
                    created_at, as_of_date, duration_ms, commit_hash, commit_short, branch, dirty,
                    response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    judgement.id,
                    judgement.ticker,
                    judgement.normalized_ticker,
                    judgement.market,
                    int(judgement.result),
                    judgement.weight,
                    judgement.ruleset_version,
                    judgement.created_at.isoformat(),
                    judgement.as_of_date.isoformat(),
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
            # 지평별 채점 슬롯을 미리 만들어 둔다. 채점기는 이 pending 행만 훑으면 된다.
            conn.executemany(
                """
                INSERT INTO outcomes (judgement_id, horizon_days, status)
                VALUES (?, ?, 'pending')
                """,
                [(judgement.id, h) for h in judgement.horizons],
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

    # ---- outcomes ----------------------------------------------------

    def get_outcomes(self, judgement_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM outcomes WHERE judgement_id = ? ORDER BY horizon_days",
                (judgement_id,),
            ).fetchall()
        return [self._outcome_row(r) for r in rows]

    def pending_outcomes(self, limit: int = 500,
                         include_unavailable: bool = False) -> List[Dict[str, Any]]:
        """채점 대기 중인 (판정, 지평) 쌍을 판정 정보와 함께 돌려준다.

        시세를 일시적으로 못 받아 unavailable로 남은 건은 기본적으로 건너뛴다.
        include_unavailable을 켜면 그 건들까지 다시 훑는다.
        """
        statuses = ("pending", "unavailable") if include_unavailable else ("pending",)
        placeholders = ", ".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT o.judgement_id, o.horizon_days,
                       j.normalized_ticker, j.market, j.result, j.as_of_date
                FROM outcomes o
                JOIN judgements j ON j.id = o.judgement_id
                WHERE o.status IN ({placeholders})
                ORDER BY j.as_of_date, o.horizon_days
                LIMIT ?
                """,
                (*statuses, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_outcome(self, judgement_id: str, horizon_days: int, status: str,
                       evaluated_at: str, entry_date: Optional[str] = None,
                       entry_price: Optional[float] = None, exit_date: Optional[str] = None,
                       exit_price: Optional[float] = None, return_pct: Optional[float] = None,
                       hit: Optional[bool] = None, price_source: Optional[str] = None,
                       note: Optional[str] = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE outcomes SET
                    status = ?, entry_date = ?, entry_price = ?, exit_date = ?,
                    exit_price = ?, return_pct = ?, hit = ?, price_source = ?,
                    note = ?, evaluated_at = ?
                WHERE judgement_id = ? AND horizon_days = ?
                """,
                (
                    status, entry_date, entry_price, exit_date, exit_price,
                    return_pct, None if hit is None else int(hit), price_source,
                    note, evaluated_at, judgement_id, horizon_days,
                ),
            )

    def hit_rate(self, horizon_days: int, ticker: Optional[str] = None) -> Dict[str, Any]:
        """지평별 적중률. 룰이 실제로 되는지 보는 최소 지표."""
        sql = """
            SELECT COUNT(*) AS n,
                   SUM(o.hit) AS hits,
                   AVG(o.return_pct) AS avg_return
            FROM outcomes o
            JOIN judgements j ON j.id = o.judgement_id
            WHERE o.status = 'scored' AND o.horizon_days = ?
        """
        params: List[Any] = [horizon_days]
        if ticker:
            sql += " AND j.normalized_ticker = ?"
            params.append(ticker.strip().upper())

        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()

        n = row["n"] or 0
        hits = row["hits"] or 0
        return {
            "horizon_days": horizon_days,
            "scored": n,
            "hits": hits,
            "hit_rate": round(hits / n, 4) if n else None,
            "avg_return_pct": round(row["avg_return"], 4) if row["avg_return"] is not None else None,
        }

    @staticmethod
    def _outcome_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "horizon_days": row["horizon_days"],
            "status": row["status"],
            "entry_date": row["entry_date"],
            "entry_price": row["entry_price"],
            "exit_date": row["exit_date"],
            "exit_price": row["exit_price"],
            "return_pct": row["return_pct"],
            "hit": None if row["hit"] is None else bool(row["hit"]),
            "price_source": row["price_source"],
            "note": row["note"],
            "evaluated_at": row["evaluated_at"],
        }

    @staticmethod
    def _summary_row(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "ticker": row["ticker"],
            "normalized_ticker": row["normalized_ticker"],
            "market": row["market"],
            "result": bool(row["result"]),
            "weight": row["weight"],
            "ruleset_version": row["ruleset_version"],
            "created_at": row["created_at"],
            "as_of_date": row["as_of_date"],
            "duration_ms": row["duration_ms"],
            "build": {
                "commit": row["commit_hash"],
                "commit_short": row["commit_short"],
                "branch": row["branch"],
                "dirty": bool(row["dirty"]),
            },
        }
