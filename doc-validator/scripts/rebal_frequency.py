"""되맞춤 주기를 얼마로 할 것인가.

리밸런싱 프리미엄은 자주 되맞출수록 커진다. 이론상 연속이 최대다.
그런데 회전율도 같이 커지고 비용은 회전율에 비례한다. 둘이 반대로
움직이므로 최적이 중간 어딘가에 있다.

주기를 1일부터 1년까지 훑고 비용을 0·5·10·20bp로 바꿔가며 잰다.
비용 0은 이론값 확인용이고 실제로는 존재하지 않는다.

밴드 방식도 같이 본다. 정해진 날에 무조건 맞추는 대신 목표에서 일정
비율 이상 벗어났을 때만 손대는 방식이다. 잔잔한 구간에서는 거래하지
않으므로 회전율이 크게 준다.

    python scripts/rebal_frequency.py --data fixtures/wide
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

SEVEN = ["BTC/USD", "GLD", "TLT", "QQQ", "SPY", "069500", "VNQ"]
PERIODS = [("탐색", "2010-01-01", "2018-12-31"),
           ("검증", "2019-01-01", "2022-12-31"),
           ("최종", "2023-01-01", "2026-12-31"),
           ("전체", "2010-01-01", "2026-12-31")]
TRADING_DAYS = 252
FREQS = [(1, "매일"), (2, "2일"), (5, "주 1회"), (10, "2주"), (21, "월 1회"),
         (63, "분기"), (126, "반기"), (252, "연 1회"), (0, "안 함")]
COSTS = [0.0, 5.0, 10.0, 20.0]


def rets(store: PriceStore, sym: str) -> Dict[str, float]:
    b = store._all_bars(sym)
    return {b[i].date: b[i].close / b[i - 1].close - 1
            for i in range(1, len(b)) if b[i - 1].close}


def simulate(series, calendar, syms, lo, hi, freq: int, cost_bp: float,
             band: Optional[float] = None) -> Optional[Dict]:
    days = [d for d in calendar if lo <= d <= hi]
    held: Dict[str, float] = {}
    eq, peak, mdd, path, turnover = 1.0, 1.0, 0.0, [], 0.0
    for k, d in enumerate(days):
        avail = [s for s in syms if d in series.get(s, {})]
        if not avail:
            continue
        target = {s: 1.0 / len(avail) for s in avail}
        do = not held
        if not do and band is not None:
            # 목표 대비 상대 편차가 밴드를 넘으면 손댄다.
            do = any(abs(held.get(s, 0) - target[s]) / target[s] > band for s in avail)
        elif not do and freq > 0:
            do = (k % freq == 0)
        if do:
            turn = sum(abs(target.get(s, 0) - held.get(s, 0))
                       for s in set(target) | set(held))
            turnover += turn
            eq *= (1 - turn * cost_bp / 10000)
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
            "mdd": mdd * 100, "turn": turnover / yrs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))
    syms = [s for s in SEVEN if store.has(s)]
    series = {s: rets(store, s) for s in syms}
    calendar = sorted(rets(store, "SPY"))

    print(f"자산 {len(syms)}개: {', '.join(syms)}")
    print("균등 비중. 주기와 비용만 바꿔가며 잰다.\n")

    print("=" * 78)
    print("전체 구간 (2010~2026). 비용별 CAGR\n")
    print(f"  {'주기':<10}{'연 회전율':>10}" + "".join(f"{c:.0f}bp".rjust(11) for c in COSTS)
          + f"{'샤프(10bp)':>12}")
    print("  " + "-" * 74)
    for f, label in FREQS:
        row, sh = [], None
        for c in COSTS:
            m = simulate(series, calendar, syms, "2010-01-01", "2026-12-31", f, c)
            if m is None:
                row.append(None)
                continue
            row.append(m["cagr"])
            if c == 10.0:
                sh, turn = m["sharpe"], m["turn"]
        if any(v is None for v in row):
            continue
        cells = "".join(f"{v:+10.2f}%" for v in row)
        print(f"  {label:<10}{turn:>9.1f}회{cells}{sh:>11.2f}")

    print("\n  비용 0은 이론값이다. 실제로는 존재하지 않는다.")
    print("  주기가 짧을수록 총수익(0bp)은 커지지만 비용을 넣으면 뒤집힌다.\n")

    print("=" * 78)
    print("밴드 방식. 목표에서 벗어난 만큼만 손댄다 (비용 10bp)\n")
    print(f"  {'방식':<16}{'연 회전율':>10}{'CAGR':>10}{'샤프':>9}{'MDD':>9}")
    print("  " + "-" * 56)
    for band, label in [(0.05, "밴드 5%"), (0.10, "밴드 10%"),
                        (0.20, "밴드 20%"), (0.30, "밴드 30%")]:
        m = simulate(series, calendar, syms, "2010-01-01", "2026-12-31", 0, 10.0, band)
        if m:
            print(f"  {label:<16}{m['turn']:>9.1f}회{m['cagr']:>+9.2f}%"
                  f"{m['sharpe']:>9.2f}{m['mdd']:>+8.1f}%")
    for f, label in [(1, "매일 (비교)"), (21, "월 1회 (비교)")]:
        m = simulate(series, calendar, syms, "2010-01-01", "2026-12-31", f, 10.0)
        if m:
            print(f"  {label:<16}{m['turn']:>9.1f}회{m['cagr']:>+9.2f}%"
                  f"{m['sharpe']:>9.2f}{m['mdd']:>+8.1f}%")

    print("\n" + "=" * 78)
    print("구간별로 매일과 월 1회 비교 (비용 10bp)\n")
    print(f"  {'구간':<8}{'매일 CAGR':>11}{'월1회 CAGR':>12}{'차이':>9}"
          f"{'매일 샤프':>11}{'월1회 샤프':>11}")
    print("  " + "-" * 62)
    for pname, lo, hi in PERIODS:
        a = simulate(series, calendar, syms, lo, hi, 1, 10.0)
        b = simulate(series, calendar, syms, lo, hi, 21, 10.0)
        if a and b:
            print(f"  {pname:<8}{a['cagr']:>+10.2f}%{b['cagr']:>+11.2f}%"
                  f"{a['cagr']-b['cagr']:>+8.2f}p{a['sharpe']:>11.2f}{b['sharpe']:>11.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
