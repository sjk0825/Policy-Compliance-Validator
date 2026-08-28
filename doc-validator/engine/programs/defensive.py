"""방어. 위험 신호가 하나라도 켜지면 잡지 않는다."""
from typing import Any, Dict

from .base import Program, ProgramResult, Signal


class Defensive(Program):
    name = "defensive"
    title = "방어"
    version = "v1"
    when_to_use = (
        "국면이 어수선하거나 신호가 서로 어긋날 때. 변동성 급증·깊은 낙폭·"
        "추세 붕괴 중 하나라도 걸리면 잡지 않는다. 확신이 없을 때의 기본값."
    )

    # 전문 프로그램이 이 값을 넘지 못하면 방어가 이긴다.
    # 라우터에서 조정 가능한 유일한 손잡이다.
    FLOOR = 0.45

    def fitness(self, ctx: Dict[str, Any]) -> float:
        """국면과 무관한 고정값.

        방어는 특정 국면의 전문가가 아니라 "아무것도 확신하지 못할 때"의
        기본값이다. 그래서 점수를 계산하지 않고 바닥을 깔아둔다.
        """
        return self.FLOOR

    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        t, v = ctx["trend"], ctx["volatility"]
        dd = (ctx.get("drawdown") or {}).get("pct")
        # 여기서는 "위험이 아님"을 통과로 본다.
        s = [
            Signal("변동성 급증 아님", _lt(v["vol_ratio_20_60"], 1.25),
                   f"20/60 변동성비 {_f(v['vol_ratio_20_60'], 2)}", v["vol_ratio_20_60"]),
            Signal("깊은 낙폭 아님", _gt(dd, -12.0), f"낙폭 {_f(dd)}%", dd),
            Signal("추세 붕괴 아님", _gt(t["px_vs_sma60_pct"], -3.0),
                   f"60일선 대비 {_f(t['px_vs_sma60_pct'])}%", t["px_vs_sma60_pct"]),
            Signal("절대 변동성 과열 아님", _lt(v["ann_vol_60d_pct"], 45.0),
                   f"60일 변동성 {_f(v['ann_vol_60d_pct'], 1)}%", v["ann_vol_60d_pct"]),
        ]
        # 방어는 하나라도 걸리면 거짓이다. 다수결이 아니라 전원 통과를 본다.
        decision, conf = self.decide_by_majority(s, need=len(s))
        return ProgramResult(
            program=self.name, version=self.version, decision=decision, confidence=conf,
            summary=("위험 신호가 없어 보유해도 무방하다" if decision
                     else "위험 신호가 있어 잡지 않는다"),
            signals=s,
        )


def _lt(x, t): return None if x is None else x < t
def _gt(x, t): return None if x is None else x > t
def _f(x, n=2): return "-" if x is None else f"{x:+.{n}f}"
