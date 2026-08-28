import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

from .buildinfo import current_build

# 판정 규칙 세트 버전. 규칙이 바뀌면 올린다 (과거 판정이 어떤 규칙으로 났는지 추적용).
RULESET_VERSION = "stub-always-true.v0"

_KRX_PATTERN = re.compile(r"^\d{6}$")


@dataclass
class ProcessStep:
    seq: int
    name: str
    title: str
    description: str
    status: str
    input: Dict[str, Any]
    output: Dict[str, Any]
    duration_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "input": self.input,
            "output": self.output,
            "duration_ms": self.duration_ms,
        }


@dataclass
class Judgement:
    id: str
    ticker: str
    normalized_ticker: str
    market: str
    result: bool
    ruleset_version: str
    created_at: datetime
    duration_ms: float
    steps: List[ProcessStep] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "normalized_ticker": self.normalized_ticker,
            "market": self.market,
            "result": self.result,
            "ruleset_version": self.ruleset_version,
            "created_at": self.created_at.isoformat(),
            "duration_ms": self.duration_ms,
            "build": current_build().to_dict(),
            "process": [s.to_dict() for s in self.steps],
        }


class _Recorder:
    """단계 실행 시간과 입출력을 그대로 기록한다. 설명은 사후 서술이 아니라 실행 흔적이다."""

    def __init__(self) -> None:
        self.steps: List[ProcessStep] = []

    def record(self, name: str, title: str, description: str,
               step_input: Dict[str, Any], fn) -> Any:
        started = time.perf_counter()
        status = "ok"
        try:
            output = fn()
        except Exception as exc:
            status = "error"
            output = {"error": str(exc)}
            raise
        finally:
            self.steps.append(ProcessStep(
                seq=len(self.steps) + 1,
                name=name,
                title=title,
                description=description,
                status=status,
                input=step_input,
                output=output if status == "ok" else output,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            ))
        return output


def _new_id() -> str:
    return f"jdg_{uuid.uuid4().hex[:12]}"


def _classify_market(symbol: str) -> str:
    if _KRX_PATTERN.match(symbol):
        return "KRX"
    if symbol.isalpha():
        return "US"
    return "UNKNOWN"


def run(ticker: str) -> Judgement:
    """종목 하나에 대한 판정 파이프라인.

    지금 evaluate 단계는 상수 True를 돌려주는 스텁이다. 실제 판정 로직이
    들어갈 자리는 여기 한 곳뿐이고, 나머지 단계와 기록 구조는 그대로 쓴다.
    """
    started = time.perf_counter()
    rec = _Recorder()

    normalized = rec.record(
        name="normalize_input",
        title="입력 정규화",
        description="앞뒤 공백을 제거하고 영문 티커를 대문자로 맞춘다.",
        step_input={"ticker": ticker},
        fn=lambda: {"normalized_ticker": ticker.strip().upper()},
    )["normalized_ticker"]

    market = rec.record(
        name="resolve_market",
        title="시장 판별",
        description="6자리 숫자면 KRX, 알파벳만이면 US, 그 외는 UNKNOWN으로 분류한다.",
        step_input={"normalized_ticker": normalized},
        fn=lambda: {"market": _classify_market(normalized)},
    )["market"]

    ruleset = rec.record(
        name="load_ruleset",
        title="규칙 세트 로드",
        description="판정에 적용할 규칙 세트를 고정한다. 현재는 스텁 규칙 세트 하나뿐이다.",
        step_input={"market": market},
        fn=lambda: {"ruleset_version": RULESET_VERSION, "rules": ["always_true"]},
    )["ruleset_version"]

    result = rec.record(
        name="evaluate",
        title="규칙 평가",
        description=(
            "규칙 세트를 평가해 불리언 판정을 만든다. "
            "stub-always-true.v0은 입력과 무관하게 True를 돌려준다 — 실제 판정 로직 미구현."
        ),
        step_input={"normalized_ticker": normalized, "market": market, "ruleset_version": ruleset},
        fn=lambda: {"result": True, "reason": "stub ruleset: 무조건 True"},
    )["result"]

    judgement_id = rec.record(
        name="finalize",
        title="판정 확정",
        description="판정 id를 발급하고 결과와 실행 기록을 저장 대상으로 확정한다.",
        step_input={"result": result},
        fn=lambda: {"judgement_id": _new_id()},
    )["judgement_id"]

    return Judgement(
        id=judgement_id,
        ticker=ticker,
        normalized_ticker=normalized,
        market=market,
        result=result,
        ruleset_version=ruleset,
        created_at=datetime.now(),
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        steps=rec.steps,
    )
