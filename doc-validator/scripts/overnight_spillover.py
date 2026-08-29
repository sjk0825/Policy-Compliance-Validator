"""전날 미국 시장이 한국 시장 당일 방향을 예측하는가.

지금까지의 측정은 전부 횡단면 상대 성과였다. 동료 중앙값을 뺐으므로
시장 전체의 방향은 상쇄돼 사라진다. 이 신호는 종류가 다르다. 개별
종목의 상대 순위가 아니라 시장 전체의 방향을 맞히려는 것이다.

한국 거래일 d에 대해, d 이전의 마지막 미국 거래일 수익률을 본다.
시차 때문에 미국 종가는 한국 개장 전에 확정된다. 미래를 보는 것이 아니다.

    python scripts/overnight_spillover.py --data fixtures/wide
"""
import argparse
import statistics as st
import sys
from bisect import bisect_left
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore  # noqa: E402

US_LEADERS = ["SPY", "QQQ"]

# 종가-종가로 재면 갭이 결과를 다 만든다. 전날 종가에는 살 수 없으므로
# 그 숫자는 체결 가능한 성과가 아니다. 시가 매수 → 종가 매도가 실제로
# 담을 수 있는 구간이고, 거기서는 신호의 방향이 뒤집힌다. 갭이 과잉
# 반응하고 장중에 되돌리기 때문이다.
#
#   KODEX 200, 전날 SPY -1% 이하  →  장중 평균 +0.15%, 상승 55.7% (기준 49.8%)
#   KODEX 200, 전날 SPY +1% 이상  →  장중 평균 -0.11%, 상승 45.7%
#
# 다만 기간을 셋으로 쪼개면 t가 0.7~2.1로 어느 구간도 단독으로는 유의하지
# 않다. 방향은 세 구간에서 모두 같지만 크기가 작아 표본이 더 필요하다.
KR_TARGETS = [("069500", "KODEX 200"), ("005930", "삼성전자"),
              ("000660", "SK하이닉스"), ("122630", "KODEX 레버리지")]


def series(store: PriceStore, sym: str) -> Tuple[List[str], List[float]]:
    bars = store._all_bars(sym)
    dates = [b.date for b in bars]
    rets = [None] + [(bars[i].close / bars[i - 1].close - 1) * 100
                     for i in range(1, len(bars))]
    return dates, rets


def prev_us_return(us_dates: List[str], us_rets: List[float], kr_day: str) -> Optional[float]:
    """한국 거래일 직전에 끝난 미국 거래일 수익률.

    같은 날짜의 미국 종가는 한국 장 마감 뒤에 나오므로 쓸 수 없다.
    반드시 그 이전 날짜여야 한다.
    """
    i = bisect_left(us_dates, kr_day) - 1
    return us_rets[i] if 0 <= i < len(us_rets) else None


def report(name: str, pairs: List[Tuple[float, float]]) -> None:
    if len(pairs) < 200:
        print(f"  {name}: 표본 부족 ({len(pairs)})")
        return

    follow = sum(1 for u, k in pairs if (u > 0) == (k > 0)) / len(pairs) * 100
    base_up = sum(1 for _, k in pairs if k > 0) / len(pairs) * 100
    # 방향을 무시하고 늘 상승에 걸었을 때와 비교해야 공정하다.
    always_up = base_up
    print(f"\n  [{name}]  표본 {len(pairs):,}일")
    print(f"    미국 방향 추종 적중률 {follow:5.2f}%   "
          f"무조건 상승 베팅 {always_up:5.2f}%   차이 {follow-always_up:+5.2f}p")

    # 미국 등락폭 구간별로 나눠 본다. 큰 움직임일수록 잘 따라오는가.
    buckets = [(-99, -2), (-2, -1), (-1, -0.3), (-0.3, 0.3), (0.3, 1), (1, 2), (2, 99)]
    print(f"    {'전날 미국':<14}{'표본':>7}{'한국 상승비율':>14}{'평균 수익률':>13}")
    for lo, hi in buckets:
        sel = [k for u, k in pairs if lo <= u < hi]
        if len(sel) < 30:
            continue
        up = sum(1 for k in sel if k > 0) / len(sel) * 100
        print(f"    {f'{lo:+.1f}~{hi:+.1f}%':<14}{len(sel):>7}{up:>13.1f}%{st.mean(sel):>+12.2f}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data")
    args = ap.parse_args()
    store = PriceStore(Path(args.data) if args.data else None)

    for leader in US_LEADERS:
        if not store.has(leader):
            continue
        ud, ur = series(store, leader)
        print(f"\n{'='*70}\n선행: {leader}")
        for sym, label in KR_TARGETS:
            if not store.has(sym):
                continue
            kd, kr = series(store, sym)
            pairs = []
            for i, day in enumerate(kd):
                if kr[i] is None:
                    continue
                u = prev_us_return(ud, ur, day)
                if u is not None:
                    pairs.append((u, kr[i]))
            report(f"{leader} → {label}({sym})", pairs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
