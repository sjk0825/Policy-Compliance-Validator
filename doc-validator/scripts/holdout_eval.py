"""탐색 / 검증 / 최종으로 나눠 한 번에 평가한다.

지금까지는 같은 구간에서 규칙을 만들고 같은 구간에서 재는 일이 반복됐다.
플라시보 실험에서 관계가 없어도 200개 중 27개가 유의해 보인다는 것이
확인됐으므로, 구간을 나누지 않으면 어떤 숫자도 믿을 수 없다.

    탐색  2010~2018   여기서 규칙을 만들고 골랐다
    검증  2019~2022   여기서 살아남는지 본다
    최종  2023~2026   여기서 한 번만 잰다. 여기 보고 규칙을 고치면 안 된다

프로그램은 이미 다 만들어져 있다. 이 스크립트는 고르지 않고 재기만 한다.

    python scripts/holdout_eval.py --data fixtures/wide --period final
"""
import argparse
import json
import math
import statistics as st
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore, build_context            # noqa: E402
from engine import programs                             # noqa: E402
from engine.router import ROUTING_PROFILES, heuristic_route   # noqa: E402

PERIODS = {
    "search":  ("2010-01-01", "2018-12-31", "탐색"),
    "valid":   ("2019-01-01", "2022-12-31", "검증"),
    "final":   ("2023-01-01", "2026-12-31", "최종"),
}
HORIZONS = [21, 63]
OUT = ROOT / "fixtures" / "backtests"


def week_last_days(dates: List[str], every: int = 2) -> List[str]:
    """각 주의 마지막 거래일. every=2면 격주로 솎는다."""
    last: Dict[str, str] = {}
    for d in dates:
        y, w, _ = date.fromisoformat(d).isocalendar()
        last[f"{y}-{w:02d}"] = d
    keys = sorted(last)
    return [last[k] for i, k in enumerate(keys) if i % every == 0]


def profile_stats(vals: List[float]) -> Optional[Dict[str, Any]]:
    if len(vals) < 100:
        return None
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    m, sd = st.mean(vals), st.pstdev(vals)
    return {
        "n": len(vals),
        "win_rate": round(len(wins) / len(vals) * 100, 2),
        "median": round(st.median(vals), 3),
        "mean": round(m, 3),
        "skew": round(sum((v - m) ** 3 for v in vals) / len(vals) / sd ** 3, 2) if sd else None,
        "win_loss": round(st.mean(wins) / st.mean(losses), 2) if wins and losses else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data")
    ap.add_argument("--period", required=True, choices=list(PERIODS))
    ap.add_argument("--every", type=int, default=2, help="판정일 솎기 간격(주)")
    args = ap.parse_args()

    lo, hi, label = PERIODS[args.period]
    store = PriceStore(Path(args.data) if args.data else None)

    by_market = defaultdict(list)
    for s in store.symbols:
        m = store.meta(s)
        if m.kind == "암호화폐":
            continue
        by_market[m.market].append(s)

    print(f"[{label}] {lo} ~ {hi}   종목 "
          + ", ".join(f"{k} {len(v)}" for k, v in sorted(by_market.items())))

    idx: Dict[str, Dict[str, int]] = {}

    def fwd(sym, day, h):
        if sym not in idx:
            idx[sym] = {b.date: i for i, b in enumerate(store._all_bars(sym))}
        bars = store._all_bars(sym)
        i = idx[sym].get(day)
        return None if i is None or i + h >= len(bars) else (
            bars[i + h].close / bars[i].close - 1) * 100

    rows = {p: [] for p in ROUTING_PROFILES}
    t0 = time.perf_counter()
    total_dates = 0

    for market, syms in sorted(by_market.items()):
        pool = sorted({b.date for s in syms for b in store._all_bars(s)
                       if lo <= b.date <= hi})
        days = week_last_days(pool, args.every)
        total_dates += len(days)
        for n, day in enumerate(days, 1):
            recs = []
            for sym in syms:
                try:
                    ctx = build_context(store, sym, day).to_dict()
                except Exception:
                    continue
                recs.append((sym, ctx, {h: fwd(sym, day, h) for h in HORIZONS}))
            if len(recs) < 30:
                continue
            # 동료 중앙값 대비 상대 성과
            med = {}
            for h in HORIZONS:
                vals = sorted(r[2][h] for r in recs if r[2][h] is not None)
                if len(vals) >= 30:
                    k = len(vals)
                    med[h] = vals[k // 2] if k % 2 else (vals[k // 2 - 1] + vals[k // 2]) / 2
            for pname in ROUTING_PROFILES:
                for sym, ctx, rets in recs:
                    route = heuristic_route(ctx, profile=pname)
                    res = programs.get(route.program).run(ctx)
                    if not res.decision:
                        continue
                    for h in HORIZONS:
                        if h in med and rets[h] is not None:
                            rows[pname].append((h, rets[h] - med[h]))
            if n % 20 == 0:
                print(f"    {market} {day} ({n}/{len(days)}, "
                      f"{time.perf_counter()-t0:.0f}초)", flush=True)

    print(f"\n  판정일 {total_dates}개, {time.perf_counter()-t0:.0f}초\n")
    summary: Dict[str, Any] = {"period": args.period, "range": [lo, hi]}

    for h in HORIZONS:
        print(f"  === {h}거래일 · 매수 판정의 동료 대비 초과수익")
        print(f"  {'프로파일':<16}{'건수':>9}{'승률':>9}{'중앙값':>10}{'평균':>10}"
              f"{'왜도':>8}{'이익/손실':>10}")
        print("  " + "-" * 72)
        for pname in ROUTING_PROFILES:
            vals = [v for hh, v in rows[pname] if hh == h]
            s = profile_stats(vals)
            if not s:
                print(f"  {pname:<16} (표본 부족)")
                continue
            summary.setdefault(pname, {})[h] = s
            print(f"  {pname:<16}{s['n']:>9,}{s['win_rate']:>8.2f}%"
                  f"{s['median']:>+9.2f}%{s['mean']:>+9.2f}%"
                  f"{s['skew']:>+8.2f}{s['win_loss']:>10.2f}")
        print()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"holdout_{args.period}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: fixtures/backtests/holdout_{args.period}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
