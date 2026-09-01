"""BTAL과 HIBL은 상관이 -0.78인데 왜 위기에 같이 잃는가.

두 자산의 방향은 실제로 반대다. 위기 구간에서 BTAL은 오르고 HIBL은
떨어진다. 그런데도 50:50이 SPY보다 크게 잃는 이유를 네 갈래로 나눠 본다.

    1. 크기가 다르다      같은 1원이 만드는 손익의 폭이 자산마다 다르다
    2. 되맞춤이 역풍이다   추세 구간에서 떨어지는 쪽을 계속 사들인다
    3. 3배가 감쇠한다     일간 3배는 변동성이 커질수록 누적 3배에 못 미친다
    4. 헤지의 상한이 낮다  시장중립 상품은 시장이 빠지는 만큼 벌지 않는다

    python scripts/why_crisis.py --data fixtures/wide
"""
import argparse
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import PriceStore            # noqa: E402
from btal_hibl import (closes, daily_returns, one_path,   # noqa: E402
                       summarize, tranche, CRISES)


def window(rets, sym, days) -> List[float]:
    return [rets[sym][d] for d in days if d in rets[sym]]


def cum(rs: List[float]) -> float:
    e = 1.0
    for r in rs:
        e *= (1 + r)
    return (e - 1) * 100


def beta(rets, a: str, b: str, days) -> float:
    xs = [(rets[a][d], rets[b][d]) for d in days
          if d in rets[a] and d in rets[b]]
    ra = [x for x, _ in xs]
    rb = [y for _, y in xs]
    var = st.pvariance(rb)
    return st.covariance(ra, rb) * (len(rb) - 1) / len(rb) / var if var else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))
    cal = sorted(closes(store, "SPY"))
    px = {s: closes(store, s) for s in ("BTAL", "HIBL", "SPHB", "SPY")}
    rets = daily_returns(px, cal)

    LO, HI = "2019-11-08", "2026-12-31"
    full = [d for d in cal if LO <= d <= HI]

    print("1. 크기가 다르다 — 같은 1원이 만드는 폭\n")
    print(f"  {'':<8}{'연변동성':>10}{'SPY 베타':>11}{'하루 최악':>11}"
          f"{'위험기여(50:50)':>17}")
    print("  " + "-" * 58)
    vols = {}
    for s in ("BTAL", "HIBL", "SPY"):
        r = window(rets, s, full)
        vols[s] = st.pstdev(r) * math.sqrt(252) * 100
        print(f"  {s:<8}{vols[s]:>9.1f}%{beta(rets, s, 'SPY', full):>+11.2f}"
              f"{min(r)*100:>+10.1f}%", end="")
        print(f"{'':>17}" if s == "SPY" else "")
    # 50:50의 변동성 중 각 다리가 만든 몫
    ra = window(rets, "BTAL", full)
    rb = window(rets, "HIBL", full)
    n = min(len(ra), len(rb))
    ra, rb = ra[:n], rb[:n]
    port = [0.5 * x + 0.5 * y for x, y in zip(ra, rb)]
    vp = st.pvariance(port)
    ca = 0.5 * st.covariance(ra, port) * (n - 1) / n / vp
    cb = 0.5 * st.covariance(rb, port) * (n - 1) / n / vp
    print(f"\n  50:50 포트폴리오 변동성 {st.pstdev(port)*math.sqrt(252)*100:.1f}%"
          f" 중  BTAL {ca*100:.0f}%  HIBL {cb*100:.0f}%")
    print(f"  → 돈으로는 반반이지만 위험으로는 {cb/(ca+cb)*100:.0f}%가 HIBL이다.")
    print(f"  → 변동성을 같게 맞추는 비중은 "
          f"BTAL {vols['HIBL']/(vols['BTAL']+vols['HIBL'])*100:.0f}% / "
          f"HIBL {vols['BTAL']/(vols['BTAL']+vols['HIBL'])*100:.0f}%.")

    print("\n\n2. 위기 구간 손익 분해 (되맞춤 없이, 산술)\n")
    print(f"  {'구간':<14}{'BTAL':>9}{'HIBL':>10}{'50:50 기여':>14}"
          f"{'실제 되맞춤':>13}{'되맞춤 몫':>11}")
    print("  " + "-" * 72)
    for name, lo, hi in CRISES:
        if lo < LO:
            continue
        days = [d for d in cal if lo <= d <= hi]
        a, b = cum(window(rets, "BTAL", days)), cum(window(rets, "HIBL", days))
        bh = tranche(rets, cal, {"BTAL": .5, "HIBL": .5}, lo, hi,
                     period=0, min_days=20)
        rb_ = tranche(rets, cal, {"BTAL": .5, "HIBL": .5}, lo, hi, min_days=20)
        print(f"  {name:<14}{a:>+8.1f}%{b:>+9.1f}%{bh['total']:>+13.1f}%"
              f"{rb_['total']:>+12.1f}%{rb_['total']-bh['total']:>+10.1f}%p")
    print("\n  BTAL은 올랐다. 다만 HIBL이 잃은 폭의 1/8~1/5을 벌었을 뿐이고,")
    print("  되맞춤은 추세 구간에서 떨어지는 쪽을 계속 사들여 손실을 더 키웠다.")

    print("\n\n3. 3배의 감쇠 — HIBL vs SPHB를 매일 3배로 굴린 값\n")
    print(f"  {'구간':<14}{'SPHB(1배)':>12}{'단순 3배':>11}"
          f"{'일간 3배 이론':>14}{'HIBL 실제':>12}")
    print("  " + "-" * 64)
    for name, lo, hi in CRISES:
        days = [d for d in cal if lo <= d <= hi]
        s1 = window(rets, "SPHB", days)
        if not s1:
            continue
        one = cum(s1)
        daily3 = cum([3 * r for r in s1])
        act = cum(window(rets, "HIBL", days)) if any(
            d in rets["HIBL"] for d in days) else None
        print(f"  {name:<14}{one:>+11.1f}%{one*3:>+10.1f}%{daily3:>+13.1f}%"
              + (f"{act:>+11.1f}%" if act is not None else f"{'-':>12}"))
    print("\n  일간 3배는 하락이 이어질수록 누적 3배보다 덜 빠지지만(복리 바닥),")
    print("  변동성이 클수록 반등 국면에서 되돌리지 못한다. 왕복하면 손해다.")

    print("\n\n4. 헤지의 상한 — 시장이 빠질 때 BTAL이 버는 양\n")
    print(f"  {'구간':<14}{'SPY':>9}{'BTAL':>9}{'헤지비율':>11}")
    print("  " + "-" * 44)
    for name, lo, hi in CRISES:
        days = [d for d in cal if lo <= d <= hi]
        sp, bt = cum(window(rets, "SPY", days)), cum(window(rets, "BTAL", days))
        print(f"  {name:<14}{sp:>+8.1f}%{bt:>+8.1f}%{bt/-sp:>10.2f}배")
    print("\n  BTAL은 시장이 1 빠질 때 0.2~1.5를 번다. 3배 상품이 3 빠지는 것을")
    print("  같은 금액으로 덮으려면 원리상 불가능한 배율이 필요하다.")

    print("\n\n5. 그래서 변동성을 맞추면 — 위기 구간 (%)\n")
    mixes = [("BTAL50 / HIBL50", {"BTAL": .5, "HIBL": .5}),
             ("BTAL70 / HIBL30", {"BTAL": .7, "HIBL": .3}),
             ("BTAL82 / HIBL18", {"BTAL": .82, "HIBL": .18}),
             ("SPY 100%", {"SPY": 1.0})]
    live = [c for c in CRISES if c[1] >= LO]
    print(f"  {'조합':<20}" + "".join(f"{c[0]:>14}" for c in live)
          + f"{'CAGR':>10}{'샤프':>8}{'MDD':>9}")
    print("  " + "-" * 79)
    for label, w in mixes:
        cells = [f"{tranche(rets, cal, w, lo, hi, min_days=20)['total']:+.1f}%"
                 for _, lo, hi in live]
        m = tranche(rets, cal, w, LO, HI)
        print(f"  {label:<20}" + "".join(f"{c:>14}" for c in cells)
              + f"{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}{m['mdd']:>+8.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
