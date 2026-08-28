import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .buildinfo import current_build

try:
    from engine import decide as engine_decide
except Exception:  # 엔진을 못 불러와도 API는 떠야 한다
    engine_decide = None

# 판정 규칙 세트 버전. 규칙이 바뀌면 올린다 (과거 판정이 어떤 규칙으로 났는지 추적용).
RULESET_VERSION = "router+programs.v1"

# fixture에 없는 종목이나 컨텍스트를 못 만드는 날짜가 들어올 수 있다.
# 그때 쓰는 표시. 이 버전으로 남은 판정은 실제 판단이 아니다.
FALLBACK_RULESET_VERSION = "unavailable-stub.v0"

# 판정 1건을 채점할 지평(거래일 기준). 지금 하나로 못 박으면 나중에
# "어느 주기에서 이 룰이 유효했나"를 사후에 물을 수 없다.
HORIZONS = [3, 10, 21, 63]

# 화면·요약에서 대표로 보여줄 지평.
DEFAULT_HORIZON = 21

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
    as_of_date: date
    duration_ms: float
    horizons: List[int] = field(default_factory=lambda: list(HORIZONS))
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
            "as_of_date": self.as_of_date.isoformat(),
            "duration_ms": self.duration_ms,
            "horizons": self.horizons,
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


def _run_engine(rec: "_Recorder", symbol: str, market: str, as_of: date) -> Dict[str, Any]:
    """컨텍스트 → 라우팅 → 프로그램 실행. 각 단계를 그대로 기록한다.

    엔진을 못 돌리는 경우(fixture에 없는 종목, 데이터 없는 날짜)에도 판정
    자체는 돌려준다. 대신 스텁 규칙 세트로 표시해 실제 판단과 구분한다.
    """
    if engine_decide is None:
        rec.record(
            name="decide", title="판단 엔진",
            description="engine 패키지를 불러오지 못해 스텁으로 처리한다.",
            step_input={"symbol": symbol},
            fn=lambda: {"available": False},
        )
        return {"result": True, "ruleset_version": FALLBACK_RULESET_VERSION}

    try:
        decision = engine_decide(symbol, as_of.isoformat())
    except Exception as exc:
        rec.record(
            name="decide", title="판단 엔진",
            description="컨텍스트를 만들지 못해 스텁으로 처리한다. fixture에 없는 종목이거나 해당 날짜 이전 데이터가 없는 경우다.",
            step_input={"symbol": symbol, "as_of": as_of.isoformat()},
            fn=lambda: {"available": False, "error": f"{type(exc).__name__}: {exc}"},
        )
        return {"result": True, "ruleset_version": FALLBACK_RULESET_VERSION}

    ctx = decision.context
    rec.record(
        name="build_context",
        title="컨텍스트 수집",
        description=(
            "기준일까지의 시세만 읽어 종목 상태와 시장 국면을 만든다. "
            "기준일 이후 데이터는 저장소 계층에서 차단된다."
        ),
        step_input={"symbol": symbol, "as_of": as_of.isoformat()},
        fn=lambda: {
            "bars_available": ctx["coverage"]["bars_available"],
            "last_trading_date": ctx["coverage"]["last_trading_date"],
            "returns_pct": ctx["returns"],
            "px_vs_sma60_pct": ctx["trend"]["px_vs_sma60_pct"],
            "vol_ratio_20_60": ctx["volatility"]["vol_ratio_20_60"],
            "drawdown_pct": (ctx.get("drawdown") or {}).get("pct"),
            "regime_assets": list(ctx.get("regime", {})),
            "warnings": ctx["warnings"],
        },
    )

    route = decision.route
    rec.record(
        name="route",
        title="프로그램 라우팅",
        description=(
            "LLM이 컨텍스트를 보고 어떤 판단 프로그램을 태울지 고른다. "
            "LLM은 매수·매도를 판단하지 않는다. LLM을 못 쓰면 규칙 기반으로 떨어진다."
        ),
        step_input={"candidates": route["candidates"]},
        fn=lambda: {
            "program": route["program"], "reason": route["reason"],
            "source": route["source"], "model": route["model"],
            "latency_ms": route["latency_ms"], "error": route["error"],
        },
    )

    pr = decision.program_result
    rec.record(
        name="evaluate",
        title="프로그램 실행",
        description=(
            f"{pr['program']} 프로그램이 결정론적으로 판정한다. "
            "여기서는 LLM을 쓰지 않는다."
        ),
        step_input={"program": pr["program"], "version": pr["version"]},
        fn=lambda: {
            "result": pr["decision"], "confidence": pr["confidence"],
            "summary": pr["summary"], "signals": pr["signals"],
        },
    )

    return {
        "result": pr["decision"],
        "ruleset_version": f"{RULESET_VERSION}:{pr['program']}.{pr['version']}",
    }


def run(ticker: str, as_of: Optional[date] = None) -> Judgement:
    """종목 하나에 대한 판정 파이프라인.

    컨텍스트 수집 → 라우팅 → 프로그램 실행 순서로 돈다. 각 단계의 입출력을
    그대로 남기므로, 어떤 국면을 보고 어떤 프로그램이 골라져 무엇을 근거로
    답이 나왔는지가 판정 기록에서 되짚어진다.
    """
    started = time.perf_counter()
    as_of = as_of or date.today()
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

    decision = _run_engine(rec, normalized, market, as_of)
    ruleset = decision["ruleset_version"]
    result = decision["result"]

    judgement_id = rec.record(
        name="finalize",
        title="판정 확정",
        description=(
            "판정 id를 발급하고, 이 판정을 채점할 기준일과 지평을 고정한다. "
            "실제 채점은 지평이 경과한 뒤 별도로 이뤄진다."
        ),
        step_input={"result": result, "as_of_date": as_of.isoformat()},
        fn=lambda: {"judgement_id": _new_id(), "horizons": list(HORIZONS)},
    )["judgement_id"]

    return Judgement(
        id=judgement_id,
        ticker=ticker,
        normalized_ticker=normalized,
        market=market,
        result=result,
        ruleset_version=ruleset,
        created_at=datetime.now(),
        as_of_date=as_of,
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        steps=rec.steps,
    )
