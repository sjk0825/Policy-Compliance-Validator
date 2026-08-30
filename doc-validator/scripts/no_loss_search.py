"""모든 해가 플러스인 조합을 찾을 수 있는가. 찾으면 믿을 수 있는가.

제약을 걸고 최적화하면 찾아진다. 2020~2026 일곱 해가 모두 플러스이고
CAGR이 +20.10%인 조합이 나온다. 문제는 그 조합이 무엇을 하고 있는지다.

무작위 3000개 중 181개(6.0%)가 제약을 만족했다. 그중 63개는 2022년
수익률이 0~2% 사이다. 제약선에 딱 붙어 있다는 뜻이고, 최적화가 그 해를
정확히 겨냥했다는 신호다.

제약을 하나 더 걸어 코로나도 -15% 이내로 막게 하면 84개가 남는다. 그중
CAGR 최고는 GLD 32.6%, UUP 29.4%, DBC 23.6%, IEF 7.3%, BTC 7.1%로
주식이 하나도 없는 조합이고 CAGR +12.57%, 최악의 해 +1.64%다.

여기까지는 좋아 보인다. 그런데 최적화에 쓰지 않은 2010~2019로 늘리면
무너진다.

    조합                        2010~2026        2010~2019      마이너스 해
    최적화 조합                  +7.91% (0.92)   +4.09% (0.55)   4회
    E 조합                     +12.33% (1.30)  +12.51% (1.41)   -
    7종만                      +17.67% (1.24)  +16.84% (1.41)   -

2013 -13.6%, 2014 -5.6%, 2015 -5.1%, 2018 -8.6%로 네 해가 마이너스다.
"모든 해 플러스"는 2020~2026이라는 특정 7년에 맞춰진 성질이었다.

    python scripts/no_loss_search.py --data fixtures/wide --iters 3000
"""
import argparse
import math
import random
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

FIT_WINDOW = ("2019-06-01", "2026-12-31")
FIT_YEARS = list(range(2020, 2027))
CHECK_WINDOW = ("2010-01-01", "2019-05-31")
POOL = ["BTC/USD", "GLD", "TLT", "QQQ", "SPY", "069500", "VNQ",
        "DBMF", "BTAL", "UUP", "KMLM", "TAIL", "SH",
        "XLE", "DBC", "BIL", "SHY", "IEF"]
COVID = ("2020-02-19", "2020-03-23")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    ap.add_argument("--iters", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()

    store = PriceStore(args.data)
    pool = [s for s in POOL if store.has(s)]
    cal = sorted(b.date for b in store._all_bars("SPY"))
    R: Dict[str, Dict[str, float]] = {}
    for s in pool:
        bars = store._all_bars(s)
        R[s] = {bars[i].date: bars[i].close / bars[i - 1].close - 1
                for i in range(1, len(bars)) if bars[i - 1].close}

    def run(w, lo, hi, period=21) -> List[float]:
        days = [d for d in cal if lo <= d <= hi]
        held: Dict[str, float] = {}
        path: List[float] = []
        for k, d in enumerate(days):
            av = [s for s in w if w[s] > 0 and d in R[s]]
            if not av:
                continue
            if held:
                path.append(sum(held.get(s, 0) * R[s][d] for s in av))
                g = {s: held.get(s, 0) * (1 + R[s][d]) for s in av}
                t = sum(g.values())
                if t > 0:
                    held = {s: v / t for s, v in g.items()}
            if not held or k % period == 0:
                tw = sum(w[s] for s in av)
                tg = {s: w[s] / tw for s in av}
                turn = sum(abs(tg.get(s, 0) - held.get(s, 0))
                           for s in set(tg) | set(held))
                if path:
                    path[-1] -= turn * 10 / 10000
                held = tg
        return path

    def total(p: List[float]) -> float:
        e = 1.0
        for x in p:
            e *= (1 + x)
        return (e - 1) * 100

    rng = random.Random(args.seed)
    feasible = []
    for _ in range(args.iters):
        syms = rng.sample(pool, rng.randint(5, 10))
        raw = [rng.random() for _ in syms]
        s0 = sum(raw)
        w = {s: v / s0 for s, v in zip(syms, raw)}
        years, ok = {}, True
        for y in FIT_YEARS:
            p = run(w, f"{y}-01-01", f"{y}-12-31")
            if len(p) < 150:
                ok = False
                break
            years[y] = total(p)
        if not ok or min(years.values()) < 0:
            continue
        full = run(w, *FIT_WINDOW)
        e = 1.0
        for x in full:
            e *= (1 + x)
        feasible.append({
            "w": w, "years": years,
            "cagr": (e ** (252 / len(full)) - 1) * 100,
            "covid": total(run(w, *COVID)),
        })

    print(f"무작위 {args.iters}개 중 '모든 해 플러스' 만족: "
          f"{len(feasible)}개 ({len(feasible)/args.iters*100:.1f}%)")
    near = sum(1 for f in feasible if 0 <= f["years"][2022] < 2)
    print(f"  그중 2022년이 0~2%인 것: {near}개 — 제약선에 붙어 있다\n")

    both = sorted([f for f in feasible if f["covid"] > -15.0],
                  key=lambda x: -x["cagr"])
    print(f"코로나도 -15% 이내로 막은 것: {len(both)}개")
    if not both:
        return 0
    b = both[0]
    print(f"  최고  CAGR {b['cagr']:+.2f}%  최악의 해 {min(b['years'].values()):+.2f}%  "
          f"코로나 {b['covid']:+.1f}%")
    print("  비중  " + ", ".join(f"{s} {v*100:.1f}%"
                                for s, v in sorted(b["w"].items(), key=lambda x: -x[1])
                                if v > 0.01))

    print(f"\n최적화에 쓰지 않은 {CHECK_WINDOW[0][:4]}~{CHECK_WINDOW[1][:4]}에서 확인")
    neg = []
    for y in range(int(CHECK_WINDOW[0][:4]), int(CHECK_WINDOW[1][:4]) + 1):
        p = run(b["w"], f"{y}-01-01", f"{y}-12-31")
        if len(p) < 150:
            continue
        v = total(p)
        if v < 0:
            neg.append((y, v))
    if neg:
        print("  마이너스 난 해: " + ", ".join(f"{y} {v:+.1f}%" for y, v in neg))
        print("  '모든 해 플러스'는 맞춘 구간에서만 성립한다.")
    else:
        print("  마이너스 난 해 없음.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
