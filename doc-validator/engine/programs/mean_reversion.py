"""역추세. 과하게 밀린 것이 되돌아온다는 쪽에 선다."""
from typing import Any, Dict

from .base import Program, ProgramResult, Signal


class MeanReversion(Program):
    name = "mean_reversion"
    title = "역추세"
    version = "v1"
    when_to_use = (
        "고점 대비 낙폭이 크고 단기적으로 더 밀렸으며 변동성이 확대되는 중일 때. "
        "패닉 구간에서 되돌림에 건다. 추세가 멀쩡히 살아 있을 때는 쓰지 않는다."
    )

    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        t, v, r = ctx["trend"], ctx["volatility"], ctx["returns"]
        dd = (ctx.get("drawdown") or {}).get("pct")
        s = [
            Signal("고점 대비 8% 이상 하락", _le(dd, -8.0),
                   f"낙폭 {_f(dd)}%", dd),
            Signal("가격이 20일선 아래", _lt(t["px_vs_sma20_pct"], 0),
                   f"20일선 대비 {_f(t['px_vs_sma20_pct'])}%", t["px_vs_sma20_pct"]),
            Signal("변동성 확대", _ge(v["vol_ratio_20_60"], 1.1),
                   f"20/60 변동성비 {_f(v['vol_ratio_20_60'], 2)}", v["vol_ratio_20_60"]),
            Signal("최근 5일 약세", _lt(r.get("5d"), 0),
                   f"5일 {_f(r.get('5d'))}%", r.get("5d")),
        ]
        decision, conf = self.decide_by_majority(s, need=3)
        return ProgramResult(
            program=self.name, version=self.version, decision=decision, confidence=conf,
            summary=("과매도가 충분해 되돌림에 건다" if decision
                     else "되돌림을 걸 만큼 밀리지 않았다"),
            signals=s,
        )


def _lt(x, t): return None if x is None else x < t
def _le(x, t): return None if x is None else x <= t
def _ge(x, t): return None if x is None else x >= t
def _f(x, n=2): return "-" if x is None else f"{x:+.{n}f}"
