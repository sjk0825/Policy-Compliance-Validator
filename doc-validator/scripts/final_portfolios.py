"""최종 후보들을 트랜치로 다시 잰다.

되맞춤 날짜 하나로 CAGR이 2%p, 샤프가 0.15 벌어진다는 것이 확인됐으므로,
특정 시작일 하나로 낸 결과는 그 폭만큼 믿을 수 없다. 트랜치는 자금을
21등분해 각각 다른 날에 되맞추므로 그 운이 평균으로 씻긴다. 회전율은
월 1회와 같다.

후보는 다섯이다.

    A  7종만
    B  A + DBMF 20%
    C  A + DBMF 40% + 에너지 15% + 원자재 10%   2022년을 보고 만든 것
    D  A + DBMF 20% + BTAL 10%
    E  A + DBMF 15% + BTAL 10% + 달러 10%

C는 사후 선택임을 알면서 비교를 위해 남긴다. 다른 위기 구간에서 어떻게
되는지가 그 성격을 드러낸다.

    python scripts/final_portfolios.py --data fixtures/wide
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
PERIOD = 21
COST_BP = 10.0

CRISES = [("2020 코로나", "2020-02-19", "2020-03-23"),
          ("2022 인플레", "2022-01-01", "2022-10-12")]


def closes(store: PriceStore, sym: str) -> Dict[str, float]:
    return {b.date: b.close for b in store._all_bars(sym)}


def build(hedges: Dict[str, float]) -> Dict[str, float]:
    h = sum(hedges.values())
    w = {s: (1 - h) / len(SEVEN) for s in SEVEN}
    for s, v in hedges.items():
        w[s] = w.get(s, 0) + v
    return w


def one_path(px, cal, weights, lo, hi, offset) -> Optional[List[float]]:
    days = [d for d in cal if lo <= d <= hi]
    held: Dict[str, float] = {}
    out: List[float] = []
    for k, d in enumerate(days):
        i = cal.index(d)
        prev = cal[i - 1] if i > 0 else None
        avail = [s for s in weights if s in px and d in px[s] and prev and prev in px[s]]
        avail_set = set(avail)
        if not avail:
            continue
        if held:
            out.append(sum(held.get(s, 0) * (px[s][d] / px[s][prev] - 1) for s in avail))
            # 휴장 종목은 보유를 유지한다. avail만 순회하면 그날 시장이
            # 닫힌 자산을 전량 매도해 나머지에 분배하는 셈이 된다.
            g = {s: (w * (px[s][d] / px[s][prev]) if s in avail_set else w)
                 for s, w in held.items()}
            tot = sum(g.values())
            if tot > 0:
                held = {s: v / tot for s, v in g.items()}
        if not held or (k - offset) % PERIOD == 0:
            w = {s: weights[s] for s in avail}
            tw = sum(w.values())
            target = {s: v / tw for s, v in w.items()} if tw > 0 else {}
            turn = sum(abs(target.get(s, 0) - held.get(s, 0))
                       for s in set(target) | set(held))
            if out:
                out[-1] -= turn * COST_BP / 10000
            held = target
    return out


def tranche(store, cal, weights, lo, hi, min_days=60) -> Optional[Dict[str, float]]:
    """21개 시작일의 일별 수익률을 균등 평균한다."""
    px = {s: closes(store, s) for s in weights if store.has(s)}
    paths = [p for p in (one_path(px, cal, weights, lo, hi, o) for o in range(PERIOD))
             if p and len(p) >= min_days]
    if not paths:
        return None
    n = min(len(p) for p in paths)
    avg = [st.mean([p[i] for p in paths]) for i in range(n)]
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in avg:
        eq *= (1 + x)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    sd = st.pstdev(avg)
    yrs = len(avg) / TRADING
    return {"cagr": (eq ** (1 / yrs) - 1) * 100 if eq > 0 and yrs > 0.2 else None,
            "sharpe": st.mean(avg) / sd * math.sqrt(TRADING) if sd else 0,
            "mdd": mdd * 100, "total": (eq - 1) * 100, "final": eq}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))
    cal = sorted(closes(store, "SPY"))

    CANDS = [
        ("A  7종만", build({})),
        ("B  +DBMF20", build({"DBMF": 0.20})),
        ("C  +DBMF40 에너지15 원자재10", build({"DBMF": 0.40, "XLE": 0.15, "DBC": 0.10})),
        ("D  +DBMF20 BTAL10", build({"DBMF": 0.20, "BTAL": 0.10})),
        ("E  +DBMF15 BTAL10 달러10", build({"DBMF": 0.15, "BTAL": 0.10, "UUP": 0.10})),
    ]
    LO, HI = "2019-06-01", "2026-12-31"

    print(f"트랜치 적용 (자금 21등분, 각 조각을 21일마다 되맞춤, 비용 {COST_BP:.0f}bp)")
    print(f"기간 {LO[:7]} ~ {HI[:7]}  (DBMF 상장 이후 7.3년)\n")
    print(f"  {'조합':<28}{'CAGR':>9}{'샤프':>8}{'MDD':>9}{'최악의 해':>10}{'1억 →':>10}")
    print("  " + "-" * 76)
    results = {}
    for label, w in CANDS:
        m = tranche(store, cal, w, LO, HI)
        if not m:
            continue
        worst = 99.0
        for y in range(2020, 2027):
            a = tranche(store, cal, w, f"{y}-01-01", f"{y}-12-31", min_days=150)
            if a and a["total"] is not None:
                worst = min(worst, a["total"])
        results[label] = m
        print(f"  {label:<28}{m['cagr']:>+8.2f}%{m['sharpe']:>8.2f}{m['mdd']:>+8.1f}%"
              f"{worst:>+9.1f}%{m['final']:>8.2f}억")

    print(f"\n  연도별 수익률 (%)\n")
    print(f"  {'조합':<28}" + "".join(f"{y:>8}" for y in range(2020, 2027)))
    print("  " + "-" * 84)
    for label, w in CANDS:
        cells = []
        for y in range(2020, 2027):
            a = tranche(store, cal, w, f"{y}-01-01", f"{y}-12-31", min_days=150)
            cells.append(f"{a['total']:+.1f}" if a else "-")
        print(f"  {label:<28}" + "".join(f"{c:>8}" for c in cells))

    print(f"\n  위기 구간 수익률 (%)\n")
    print(f"  {'조합':<28}" + "".join(f"{c[0]:>14}" for c in CRISES))
    print("  " + "-" * 60)
    for label, w in CANDS:
        cells = []
        for _, lo, hi in CRISES:
            a = tranche(store, cal, w, lo, hi, min_days=20)
            cells.append(f"{a['total']:+.1f}%" if a else "-")
        print(f"  {label:<28}" + "".join(f"{c:>14}" for c in cells))

    print(f"\n\n  헤지 없이 긴 구간에서 (2010~2026, DBMF 이전 포함)\n")
    print(f"  {'조합':<28}{'CAGR':>9}{'샤프':>8}{'MDD':>9}")
    print("  " + "-" * 56)
    for label, w in [("A  7종만", build({})),
                     ("C' 에너지15 원자재10", build({"XLE": 0.15, "DBC": 0.10})),
                     ("D' BTAL10", build({"BTAL": 0.10})),
                     ("E' BTAL10 달러10", build({"BTAL": 0.10, "UUP": 0.10}))]:
        m = tranche(store, cal, w, "2012-01-01", "2026-12-31")
        if m:
            print(f"  {label:<28}{m['cagr']:>+8.2f}%{m['sharpe']:>8.2f}{m['mdd']:>+8.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
