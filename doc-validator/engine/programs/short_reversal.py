"""단기 반전 v2. 조용한 종목이 잠깐 밀렸을 때만 잡는다.

v1은 실패했다. 21일 승률 45.1%, 중앙값 -0.86%로 전 프로그램 중 최악이었다.
원인은 전제에 있었다. v1은 "장기 추세가 살아 있을 것"을 요구했는데,
그러면 모멘텀 상위 종목 중 잠깐 밀린 것을 고르게 된다. 모멘텀이 이기는
표본에서 그 종목의 하락에 반대로 걸었으니 정면충돌이었다.

v2는 추세 조건을 버리고 성격 조건으로 바꾼다. 되돌아오는 것은 추세가
있는 종목이 아니라 원래 조용한 종목이다. 변동성이 큰 종목이 밀린 것은
되돌림이 아니라 무언가 벌어지고 있는 것이다.

  조용한 종목이 밀렸다  →  대개 되돌아온다   (자주 이김, 폭 작음)
  시끄러운 종목이 밀렸다 →  계속 밀린다      (v1이 여기 걸렸다)

승률을 얻는 대신 드물게 크게 잃는다. 조용하던 종목이 조용하지 않게 되는
순간이 그때다. 이 프로파일은 선택이지 우위가 아니다.
"""
from typing import Any, Dict

from .base import Program, ProgramResult, Signal, ramp

# 단기 수익률 하위 몇 %를 과매도로 볼 것인가. v1(0.35)보다 좁힌다.
OVERSOLD_BELOW = 0.20
# 이 종목이 원래 조용한가. 변동성 백분위 상한.
CALM_BELOW = 0.50
# 구조적 붕괴 배제. 낙폭 백분위가 이 아래면 이미 무너진 종목이다.
NOT_BROKEN_ABOVE = 0.35
MIN_PEERS = 20


class ShortReversal(Program):
    name = "short_reversal"
    title = "단기 반전"
    version = "v2"
    when_to_use = (
        "평소 변동성이 낮은 종목이 최근 5~20일에만 동료 대비 크게 밀렸을 때. "
        "성격이 조용한 종목의 일시적 하락은 되돌아오는 경향이 있다. "
        "변동성이 원래 큰 종목이나 이미 깊이 무너진 종목에는 쓰지 않는다. "
        "추세 방향은 보지 않는다."
    )

    def fitness(self, ctx: Dict[str, Any]) -> float:
        cs = ctx.get("cross_section") or {}
        pct = cs.get("percentile") or {}
        rev = (cs.get("styles") or {}).get("reversal")
        vol, dd = pct.get("vol_20d"), pct.get("drawdown")
        if None in (rev, vol, dd) or cs.get("peer_count", 0) < MIN_PEERS:
            return 0.0
        return self.mean_fit([
            ramp(rev, OVERSOLD_BELOW + 0.15, 0.02),   # 깊게 밀릴수록
            ramp(vol, CALM_BELOW + 0.15, 0.10),       # 조용할수록
            ramp(dd, NOT_BROKEN_ABOVE, 0.70),         # 덜 무너졌을수록
        ])

    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        cs = ctx.get("cross_section") or {}
        pct = cs.get("percentile") or {}
        rev = (cs.get("styles") or {}).get("reversal")

        s = [
            Signal("단기 과매도",
                   None if rev is None else rev <= OVERSOLD_BELOW,
                   f"반전 백분위 {rev:.2f}" if rev is not None else "-", rev),
            Signal("평소 조용한 종목",
                   None if pct.get("vol_20d") is None else pct["vol_20d"] <= CALM_BELOW,
                   f"변동성 백분위 {pct['vol_20d']:.2f}" if pct.get("vol_20d") is not None else "-",
                   pct.get("vol_20d")),
            Signal("구조적 붕괴 아님",
                   None if pct.get("drawdown") is None else pct["drawdown"] >= NOT_BROKEN_ABOVE,
                   f"낙폭 백분위 {pct['drawdown']:.2f}" if pct.get("drawdown") is not None else "-",
                   pct.get("drawdown")),
            Signal("변동성 급확대 아님",
                   None if pct.get("vol_ratio") is None else pct["vol_ratio"] <= 0.80,
                   f"변동성비 백분위 {pct['vol_ratio']:.2f}" if pct.get("vol_ratio") is not None else "-",
                   pct.get("vol_ratio")),
        ]
        judged = [x for x in s if x.passed is not None]
        # 되돌림은 조건이 다 맞을 때만 성립한다. 하나라도 어긋나면 잡지 않는다.
        decision = len(judged) >= 3 and all(x.passed for x in judged)
        conf = round(sum(1 for x in judged if x.passed) / len(judged), 3) if judged else 0.0

        return ProgramResult(
            program=self.name, version=self.version, decision=decision, confidence=conf,
            summary=("조용하던 종목이 잠깐 밀려 되돌림에 건다" if decision
                     else "되돌림 조건이 갖춰지지 않았다"),
            signals=s,
        )
