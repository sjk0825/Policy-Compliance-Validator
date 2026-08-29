"""보유 가정이 다른 프로그램을 제대로 채점한다.

기존 백테스트는 기준일 종가에 사서 N거래일 뒤 종가에 판다. overnight_reversal은
기준일 다음 거래일 시가에 사서 그날 종가에 판다. 잣대가 다르므로 같은
백테스트로 재면 결과가 틀린다.

시각 정합성이 핵심이다.

    D 한국 마감 → D 미국 마감(새벽) → D+1 한국 개장 → D+1 한국 마감
    └ 컨텍스트는 여기까지 ┘  └ 신호 ┘   └ 매수 ┘        └ 매도 ┘

컨텍스트는 D 종가까지만 쓰고, 미국 세션은 D 것을 쓰며, 거래는 D+1이다.
D+1 시가에 매수하는 시점에 세 정보가 모두 확정돼 있다.

비교 기준은 "같은 날 무조건 시가 매수"다. 신호가 없어도 시장은 오르내리므로
그것과 비교해야 신호의 몫이 나온다.

    python scripts/backtest_overnight.py --data fixtures/wide
"""
import argparse
import json
import math
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore, build_context          # noqa: E402
from engine import programs                           # noqa: E402
from engine.router import heuristic_route             # noqa: E402

OUT = ROOT / "fixtures" / "backtests"


def stats(vals: List[float]) -> Optional[Dict[str, Any]]:
    if len(vals) < 30:
        return None
    m, sd = st.mean(vals), st.stdev(vals)
    return {
        "n": len(vals),
        "mean": round(m, 4),
        "median": round(st.median(vals), 4),
        "up_rate": round(sum(1 for v in vals if v > 0) / len(vals) * 100, 2),
        "t": round(m / sd * math.sqrt(len(vals)), 2) if sd else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data")
    ap.add_argument("--profile", default="overnight")
    ap.add_argument("--symbols", default="069500,122630,005930,000660,069660",
                    help="한국 종목만 의미가 있다")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--direct", action="store_true",
                    help="라우터를 거치지 않고 overnight_reversal만 평가한다. "
                         "라우터를 태우면 미국이 잠잠한 날에 다른 프로그램이 "
                         "뽑혀 판정이 섞이므로, 이 신호만 보려면 이쪽을 쓴다.")
    args = ap.parse_args()

    store = PriceStore(Path(args.data) if args.data else None)
    symbols = [s for s in args.symbols.split(",") if store.has(s)]
    if not symbols:
        print("대상 종목이 저장소에 없습니다.")
        return 1

    print(f"보유 가정: 기준일 다음 거래일 시가 매수 → 그날 종가 매도")
    print(f"라우팅 프로파일: {args.profile}   종목 {len(symbols)}개\n")

    rows: List[Dict[str, Any]] = []
    t0 = time.perf_counter()

    for sym in symbols:
        bars = store._all_bars(sym)
        meta = store.meta(sym)
        # i가 기준일 D, i+1이 거래일 D+1.
        for i in range(len(bars) - 1):
            d, nxt = bars[i], bars[i + 1]
            if d.date < args.start or not nxt.open:
                continue
            try:
                ctx = build_context(store, sym, d.date).to_dict()
            except Exception:
                continue
            if args.direct:
                prog = programs.get("overnight_reversal")
                route_name = prog.name
            else:
                route_name = heuristic_route(ctx, profile=args.profile).program
                prog = programs.get(route_name)
            res = prog.run(ctx)
            on = ctx.get("overnight") or {}
            rows.append({
                "symbol": sym, "name": meta.name,
                "as_of": d.date, "trade_date": nxt.date,
                "program": route_name, "decision": res.decision,
                "us_pct": on.get("mean_pct"),
                # 실제로 체결 가능한 구간
                "open_to_close": round((nxt.close / nxt.open - 1) * 100, 4),
                # 참고용. 전일 종가에는 살 수 없다.
                "close_to_close": round((nxt.close / d.close - 1) * 100, 4),
                "gap": round((nxt.open / d.close - 1) * 100, 4),
            })
        print(f"  {sym} {meta.name or '':<12} {len(bars):>5}봉 "
              f"({time.perf_counter()-t0:.0f}초)", flush=True)

    print(f"\n관측 {len(rows):,}건\n")
    print(f"  {'종목':<20}{'구분':<18}{'건수':>7}{'평균':>9}{'중앙값':>9}"
          f"{'상승%':>8}{'t':>7}")
    print("  " + "-" * 78)

    summary: Dict[str, Any] = {}
    for sym in symbols:
        sub = [r for r in rows if r["symbol"] == sym]
        if not sub:
            continue
        label = f"{sym} {sub[0]['name'] or ''}"[:18]
        base = stats([r["open_to_close"] for r in sub])
        taken = stats([r["open_to_close"] for r in sub if r["decision"]])
        skipped = stats([r["open_to_close"] for r in sub if not r["decision"]])

        for tag, s in (("전체(무조건 매수)", base), ("프로그램 매수", taken),
                       ("프로그램 회피", skipped)):
            if s is None:
                continue
            mark = " *" if s["t"] is not None and abs(s["t"]) >= 2 else ""
            print(f"  {label if tag.startswith('전체') else '':<20}{tag:<18}"
                  f"{s['n']:>7}{s['mean']:>+8.3f}%{s['median']:>+8.3f}%"
                  f"{s['up_rate']:>7.1f}%{(s['t'] or 0):>+7.2f}{mark}")
        if base and taken:
            print(f"  {'':<20}{'→ 기준 대비':<18}{'':>7}"
                  f"{taken['mean']-base['mean']:>+8.3f}%{'':>9}"
                  f"{taken['up_rate']-base['up_rate']:>+7.1f}p")
            summary[sym] = {"base": base, "taken": taken, "skipped": skipped}
        print()

    # 미국 등락폭 구간별로도 본다. 임계값 -1%가 자의적이지 않은지 확인한다.
    print("  미국 등락폭 구간별 (전 종목 합산, 시가→종가)")
    print(f"    {'직전 미국':<14}{'건수':>7}{'평균':>9}{'중앙값':>9}{'상승%':>8}{'t':>7}")
    for lo, hi, tag in [(-99, -2, "-2% 이하"), (-2, -1, "-2~-1%"),
                        (-1, -0.5, "-1~-0.5%"), (-0.5, 0.5, "보합"),
                        (0.5, 1, "+0.5~1%"), (1, 2, "+1~2%"), (2, 99, "+2% 이상")]:
        sel = [r["open_to_close"] for r in rows
               if r["us_pct"] is not None and lo <= r["us_pct"] < hi]
        s = stats(sel)
        if s is None:
            continue
        mark = " *" if s["t"] is not None and abs(s["t"]) >= 2 else ""
        print(f"    {tag:<14}{s['n']:>7}{s['mean']:>+8.3f}%{s['median']:>+8.3f}%"
              f"{s['up_rate']:>7.1f}%{(s['t'] or 0):>+7.2f}{mark}")
    print()

    # 갭을 포함한 종가-종가로 재면 얼마나 부풀려지는지 보여준다.
    taken_all = [r for r in rows if r["decision"]]
    if taken_all:
        oc = stats([r["open_to_close"] for r in taken_all])
        cc = stats([r["close_to_close"] for r in taken_all])
        gp = stats([r["gap"] for r in taken_all])
        print("  매수 판정 건의 수익률 분해 (전 종목 합산)")
        print(f"    갭(전일종가→시가)   평균 {gp['mean']:+.3f}%   ← 전일 종가에는 살 수 없다")
        print(f"    장중(시가→종가)     평균 {oc['mean']:+.3f}%   ← 실제 체결 가능")
        print(f"    종가종가            평균 {cc['mean']:+.3f}%   ← 갭이 섞여 부풀려진 값")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "overnight_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: fixtures/backtests/overnight_summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
