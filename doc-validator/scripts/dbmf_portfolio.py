"""관리선물을 넣은 포트폴리오. 비중을 얼마로 할 것인가.

관리선물은 추세추종 전략을 ETF로 만든 것이다. 주식·채권·통화·원자재
선물을 오르면 롱, 내리면 숏으로 기계적으로 따라간다. 하락 추세에서
숏으로 돌아서므로 위기에 오른다. DBMF·KMLM·CTA가 여기 속한다.

BTAL은 다르다. 저베타 주식 롱, 고베타 주식 숏인 주식 시장중립 전략이다.
위기 방어라는 결과는 비슷하지만 구조가 다르므로 따로 본다.

DBMF는 2019-05 상장이라 표본이 7년이다. 그 안에서 반으로 갈라 본다.
짧지만 2020년 코로나와 2022년 하락장을 모두 포함한다.

    python scripts/dbmf_portfolio.py --data fixtures/wide
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
TRADING = 252
REBAL = 21
COST_BP = 10.0


def closes(store: PriceStore, sym: str) -> Dict[str, float]:
    return {b.date: b.close for b in store._all_bars(sym)}


def simulate(store: PriceStore, calendar: List[str], weights: Dict[str, float],
             lo: str, hi: str) -> Optional[Dict]:
    """고정 목표비중. 어제 정한 비중을 오늘 수익률에 적용한다."""
    syms = [s for s in weights if store.has(s)]
    px = {s: closes(store, s) for s in syms}
    days = [d for d in calendar if lo <= d <= hi]
    held: Dict[str, float] = {}
    eq, peak, mdd, path, turnover = 1.0, 1.0, 0.0, [], 0.0

    for k, d in enumerate(days):
        i = calendar.index(d)
        prev = calendar[i - 1] if i > 0 else None
        avail = [s for s in syms if d in px[s]]
        avail_set = set(avail)
        if not avail:
            continue
        if held:
            port = sum(held.get(s, 0) * (px[s][d] / px[s][prev] - 1)
                       for s in avail if prev and prev in px[s] and px[s][prev])
            eq *= (1 + port)
            path.append(port)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
            # 휴장 종목은 보유를 유지한다.
            grown = {s: (w * (px[s][d] / px[s][prev])
                         if (s in avail_set and prev and prev in px[s]
                             and px[s][prev]) else w)
                     for s, w in held.items()}
            tot = sum(grown.values())
            if tot > 0:
                held = {s: v / tot for s, v in grown.items()}
        if not held or k % REBAL == 0:
            w = {s: weights[s] for s in avail}
            tw = sum(w.values())
            target = {s: v / tw for s, v in w.items()} if tw > 0 else {}
            turn = sum(abs(target.get(s, 0) - held.get(s, 0))
                       for s in set(target) | set(held))
            turnover += turn
            eq *= (1 - turn * COST_BP / 10000)
            held = target

    if len(path) < 150:
        return None
    sd = st.pstdev(path)
    yrs = len(path) / TRADING
    return {"cagr": (eq ** (1 / yrs) - 1) * 100 if eq > 0 else -100,
            "sharpe": st.mean(path) / sd * math.sqrt(TRADING) if sd else 0,
            "mdd": mdd * 100, "final": eq, "turn": turnover / yrs}


def mix(base: List[str], hedge: Optional[str], w: float) -> Dict[str, float]:
    """헤지가 전체의 w 비중이 되도록 맞춘다."""
    d = {s: (1 - w) / len(base) for s in base}
    if hedge and w > 0:
        d[hedge] = d.get(hedge, 0) + w
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))
    base = [s for s in SEVEN if store.has(s)]
    cal = sorted(closes(store, "SPY"))

    print("기준 7종: " + ", ".join(base))
    print(f"월 1회 되맞춤, 비용 {COST_BP:.0f}bp\n")

    LO, HI = "2019-06-01", "2026-12-31"
    MID = "2023-01-01"
    print("=" * 74)
    print(f"DBMF 비중별  ({LO[:7]} ~ 상장 이후 전체)\n")
    print(f"  {'DBMF 비중':<11}{'CAGR':>9}{'샤프':>8}{'MDD':>9}{'회전율':>9}{'1억 →':>10}")
    print("  " + "-" * 58)
    for w in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40):
        m = simulate(store, cal, mix(base, "DBMF" if w else None, w), LO, HI)
        if m:
            tag = "  ←" if abs(w - 0.20) < 1e-9 else ""
            print(f"  {w:>9.0%}  {m['cagr']:>+8.2f}%{m['sharpe']:>8.2f}"
                  f"{m['mdd']:>+8.1f}%{m['turn']:>8.1f}회{m['final']:>8.2f}억{tag}")

    print("\n" + "=" * 74)
    print("반으로 갈라서\n")
    print(f"  {'구간':<20}{'DBMF 0%':>22}{'DBMF 20%':>24}")
    print(f"  {'':<20}{'CAGR    샤프     MDD':>22}{'CAGR    샤프     MDD':>24}")
    print("  " + "-" * 66)
    for pn, lo, hi in [("전반 2019~2022", LO, MID), ("후반 2023~2026", MID, HI),
                       ("전체", LO, HI)]:
        a = simulate(store, cal, mix(base, None, 0.0), lo, hi)
        b = simulate(store, cal, mix(base, "DBMF", 0.20), lo, hi)
        if a and b:
            print(f"  {pn:<20}{a['cagr']:>+8.1f}%{a['sharpe']:>7.2f}{a['mdd']:>+8.1f}%"
                  f"{b['cagr']:>+9.1f}%{b['sharpe']:>7.2f}{b['mdd']:>+8.1f}%")

    print("\n" + "=" * 74)
    print("연도별 (DBMF 0% vs 20%)\n")
    print(f"  {'연도':<8}{'DBMF 0%':>11}{'DBMF 20%':>12}{'차이':>10}")
    print("  " + "-" * 42)
    for y in range(2020, 2027):
        a = simulate(store, cal, mix(base, None, 0.0), f"{y}-01-01", f"{y}-12-31")
        b = simulate(store, cal, mix(base, "DBMF", 0.20), f"{y}-01-01", f"{y}-12-31")
        if a and b:
            print(f"  {y:<8}{a['cagr']:>+10.1f}%{b['cagr']:>+11.1f}%"
                  f"{b['cagr']-a['cagr']:>+9.1f}p")

    print("\n" + "=" * 74)
    print("다른 관리선물·유사 상품과 비교 (각 20%, 상품별 상장 이후)\n")
    print(f"  {'상품':<22}{'기간':<12}{'CAGR':>9}{'샤프':>8}{'MDD':>9}{'기준 대비 샤프':>14}")
    print("  " + "-" * 74)
    for sym, label, start in [("DBMF", "DBMF 관리선물", "2019-06-01"),
                              ("KMLM", "KMLM 관리선물", "2021-01-01"),
                              ("CTA", "CTA 관리선물", "2022-04-01"),
                              ("BTAL", "BTAL 주식중립", "2011-10-01"),
                              ("GLD", "금 비중확대", "2010-01-01")]:
        if not store.has(sym):
            continue
        a = simulate(store, cal, mix(base, None, 0.0), start, HI)
        b = simulate(store, cal, mix(base, sym, 0.20), start, HI)
        if a and b:
            print(f"  {label:<22}{start[:7]:<12}{b['cagr']:>+8.2f}%{b['sharpe']:>8.2f}"
                  f"{b['mdd']:>+8.1f}%{b['sharpe']-a['sharpe']:>+13.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
