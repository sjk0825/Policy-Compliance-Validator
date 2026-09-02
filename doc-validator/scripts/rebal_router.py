"""주기 변형을 잔뜩 만들고 데이터로 고른다.

되맞춤은 1년 전 기준으로도, 한 달 전 기준으로도 매일 할 수 있다. 신호도
마찬가지다. 그러면 변형이 수십 개 나오고, 그중 어느 것을 쓸지를 데이터가
정하게 하면 되지 않느냐 — 이 물음을 잰다.

    신호 규칙   ma100 ma150 ma200 ma250 mom6 mom12
    신호 주기   21일 63일
    되맞춤 주기  21일 63일 126일 252일
    + 필터 없음 4개
    = 52개

라우터는 판정일마다 직전 구간의 성적을 보고 다음 구간에 쓸 변형을 고른다.
직전 구간까지만 본다.

비교 대상이 중요하다. 최악을 이기는 것은 의미가 없다. 라우팅이 값어치가
있으려면 "전부 균등하게 섞은 것"을 이겨야 한다. 고르는 행위가 아무것도
더하지 못하면 평균이 곧 상한이다. 사후 최선과 사후 최악도 함께 놓아
고를 수 있었던 폭이 얼마였는지 본다.

변형끼리 갈아탈 때는 실제로 포트폴리오가 달라지므로 비용이 든다. 비용
없이도 평균을 못 이기면 결론은 그대로이므로 양쪽을 다 보여준다.

    python scripts/rebal_router.py
"""
import argparse
import math
import statistics as st
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import PriceStore                        # noqa: E402
from btal_hibl import closes, summarize              # noqa: E402
from worst_year_push import ma_grade, daily          # noqa: E402
import rebal_period as RP                            # noqa: E402

CORE = ["SPY", "QQQ", "069500", "VNQ", "TLT", "IEF", "GLD", "SLV",
        "DBC", "XLE", "XLU", "EFA", "EEM", "BTC/USD"]
CASH = "BIL"
LO, HI = "2012-05-07", "2026-12-31"
YEARS = range(2013, 2027)
TRADING = 252
SWITCH_BP = 30.0        # 변형을 갈아탈 때의 편도 비용 가정


def mom_grade(px: Dict[str, float], cal: List[str], months: int) -> Dict[str, float]:
    n = months * 21
    ds = [d for d in cal if d in px]
    return {ds[i + 1]: (1.0 if px[ds[i]] > px[ds[i - n]] else 0.0)
            for i in range(n, len(ds) - 1)}


def build_family(px, cal) -> Dict[str, Dict[str, Dict[str, float]]]:
    fam = {}
    for n in (100, 150, 200, 250):
        fam[f"ma{n}"] = {s: ma_grade(px[s], cal, ns=(n,)) for s in CORE}
    for m in (6, 12):
        fam[f"mom{m}"] = {s: mom_grade(px[s], cal, m) for s in CORE}
    fam["none"] = {s: {} for s in CORE}
    return fam


def series_of(rets, exp, cal, base, rebal, sig_every, offsets) -> Dict[str, float]:
    days = [d for d in cal if LO <= d <= HI]
    offs = [round(i * rebal / offsets) for i in range(min(rebal, offsets))]
    res = [RP.one_path(rets, exp, days, base, CASH, rebal, sig_every, o)
           for o in offs]
    paths = [p for p, _ in res]
    n = min(len(p) for p in paths)
    avg = [st.mean([p[i] for p in paths]) for i in range(n)]
    return dict(zip(days[len(days) - n:], avg))


def stats(series: Dict[str, float], cal: List[str]) -> Dict:
    ds = [d for d in cal if d in series]
    m = summarize([series[d] for d in ds])
    ys = {}
    for y in YEARS:
        r = [series[d] for d in ds if f"{y}-01-01" <= d <= f"{y}-12-31"]
        if len(r) > 150:
            e = 1.0
            for x in r:
                e *= (1 + x)
            ys[y] = (e - 1) * 100
    m["worst"] = min(ys.values()) if ys else None
    m["neg"] = sum(1 for v in ys.values() if v < 0)
    m["nyears"] = len(ys)
    m["years"] = ys
    return m


def route(series: Dict[str, Dict[str, float]], days: List[str],
          lookback: int, reselect: int, top_k: int,
          switch_cost: bool) -> Dict[str, float]:
    names = list(series)
    out: Dict[str, float] = {}
    cur: List[str] = []
    for i, d in enumerate(days):
        if i % reselect == 0 and i >= lookback:
            hist = days[i - lookback:i]          # 직전 구간까지만
            score = {}
            for nm in names:
                r = [series[nm][x] for x in hist if x in series[nm]]
                if len(r) < lookback * 0.6:
                    continue
                sd = st.pstdev(r)
                score[nm] = st.mean(r) / sd * math.sqrt(TRADING) if sd else 0
            if score:
                new = sorted(score, key=score.get, reverse=True)[:top_k]
                if switch_cost and cur and set(new) != set(cur):
                    frac = len(set(new) - set(cur)) / max(len(new), 1)
                    if out and days[i - 1] in out:
                        out[days[i - 1]] -= frac * 2 * SWITCH_BP / 10000
                cur = new
        if cur:
            vals = [series[nm][d] for nm in cur if d in series[nm]]
            if vals:
                out[d] = st.mean(vals)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offsets", type=int, default=14)
    args = ap.parse_args()
    t0 = time.perf_counter()

    store = PriceStore(Path("fixtures/wide"))
    cal = sorted(closes(store, "SPY"))
    px = {s: closes(store, s) for s in CORE + [CASH]}
    rets = daily(px, cal)
    base = {s: 1 / len(CORE) for s in CORE}
    fam = build_family(px, cal)

    print(f"14종 균등, {LO} ~ 2026, 트랜치 오프셋 {args.offsets}개 표집\n")
    print("변형을 만드는 중 …", flush=True)
    series: Dict[str, Dict[str, float]] = {}
    for rule, exp in fam.items():
        sigs = (10 ** 6,) if rule == "none" else (21, 63)
        for se in sigs:
            for rb in (21, 63, 126, 252):
                nm = (f"{rule}/되맞춤{rb}" if rule == "none"
                      else f"{rule}/신호{se}/되맞춤{rb}")
                series[nm] = series_of(rets, exp, cal, base, rb, se, args.offsets)
    days = sorted(set.intersection(*(set(s) for s in series.values())))
    print(f"  {len(series)}개 / {len(days)}일 / {time.perf_counter()-t0:.0f}초\n")

    allst = {nm: stats(s, cal) for nm, s in series.items()}
    best = max(allst, key=lambda n: allst[n]["sharpe"])
    worst = min(allst, key=lambda n: allst[n]["sharpe"])
    eq = {d: st.mean([s[d] for s in series.values() if d in s]) for d in days}

    rows: List[Tuple[str, Dict]] = []
    rows.append(("사후 최선  " + best, allst[best]))
    rows.append(("균등 평균 (52개 전부)", stats(eq, cal)))
    rows.append(("고정 ma200/신호21/되맞춤126",
                 allst["ma200/신호21/되맞춤126"]))
    for lb, rs, k in [(252, 21, 1), (252, 63, 1), (126, 21, 1),
                      (63, 21, 1), (252, 21, 3), (252, 21, 5)]:
        r = route(series, days, lb, rs, k, switch_cost=False)
        rows.append((f"라우팅 lb{lb}/재선택{rs}/top{k}  비용무시", stats(r, cal)))
    for lb, rs, k in [(252, 21, 1), (252, 63, 3)]:
        r = route(series, days, lb, rs, k, switch_cost=True)
        rows.append((f"라우팅 lb{lb}/재선택{rs}/top{k}  전환 {SWITCH_BP:.0f}bp",
                     stats(r, cal)))
    rows.append(("사후 최악  " + worst, allst[worst]))

    print(f"  {'':<40}{'CAGR':>9}{'샤프':>7}{'MDD':>9}{'최악의 해':>10}{'마이너스 해':>12}")
    print("  " + "-" * 88)
    for label, m in rows:
        print(f"  {label:<40}{m['cagr']:>+8.2f}%{m['sharpe']:>7.2f}"
              f"{m['mdd']:>+8.1f}%{m['worst']:>+9.1f}%"
              f"{m['neg']:>7}/{m['nyears']}회")

    print(f"\n\n변형 52개의 분포 (사후)\n")
    sh = sorted(m["sharpe"] for m in allst.values())
    cg = sorted(m["cagr"] for m in allst.values())
    wo = sorted(m["worst"] for m in allst.values())
    def q(v, p):
        return v[min(len(v) - 1, int(len(v) * p))]
    print(f"  {'':<10}{'최소':>10}{'25%':>10}{'중앙':>10}{'75%':>10}{'최대':>10}")
    print("  " + "-" * 60)
    print(f"  {'샤프':<10}{sh[0]:>10.2f}{q(sh,.25):>10.2f}{q(sh,.5):>10.2f}"
          f"{q(sh,.75):>10.2f}{sh[-1]:>10.2f}")
    print(f"  {'CAGR':<10}{cg[0]:>9.2f}%{q(cg,.25):>9.2f}%{q(cg,.5):>9.2f}%"
          f"{q(cg,.75):>9.2f}%{cg[-1]:>9.2f}%")
    print(f"  {'최악의 해':<10}{wo[0]:>9.1f}%{q(wo,.25):>9.1f}%{q(wo,.5):>9.1f}%"
          f"{q(wo,.75):>9.1f}%{wo[-1]:>9.1f}%")

    print(f"\n\n라우터가 고른 것이 다음 구간에 실제로 좋았나"
          f"  (lb252/재선택21/top1)\n")
    hit, tot, gain = 0, 0, []
    for i in range(252, len(days) - 21, 21):
        hist, fwd = days[i - 252:i], days[i:i + 21]
        sc, fw = {}, {}
        for nm, s in series.items():
            r = [s[x] for x in hist if x in s]
            f = [s[x] for x in fwd if x in s]
            if len(r) < 200 or len(f) < 15:
                continue
            sd = st.pstdev(r)
            sc[nm] = st.mean(r) / sd if sd else 0
            fw[nm] = sum(f)
        if not sc:
            continue
        pick = max(sc, key=sc.get)
        med = st.median(fw.values())
        tot += 1
        hit += fw[pick] > med
        gain.append((fw[pick] - med) * 100)
    print(f"  판정 {tot}회 중 중앙값보다 나은 선택 {hit}회 ({hit/tot*100:.1f}%)")
    print(f"  선택의 초과수익 평균 {st.mean(gain):+.3f}%p / 21일"
          f"  (연 {st.mean(gain)*12:+.2f}%p)")
    print(f"  표준오차 {st.pstdev(gain)/math.sqrt(len(gain)):.3f}%p")
    return 0


if __name__ == "__main__":
    sys.exit(main())
