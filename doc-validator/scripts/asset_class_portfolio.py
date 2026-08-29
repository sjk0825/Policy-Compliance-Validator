"""성격이 다른 자산군으로 포트폴리오를 짠다.

리밸런싱이 회수하는 몫은 σ²(1-ρ)/4다. σ는 자산이 정하고 ρ는 조합이
정한다. 그러니 실제로 손댈 수 있는 것은 ρ뿐이고, 서로 다르게 움직이는
것들을 모으는 것이 전부다.

앞서 쓴 10자산은 주식이 절반이라 평균 상관이 높았다. 여기서는 자산군마다
대표를 하나씩만 넣어 겹침을 없앤다.

종목마다 상장일이 달라 공통 구간이 짧아지는 문제가 있다. 교집합을 쓰면
비트코인 때문에 2014년, DBMF 때문에 2019년부터가 된다. 그래서 그날
존재하는 자산에만 균등 배분한다. 자산이 늘면 자연히 편입된다.

    python scripts/asset_class_portfolio.py --data fixtures/wide
"""
import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

PERIODS = [("탐색", "2010-01-01", "2018-12-31"),
           ("검증", "2019-01-01", "2022-12-31"),
           ("최종", "2023-01-01", "2026-12-31")]
TRADING_DAYS = 252
REBAL = 21
COST_BP = 10.0

# 자산군마다 대표 하나. 겹치는 것은 넣지 않는다.
UNIVERSE = [
    ("SPY", "미국 대형주"),
    ("QQQ", "미국 기술주"),
    ("IWM", "미국 소형주"),
    ("EFA", "선진국 주식"),
    ("VWO", "신흥국 주식"),
    ("069500", "한국 주식"),
    ("VNQ", "부동산"),
    ("XLE", "에너지"),
    ("XLU", "유틸리티"),
    ("TLT", "미국 장기채"),
    ("TIP", "물가연동채"),
    ("HYG", "하이일드"),
    ("EMB", "신흥국 채권"),
    ("GLD", "금"),
    ("DBC", "원자재"),
    ("USO", "원유"),
    ("DBA", "농산물"),
    ("UUP", "달러"),
    ("FXY", "엔화"),
    ("DBMF", "관리선물"),
    ("BTC/USD", "비트코인"),
]

# 비교 대상. 앞서 쓴 조합과 단일 자산.
COMPARE = [
    (["SPY", "QQQ", "IWM", "EEM", "GLD", "SLV", "TLT", "UUP", "069500", "BTC/USD"],
     "이전 10자산"),
]


def rets(store: PriceStore, sym: str) -> Dict[str, float]:
    b = store._all_bars(sym)
    return {b[i].date: b[i].close / b[i - 1].close - 1
            for i in range(1, len(b)) if b[i - 1].close}


def corr(a: List[float], b: List[float]) -> float:
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def avg_corr(series: Dict[str, Dict[str, float]], syms: List[str],
             lo: str, hi: str) -> Tuple[float, float]:
    """평균 쌍상관과 평균 변동성."""
    cs, vols = [], []
    for i, a in enumerate(syms):
        va = [v for d, v in series[a].items() if lo <= d <= hi]
        if len(va) > 100:
            vols.append(st.pstdev(va) * math.sqrt(TRADING_DAYS))
        for b in syms[i + 1:]:
            days = sorted(set(series[a]) & set(series[b]))
            days = [d for d in days if lo <= d <= hi]
            if len(days) < 200:
                continue
            cs.append(corr([series[a][d] for d in days],
                           [series[b][d] for d in days]))
    return (st.mean(cs) if cs else 0.0), (st.mean(vols) if vols else 0.0)


def run(series: Dict[str, Dict[str, float]], syms: List[str],
        lo: str, hi: str, calendar: Optional[List[str]] = None) -> Optional[Dict[str, float]]:
    """그날 존재하는 자산에만 균등 배분하고 REBAL마다 되맞춘다.

    달력을 반드시 고정해야 한다. 모든 자산의 날짜를 합집합으로 쓰면
    주말에는 비트코인만 거래되므로 포트폴리오가 그날 100% 비트코인이 된다.
    실제로 그렇게 재보니 최대낙폭이 -65%로 나왔다. 미국 거래일을 기준
    달력으로 삼고 그날 값이 있는 자산만 담는다.
    """
    days = [d for d in (calendar or sorted(series[syms[0]])) if lo <= d <= hi]
    if len(days) < 200:
        return None
    held: Dict[str, float] = {}
    eq, peak, mdd, path = 1.0, 1.0, 0.0, []
    for k, d in enumerate(days):
        avail = [s for s in syms if d in series[s]]
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
    yrs = len(path) / TRADING_DAYS
    sd = st.pstdev(path)
    return {"cagr": (eq ** (1 / yrs) - 1) * 100 if yrs > 0 and eq > 0 else -100,
            "sharpe": st.mean(path) / sd * math.sqrt(TRADING_DAYS) if sd else 0,
            "mdd": mdd * 100, "n": len(path)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))

    uni = [(s, n) for s, n in UNIVERSE if store.has(s)]
    syms = [s for s, _ in uni]
    all_syms = set(syms) | {s for grp, _ in COMPARE for s in grp} | {"SPY", "QQQ", "069500"}
    series = {s: rets(store, s) for s in all_syms if store.has(s)}

    print(f"자산군 {len(uni)}개")
    for s, n in uni:
        first = min(series[s]) if s in series else "-"
        print(f"  {s:<9}{n:<14}{first}~")

    print(f"\n{'='*70}\n구간별 평균 쌍상관과 변동성\n")
    print(f"  {'조합':<16}{'구간':<6}{'평균 ρ':>9}{'평균 σ':>9}{'상한 σ²(1-ρ)/4':>16}")
    print("  " + "-" * 58)
    for grp, label in [(syms, "자산군 21개")] + [(g, l) for g, l in COMPARE]:
        g = [s for s in grp if s in series]
        for pname, lo, hi in PERIODS:
            rho, sig = avg_corr(series, g, lo, hi)
            print(f"  {label:<16}{pname:<6}{rho:>+8.2f}{sig*100:>8.1f}%"
                  f"{sig*sig*(1-rho)/4*100:>14.2f}%")
        print()

    calendar = sorted(series["SPY"]) if "SPY" in series else None
    print(f"{'='*70}\n성과  (미국 거래일 기준)\n")
    for pname, lo, hi in PERIODS:
        print(f"  === {pname} ({lo[:7]}~{hi[:7]})")
        print(f"  {'전략':<20}{'CAGR':>9}{'샤프':>8}{'MDD':>9}")
        print("  " + "-" * 46)
        m = run(series, syms, lo, hi, calendar)
        if m:
            print(f"  {'자산군 21개':<20}{m['cagr']:>+8.2f}%{m['sharpe']:>8.2f}"
                  f"{m['mdd']:>+8.1f}%  ←")
        for grp, label in COMPARE:
            g = [s for s in grp if s in series]
            m2 = run(series, g, lo, hi, calendar)
            if m2:
                print(f"  {label:<20}{m2['cagr']:>+8.2f}%{m2['sharpe']:>8.2f}"
                      f"{m2['mdd']:>+8.1f}%")
        for s, label in (("SPY", "(참고) SPY"), ("QQQ", "(참고) QQQ"),
                         ("069500", "(참고) KODEX200")):
            m3 = run(series, [s], lo, hi, calendar)
            if m3:
                print(f"  {label:<20}{m3['cagr']:>+8.2f}%{m3['sharpe']:>8.2f}"
                      f"{m3['mdd']:>+8.1f}%")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
