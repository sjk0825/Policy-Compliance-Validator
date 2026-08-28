"""횡단면 모멘텀. 동료 대비 몇 등인가로 판단한다.

절대 임계값을 쓰지 않는 유일한 프로그램이다. IC 측정에서 모멘텀은
횡단면 순위로 작동하는 것이 확인됐다. "60일 수익률이 0보다 크다"와
"동료 20종목 중 상위권이다"는 다른 이야기이고, 신호가 있는 쪽은
후자다.
"""
from typing import Any, Dict

from .base import Program, ProgramResult, Signal, ramp

# 상위 몇 %부터 잡을 것인가. 백분위 기준이므로 시장 수준과 무관하다.
TAKE_ABOVE = 0.55
MIN_PEERS = 8


class CrossMomentum(Program):
    name = "cross_momentum"
    title = "횡단면 모멘텀"
    version = "v1"
    when_to_use = (
        "같은 시장에 비교할 동료 종목이 충분하고, 이 종목이 모멘텀 순위에서 "
        "위든 아래든 뚜렷하게 치우쳐 있을 때. 시장 전체의 방향이 아니라 "
        "동료 대비 상대적 위치를 본다."
    )

    def fitness(self, ctx: Dict[str, Any]) -> float:
        cs = ctx.get("cross_section") or {}
        comp = cs.get("composite")
        if comp is None or cs.get("peer_count", 0) < MIN_PEERS:
            return 0.0
        # 순위가 가운데면 할 말이 없다. 위든 아래든 치우칠수록 적합하다.
        return self.mean_fit([
            ramp(abs(comp - 0.5), 0.10, 0.35),
            ramp(cs.get("ranked_axes"), 1, 4),
        ])

    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        cs = ctx.get("cross_section") or {}
        pct = cs.get("percentile") or {}
        comp = cs.get("composite")

        s = [
            Signal(f"{axis} 상위 {int((1-TAKE_ABOVE)*100)}% 이내",
                   None if pct.get(axis) is None else pct[axis] >= TAKE_ABOVE,
                   f"백분위 {pct[axis]:.2f}" if pct.get(axis) is not None else "-",
                   pct.get(axis))
            for axis in ("ret_60d", "ret_120d", "px_vs_sma60", "slope60")
        ]
        # 종합 백분위가 최종 근거다. 개별 축은 왜 그렇게 됐는지 보여준다.
        decision = comp is not None and comp >= TAKE_ABOVE
        judged = [x for x in s if x.passed is not None]
        conf = round(sum(1 for x in judged if x.passed) / len(judged), 3) if judged else 0.0

        return ProgramResult(
            program=self.name, version=self.version,
            decision=decision, confidence=conf,
            summary=(f"동료 {cs.get('peer_count', 0)}종목 중 종합 백분위 "
                     f"{comp:.2f} — " + ("상위권이라 잡는다" if decision else "상위권이 아니라 잡지 않는다")
                     if comp is not None else "비교할 동료가 부족하다"),
            signals=s,
        )
