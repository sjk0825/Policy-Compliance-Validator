"""최악의 해를 더 내린다.

ma200 이진 필터는 22년 최악의 해를 -22.7%에서 -13.9%로 내렸다. 남은
손실이 어디서 오는지를 보면 더 내릴 자리가 보인다. 셋이다.

    헛방      추세선을 오르내리면 싸게 팔고 비싸게 산다. 껐다 켰다가
              전부 아니면 전무이기 때문이다. 등급을 두면 완화된다.
    급락      200일선은 느려서 한 달짜리 폭락을 못 따라간다. 변동성이
              튈 때 노출을 줄이면 신호가 오기 전에 미리 빠진다.
    켤 것이 없음  2022년에는 5종이 동시에 꺼졌다. 그해에 켜져 있던
              자산군(원자재·달러)이 판에 없으면 현금만 남는다.

각각에 장치를 하나씩 대응시켜 겹쳐 본다.

    graded    ma50/100/150/200 중 만족한 개수 비율만큼만 보유 (0~1)
    voltgt    직전 60일 실현변동성이 목표를 넘으면 그 비율만큼 축소
    crash     20일 고점 대비 낙폭이 임계를 넘으면 그 자산은 0
    universe  5종 -> 10종 (IEF DBC UUP EFA EEM 추가)

전부 전일까지의 정보만 쓴다. 2005~2026, 22년.

    python scripts/worst_year_push.py
"""
import argparse
import math
import statistics as st
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from btal_hibl import summarize        # noqa: E402
from trend_longrun import load         # noqa: E402

CASH = "SHY"
FIVE = ["SPY", "QQQ", "TLT", "GLD", "VNQ"]
TEN = FIVE + ["IEF", "DBC", "UUP", "EFA", "EEM"]
LO, HI = "2005-01-03", "2026-12-31"
PERIOD = 21
COST_BP = 10.0
TRADING = 252


def daily(px, cal):
    out = {}
    for s, series in px.items():
        r, prev = {}, None
        for d in cal:
            if d in series:
                if prev is not None:
                    r[d] = series[d] / series[prev] - 1
                prev = d
        out[s] = r
    return out


def ma_grade(px: Dict[str, float], cal: List[str],
             ns=(50, 100, 150, 200)) -> Dict[str, float]:
    """만족한 이동평균 개수의 비율. 전일까지로 판정해 당일 적용."""
    ds = [d for d in cal if d in px]
    sums = {n: 0.0 for n in ns}
    out: Dict[str, float] = {}
    for i, d in enumerate(ds):
        hit, tot = 0, 0
        for n in ns:
            sums[n] += px[d]
            if i >= n:
                sums[n] -= px[ds[i - n]]
            if i >= n - 1:
                tot += 1
                if px[d] > sums[n] / n:
                    hit += 1
        if tot and i + 1 < len(ds):
            out[ds[i + 1]] = hit / tot
    return out


def ma_binary(px, cal, n=200) -> Dict[str, float]:
    g = ma_grade(px, cal, ns=(n,))
    return g


def vol_scale(px: Dict[str, float], cal: List[str], target: float,
              win: int = 60) -> Dict[str, float]:
    ds = [d for d in cal if d in px]
    rs = [px[ds[i]] / px[ds[i - 1]] - 1 for i in range(1, len(ds))]
    out: Dict[str, float] = {}
    for i in range(win, len(rs)):
        v = st.pstdev(rs[i - win:i]) * math.sqrt(TRADING)
        if i + 1 < len(ds):
            out[ds[i + 1]] = min(1.0, target / v) if v > 0 else 1.0
    return out


def crash_gate(px: Dict[str, float], cal: List[str],
               win: int = 20, thr: float = 0.08) -> Dict[str, float]:
    ds = [d for d in cal if d in px]
    out: Dict[str, float] = {}
    for i in range(win, len(ds) - 1):
        hi = max(px[d] for d in ds[i - win:i + 1])
        out[ds[i + 1]] = 0.0 if px[ds[i]] < hi * (1 - thr) else 1.0
    return out


def combine(*maps: Dict[str, float]) -> Dict[str, float]:
    if not maps:
        return {}
    keys = set(maps[0])
    for m in maps[1:]:
        keys &= set(m)
    return {d: math.prod(m[d] for m in maps) for d in keys}


def one_path(rets, exp, days, base, offset) -> List[float]:
    held: Dict[str, float] = {}
    out: List[float] = []
    for k, d in enumerate(days):
        avail = [s for s in list(base) + [CASH] if d in rets.get(s, {})]
        aset = set(avail)
        if not avail:
            continue
        if held:
            out.append(sum(w * rets[s][d] for s, w in held.items() if s in aset))
            g = {s: (w * (1 + rets[s][d]) if s in aset else w)
                 for s, w in held.items()}
            t = sum(g.values())
            if t > 0:
                held = {s: v / t for s, v in g.items()}
        if not held or (k - offset) % PERIOD == 0:
            tgt: Dict[str, float] = {}
            for s, w in base.items():
                if s not in aset:
                    continue
                e = exp.get(s, {}).get(d, 1.0)
                if e > 0:
                    tgt[s] = tgt.get(s, 0) + w * e
                if e < 1 and CASH in aset:
                    tgt[CASH] = tgt.get(CASH, 0) + w * (1 - e)
            tw = sum(tgt.values())
            tgt = {s: v / tw for s, v in tgt.items()} if tw > 0 else {}
            turn = sum(abs(tgt.get(s, 0) - held.get(s, 0))
                       for s in set(tgt) | set(held))
            if out:
                out[-1] -= turn * COST_BP / 10000
            held = tgt
    return out


def run(rets, exp, cal, base, lo, hi, min_days=60) -> Optional[Dict]:
    days = [d for d in cal if lo <= d <= hi]
    paths = [p for p in (one_path(rets, exp, days, base, o)
                         for o in range(PERIOD)) if len(p) >= min_days]
    if not paths:
        return None
    n = min(len(p) for p in paths)
    return summarize([st.mean([p[i] for p in paths]) for i in range(n)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-vol", type=float, default=0.12)
    args = ap.parse_args()
    px = load()
    cal = sorted(px["SPY"])
    rets = daily(px, cal)
    years = list(range(2005, 2027))

    def exps(universe, kind) -> Dict[str, Dict[str, float]]:
        out = {}
        for s in universe:
            if kind == "none":
                out[s] = {}
            elif kind == "ma200":
                out[s] = ma_binary(px[s], cal, 200)
            elif kind == "graded":
                out[s] = ma_grade(px[s], cal)
            elif kind == "graded+vol":
                out[s] = combine(ma_grade(px[s], cal),
                                 vol_scale(px[s], cal, args.target_vol))
            elif kind == "graded+vol+crash":
                out[s] = combine(ma_grade(px[s], cal),
                                 vol_scale(px[s], cal, args.target_vol),
                                 crash_gate(px[s], cal))
        return out

    CASES = [("5종", FIVE, "none"), ("5종", FIVE, "ma200"),
             ("5종", FIVE, "graded"), ("5종", FIVE, "graded+vol"),
             ("10종", TEN, "none"), ("10종", TEN, "ma200"),
             ("10종", TEN, "graded"), ("10종", TEN, "graded+vol"),
             ("10종", TEN, "graded+vol+crash")]

    print(f"2005~2026, 21일 트랜치, 비용 {COST_BP:.0f}bp, 현금 {CASH}, "
          f"목표변동성 {args.target_vol*100:.0f}%\n")
    print(f"  {'판':<6}{'장치':<20}{'CAGR':>9}{'샤프':>7}{'변동성':>8}{'MDD':>9}"
          f"{'최악의 해':>10}{'마이너스 해':>12}")
    print("  " + "-" * 82)
    keep = {}
    for uni_label, uni, kind in CASES:
        base = {s: 1 / len(uni) for s in uni}
        exp = exps(uni, kind)
        m = run(rets, exp, cal, base, LO, HI)
        ys = {}
        for y in years:
            a = run(rets, exp, cal, base, f"{y}-01-01", f"{y}-12-31", min_days=150)
            if a:
                ys[y] = a["total"]
        neg = sum(1 for v in ys.values() if v < 0)
        keep[(uni_label, kind)] = ys
        print(f"  {uni_label:<6}{kind:<20}{m['cagr']:>+8.2f}%{m['sharpe']:>7.2f}"
              f"{m['vol']:>7.1f}%{m['mdd']:>+8.1f}%{min(ys.values()):>+9.1f}%"
              f"{neg:>7}/{len(ys)}회")

    print(f"\n\n연도별 (%)\n")
    print(f"  {'':<24}" + "".join(f"{y%100:>6}" for y in years))
    print("  " + "-" * (24 + 6 * len(years)))
    for k in [("5종", "none"), ("5종", "ma200"), ("10종", "ma200"),
              ("10종", "graded"), ("10종", "graded+vol"),
              ("10종", "graded+vol+crash")]:
        ys = keep[k]
        print(f"  {k[0]+' '+k[1]:<24}"
              + "".join(f"{ys.get(y, float('nan')):>+6.1f}" for y in years))
    return 0


if __name__ == "__main__":
    sys.exit(main())
