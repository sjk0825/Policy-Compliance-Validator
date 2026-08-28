"""컨텍스트를 사람이 눈으로 확인하기 위한 도구.

    python scripts/show_context.py QQQ 2024-06-14
    python scripts/show_context.py 005930 2024-06-14 --json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import PriceStore, build_context  # noqa: E402


def pct(v, width=0):
    """지표가 아직 안 잡히는 구간(데이터 부족)에서는 None이 온다."""
    return f"{v:+.2f}%".rjust(width) if v is not None else "-".rjust(width or 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("as_of")
    ap.add_argument("--source", help="fixture 디렉터리 (기본: 전체 fixture)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    store = PriceStore(Path(args.source) if args.source else None)
    ctx = build_context(store, args.symbol, args.as_of)

    if args.json:
        print(json.dumps(ctx.to_dict(), ensure_ascii=False, indent=2))
        return 0

    d = ctx.to_dict()
    print(f"{d['symbol']}  {d['meta']['name']}  [{d['meta']['market']}/{d['meta']['group']}]")
    print(f"기준일 {d['as_of']}  (실거래일 {d['coverage']['last_trading_date']}, "
          f"봉 {d['coverage']['bars_available']}개)")
    for w in d["warnings"]:
        print(f"  ! {w}")

    print(f"\n종가 {d['price']['close']:,.2f}")
    print("수익률:", "  ".join(
        f"{k}={v:+.2f}%" for k, v in d["returns"].items() if v is not None))

    t = d["trend"]
    print(f"추세  : 20일선 대비 {pct(t['px_vs_sma20_pct'])}  "
          f"60일선 대비 {pct(t['px_vs_sma60_pct'])}  "
          f"20/60 이격 {pct(t['sma20_vs_sma60_pct'])}")
    v = d["volatility"]
    vr = f"{v['vol_ratio_20_60']:.2f}" if v["vol_ratio_20_60"] is not None else "-"
    print(f"변동성: 20일 {pct(v['ann_vol_20d_pct'])}  60일 {pct(v['ann_vol_60d_pct'])}  비율 {vr}")
    dd = d["drawdown"]
    if dd:
        print(f"낙폭  : 고점 대비 {pct(dd['pct'])}  (고점 후 {dd['days_since_high']}거래일, "
              f"{dd['window_used']}봉 기준)")

    print("\n국면:")
    for sym, r in d["regime"].items():
        arrow = {True: "↑", False: "↓"}.get(r["sma20_above_sma60"], " ")
        print(f"  {sym:<9} {r['label']:<14} 20일 {pct(r['ret_20d_pct'], 8)}  "
              f"60일 {pct(r['ret_60d_pct'], 8)}  60일선 대비 {pct(r['px_vs_sma60_pct'], 7)} {arrow}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
