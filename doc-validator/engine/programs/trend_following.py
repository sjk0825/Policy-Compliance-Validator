"""추세추종. 오르던 것이 계속 오른다는 쪽에 선다."""
from typing import Any, Dict

from .base import Program, ProgramResult, Signal


class TrendFollowing(Program):
    name = "trend_following"
    title = "추세추종"
    version = "v1"
    when_to_use = (
        "가격이 이동평균 위에 있고 단기선이 장기선 위로 벌어져 있으며 변동성이 "
        "안정적일 때. 방향이 잡힌 상승 국면에서 그 방향에 붙는다."
    )

    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        t, v = ctx["trend"], ctx["volatility"]
        s = [
            Signal("가격이 60일선 위", _gt(t["px_vs_sma60_pct"], 0),
                   f"60일선 대비 {_f(t['px_vs_sma60_pct'])}%", t["px_vs_sma60_pct"]),
            Signal("20일선이 60일선 위", _gt(t["sma20_vs_sma60_pct"], 0),
                   f"20/60 이격 {_f(t['sma20_vs_sma60_pct'])}%", t["sma20_vs_sma60_pct"]),
            Signal("20일 기울기 상승", _gt(t["slope20_pct_per_day"], 0),
                   f"일당 {_f(t['slope20_pct_per_day'], 4)}%", t["slope20_pct_per_day"]),
            Signal("변동성 안정", _lt(v["vol_ratio_20_60"], 1.4),
                   f"20/60 변동성비 {_f(v['vol_ratio_20_60'], 2)}", v["vol_ratio_20_60"]),
        ]
        decision, conf = self.decide_by_majority(s, need=3)
        return ProgramResult(
            program=self.name, version=self.version, decision=decision, confidence=conf,
            summary=("추세가 살아 있어 방향에 붙는다" if decision
                     else "추세 조건이 모자라 붙지 않는다"),
            signals=s,
        )


def _gt(x, t): return None if x is None else x > t
def _lt(x, t): return None if x is None else x < t
def _f(x, n=2): return "-" if x is None else f"{x:+.{n}f}"
