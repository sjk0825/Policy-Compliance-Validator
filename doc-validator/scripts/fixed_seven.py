"""한 번 고르고 안 바꾸는 조합. 그리고 그 선택이 얼마나 위태로운가.

재선정을 하지 않으면 과적합할 여지가 없다. 대신 처음 고른 것이 틀리면
고칠 방법도 없다. 그래서 두 가지를 같이 본다.

  1. 세 구간에서 어떻게 나오는가
  2. 자산을 하나씩 빼면 결과가 얼마나 흔들리는가

두 번째가 핵심이다. 특정 자산 하나에 결과가 매달려 있으면 그 선택이
운이었을 가능성이 높다. 어느 것을 빼도 비슷하면 조합 자체가 작동한 것이다.

    python scripts/fixed_seven.py --data fixtures/wide
"""
import argparse
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

PERIODS = [("탐색", "2010-01-01", "2018-12-31"),
           ("검증", "2019-01-01", "2022-12-31"),
           ("최종", "2023-01-01", "2026-12-31"),
           ("전체", "2010-01-01", "2026-12-31")]
TRADING_DAYS = 252
REBAL = 21
COST_BP = 10.0

SEVEN = [("BTC/USD", "비트코인"), ("GLD", "금"), ("TLT", "금리(장기채)"),
         ("QQQ", "나스닥"), ("SPY", "S&P500"), ("069500", "코스피"),
         ("VNQ", "부동산")]
FIXED10 = ["SPY", "QQQ", "IWM", "EEM", "GLD", "SLV", "TLT", "UUP", "069500", "BTC/USD"]


def rets(store: PriceStore, sym: str) -> Dict[str, float]:
    b = store._all_bars(sym)
    return {b[i].date: b[i].close / b[i - 1].close - 1
            for i in range(1, len(b)) if b[i - 1].close}


def simulate(series: Dict[str, Dict[str, float]], calendar: List[str],
             syms: List[str], lo: str, hi: str) -> Optional[Dict]:
    """미국 거래일 달력 위에서, 그날 값이 있는 자산에만 균등 배분한다."""
    days = [d for d in calendar if lo <= d <= hi]
    held: Dict[str, float] = {}
    eq, peak, mdd, path = 1.0, 1.0, 0.0, []
    for k, d in enumerate(days):
        avail = [s for s in syms if d in series.get(s, {})]
        if not avail:
            continue
        if not held or k % REBAL == 0:
            target = {s: 1.0 / len(avail) for s in avail}
            turn = sum(abs(target.get(s, 0) - held.get(s, 0))
                       for s in set(target) | set(held))
            eq *= (1 - turn * COST_BP / 10000)
            held = target
        port = sum(held.get(s, 0) * series[s][d] for s in avail)
        eq *= (1 + port)
        path.append(port)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
        grown = {s: held.get(s, 0) * (1 + series[s][d]) for s in avail}
        tot = sum(grown.values())
        if tot > 0:
            held = {s: v / tot for s, v in grown.items()}
    if len(path) < 200:
        return None
    sd = st.pstdev(path)
    yrs = len(path) / TRADING_DAYS
    return {"cagr": (eq ** (1 / yrs) - 1) * 100 if eq > 0 else -100,
            "sharpe": st.mean(path) / sd * math.sqrt(TRADING_DAYS) if sd else 0,
            "mdd": mdd * 100, "final": eq}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))

    seven = [(s, n) for s, n in SEVEN if store.has(s)]
    syms = [s for s, _ in seven]
    need = set(syms) | set(FIXED10) | {"SPY", "QQQ", "069500"}
    series = {s: rets(store, s) for s in need if store.has(s)}
    calendar = sorted(series["SPY"])

    print("조합 7종")
    for s, n in seven:
        print(f"  {s:<9}{n:<14}{min(series[s])} ~")
    print("\n미국 거래일 기준, 21일마다 균등 되맞춤, 비용 10bp\n")

    print("=" * 62)
    for pname, lo, hi in PERIODS:
        print(f"  === {pname} ({lo[:7]}~{hi[:7]})")
        print(f"  {'전략':<20}{'CAGR':>9}{'샤프':>8}{'MDD':>9}{'배수':>9}")
        print("  " + "-" * 56)
        rows = [(syms, "7종 조합"), ([s for s in FIXED10 if s in series], "기존 10종"),
                (["SPY"], "(참고) SPY"), (["QQQ"], "(참고) QQQ"),
                (["069500"], "(참고) 코스피")]
        for g, label in rows:
            m = simulate(series, calendar, g, lo, hi)
            if m:
                tag = "  ←" if label == "7종 조합" else ""
                print(f"  {label:<20}{m['cagr']:>+8.2f}%{m['sharpe']:>8.2f}"
                      f"{m['mdd']:>+8.1f}%{m['final']:>8.2f}배{tag}")
        print()

    print("=" * 62)
    print("하나씩 빼보기 — 결과가 특정 자산에 매달려 있는가 (전체 구간)\n")
    base = simulate(series, calendar, syms, "2010-01-01", "2026-12-31")
    print(f"  {'제외한 자산':<20}{'CAGR':>9}{'샤프':>8}{'MDD':>9}{'CAGR 변화':>11}")
    print("  " + "-" * 58)
    print(f"  {'(없음, 7종 전부)':<20}{base['cagr']:>+8.2f}%{base['sharpe']:>8.2f}"
          f"{base['mdd']:>+8.1f}%{'':>11}")
    deltas = []
    for s, n in seven:
        g = [x for x in syms if x != s]
        m = simulate(series, calendar, g, "2010-01-01", "2026-12-31")
        if not m:
            continue
        d = m["cagr"] - base["cagr"]
        deltas.append(abs(d))
        print(f"  {n:<20}{m['cagr']:>+8.2f}%{m['sharpe']:>8.2f}"
              f"{m['mdd']:>+8.1f}%{d:>+10.2f}p")
    if deltas:
        print(f"\n  CAGR 변화폭 최대 {max(deltas):.2f}p, 평균 {st.mean(deltas):.2f}p")
    return 0


if __name__ == "__main__":
    sys.exit(main())
