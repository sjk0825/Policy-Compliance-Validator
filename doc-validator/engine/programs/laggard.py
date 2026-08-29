"""소외주 v2. 두 구간에서 모두 재현된 축만 쓴다.

v1은 60일 모멘텀 하위권을 골랐다. 개발 구간에서 ret_60d 십분위 스프레드가
-7.3p로 크게 나왔기 때문이다. 그런데 구간외에서는 +0.4p로 사라졌다.
한 구간에서만 보이는 것은 신호가 아니라 그 구간의 성질이다.

두 구간에서 부호와 크기가 함께 유지된 축만 남긴다.

    지표(63일)        개발      구간외
    ret_20d          -3.2p     -3.2p     단기 패자가 중앙값을 더 자주 넘긴다
    up_day_ratio_60  -3.3p     -3.9p     상승일이 적었던 종목이 더 자주 넘긴다
    px_vs_sma20      -1.9p     -1.8p
    px_vs_sma60      -5.1p     -2.1p
    vol_ratio        -3.6p     -1.5p     변동성이 확대되면 승률이 깎인다

전부 같은 방향을 가리킨다. 최근에 뒤처졌고 조용한 종목이 중앙값을 넘길
확률이 높다. 크게 오른다는 말이 아니다. 중앙값을 넘긴다는 말이다.

버린 축도 남겨둔다. ret_60d와 slope60은 개발 구간에서 가장 커 보였지만
구간외에서 사라졌고, jump_max_60·vol_20d·down_up_vol은 부호가 뒤집혔다.
"""
from typing import Any, Dict

from .base import Program, ProgramResult, Signal, ramp

# 재현된 축들의 임계값. 십분위 D1~D3 구간이 승률 우위를 보였다.
LAG_BELOW = 0.30          # 단기 수익률·이격
TREND_BELOW = 0.40        # 중기 이격
VOL_STABLE_BELOW = 0.50   # 변동성 확대 아님
NOT_BROKEN_ABOVE = 0.15   # 뒤처진 것과 무너진 것을 가른다
MIN_PEERS = 30


class Laggard(Program):
    name = "laggard"
    title = "소외주"
    version = "v2"
    when_to_use = (
        "최근 20일 수익률과 단기 이격이 동료 대비 하위권이고, 변동성이 "
        "확대되지 않았으며 구조적으로 무너지지도 않은 종목일 때. "
        "크게 오르기를 기대하지 않고 중앙값을 넘길 확률이 높은 쪽을 택한다."
    )

    def fitness(self, ctx: Dict[str, Any]) -> float:
        cs = ctx.get("cross_section") or {}
        pct = cs.get("percentile") or {}
        need = ["ret_20d", "px_vs_sma20", "vol_ratio", "drawdown"]
        if any(pct.get(k) is None for k in need) or cs.get("peer_count", 0) < MIN_PEERS:
            return 0.0
        return self.mean_fit([
            ramp(pct["ret_20d"], LAG_BELOW + 0.15, 0.05),
            ramp(pct["px_vs_sma20"], LAG_BELOW + 0.15, 0.05),
            ramp(pct["vol_ratio"], VOL_STABLE_BELOW + 0.15, 0.05),
            ramp(pct["drawdown"], NOT_BROKEN_ABOVE, 0.55),
        ])

    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        pct = (ctx.get("cross_section") or {}).get("percentile") or {}

        def sig(title, axis, cmp_val, direction):
            v = pct.get(axis)
            passed = None if v is None else (v <= cmp_val if direction == "below" else v >= cmp_val)
            return Signal(title, passed,
                          f"백분위 {v:.2f}" if v is not None else "-", v)

        lag = [
            sig("20일 수익률 하위권", "ret_20d", LAG_BELOW, "below"),
            sig("20일선 이격 하위권", "px_vs_sma20", LAG_BELOW, "below"),
            sig("60일선 이격 하위권", "px_vs_sma60", TREND_BELOW, "below"),
            sig("상승일 비율 하위권", "up_day_ratio_60", 0.40, "below"),
        ]
        safe = [
            sig("변동성 확대 아님", "vol_ratio", VOL_STABLE_BELOW, "below"),
            sig("구조적 붕괴 아님", "drawdown", NOT_BROKEN_ABOVE, "above"),
        ]
        s = lag + safe

        judged_lag = [x for x in lag if x.passed is not None]
        judged_safe = [x for x in safe if x.passed is not None]
        # 소외 신호는 과반, 안전 조건은 전부여야 한다. 안전 조건 하나가
        # 어긋나면 뒤처진 것이 아니라 무너지는 중일 가능성이 크다.
        lag_ok = bool(judged_lag) and sum(1 for x in judged_lag if x.passed) >= max(2, len(judged_lag) // 2 + 1)
        safe_ok = bool(judged_safe) and all(x.passed for x in judged_safe)
        decision = lag_ok and safe_ok

        judged = judged_lag + judged_safe
        conf = round(sum(1 for x in judged if x.passed) / len(judged), 3) if judged else 0.0

        return ProgramResult(
            program=self.name, version=self.version, decision=decision, confidence=conf,
            summary=("뒤처졌지만 무너지지 않아 중앙값 회복에 건다" if decision
                     else "소외 조건 또는 안전 조건이 어긋난다"),
            signals=s,
        )
