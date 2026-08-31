"""포트폴리오 레벨 거래방법론.

종목 하나를 두고 오를지 내릴지 답하는 engine/programs 와는 층이 다르다.
여기 프로그램은 "이번 리밸런싱에서 어떤 비중표를 쓸 것인가"에 답한다.

방향 예측에는 우위가 확인되지 않았으므로 어떤 프로그램도 개별 자산의
등락을 맞히려 하지 않는다. 하는 일은 셋 중 하나다.
  - 노출을 줄인다(현금으로)
  - 노출을 다른 자산군으로 옮긴다(인플레이션 국면)
  - 자기 추세 아래인 자산만 빼둔다

어떤 프로그램을 쓸지는 라우터가 고른다. 프로그램 자신은 결정론적이다.
같은 컨텍스트를 넣으면 항상 같은 비중표가 나온다.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

# 기본 코어. reports/portfolio_e.html 의 E 조합.
CORE = {
    "DBMF": 0.15, "BTAL": 0.10, "UUP": 0.10,
    "BTC/USD": 0.65 / 7, "GLD": 0.65 / 7, "TLT": 0.65 / 7,
    "QQQ": 0.65 / 7, "SPY": 0.65 / 7, "069500": 0.65 / 7, "VNQ": 0.65 / 7,
}
HEDGE = ("DBMF", "BTAL", "UUP")
GROWTH = ("QQQ", "SPY", "069500", "VNQ", "BTC/USD")
INFLATION = ("XLE", "DBC")
CASH = "BIL"


@dataclass
class Allocation:
    """비중표. 자산 비중 + 현금 비중. 합은 1이다."""
    weights: Dict[str, float]
    cash: float = 0.0
    note: str = ""

    def normalized(self) -> "Allocation":
        total = sum(self.weights.values()) + self.cash
        if total <= 0:
            return Allocation({}, 1.0, self.note)
        return Allocation({k: v / total for k, v in self.weights.items() if v > 0},
                          self.cash / total, self.note)


@dataclass
class PortfolioProgram:
    name: str
    title: str
    when_to_use: str
    fn: Callable[[Dict[str, Any]], Allocation]
    # 이 프로그램이 쓸 수 있어야 하는 심볼. 없으면 라우터 후보에서 뺀다.
    requires: List[str] = field(default_factory=list)

    def run(self, ctx: Dict[str, Any]) -> Allocation:
        return self.fn(ctx).normalized()


def _avail(ctx) -> List[str]:
    return ctx["available"]


def _base(ctx) -> Dict[str, float]:
    """그날 거래 가능한 코어 자산만 남기고 재정규화."""
    av = set(_avail(ctx))
    w = {s: v for s, v in CORE.items() if s in av}
    t = sum(w.values())
    return {s: v / t for s, v in w.items()} if t > 0 else {}


# ---------------------------------------------------------------- 프로그램

def core_balanced(ctx) -> Allocation:
    return Allocation(_base(ctx), 0.0, "코어 고정비중")


def trend_gated(ctx) -> Allocation:
    """자기 200일선 아래인 자산의 몫만 현금으로.

    자산 간 비교(어느 게 더 오를까)를 하지 않는다. 각 자산이 자기
    자신에 대해서만 판정된다. 그래서 예측이 아니라 규칙이다.
    """
    base, out, cash = _base(ctx), {}, 0.0
    above = ctx["above_ma"]
    for s, w in base.items():
        if above.get(s, True):
            out[s] = w
        else:
            cash += w
    return Allocation(out, cash, "추세 아래 자산은 현금")


def defensive_tilt(ctx) -> Allocation:
    """헤지 슬리브를 2배로 키우고 성장 자산을 줄인다."""
    base = _base(ctx)
    out = {}
    for s, w in base.items():
        if s in HEDGE:
            out[s] = w * 2.0
        elif s in GROWTH:
            out[s] = w * 0.5
        else:
            out[s] = w
    return Allocation(out, 0.0, "헤지 2배·성장 절반")


def inflation_tilt(ctx) -> Allocation:
    """주식과 채권이 같이 무너지는 국면. 에너지·원자재로 옮긴다.

    2022년형 국면 전용이다. 이 자산군은 2020·2018·2015·2011에
    가장 크게 빠졌으므로 상시 보유용이 아니다.
    """
    base = _base(ctx)
    av = set(_avail(ctx))
    infl = [s for s in INFLATION if s in av]
    if not infl:
        return defensive_tilt(ctx)
    out = {s: w * 0.75 for s, w in base.items()}
    share = 0.25 / len(infl)
    for s in infl:
        out[s] = out.get(s, 0.0) + share
    return Allocation(out, 0.0, "에너지·원자재 25%")


def vol_scaled(ctx) -> Allocation:
    """실현변동성이 목표를 넘으면 전체 노출을 그만큼 줄인다.

    방향은 건드리지 않는다. 크기만 조절한다.
    """
    base = _base(ctx)
    rv = ctx.get("port_vol_pct") or 0.0
    target = ctx.get("vol_target_pct", 10.0)
    k = 1.0 if rv <= 0 else min(1.0, target / rv)
    k = max(0.3, k)
    return Allocation({s: w * k for s, w in base.items()}, 1.0 - k,
                      f"노출 {k*100:.0f}%")


def risk_off(ctx) -> Allocation:
    """40%를 현금으로. 국면이 나쁘다고 판단됐을 때의 마지막 단계."""
    base = _base(ctx)
    return Allocation({s: w * 0.6 for s, w in base.items()}, 0.4, "현금 40%")


REGISTRY: Dict[str, PortfolioProgram] = {
    p.name: p for p in [
        PortfolioProgram("core_balanced", "코어 고정비중",
                         "국면이 특별하지 않을 때. 주식이 추세 위이고 변동성이 평소 수준일 때.",
                         core_balanced),
        PortfolioProgram("trend_gated", "자산별 추세 게이트",
                         "주가지수가 자기 장기추세 아래로 내려갔을 때. 하락 자산만 골라서 현금으로 뺀다.",
                         trend_gated),
        PortfolioProgram("defensive_tilt", "방어 기울이기",
                         "변동성이 급등했지만 아직 추세가 깨지지는 않았을 때. 헤지를 키운다.",
                         defensive_tilt),
        PortfolioProgram("inflation_tilt", "인플레이션 기울이기",
                         "주식과 장기채가 동시에 추세 아래일 때(2022년형). 에너지·원자재로 옮긴다.",
                         inflation_tilt, requires=["XLE", "DBC"]),
        PortfolioProgram("vol_scaled", "변동성 타겟팅",
                         "포트폴리오 실현변동성이 목표를 크게 넘을 때. 방향은 그대로 두고 크기만 줄인다.",
                         vol_scaled),
        PortfolioProgram("risk_off", "위험 회피",
                         "추세도 깨지고 변동성도 극단일 때. 절반 가까이 현금으로 물러난다.",
                         risk_off),
    ]
}


def menu(names=None) -> List[Dict[str, str]]:
    names = names or list(REGISTRY)
    return [{"name": n, "title": REGISTRY[n].title,
             "when_to_use": REGISTRY[n].when_to_use}
            for n in names if n in REGISTRY]


def candidates(available) -> List[str]:
    """쓸 수 있는 심볼이 없는 프로그램은 후보에서 뺀다."""
    av = set(available)
    return [n for n, p in REGISTRY.items()
            if all(r in av for r in p.requires)]
