from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class JudgeRequest(BaseModel):
    ticker: str = Field(..., description="종목 코드 또는 티커 (예: 005930, QQQ)")

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


class JudgementOut(BaseModel):
    id: str
    ticker: str
    normalized_ticker: str
    market: str
    result: bool
    ruleset_version: str
    created_at: str
    duration_ms: float
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
