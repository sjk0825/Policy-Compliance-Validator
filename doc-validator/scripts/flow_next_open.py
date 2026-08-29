"""수급 1일 신호를 실제로 체결 가능한 구간에서 잰다.

수급은 장 마감 뒤에 공표된다. 그러니 D일 수급을 보고 D일 종가에 살 수는
없다. D+1 개장에나 살 수 있고, 그 사이 갭이 벌어진다. 오버나이트 신호에서
갭이 효과를 전부 먹었던 것과 같은 구조다.

    D 마감 → D 수급 공표 → D+1 개장 → D+1 마감
    └ 신호 ┘               └ 매수 ┘   └ 매도 ┘

세 구간을 나눠 본다. 갭(D종가→D+1시가)은 살 수 없는 구간, 장중
(D+1시가→D+1종가)은 살 수 있는 구간, 종가종가는 둘의 합이다.

같은 날 종목들 사이에서 십분위로 가르고, 동료 중앙값 대비로 잰다.
시장 전체가 오른 날이 신호의 힘으로 오인되지 않게 하기 위해서다.

    python scripts/flow_next_open.py
"""
import argparse
import csv
import json
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

FLOWS = ROOT / "fixtures" / "flows"
FEATURES = ["inst_ratio_1", "fgn_ratio_1", "both_ratio_1"]
SPLIT = "2024-05-01"     # 표본을 반으로 가르는 지점


def load_flow(path: Path) -> List[Dict]:
    out = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                out.append({"Date": r["Date"], "Volume": float(r["Volume"]),
                            "InstNet": float(r["InstNet"]),
                            "ForeignNet": float(r["ForeignNet"])})
            except (TypeError, ValueError):
                continue
    return out


def stats(vals: List[float]) -> Optional[Dict]:
    if len(vals) < 200:
        return None
    m, sd = st.mean(vals), st.stdev(vals)
    return {"n": len(vals), "mean": m, "median": st.median(vals),
            "up": sum(1 for v in vals if v > 0) / len(vals) * 100,
            "t": m / sd * math.sqrt(len(vals)) if sd else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    ap.add_argument("--min-symbols", type=int, default=20)
    args = ap.parse_args()

    store = PriceStore(Path(args.data))
    manifest = json.loads((FLOWS / "manifest.json").read_text(encoding="utf-8"))

    # 종목별로 수급과 시가·종가를 맞춘다.
    recs_by_date: Dict[str, List] = defaultdict(list)
    used = 0
    for e in manifest["symbols"]:
        sym = e["symbol"]
        if not store.has(sym):
            continue
        flows = load_flow(ROOT / e["file"])
        bars = {b.date: b for b in store._all_bars(sym)}
        dates = sorted(b for b in bars)
        pos = {d: i for i, d in enumerate(dates)}
        used += 1
        for f in flows:
            d = f["Date"]
            i = pos.get(d)
            if i is None or i + 1 >= len(dates) or not f["Volume"]:
                continue
            nxt = bars[dates[i + 1]]
            cur = bars[d]
            if not (nxt.open and cur.close):
                continue
            inst = f["InstNet"] / f["Volume"] * 100
            fgn = f["ForeignNet"] / f["Volume"] * 100
            recs_by_date[d].append({
                "symbol": sym,
                "inst_ratio_1": inst, "fgn_ratio_1": fgn,
                "both_ratio_1": inst + fgn,
                "gap": (nxt.open / cur.close - 1) * 100,
                "intraday": (nxt.close / nxt.open - 1) * 100,
                "c2c": (nxt.close / cur.close - 1) * 100,
            })

    print(f"종목 {used}개, 날짜 {len(recs_by_date)}개")
    print(f"수급은 D일 마감 후 공표 → D+1 시가 매수 → D+1 종가 매도\n")

    # 십분위별로 동료 중앙값 대비 성과를 모은다.
    buckets: Dict[tuple, List[float]] = defaultdict(list)
    for day, recs in recs_by_date.items():
        if len(recs) < args.min_symbols:
            continue
        half = "전반" if day < SPLIT else "후반"
        for field in ("gap", "intraday", "c2c"):
            vals = sorted(r[field] for r in recs)
            n = len(vals)
            med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
            for feat in FEATURES:
                fs = sorted(r[feat] for r in recs)
                for r in recs:
                    d = min(9, int(sum(1 for x in fs if x < r[feat]) / len(fs) * 10))
                    buckets[(feat, field, d)].append(r[field] - med)
                    buckets[(feat, field, d, half)].append(r[field] - med)

    for field, label in [("gap", "갭 (D종가→D+1시가) — 살 수 없는 구간"),
                         ("intraday", "장중 (D+1시가→D+1종가) — 실제 체결 가능"),
                         ("c2c", "종가종가 — 갭이 섞인 값")]:
        print(f"\n=== {label}")
        print(f"  {'지표':<16}" + "".join(f"D{i+1}".rjust(7) for i in range(10))
              + "   상위-하위")
        print("  " + "-" * 88)
        for feat in FEATURES:
            cells = []
            for d in range(10):
                s = stats(buckets.get((feat, field, d), []))
                cells.append(s["mean"] if s else None)
            if any(c is None for c in cells):
                continue
            spread = cells[-1] - cells[0]
            print(f"  {feat:<16}" + "".join(f"{c:+7.3f}" for c in cells)
                  + f"{spread:>+10.3f}%{' *' if abs(spread) >= 0.1 else ''}")

    # 가장 큰 신호를 전반·후반으로 갈라 확인한다.
    print(f"\n=== 극단 십분위를 전반/후반으로 나눠 확인 (장중 기준, 기준일 {SPLIT})")
    print(f"  {'지표':<16}{'십분위':<8}{'구간':<6}{'건수':>7}{'평균':>9}"
          f"{'중앙값':>9}{'승률':>8}{'t':>7}")
    print("  " + "-" * 72)
    for feat in FEATURES:
        for d, dname in ((0, "D1 최저"), (9, "D10 최고")):
            for half in ("전반", "후반"):
                s = stats(buckets.get((feat, "intraday", d, half), []))
                if not s:
                    continue
                print(f"  {feat:<16}{dname:<8}{half:<6}{s['n']:>7}"
                      f"{s['mean']:>+8.3f}%{s['median']:>+8.3f}%"
                      f"{s['up']:>7.1f}%{s['t']:>+7.2f}"
                      f"{' *' if abs(s['t']) >= 2 else ''}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
