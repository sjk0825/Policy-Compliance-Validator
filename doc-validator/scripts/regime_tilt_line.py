"""선 위냐 아래냐로 역추세와 추세를 바꾼다. 그리고 수평선도 써 본다.

두 가지를 시험한다.

    1) 자산마다 제 이동평균 위/아래를 보고 기울기를 바꾼다
       선 아래  떨어진 것을 산다 (역추세)
       선 위    오른 것을 산다 (추세)
       부호를 미리 정하지 않고 네 조합을 모두 잰다

    2) 지금까지 쓴 선은 전부 이동평균이었다. 수평선(N일 최고/최저,
       돈치안 채널)으로 바꾸면 다른지 본다. 이동평균은 값이 계속
       움직이므로 횡보 구간에서 자주 교차하고, 수평선은 갱신되기
       전까지 고정이라 덜 교차한다.

기존 ma200 필터는 "선 아래면 현금"이라 1)의 극단이다. 그래서 필터를 뺀
판과 얹은 판을 나란히 놓는다.

    python scripts/regime_tilt_line.py
"""
import argparse
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import PriceStore                       # noqa: E402
from btal_hibl import closes, summarize             # noqa: E402
from worst_year_push import ma_grade, daily         # noqa: E402
import contrarian_tilt as CT                        # noqa: E402

CORE, CASH = CT.CORE, CT.CASH
LO, HI, SPLIT = "2012-05-07", "2026-12-31", "2019-12-31"
TRADING, PERIOD, SIG, COST_BP = 252, 126, 21, 10.0
OFFS = 14


def above_ma(px, cal, w) -> Dict[str, bool]:
    ds = [d for d in cal if d in px]
    out, run = {}, 0.0
    for i, d in enumerate(ds):
        run += px[d]
        if i >= w:
            run -= px[ds[i - w]]
        if i >= w - 1 and i + 1 < len(ds):
            out[ds[i + 1]] = px[d] > run / w
    return out


def donchian(px, cal, w) -> Dict[str, float]:
    """N일 최고를 넘으면 1, N일 최저를 깨면 0, 사이면 직전 상태 유지."""
    ds = [d for d in cal if d in px]
    out, state = {}, 1.0
    for i in range(w, len(ds) - 1):
        win = [px[x] for x in ds[i - w:i]]
        if px[ds[i]] >= max(win):
            state = 1.0
        elif px[ds[i]] <= min(win):
            state = 0.0
        out[ds[i + 1]] = state
    return out


def one_path(rets, exp, tr, above, days, ka, kb, offset,
             use_filter: bool) -> List[float]:
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
        if not sleeve or i % SIG == 0:
            for s in avail:
                tgt = exp.get(s, {}).get(d, 1.0) if use_filter else 1.0
                traded += 2 * sleeve.get(s, 0) * abs(tgt - inner.get(s, tgt))
                inner[s] = tgt
        if not sleeve or (aset - set(sleeve)) or (i - offset) % PERIOD == 0:
            vals = {s: tr[s][d] for s in avail if d in tr[s]}
            if len(vals) >= 3:
                mu, sd = st.mean(vals.values()), st.pstdev(vals.values())
                wts = {}
                for s in avail:
                    k = ka if above.get(s, {}).get(d, True) else kb
                    z = (vals[s] - mu) / sd if (sd and s in vals) else 0.0
                    wts[s] = math.exp(max(-3.0, min(3.0, -k * z)))
                tot = sum(wts.values())
                tgt = {s: v / tot for s, v in wts.items()}
            else:
                tgt = {s: 1 / len(avail) for s in avail}
            traded += sum(abs(tgt.get(s, 0) - sleeve.get(s, 0))
                          for s in set(tgt) | set(sleeve))
            sleeve = tgt
            for s in avail:
                inner.setdefault(s, exp.get(s, {}).get(d, 1.0) if use_filter else 1.0)
        if traded and out:
            out[-1] -= traded * COST_BP / 10000
    return out


def run(rets, exp, tr, above, cal, ka, kb, use_filter,
        lo=LO, hi=HI, min_days=60) -> Optional[Dict]:
    days = [d for d in cal if lo <= d <= hi]
    offs = [round(i * PERIOD / OFFS) for i in range(OFFS)]
    paths = [p for p in (one_path(rets, exp, tr, above, days, ka, kb, o, use_filter)
                         for o in offs) if len(p) >= min_days]
    if not paths:
        return None
    n = min(len(p) for p in paths)
    m = summarize([st.mean([p[i] for p in paths]) for i in range(n)])
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--line", type=int, default=60)
    args = ap.parse_args()
    store = PriceStore(Path("fixtures/wide"))
    cal = sorted(closes(store, "SPY"))
    px = {s: closes(store, s) for s in CORE + [CASH]}
    rets = daily(px, cal)
    exp = {s: ma_grade(px[s], cal, ns=(200,)) for s in CORE}
    tr = CT.trail(px, cal)[5]
    years = range(2013, 2027)

    def worst(ka, kb, uf, ab):
        vs = []
        for y in years:
            a = run(rets, exp, tr, ab, cal, ka, kb, uf,
                    f"{y}-01-01", f"{y}-12-31", 150)
            if a:
                vs.append(a["total"])
        return min(vs), sum(1 for v in vs if v < 0), len(vs)

    for W in (args.line, 120, 200):
        ab = {s: above_ma(px[s], cal, W) for s in CORE}
        print(f"\n{W}일선 위/아래로 기울기를 바꾼다  "
              f"(k>0 떨어진 것 산다 / k<0 오른 것 산다)\n")
        print(f"  {'선 위 k':>9}{'선 아래 k':>10}{'필터':>7}{'CAGR':>9}{'샤프':>7}"
              f"{'MDD':>9}{'최악의 해':>10}{'마이너스':>8}{'전반':>7}{'후반':>7}")
        print("  " + "-" * 84)
        for uf in (False, True):
            for ka, kb in [(0.0, 0.0), (-0.5, 0.5), (0.5, -0.5),
                           (-0.5, 0.0), (0.0, 0.5), (0.5, 0.0), (0.0, -0.5)]:
                m = run(rets, exp, tr, ab, cal, ka, kb, uf)
                if not m:
                    continue
                w, neg, ny = worst(ka, kb, uf, ab)
                m1 = run(rets, exp, tr, ab, cal, ka, kb, uf, LO, SPLIT)
                m2 = run(rets, exp, tr, ab, cal, ka, kb, uf, "2020-01-01", HI)
                tag = "○" if uf else "×"
                base = "  ← 지금" if (ka == kb == 0.0 and uf) else ""
                print(f"  {ka:>+9.2f}{kb:>+10.2f}{tag:>7}{m['cagr']:>+8.2f}%"
                      f"{m['sharpe']:>7.2f}{m['mdd']:>+8.1f}%{w:>+9.1f}%"
                      f"{neg:>5}/{ny}{m1['sharpe']:>7.2f}{m2['sharpe']:>7.2f}{base}")
            print()


    print(f"\n\n지평선 — 이동평균 대신 돈치안 채널(N일 최고/최저)로 필터\n")
    print(f"  {'필터':<20}{'CAGR':>9}{'샤프':>7}{'MDD':>9}{'최악의 해':>10}"
          f"{'마이너스':>8}{'전반':>7}{'후반':>7}")
    print("  " + "-" * 78)
    flat = {s: {} for s in CORE}
    for lab, e in [("없음", flat),
                   ("ma200 (지금)", {s: ma_grade(px[s], cal, ns=(200,)) for s in CORE}),
                   ("ma100", {s: ma_grade(px[s], cal, ns=(100,)) for s in CORE}),
                   ("돈치안 60일", {s: donchian(px[s], cal, 60) for s in CORE}),
                   ("돈치안 120일", {s: donchian(px[s], cal, 120) for s in CORE}),
                   ("돈치안 200일", {s: donchian(px[s], cal, 200) for s in CORE}),
                   ("돈치안 252일", {s: donchian(px[s], cal, 252) for s in CORE})]:
        ab = {s: {} for s in CORE}
        m = run(rets, e, tr, ab, cal, 0.0, 0.0, True)
        vs = [a["total"] for y in years
              if (a := run(rets, e, tr, ab, cal, 0.0, 0.0, True,
                           f"{y}-01-01", f"{y}-12-31", 150))]
        m1 = run(rets, e, tr, ab, cal, 0.0, 0.0, True, LO, SPLIT)
        m2 = run(rets, e, tr, ab, cal, 0.0, 0.0, True, "2020-01-01", HI)
        print(f"  {lab:<20}{m['cagr']:>+8.2f}%{m['sharpe']:>7.2f}{m['mdd']:>+8.1f}%"
              f"{min(vs):>+9.1f}%{sum(1 for v in vs if v<0):>5}/{len(vs)}"
              f"{m1['sharpe']:>7.2f}{m2['sharpe']:>7.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
