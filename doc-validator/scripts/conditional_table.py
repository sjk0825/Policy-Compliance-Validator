"""두 자산의 상태 조합으로 조건부 확률표를 만든다.

"A가 이런 상태고 B가 이런 상태면 내일 B가 오를 확률은 몇 %인가"를 직접
센다. 지금까지의 측정은 지표 하나와 수익률의 관계였는데, 이것은 두 자산의
상태 조합을 본다. 조합에서만 드러나는 관계가 있다면 여기서 보인다.

각 자산의 전일 수익률을 5분위로 나눠 25칸을 만든다. 칸마다 다음 날 B의
상승 비율을 세고 전체 기준과 비교한다.

칸이 25개이므로 우연히 크게 벗어나는 칸이 반드시 나온다. 그래서 두 가지를
같이 한다.

  1. 앞구간에서 표를 만들고 뒷구간에서 같은 칸을 다시 센다.
     앞구간에서만 크고 뒷구간에서 사라지면 우연이다.
  2. 날짜를 섞어 관계를 없앤 플라시보에서 같은 절차를 밟는다.
     관계가 없어도 얼마나 커 보이는지가 기준선이 된다.

    python scripts/conditional_table.py --data fixtures/wide
"""
import argparse
import math
import random
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

SPLIT = "2019-01-01"
BINS = 5

PAIRS = [
    ("SPY", "069500", "SPY → KODEX200"),
    ("QQQ", "005930", "QQQ → 삼성전자"),
    ("SPY", "QQQ", "SPY → QQQ"),
    ("GLD", "069500", "금 → KODEX200"),
    ("TLT", "SPY", "장기채 → SPY"),
    ("069500", "005930", "KODEX200 → 삼성전자"),
]


def series(store: PriceStore, sym: str) -> Tuple[List[str], List[float]]:
    b = store._all_bars(sym)
    d = [b[i].date for i in range(1, len(b))]
    r = [(b[i].close / b[i - 1].close - 1) * 100
         for i in range(1, len(b)) if b[i - 1].close]
    return d[:len(r)], r


def quintile(values: List[float], v: float) -> int:
    return min(BINS - 1, int(sum(1 for x in values if x < v) / len(values) * BINS))


def build(pairs_data: List[Tuple[int, int, bool]], bins: int = BINS):
    """(A분위, B분위, 다음날 B상승) 목록에서 표를 만든다."""
    cnt = [[0] * bins for _ in range(bins)]
    up = [[0] * bins for _ in range(bins)]
    for ia, ib, u in pairs_data:
        cnt[ia][ib] += 1
        up[ia][ib] += 1 if u else 0
    return cnt, up


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    ap.add_argument("--placebo", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    store = PriceStore(Path(args.data))
    rng = random.Random(args.seed)

    print(f"각 자산 전일 수익률을 {BINS}분위로 나눠 {BINS*BINS}칸")
    print(f"앞구간 ~{SPLIT} / 뒷구간 {SPLIT}~")
    if args.placebo:
        print("[플라시보] B의 다음날 방향을 무작위로 다시 붙였다. 진짜 관계는 없다.")
    print()

    summary = []
    for a, b, label in PAIRS:
        if not (store.has(a) and store.has(b)):
            continue
        da, ra = series(store, a)
        db, rb = series(store, b)
        ma = dict(zip(da, ra))
        mb = dict(zip(db, rb))
        days = sorted(set(ma) & set(mb))
        if len(days) < 500:
            continue

        nxt = {days[i]: mb[days[i + 1]] > 0 for i in range(len(days) - 1)}
        if args.placebo:
            vals = [nxt[d] for d in days[:-1]]
            rng.shuffle(vals)
            nxt = dict(zip(days[:-1], vals))

        qa = sorted(ma[d] for d in days)
        qb = sorted(mb[d] for d in days)

        tr, te = [], []
        for d in days[:-1]:
            rec = (quintile(qa, ma[d]), quintile(qb, mb[d]), nxt[d])
            (tr if d < SPLIT else te).append(rec)
        if len(tr) < 300 or len(te) < 200:
            continue

        ctr, utr = build(tr)
        cte, ute = build(te)
        base_tr = sum(1 for r in tr if r[2]) / len(tr) * 100
        base_te = sum(1 for r in te if r[2]) / len(te) * 100

        # 앞구간에서 기준 대비 가장 크게 벗어난 칸을 고른다.
        best = None
        for i in range(BINS):
            for j in range(BINS):
                if ctr[i][j] < 60:
                    continue
                rate = utr[i][j] / ctr[i][j] * 100
                dev = rate - base_tr
                if best is None or abs(dev) > abs(best[2]):
                    best = (i, j, dev, rate, ctr[i][j])
        if best is None:
            continue
        i, j, dev, rate_tr, n_tr = best
        n_te = cte[i][j]
        rate_te = (ute[i][j] / n_te * 100) if n_te >= 30 else None
        dev_te = (rate_te - base_te) if rate_te is not None else None

        print(f"[{label}]  기준 상승률 앞 {base_tr:.1f}% / 뒤 {base_te:.1f}%")
        print(f"  앞구간 최대 편차 칸: A {i+1}분위 × B {j+1}분위")
        print(f"    앞구간  {rate_tr:5.1f}%  (기준 대비 {dev:+5.1f}p, n={n_tr})")
        if dev_te is None:
            print(f"    뒷구간  표본 부족 (n={n_te})")
        else:
            print(f"    뒷구간  {rate_te:5.1f}%  (기준 대비 {dev_te:+5.1f}p, n={n_te})"
                  f"{'   유지' if dev*dev_te > 0 and abs(dev_te) >= 2 else '   사라짐'}")
        summary.append((label, dev, dev_te))
        print()

    kept = [s for s in summary if s[2] is not None and s[1] * s[2] > 0 and abs(s[2]) >= 2]
    print("=" * 66)
    print(f"쌍 {len(summary)}개 중 뒷구간까지 유지된 것: {len(kept)}개")
    if summary:
        print(f"  앞구간 평균 편차 {st.mean([abs(s[1]) for s in summary]):+.1f}p")
        te = [abs(s[2]) for s in summary if s[2] is not None]
        if te:
            print(f"  뒷구간 평균 편차 {st.mean(te):+.1f}p")
    return 0


if __name__ == "__main__":
    sys.exit(main())
