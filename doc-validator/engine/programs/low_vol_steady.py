"""저변동성 안정. 크게 이기지 않는 대신 자주 이긴다.

변동성이 낮은 종목은 개별 구간에서 이길 확률이 높다. 폭이 작아 큰
수익은 없지만 지는 일도 드물다. 대신 시장 전체가 무너질 때는 같이
무너지므로, 드물게 크게 잃는다. 단기 반전과 같은 계열의 프로파일이다.

이 프로그램은 예측하지 않는다. 변동성이 낮고 추세가 완만히 우상향인
종목을 고를 뿐이다. 그것만으로 승률은 올라간다.
"""
from typing import Any, Dict

from .base import Program, ProgramResult, Signal, ramp

# 안정성 종합 백분위가 이 아래여야 저변동성으로 본다.
# (백분위는 변동성·낙폭이 클수록 높다)
CALM_BELOW = 0.40
# 완만하더라도 방향은 위여야 한다.
DRIFT_ABOVE = 0.45
MIN_PEERS = 20


class LowVolSteady(Program):
    name = "low_vol_steady"
    title = "저변동성 안정"
    version = "v1"
    when_to_use = (
        "동료 대비 변동성이 낮고 낙폭이 얕으며 완만히 우상향인 종목일 때. "
        "큰 수익을 노리지 않고 지지 않는 쪽을 택한다. 시장 전체가 흔들리는 "
        "국면에서는 이 전제가 무너진다."
    )

    def fitness(self, ctx: Dict[str, Any]) -> float:
        cs = ctx.get("cross_section") or {}
        styles = cs.get("styles") or {}
        stab, mom = styles.get("stability"), styles.get("momentum")
        if None in (stab, mom) or cs.get("peer_count", 0) < MIN_PEERS:
            return 0.0
        return self.mean_fit([
            ramp(stab, CALM_BELOW + 0.15, 0.10),   # 조용할수록
            ramp(mom, 0.30, 0.65),                  # 방향은 위쪽
        ])

    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        cs = ctx.get("cross_section") or {}
        pct = cs.get("percentile") or {}
        styles = cs.get("styles") or {}
        stab, mom = styles.get("stability"), styles.get("momentum")

        s = [
            Signal("동료 대비 저변동성",
                   None if pct.get("vol_20d") is None else pct["vol_20d"] <= CALM_BELOW,
                   f"변동성 백분위 {pct['vol_20d']:.2f}" if pct.get("vol_20d") is not None else "-",
                   pct.get("vol_20d")),
            Signal("낙폭 얕음",
                   None if pct.get("drawdown") is None else pct["drawdown"] >= 0.50,
                   f"낙폭 백분위 {pct['drawdown']:.2f}" if pct.get("drawdown") is not None else "-",
                   pct.get("drawdown")),
            Signal("완만한 우상향",
                   None if mom is None else mom >= DRIFT_ABOVE,
                   f"모멘텀 백분위 {mom:.2f}" if mom is not None else "-", mom),
            Signal("변동성 확대 아님",
                   None if pct.get("vol_ratio") is None else pct["vol_ratio"] <= 0.70,
                   f"변동성비 백분위 {pct['vol_ratio']:.2f}" if pct.get("vol_ratio") is not None else "-",
                   pct.get("vol_ratio")),
        ]
        judged = [x for x in s if x.passed is not None]
        # 지지 않는 것이 목적이므로 전원 통과를 요구한다.
        decision = bool(judged) and all(x.passed for x in judged) and len(judged) >= 3
        conf = round(sum(1 for x in judged if x.passed) / len(judged), 3) if judged else 0.0

        return ProgramResult(
            program=self.name, version=self.version, decision=decision, confidence=conf,
            summary=("변동성이 낮고 방향이 위라 잡는다" if decision
                     else "안정 조건이 갖춰지지 않았다"),
            signals=s,
        )
