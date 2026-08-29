"""내린 날 다음에 사면 나은가.

랜덤이면 오늘 내렸다는 사실이 내일에 아무 정보도 주지 않아야 한다. 실제로
그런지 센다.

측정에 함정이 하나 있어 명시해 둔다. "내린 뒤 수익률이 0보다 큰가"를 재면
안 된다. 시장에 상승 추세가 있으므로 아무 부분집합이나 평균이 양수로 나온다.
실제로 그렇게 재면 QQQ가 거래당 +0.137%에 t +3.19로 나오지만, 이것은
그냥 시장이 오른 것이다.

올바른 비교 대상은 "오른 뒤"다. 둘을 견주면 시장 전체의 추세가 상쇄되고
전날 방향이 주는 정보만 남는다.

    python scripts/buy_the_dip.py --data fixtures/wide
"""
import argparse
import math
import statistics as st
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

# 왕복 비용(bp). 한국 주식은 매도 시 증권거래세 0.15%가 붙는다.
TARGETS: List[Tuple[str, str, int]] = [
    ("SPY", "SPY", 5), ("QQQ", "QQQ", 5), ("069500", "KODEX200", 5),
    ("005930", "삼성전자", 20), ("GLD", "금", 5), ("BTC/USD", "비트코인", 10),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))

    print("내린 뒤 vs 오른 뒤 (전날 방향이 주는 정보만 남긴 비교)\n")
    print(f"  {'종목':<10}{'내린 뒤':>10}{'오른 뒤':>10}{'차이':>10}"
          f"{'t':>8}{'비용':>7}{'차이-비용':>11}")
    print("  " + "-" * 66)

    sig = 0
    rows = []
    for sym, label, cost_bp in TARGETS:
        if not store.has(sym):
            continue
        b = store._all_bars(sym)
        r = [(b[i].close / b[i - 1].close - 1) * 100
             for i in range(1, len(b)) if b[i - 1].close]
        dn = [r[i + 1] for i in range(len(r) - 1) if r[i] < 0]
        up = [r[i + 1] for i in range(len(r) - 1) if r[i] > 0]
        if len(dn) < 200 or len(up) < 200:
            continue
        md, mu = st.mean(dn), st.mean(up)
        sd = math.sqrt(st.pvariance(dn) / len(dn) + st.pvariance(up) / len(up))
        t = (md - mu) / sd if sd else 0.0
        cost = cost_bp / 100
        sig += 1 if abs(t) >= 2 else 0
        print(f"  {label:<10}{md:>+9.3f}%{mu:>+9.3f}%{md - mu:>+9.3f}%"
              f"{t:>+8.2f}{cost:>6.2f}%{md - mu - cost:>+10.3f}%"
              f"{' *' if abs(t) >= 2 else ''}")
        rows.append((sym, label, cost_bp))

    print(f"\n  유의한 종목: {sig}/{len(rows)}개")

    print("\n\n실제로 굴리면 (전 구간, 초기 1배)")
    print(f"  {'종목':<10}{'그냥 보유':>12}{'내린 뒤에만 보유':>16}{'시장 노출':>10}")
    print("  " + "-" * 50)
    for sym, label, cost_bp in rows:
        b = store._all_bars(sym)
        r = [(b[i].close / b[i - 1].close - 1)
             for i in range(1, len(b)) if b[i - 1].close]
        bh = 1.0
        for x in r:
            bh *= (1 + x)
        strat, trades = 1.0, 0
        for i in range(len(r) - 1):
            if r[i] < 0:
                strat *= (1 + r[i + 1] - cost_bp / 10000)
                trades += 1
        print(f"  {label:<10}{bh:>11.2f}배{strat:>15.2f}배"
              f"{trades / len(r) * 100:>9.1f}%")
    print("\n  시장에 절반만 들어가 있으므로 수익도 절반 아래로 떨어진다.")
    print("  전날 방향이 주는 정보가 그 손실을 메울 만큼 크지 않다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
