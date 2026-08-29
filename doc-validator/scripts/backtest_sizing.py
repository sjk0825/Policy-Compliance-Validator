"""비중 프로그램을 회전율과 거래비용까지 넣어 평가한다.

방향 프로그램과 채점 방식이 다르다. 방향은 맞았나 틀렸나를 세지만,
비중은 같은 자산을 얼마나 담았는가의 문제라 경로 전체를 봐야 한다.
CAGR, 샤프, 최대낙폭, 그리고 회전율이 지표다.

앞선 측정에서 빠져 있던 두 가지를 채운다.

1. 밴드. 목표 비중을 매일 그대로 맞추면 회전율이 감당되지 않는다.
   현재 비중이 목표에서 밴드 밖으로 벗어날 때만 조정한다.
2. 거래비용. 비중을 바꾼 만큼에 비례해 뗀다.

비중은 직전 20일까지만 보고 정하고 다음 날 수익률에 적용한다.
미래를 쓰지 않는다.

    python scripts/backtest_sizing.py --data fixtures/wide
"""
import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore                  # noqa: E402
from engine import features as F               # noqa: E402
from engine import programs                    # noqa: E402

PERIODS = [("탐색", "2010-01-01", "2018-12-31"),
           ("검증", "2019-01-01", "2022-12-31"),
           ("최종", "2023-01-01", "2026-12-31")]
TRADING_DAYS = 252
OUT = ROOT / "fixtures" / "backtests"


def sizing_context(closes: List[float]) -> Dict[str, Any]:
    """비중 프로그램이 읽는 부분만 만든다.

    전체 컨텍스트는 동료 수백 종목의 횡단면 순위까지 계산하는데, 비중
    프로그램은 자기 변동성만 본다. 매일 전부 만들면 몇 시간이 걸린다.
    쓰지 않는 것을 계산하지 않는다.
    """
    return {
        "volatility": {
            "ann_vol_20d_pct": F.ann_volatility(closes, 20),
            "ann_vol_60d_pct": F.ann_volatility(closes, 60),
        }
    }


def metrics(rets: List[float], turnover: float, years: float) -> Dict[str, Any]:
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in rets:
        eq *= (1 + x)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    sd = st.pstdev(rets) if len(rets) > 1 else 0.0
    return {
        "cagr": round((eq ** (1 / years) - 1) * 100, 2) if years > 0 and eq > 0 else None,
        "sharpe": round(st.mean(rets) / sd * math.sqrt(TRADING_DAYS), 2) if sd else None,
        "mdd": round(mdd * 100, 1),
        "vol": round(sd * math.sqrt(TRADING_DAYS) * 100, 1),
        "turnover_per_year": round(turnover / years, 1) if years > 0 else None,
    }


def simulate(daily: List[Tuple[str, float]], weights: Dict[str, float],
             band: float, cost_bp: float) -> Optional[Dict[str, Any]]:
    """비중 경로를 적용한다. band 밖으로 벗어날 때만 조정하고 조정분에 비용을 뗀다."""
    held: Optional[float] = None
    rets, turnover = [], 0.0
    for day, r in daily:
        target = weights.get(day)
        if target is None:
            continue
        if held is None or abs(target - held) > band:
            turnover += abs(target - (held or 0.0))
            rets.append(-(abs(target - (held or 0.0)) * cost_bp / 10000))
            held = target
        rets.append(held * r)
    if len(rets) < 120:
        return None
    years = sum(1 for _ in daily) / TRADING_DAYS
    return metrics(rets, turnover, years)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data")
    ap.add_argument("--symbols", default="SPY,QQQ,069500,005930")
    ap.add_argument("--band", type=float, default=0.20,
                    help="목표에서 이만큼 벗어날 때만 조정한다")
    ap.add_argument("--cost-bp", type=float, default=10.0,
                    help="비중 100%를 바꿀 때의 비용(bp). 왕복 스프레드+수수료")
    args = ap.parse_args()

    store = PriceStore(Path(args.data) if args.data else None)
    symbols = [s for s in args.symbols.split(",") if store.has(s)]

    print(f"밴드 {args.band:.0%}   비용 {args.cost_bp:.0f}bp/100% 회전")
    print(f"비중은 직전 20일까지만 보고 정하고 다음 날에 적용한다.\n")

    summary: Dict[str, Any] = {}
    for sym in symbols:
        bars = store._all_bars(sym)
        name = store.meta(sym).name or sym
        # 비중 경로를 한 번만 만들어 재사용한다.
        wpath: Dict[str, Dict[str, float]] = {p: {} for p in programs.SIZING}
        closes = [b.close for b in bars]
        for i in range(len(bars) - 1):
            ctx = sizing_context(closes[max(0, i - 120):i + 1])
            for pname in programs.SIZING:
                r = programs.get(pname).run(ctx)
                if r.weight is not None:
                    wpath[pname][bars[i + 1].date] = r.weight

        daily_all = [(bars[i].date, bars[i].close / bars[i - 1].close - 1)
                     for i in range(1, len(bars)) if bars[i - 1].close]

        print(f"[{sym} {name}]")
        print(f"  {'구간':<6}{'전략':<26}{'CAGR':>9}{'샤프':>7}{'MDD':>8}"
              f"{'변동성':>8}{'연회전율':>9}")
        print("  " + "-" * 68)
        for pname, lo, hi in PERIODS:
            seg = [(d, r) for d, r in daily_all if lo <= d <= hi]
            if len(seg) < 150:
                continue
            years = len(seg) / TRADING_DAYS
            base = metrics([r for _, r in seg], 0.0, years)
            print(f"  {pname:<6}{'그냥 보유':<26}{base['cagr']:>+8.2f}%"
                  f"{(base['sharpe'] or 0):>7.2f}{base['mdd']:>+7.1f}%"
                  f"{base['vol']:>7.1f}%{0:>9.1f}")
            for prog in programs.SIZING:
                m = simulate(seg, wpath[prog], args.band, args.cost_bp)
                if not m:
                    continue
                summary.setdefault(sym, {}).setdefault(pname, {})[prog] = m
                print(f"  {'':<6}{prog:<26}{m['cagr']:>+8.2f}%"
                      f"{(m['sharpe'] or 0):>7.2f}{m['mdd']:>+7.1f}%"
                      f"{m['vol']:>7.1f}%{(m['turnover_per_year'] or 0):>9.1f}")
            summary.setdefault(sym, {}).setdefault(pname, {})["buy_and_hold"] = base
        print()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "sizing_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("저장: fixtures/backtests/sizing_summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
