"""지표별로 "다음 h일에 동료 중앙값을 이길 확률"을 십분위로 잰다.

기존 IC 측정은 수익률 크기와의 순위상관을 봤다. 승률을 올리려면 크기가
아니라 이길 확률과의 관계를 봐야 한다. 다른 질문이므로 따로 잰다.

중앙값 기준이라 전체 평균은 구조적으로 50%다. 어떤 지표의 상위 십분위가
53%, 하위가 47%라면 그 지표에는 승률 정보가 있다.

    python scripts/hit_by_feature.py --data fixtures/wide --slice ...
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore, build_context   # noqa: E402
from engine.context import ALL_AXES            # noqa: E402

HORIZONS = [21, 63]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", required=True)
    ap.add_argument("--data")
    args = ap.parse_args()

    meta = json.loads(Path(args.slice).read_text(encoding="utf-8"))
    store = PriceStore(Path(args.data) if args.data else None)

    by_market = defaultdict(list)
    for e in meta["symbols"]:
        market = "crypto" if e.get("kind") == "암호화폐" else (
            "kr" if e["group"].startswith("kr_") else "us")
        by_market[market].append(e["symbol"])

    idx: Dict[str, Dict[str, int]] = {}

    def fwd(sym, date, h):
        if sym not in idx:
            idx[sym] = {b.date: i for i, b in enumerate(store._all_bars(sym))}
        bars = store._all_bars(sym)
        i = idx[sym].get(date)
        return None if i is None or i + h >= len(bars) else (
            bars[i + h].close / bars[i].close - 1)

    # (지표, 지평, 십분위) → [이겼는가]
    buckets: Dict[tuple, List[bool]] = defaultdict(list)
    t0 = time.perf_counter()
    total = 0

    for market, grid in meta["decision_grid"].items():
        if market == "crypto":
            continue
        for di, date in enumerate(grid["decision_dates"]):
            recs = []
            for sym in by_market.get(market, []):
                try:
                    cs = build_context(store, sym, date).to_dict()["cross_section"]
                except Exception:
                    continue
                rets = {h: fwd(sym, date, h) for h in HORIZONS}
                if all(v is None for v in rets.values()):
                    continue
                recs.append((sym, cs["percentile"], rets))
            if len(recs) < 30:
                continue
            total += len(recs)

            for h in HORIZONS:
                vals = sorted(r[2][h] for r in recs if r[2][h] is not None)
                if len(vals) < 30:
                    continue
                n = len(vals)
                med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
                for _, pct, rets in recs:
                    if rets[h] is None:
                        continue
                    won = rets[h] > med
                    for axis in ALL_AXES:
                        v = pct.get(axis)
                        if v is None:
                            continue
                        buckets[(axis, h, min(9, int(v * 10)))].append(won)
            if di % 30 == 0:
                print(f"  … {market} {date} ({time.perf_counter()-t0:.0f}초)", flush=True)

    print(f"\n관측 {total:,}건\n")
    for h in HORIZONS:
        print(f"=== {h}거래일 · 다음 구간에 동료 중앙값을 이길 확률(%)")
        print(f"  {'지표':<18}" + "".join(f"D{i+1}".rjust(6) for i in range(10))
              + "   상위-하위")
        print("  " + "-" * 92)
        scored = []
        for axis in ALL_AXES:
            cells = []
            for d in range(10):
                v = buckets.get((axis, h, d), [])
                cells.append(sum(v) / len(v) * 100 if len(v) >= 50 else None)
            if any(c is None for c in cells):
                continue
            spread = cells[-1] - cells[0]
            scored.append((axis, cells, spread))
        for axis, cells, spread in sorted(scored, key=lambda x: -abs(x[2])):
            mark = " *" if abs(spread) >= 2.0 else ""
            print(f"  {axis:<18}" + "".join(f"{c:6.1f}" for c in cells)
                  + f"{spread:>+10.1f}p{mark}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
