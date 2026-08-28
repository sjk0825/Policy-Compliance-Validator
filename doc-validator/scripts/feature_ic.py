"""지표에 예측 정보가 있는지 측정한다.

"입력이 부족한가"는 추측할 문제가 아니다. 각 지표로 종목을 줄 세우고
이후 수익률 순위와 얼마나 일치하는지 보면 된다(정보계수, IC).

날짜별로 종목 간 순위를 매기는 횡단면 방식을 쓴다. 시계열로 뭉뚱그리면
"시장 전체가 오른 날"이 지표의 힘으로 오인된다.

IC는 날짜마다 하나씩 나온다. 그 평균이 0에서 유의하게 떨어져 있는지를
t값으로 본다. |t|가 2를 넘으면 우연으로 보기 어렵다.

    python scripts/feature_ic.py
    python scripts/feature_ic.py --market kr
"""
import argparse
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore, build_context  # noqa: E402

HORIZONS = [1, 5, 21, 63]

FEATURE_NAMES = [
    "ret_5d", "ret_20d", "ret_60d", "ret_120d",
    "px_vs_sma20", "px_vs_sma60", "sma20_vs_sma60",
    "slope20", "slope60", "vol_20d", "vol_ratio", "drawdown", "rel_volume",
]


def features(ctx: Dict) -> Dict[str, Optional[float]]:
    t, v, r = ctx["trend"], ctx["volatility"], ctx["returns"]
    dd = ctx.get("drawdown") or {}
    return {
        "ret_5d": r.get("5d"),
        "ret_20d": r.get("20d"),
        "ret_60d": r.get("60d"),
        "ret_120d": r.get("120d"),
        "px_vs_sma20": t["px_vs_sma20_pct"],
        "px_vs_sma60": t["px_vs_sma60_pct"],
        "sma20_vs_sma60": t["sma20_vs_sma60_pct"],
        "slope20": t["slope20_pct_per_day"],
        "slope60": t["slope60_pct_per_day"],
        "vol_20d": v["ann_vol_20d_pct"],
        "vol_ratio": v["vol_ratio_20_60"],
        "drawdown": dd.get("pct"),
        "rel_volume": ctx["volume"]["rel_vol_20_over_60_pct"],
    }


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
    if len(a) < 5:
        return None
    ra, rb = rank(a), rank(b)
    ma, mb = st.mean(ra), st.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


def weekly_dates(store: PriceStore, symbols: List[str]) -> List[str]:
    """각 주의 마지막 거래일. 전체 기간에서 뽑는다(표본을 최대한 확보)."""
    pool = set()
    for s in symbols:
        pool.update(b.date for b in store._all_bars(s))
    last = {}
    for d in sorted(pool):
        y, w, _ = __import__("datetime").date.fromisoformat(d).isocalendar()
        last[f"{y}-{w:02d}"] = d
    return [last[k] for k in sorted(last)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="us", choices=["us", "kr"])
    args = ap.parse_args()

    store = PriceStore()
    prefix = "us_" if args.market == "us" else "kr_"
    symbols = [s for s in store.symbols
               if store.meta(s).group.startswith(prefix)
               and store.meta(s).kind != "암호화폐"]
    dates = weekly_dates(store, symbols)

    print(f"시장 {args.market}  종목 {len(symbols)}개  주간 기준일 {len(dates)}개")
    print(f"기간 {dates[0]} ~ {dates[-1]}\n")

    idx = {s: {b.date: i for i, b in enumerate(store._all_bars(s))} for s in symbols}

    ics: Dict[tuple, List[float]] = defaultdict(list)
    skipped: Dict[str, int] = defaultdict(int)
    for d in dates:
        rows = []
        for s in symbols:
            i = idx[s].get(d)
            if i is None:
                continue
            try:
                f = features(build_context(store, s, d).to_dict())
            except Exception as exc:
                skipped[type(exc).__name__ + ": " + str(exc)[:60]] += 1
                continue
            bars = store._all_bars(s)
            fwd = {h: (bars[i + h].close / bars[i].close - 1) if i + h < len(bars) else None
                   for h in HORIZONS}
            rows.append((f, fwd))
        if len(rows) < 5:
            continue
        for name in FEATURE_NAMES:
            for h in HORIZONS:
                pair = [(r[0][name], r[1][h]) for r in rows
                        if r[0].get(name) is not None and r[1][h] is not None]
                if len(pair) < 5:
                    continue
                ic = spearman([p[0] for p in pair], [p[1] for p in pair])
                if ic is not None:
                    ics[(name, h)].append(ic)

    if skipped:
        print("건너뛴 사유:")
        for k, v in sorted(skipped.items(), key=lambda kv: -kv[1])[:5]:
            print(f"  {v:>6}건  {k}")
        print()

    print(f"{'지표':<17}" + "".join(f"{h}일 IC (t)".rjust(17) for h in HORIZONS))
    print("-" * (17 + 17 * len(HORIZONS)))
    flagged = []
    for name in FEATURE_NAMES:
        line = f"{name:<17}"
        for h in HORIZONS:
            vals = ics.get((name, h), [])
            if len(vals) < 20:
                line += "               -"
                continue
            m, sd = st.mean(vals), st.pstdev(vals)
            t = m / sd * math.sqrt(len(vals)) if sd else 0.0
            mark = "*" if abs(t) >= 2 else " "
            if abs(t) >= 2:
                flagged.append((name, h, m, t))
            line += f"{m:+.4f} ({t:+5.1f}){mark}".rjust(17)
        print(line)

    print(f"\n(IC = 날짜별 횡단면 순위상관의 평균, t = 0과 다른지. |t|>=2 에 * 표시)")
    print(f"(날짜 표본 {len(ics.get(('ret_20d', 21), []))}개)")
    if flagged:
        print("\n유의한 지표:")
        for name, h, m, t in sorted(flagged, key=lambda x: -abs(x[3]))[:8]:
            print(f"  {name:<17} {h:>3}일  IC {m:+.4f}  t {t:+.1f}")
    else:
        print("\n유의한 지표 없음.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
