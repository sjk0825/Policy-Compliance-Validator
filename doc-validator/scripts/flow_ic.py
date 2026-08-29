"""수급 지표에 예측 정보가 있는지 잰다.

가격 지표에 쓴 것과 같은 잣대를 쓴다. 날짜별로 종목을 줄 세우고 이후
수익률 순위와의 일치도(IC), 그리고 십분위별로 동료 중앙값을 이길 확률을
본다. 새 데이터라고 다른 기준을 적용할 이유가 없다.

원시 순매매량은 종목 크기에 좌우되므로 그대로 쓰면 대형주 순위가 된다.
거래량으로 나눠 규모를 지운다.

    flow_ratio_1   당일 순매매량 / 당일 거래량
    flow_ratio_5   5일 누적 순매매량 / 5일 누적 거래량
    flow_ratio_20  20일 누적
    ratio_chg_20   외국인 보유율의 20일 변화(%p)

    python scripts/flow_ic.py
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
FLOWS = ROOT / "fixtures" / "flows"
HORIZONS = [1, 5, 21]

FEATURES = ["fgn_ratio_1", "fgn_ratio_5", "fgn_ratio_20",
            "inst_ratio_1", "inst_ratio_5", "inst_ratio_20",
            "both_ratio_5", "fgn_hold_chg_20"]


def load(path: Path) -> List[Dict[str, float]]:
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                rows.append({k: (r[k] if k == "Date" else float(r[k])) for k in r})
            except (TypeError, ValueError):
                continue
    return rows


def features_for(rows: List[Dict[str, float]], i: int) -> Dict[str, Optional[float]]:
    """i번째 거래일 기준. i 이후는 보지 않는다."""
    def ratio(field: str, n: int) -> Optional[float]:
        if i + 1 < n:
            return None
        net = sum(rows[j][field] for j in range(i - n + 1, i + 1))
        vol = sum(rows[j]["Volume"] for j in range(i - n + 1, i + 1))
        return net / vol * 100 if vol else None

    out = {
        "fgn_ratio_1": ratio("ForeignNet", 1),
        "fgn_ratio_5": ratio("ForeignNet", 5),
        "fgn_ratio_20": ratio("ForeignNet", 20),
        "inst_ratio_1": ratio("InstNet", 1),
        "inst_ratio_5": ratio("InstNet", 5),
        "inst_ratio_20": ratio("InstNet", 20),
        "fgn_hold_chg_20": (rows[i]["ForeignRatio"] - rows[i - 20]["ForeignRatio"]
                            if i >= 20 else None),
    }
    f5, i5 = out["fgn_ratio_5"], out["inst_ratio_5"]
    out["both_ratio_5"] = (f5 + i5) if (f5 is not None and i5 is not None) else None
    return out


def rank(xs: List[float]) -> List[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def spearman(a: List[float], b: List[float]) -> Optional[float]:
    if len(a) < 8:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-symbols", type=int, default=15)
    args = ap.parse_args()

    manifest = json.loads((FLOWS / "manifest.json").read_text(encoding="utf-8"))
    data = {}
    for e in manifest["symbols"]:
        rows = load(ROOT / e["file"])
        if len(rows) > 40:
            data[e["symbol"]] = rows
    print(f"종목 {len(data)}개  "
          f"({min(len(v) for v in data.values())}~{max(len(v) for v in data.values())}행)\n")

    # 날짜별로 모은다
    by_date: Dict[str, List] = defaultdict(list)
    for sym, rows in data.items():
        idx = {r["Date"]: k for k, r in enumerate(rows)}
        for k, r in enumerate(rows):
            f = features_for(rows, k)
            fwd = {}
            for h in HORIZONS:
                fwd[h] = ((rows[k + h]["Close"] / r["Close"] - 1) * 100
                          if k + h < len(rows) and r["Close"] else None)
            by_date[r["Date"]].append((sym, f, fwd))

    ics: Dict[tuple, List[float]] = defaultdict(list)
    hits: Dict[tuple, List[bool]] = defaultdict(list)
    for day, recs in by_date.items():
        if len(recs) < args.min_symbols:
            continue
        for h in HORIZONS:
            pair_all = [(r[1], r[2][h]) for r in recs if r[2][h] is not None]
            if len(pair_all) < args.min_symbols:
                continue
            vals = sorted(p[1] for p in pair_all)
            n = len(vals)
            med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
            for feat in FEATURES:
                pair = [(f[feat], r) for f, r in pair_all if f.get(feat) is not None]
                if len(pair) < args.min_symbols:
                    continue
                ic = spearman([p[0] for p in pair], [p[1] for p in pair])
                if ic is not None:
                    ics[(feat, h)].append(ic)
                fs = sorted(p[0] for p in pair)
                for v, r in pair:
                    d = min(9, int(sum(1 for x in fs if x < v) / len(fs) * 10))
                    hits[(feat, h, d)].append(r > med)

    print(f"{'지표':<18}" + "".join(f"{h}일 IC (t)".rjust(18) for h in HORIZONS))
    print("-" * (18 + 18 * len(HORIZONS)))
    for feat in FEATURES:
        line = f"{feat:<18}"
        for h in HORIZONS:
            v = ics.get((feat, h), [])
            if len(v) < 30:
                line += f"{'-':>18}"
                continue
            m, sd = st.mean(v), st.pstdev(v)
            t = m / sd * math.sqrt(len(v)) if sd else 0.0
            line += f"{m:+.4f} ({t:+5.1f}){'*' if abs(t) >= 2 else ' '}".rjust(18)
        print(line)
    print(f"\n(날짜 표본 {len(ics.get((FEATURES[0], HORIZONS[0]), []))}개)")

    print(f"\n십분위별 '동료 중앙값을 이길 확률' (%)")
    for h in HORIZONS:
        print(f"\n  [{h}거래일]")
        print(f"  {'지표':<18}" + "".join(f"D{i+1}".rjust(6) for i in range(10)) + "   상위-하위")
        for feat in FEATURES:
            cells = []
            for d in range(10):
                v = hits.get((feat, h, d), [])
                cells.append(sum(v) / len(v) * 100 if len(v) >= 50 else None)
            if any(c is None for c in cells):
                continue
            spread = cells[-1] - cells[0]
            print(f"  {feat:<18}" + "".join(f"{c:6.1f}" for c in cells)
                  + f"{spread:>+10.1f}p{' *' if abs(spread) >= 3 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
