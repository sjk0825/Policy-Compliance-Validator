"""오버나이트 되돌림. 미국이 빠진 다음 날 한국 시가에 산다.

다른 프로그램과 보유 가정이 다르다. 이 프로그램만 "당일 시가 매수 →
당일 종가 매도"를 전제한다. 나머지는 종가 기준 N거래일 보유다.
섞어서 채점하면 안 된다.

근거는 측정이다. 미국 종가는 한국 개장 전에 확정되고, 한국은 그것을
갭으로 반영한다. 그런데 갭이 과잉 반응해서 장중에 일부 되돌린다.

    코스피 지수(2010~2026, 4,100 거래일)
    기준: 무조건 시가매수  평균 -0.046%  상승 48.5%

    전날 다우 -1% 이하    평균 +0.17%  상승 58.7%  (+10.2p)  t +2.63
    전날 S&P -1% 이하     평균 +0.11%  상승 56.2%  ( +7.7p)  t +1.80
    전날 나스닥 +1% 이상   평균 -0.11%  상승 42.4%  ( -6.2p)  t -2.54
    전날 S&P +1% 이상     평균 -0.11%  상승 41.8%  ( -6.7p)  t -2.03

시차 논리와 결과가 일치한다는 점이 이 신호의 근거를 강화한다. 한국과
같은 시간대인 일본·중국·홍콩은 기준 대비 ±1p 이내로 효과가 없다.
전일 종가에 새 정보가 없으니 당연하다. 미국만 듣는다.

한계도 분명하다. 효과가 하루짜리이고(21일 보유하면 사라진다), 기간을
셋으로 쪼개면 각 구간 t가 1 근처로 단독 유의하지 않다. 검정을 20번
돌려 5개가 유의했으므로 다중검정 보정도 필요하다.
"""
from typing import Any, Dict

from .base import Program, ProgramResult, Signal, ramp

# 이 정도는 움직여야 갭이 과잉 반응한다.
DROP_THRESHOLD = -1.0
RISE_THRESHOLD = 1.0


class OvernightReversal(Program):
    name = "overnight_reversal"
    title = "오버나이트 되돌림"
    version = "v1"
    # 다른 프로그램과 보유 가정이 다르다는 것을 이름으로 남긴다.
    holding = "open_to_close"
    # 발동 조건이 좁고(미국이 1% 이상 움직인 한국 거래일) 근거가 별도로
    # 측정돼 있으므로, 적합도가 같으면 이쪽을 택한다.
    priority = 10
    when_to_use = (
        "한국 종목이고, 직전 미국 거래일이 1% 이상 크게 움직였을 때. "
        "미국이 빠졌으면 과매도 갭을 시가에 받고, 올랐으면 과매수 갭이라 "
        "받지 않는다. 당일 시가에 사서 당일 종가에 파는 것을 전제한다. "
        "미국 종목이나 미국이 잠잠했던 날에는 쓰지 않는다."
    )

    def fitness(self, ctx: Dict[str, Any]) -> float:
        on = ctx.get("overnight") or {}
        if not on.get("applicable") or on.get("mean_pct") is None:
            return 0.0
        # 움직임이 클수록 이 프로그램의 판이다. 방향은 판정에서 가른다.
        return ramp(abs(on["mean_pct"]), 0.5, 2.0) or 0.0

    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        on = ctx.get("overnight") or {}
        if not on.get("applicable"):
            return ProgramResult(
                program=self.name, version=self.version, decision=False, confidence=0.0,
                summary="한국 시장이 아니라 적용되지 않는다.",
                signals=[Signal("적용 가능", False, on.get("reason", "-"), None)],
            )

        mean = on.get("mean_pct")
        leaders = on.get("leaders") or {}
        s = [
            Signal("미국 시장이 확인됨", bool(leaders),
                   ", ".join(f"{k} {v:+.2f}%" for k, v in leaders.items()) or "-", mean),
            Signal(f"직전 미국 {DROP_THRESHOLD:+.0f}% 이하 하락",
                   None if mean is None else mean <= DROP_THRESHOLD,
                   f"평균 {mean:+.2f}%" if mean is not None else "-", mean),
            Signal(f"직전 미국 {RISE_THRESHOLD:+.0f}% 이상 상승 아님",
                   None if mean is None else mean < RISE_THRESHOLD,
                   f"평균 {mean:+.2f}%" if mean is not None else "-", mean),
        ]
        # 미국이 크게 빠진 날만 산다. 오른 날은 명시적으로 사지 않는다.
        decision = bool(leaders) and mean is not None and mean <= DROP_THRESHOLD
        judged = [x for x in s if x.passed is not None]
        conf = round(sum(1 for x in judged if x.passed) / len(judged), 3) if judged else 0.0

        if mean is None:
            summary = "직전 미국 거래일을 확인할 수 없다."
        elif decision:
            summary = f"직전 미국 {mean:+.2f}%. 과매도 갭을 시가에 받는다."
        elif mean >= RISE_THRESHOLD:
            summary = f"직전 미국 {mean:+.2f}%. 과매수 갭이라 받지 않는다."
        else:
            summary = f"직전 미국 {mean:+.2f}%. 움직임이 작아 되돌림을 기대할 수 없다."

        return ProgramResult(
            program=self.name, version=self.version, decision=decision, confidence=conf,
            summary=summary, signals=s,
        )
