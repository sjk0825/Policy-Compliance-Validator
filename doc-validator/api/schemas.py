from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class JudgeRequest(BaseModel):
    ticker: str = Field(..., description="종목 코드 또는 티커 (예: 005930, QQQ)")
    as_of: Optional[date] = Field(
        None,
        description="판정 기준일. 생략하면 오늘. 과거 구간을 소급 판정할 때 쓴다.",
    )

    @field_validator("ticker")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("ticker는 공백일 수 없습니다.")
        return v


class BuildMeta(BaseModel):
    commit: str
    commit_short: str
    branch: str
    dirty: bool


class ProcessStepOut(BaseModel):
    seq: int
    name: str
    title: str
    description: str
    status: str
    input: Dict[str, Any]
    output: Dict[str, Any]
    duration_ms: float


class OutcomeOut(BaseModel):
    horizon_days: int
    status: str
    entry_date: Optional[str] = None
    entry_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    return_pct: Optional[float] = None
    hit: Optional[bool] = None
    price_source: Optional[str] = None
    note: Optional[str] = None
    evaluated_at: Optional[str] = None


class JudgementOut(BaseModel):
    id: str
    ticker: str
    normalized_ticker: str
    market: str
    result: bool
    ruleset_version: str
    created_at: str
    as_of_date: str
    duration_ms: float
    horizons: List[int]
    build: BuildMeta
    process: List[ProcessStepOut]


class JudgementSummary(BaseModel):
    id: str
    ticker: str
    normalized_ticker: str
    market: str
    result: bool
    ruleset_version: str
    created_at: str
    as_of_date: str
    duration_ms: float
    build: BuildMeta


class JudgementList(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[JudgementSummary]


class ProcessOut(BaseModel):
    id: str
    ticker: str
    result: bool
    ruleset_version: str
    created_at: str
    build: BuildMeta
    process: List[ProcessStepOut]


class HealthOut(BaseModel):
    status: str
    ruleset_version: str
    build: BuildMeta
    judgement_count: int
    db_path: str


class OutcomesOut(BaseModel):
    id: str
    ticker: str
    result: bool
    as_of_date: str
    default_horizon: int
    outcomes: List[OutcomeOut]


class ScoreRunOut(BaseModel):
    checked: int
    scored: int
    still_pending: int
    unavailable: int
    errors: List[str]


class HitRateOut(BaseModel):
    horizon_days: int
    scored: int
    hits: int
    hit_rate: Optional[float] = None
    avg_return_pct: Optional[float] = None


class StatsOut(BaseModel):
    ticker: Optional[str] = None
    default_horizon: int
    by_horizon: List[HitRateOut]
