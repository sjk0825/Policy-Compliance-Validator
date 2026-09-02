"""떨어진 것을 더 산다. 강도를 조절해서.

균등 되맞춤은 이미 "떨어진 것을 사는" 규칙이다. 다만 1/N까지만 되돌린다.
더 사면 어떤가. 강도 k로 기울인다.

    w_i  ∝  (1/N) * exp(-k * z_i)      z_i = 직전 L일 수익률의 표준화 값

    k > 0   떨어진 것을 더 산다 (역추세)
    k = 0   균등 되맞춤. 지금 쓰는 것
    k < 0   오른 것을 더 산다 (모멘텀)

rebal_direction.py는 7종에서 equal/hold/momentum/top3/amplify를 비교했고
buy_the_dip.py는 개별 자산의 하루 뒤를 셌다. 여기서는 강도를 연속으로
바꿔가며 최적점이 어디인지, 그 최적점이 구간을 바꿔도 유지되는지를 본다.
14종 + ma200 필터 위에 얹는다.

되돌림이 있는지도 여러 기간에서 다시 잰다. 21일 하나만 보고 없다고
결론지었을 수 있다.

    python scripts/contrarian_tilt.py
"""
import argparse
import math
import statistics as st
import sys
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import PriceStore                          # noqa: E402
from btal_hibl import closes, summarize                # noqa: E402
from worst_year_push import ma_grade, daily            # noqa: E402

CORE = ["SPY", "QQQ", "069500", "VNQ", "TLT", "IEF", "GLD", "SLV",
        "DBC", "XLE", "XLU", "EFA", "EEM", "BTC/USD"]
CASH = "BIL"
TRADING = 252
COST_BP = 10.0
OFFSETS = 14


def trail(px, cal) -> Dict[int, Dict[str, Dict[str, float]]]:
    """전일까지의 L일 수익률. 당일은 안 쓴다."""
    out = {}
    for L in (5, 21, 63, 126, 252):
        m = {}
        for s in CORE:
            ds = [d for d in cal if d in px[s]]
            r = {}
            for i in range(L, len(ds) - 1):
                r[ds[i + 1]] = px[s][ds[i]] / px[s][ds[i - L]] - 1
            m[s] = r
        out[L] = m
    return out


def tilt_weights(tr: Dict[str, Dict[str, float]], d: str,
                 avail: List[str], k: float) -> Dict[str, float]:
    if k == 0:
        return {s: 1 / len(avail) for s in avail}
    vals = {s: tr[s][d] for s in avail if d in tr[s]}
    if len(vals) < 3:
        return {s: 1 / len(avail) for s in avail}
    mu, sd = st.mean(vals.values()), st.pstdev(vals.values())
    if sd == 0:
        return {s: 1 / len(avail) for s in avail}
    w = {s: math.exp(max(-3.0, min(3.0, -k * (v - mu) / sd))) for s, v in vals.items()}
    for s in avail:
        w.setdefault(s, 1.0)
    t = sum(w.values())
    return {s: v / t for s, v in w.items()}


def one_path(rets, exp, tr, days, k, rebal, sig_every, offset) -> List[float]:
    sleeve: Dict[str, float] = {}
    inner: Dict[str, float] = {}
    out: List[float] = []
    for i, d in enumerate(days):
        avail = [s for s in CORE if d in rets.get(s, {})]
        if not avail or d not in rets.get(CASH, {}):
            continue
        aset = set(avail)
        if sleeve:
            r = 0.0
            grow = {}
            for s, w in sleeve.items():
                if s in aset:
                    a = inner.get(s, 1.0)
                    rr = a * rets[s][d] + (1 - a) * rets[CASH][d]
                    r += w * rr
                    grow[s] = w * (1 + rr)
                    if 1 + rr != 0:
                        inner[s] = a * (1 + rets[s][d]) / (1 + rr)
                else:
                    grow[s] = w
            out.append(r)
            t = sum(grow.values())
            if t > 0:
                sleeve = {s: v / t for s, v in grow.items()}
        traded = 0.0
        if not sleeve or i % sig_every == 0:
            for s in avail:
                tgt = exp.get(s, {}).get(d, 1.0)
                traded += 2 * sleeve.get(s, 0) * abs(tgt - inner.get(s, tgt))
                inner[s] = tgt
        if not sleeve or (aset - set(sleeve)) or (i - offset) % rebal == 0:
            tgt = tilt_weights(tr, d, avail, k)
            traded += sum(abs(tgt.get(s, 0) - sleeve.get(s, 0))
                          for s in set(tgt) | set(sleeve))
            sleeve = tgt
            for s in avail:
                inner.setdefault(s, exp.get(s, {}).get(d, 1.0))
        if traded and out:
            out[-1] -= traded * COST_BP / 10000
    return out


def run(rets, exp, tr, cal, lo, hi, k, rebal=126, sig=21, min_days=60):
    days = [d for d in cal if lo <= d <= hi]
    offs = [round(i * rebal / OFFSETS) for i in range(min(rebal, OFFSETS))]
    paths = [p for p in (one_path(rets, exp, tr, days, k, rebal, sig, o)
                         for o in offs) if len(p) >= min_days]
    if not paths:
        return None
    n = min(len(p) for p in paths)
    return summarize([st.mean([p[i] for p in paths]) for i in range(n)])


def main() -> int:
    ap = argparse.ArgumentParser()
    args = ap.parse_args()
    store = PriceStore(Path("fixtures/wide"))
    cal = sorted(closes(store, "SPY"))
    px = {s: closes(store, s) for s in CORE + [CASH]}
    rets = daily(px, cal)
    exp = {s: ma_grade(px[s], cal, ns=(200,)) for s in CORE}
    TR = trail(px, cal)

    LO, HI = "2012-05-07", "2026-12-31"
    SPLIT = "2019-12-31"
    KS = [-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0, 2.0]

    print("14종 + ma200 / 신호21 / 되맞춤126,  2012-05~2026\n")
    print("k>0 = 떨어진 것을 더 산다,  k=0 = 균등 되맞춤,  k<0 = 오른 것을 더 산다\n")
    for L in (5, 21, 63, 126, 252):
        print(f"\n  기준 기간 {L}일\n")
        print(f"  {'k':>7}{'CAGR':>10}{'샤프':>8}{'MDD':>9}{'최악의 해':>10}"
              f"{'│ 전반 샤프':>14}{'후반 샤프':>11}")
        print("  " + "-" * 70)
        for k in KS:
            m = run(rets, exp, TR[L], cal, LO, HI, k)
            if not m:
                continue
            ys = [a["total"] for y in range(2013, 2027)
                  if (a := run(rets, exp, TR[L], cal, f"{y}-01-01",
                               f"{y}-12-31", k, min_days=150))]
            a1 = run(rets, exp, TR[L], cal, LO, SPLIT, k)
            a2 = run(rets, exp, TR[L], cal, "2020-01-01", HI, k)
            tag = "  ← 지금" if k == 0 else ""
            print(f"  {k:>+7.2f}{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}"
                  f"{m['mdd']:>+8.1f}%{min(ys):>+9.1f}%"
                  f"{a1['sharpe']:>13.2f}{a2['sharpe']:>11.2f}{tag}")

    print("\n\n되돌림을 기간별로 다시 — 베타 맞춘 짝의 스프레드\n")
    syms = [e for e in store._meta if store._meta[e].group in ("us_etf", "kr_etf")]
    px2 = {s: closes(store, s) for s in syms}
    r2 = daily(px2, cal)
    days = [d for d in cal if LO <= d <= HI]
    pairs = []
    for a, b in combinations(sorted(syms), 2):
        common = [d for d in days if d in r2.get(a, {}) and d in r2.get(b, {})]
        if len(common) < 2500:
            continue
        pairs.append((a, b, [r2[a][d] - r2[b][d] for d in common]))
    print(f"  짝 {len(pairs)}개\n")
    print(f"  {'기간':<10}{'회귀계수 중앙':>14}{'25%':>9}{'75%':>9}"
          f"{'음수 비율':>11}")
    print("  " + "-" * 54)
    for h in (5, 21, 63, 126, 252):
        cs = []
        for _, _, sp in pairs:
            blocks = [sum(sp[i:i + h]) for i in range(0, len(sp) - h, h)]
            if len(blocks) < 12:
                continue
            cs.append(st.correlation(blocks[:-1], blocks[1:]))
        cs.sort()
        q = lambda p: cs[min(len(cs) - 1, int(len(cs) * p))]
        print(f"  {h:<10}{st.median(cs):>+13.3f}{q(.25):>+9.3f}{q(.75):>+9.3f}"
              f"{sum(1 for v in cs if v < 0)/len(cs)*100:>10.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
