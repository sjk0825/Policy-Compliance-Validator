"""단기 반전. 자주 이기는 대신 가끔 크게 잃는 쪽을 택한다.

기존 cross_momentum은 반대 성질이었다. 승률 49.3%에 중앙값 -0.13%,
평균만 +1.59%. 자주 조금 지고 가끔 크게 이기는 형태다. 여기서는 그
반대를 노린다.

논리는 이렇다. 추세가 살아 있는 종목이 단기적으로만 밀렸다면 그 하락은
대체로 되돌아온다. 되돌림은 자주 일어나지만 폭이 작고, 되돌아오지 않을
때는 추세가 실제로 꺾인 경우라 손실이 크다. 승률은 높고 왜도는 음수다.

이 성질은 공짜가 아니다. 자주 이기는 대가로 드물게 크게 잃는다.
프로파일을 고른 것이지 우위를 만든 것이 아니다.

핵심 조건은 셋이다.
1. 장기 추세가 살아 있을 것        — 떨어지는 칼을 잡지 않는다
2. 단기적으로만 밀렸을 것          — 되돌릴 여지
3. 변동성이 폭발하지 않았을 것      — 구조적 붕괴 배제
"""
from typing import Any, Dict

from .base import Program, ProgramResult, Signal, ramp

# 단기 수익률 하위 몇 %를 과매도로 볼 것인가.
OVERSOLD_BELOW = 0.35
# 장기 모멘텀이 이 아래면 추세가 죽은 것으로 본다.
TREND_ALIVE_ABOVE = 0.45
# 변동성이 이 위로 튀면 되돌림이 아니라 붕괴로 본다.
VOL_PANIC_ABOVE = 0.85
MIN_PEERS = 20


class ShortReversal(Program):
    name = "short_reversal"
    title = "단기 반전"
    version = "v1"
    when_to_use = (
        "장기 추세는 살아 있는데 최근 5~20일만 동료 대비 밀린 종목일 때. "
        "되돌림에 건다. 추세가 이미 꺾였거나 변동성이 폭발한 종목에는 쓰지 않는다. "
        "승률은 높지만 틀릴 때 손실이 크다."
    )

    def fitness(self, ctx: Dict[str, Any]) -> float:
        cs = ctx.get("cross_section") or {}
        styles = cs.get("styles") or {}
        mom, rev, stab = styles.get("momentum"), styles.get("reversal"), styles.get("stability")
        if None in (mom, rev, stab) or cs.get("peer_count", 0) < MIN_PEERS:
            return 0.0
        # 모멘텀은 높고 단기는 낮을수록, 그리고 변동성이 낮을수록 이 프로그램의 판이다.
        return self.mean_fit([
            ramp(mom, TREND_ALIVE_ABOVE, 0.80),
            ramp(rev, OVERSOLD_BELOW + 0.15, 0.05),
            ramp(stab, VOL_PANIC_ABOVE, 0.40),
        ])

    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        cs = ctx.get("cross_section") or {}
        pct = cs.get("percentile") or {}
        styles = cs.get("styles") or {}
        mom, rev, stab = styles.get("momentum"), styles.get("reversal"), styles.get("stability")

        s = [
            Signal("장기 추세 유지",
                   None if mom is None else mom >= TREND_ALIVE_ABOVE,
                   f"모멘텀 백분위 {mom:.2f}" if mom is not None else "-", mom),
            Signal("단기 과매도",
                   None if rev is None else rev <= OVERSOLD_BELOW,
                   f"반전 백분위 {rev:.2f}" if rev is not None else "-", rev),
            Signal("변동성 미폭발",
                   None if stab is None else stab <= VOL_PANIC_ABOVE,
                   f"안정성 백분위 {stab:.2f}" if stab is not None else "-", stab),
            Signal("낙폭 과대 아님",
                   None if pct.get("drawdown") is None else pct["drawdown"] >= 0.25,
                   f"낙폭 백분위 {pct['drawdown']:.2f}" if pct.get("drawdown") is not None else "-",
                   pct.get("drawdown")),
        ]
        # 세 핵심 조건은 모두 충족해야 한다. 하나라도 어긋나면 되돌림이 아니다.
        core = s[:3]
        judged = [x for x in core if x.passed is not None]
        decision = bool(judged) and all(x.passed for x in judged) and len(judged) == 3
        if decision and s[3].passed is False:
            decision = False

        all_judged = [x for x in s if x.passed is not None]
        conf = round(sum(1 for x in all_judged if x.passed) / len(all_judged), 3) if all_judged else 0.0

        return ProgramResult(
            program=self.name, version=self.version, decision=decision, confidence=conf,
            summary=("추세는 살아 있고 단기만 밀려 되돌림에 건다" if decision
                     else "되돌림 조건이 갖춰지지 않았다"),
            signals=s,
        )
