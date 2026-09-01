"""BTAL과 HIBL 둘만으로 되맞춘다.

BTAL은 저베타를 사고 고베타를 파는 시장중립 펀드이고, HIBL은 S&P500
고베타 바스켓의 일간 3배다. 노출 방향이 정면으로 반대이므로 상관이 크게
음수이고, 둘 다 변동성이 크다. 되맞춤이 이득을 내는 조건 — 성격이 반대이고
개별 변동성이 클 것 — 을 가장 극단적으로 갖춘 짝이다.

되맞춤 프리미엄이 실제로 존재하는지, 그것이 3배 상품의 감쇠를 상쇄할
만큼인지를 본다. 비교 대상은 사고 안 파는 것(되맞춤 없음)이다. 둘의
차이가 곧 되맞춤이 만든 몫이다.

HIBL은 2019-11 상장이라 표본이 6.8년이고 하락장이 2020과 2022뿐이다.
같은 구조를 1배 고베타(SPHB)로 바꾸면 2011년까지 올라가므로, 2015년과
2018년을 포함한 긴 구간에서 결론이 유지되는지를 함께 확인한다.

    python scripts/btal_hibl.py --data fixtures/wide
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

TRADING = 252
PERIOD = 21
COST_BP = 10.0

CRISES = [("2020 코로나", "2020-02-19", "2020-03-23"),
          ("2022 인플레", "2022-01-01", "2022-10-12"),
          ("2018 4분기", "2018-10-01", "2018-12-24"),
          ("2015 차이나", "2015-08-01", "2016-02-11")]


def closes(store: PriceStore, sym: str) -> Dict[str, float]:
    return {b.date: b.close for b in store._all_bars(sym)}


def daily_returns(px, cal) -> Dict[str, Dict[str, float]]:
    """달력일 기준 전일 대비 수익률. 그날 시세가 없으면 키가 없다."""
    out: Dict[str, Dict[str, float]] = {}
    for s, series in px.items():
        r: Dict[str, float] = {}
        prev = None
        for d in cal:
            if d in series:
                if prev is not None:
                    r[d] = series[d] / series[prev] - 1
                prev = d
        out[s] = r
    return out


def one_path(rets, days, weights, period: int, offset: int) -> List[float]:
    """offset일부터 period마다 되맞추는 경로의 일별 수익률.

    period가 0이면 처음 한 번만 사고 그대로 둔다.
    """
    syms = [s for s in weights if s in rets]
    held: Dict[str, float] = {}
    out: List[float] = []
    for k, d in enumerate(days):
        avail = [s for s in syms if d in rets[s]]
        if not avail:
            continue
        avail_set = set(avail)
        if held:
            out.append(sum(held.get(s, 0) * rets[s][d] for s in avail))
            # 휴장 종목은 보유를 유지한다. avail만 순회하면 그날 시장이
            # 닫힌 자산을 전량 매도해 나머지에 분배하는 셈이 된다.
            g = {s: (w * (1 + rets[s][d]) if s in avail_set else w)
                 for s, w in held.items()}
            tot = sum(g.values())
            if tot > 0:
                held = {s: v / tot for s, v in g.items()}
        if not held or (period and (k - offset) % period == 0):
            w = {s: weights[s] for s in avail}
            tw = sum(w.values())
            target = {s: v / tw for s, v in w.items()} if tw > 0 else {}
            turn = sum(abs(target.get(s, 0) - held.get(s, 0))
                       for s in set(target) | set(held))
            if out:
                out[-1] -= turn * COST_BP / 10000
            held = target
    return out


def summarize(path: List[float]) -> Dict[str, float]:
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in path:
        eq *= (1 + x)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    sd = st.pstdev(path)
    yrs = len(path) / TRADING
    return {"cagr": (eq ** (1 / yrs) - 1) * 100 if eq > 0 and yrs > 0.2 else None,
            "sharpe": st.mean(path) / sd * math.sqrt(TRADING) if sd else 0,
            "mdd": mdd * 100, "total": (eq - 1) * 100, "final": eq,
            "vol": sd * math.sqrt(TRADING) * 100, "days": len(path)}


def tranche(rets, cal, weights, lo, hi, period=PERIOD, min_days=60) -> Optional[Dict]:
    """period개 시작일의 일별 수익률을 균등 평균한다."""
    days = [d for d in cal if lo <= d <= hi]
    if not period:
        p = one_path(rets, days, weights, 0, 0)
        return summarize(p) if len(p) >= min_days else None
    paths = [p for p in (one_path(rets, days, weights, period, o)
                         for o in range(period)) if len(p) >= min_days]
    if not paths:
        return None
    n = min(len(p) for p in paths)
    return summarize([st.mean([p[i] for p in paths]) for i in range(n)])


def corr(px, a: str, b: str, lo: str, hi: str) -> Optional[float]:
    days = sorted(set(px[a]) & set(px[b]))
    days = [d for d in days if lo <= d <= hi]
    ra, rb = [], []
    for i in range(1, len(days)):
        ra.append(px[a][days[i]] / px[a][days[i - 1]] - 1)
        rb.append(px[b][days[i]] / px[b][days[i - 1]] - 1)
    if len(ra) < 60:
        return None
    return st.correlation(ra, rb)


def pair_table(rets, cal, hi_sym: str, lo_date: str, hi_date: str, years) -> None:
    grid = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    print(f"  {'BTAL':>6}{hi_sym:>7}{'CAGR':>10}{'샤프':>8}{'변동성':>9}"
          f"{'MDD':>9}{'최악의 해':>10}")
    print("  " + "-" * 60)
    best = None
    for b in grid:
        w = {"BTAL": b / 100, hi_sym: 1 - b / 100}
        w = {k: v for k, v in w.items() if v > 0}
        m = tranche(rets, cal, w, lo_date, hi_date)
        if not m:
            continue
        worst = 99.0
        for y in years:
            a = tranche(rets, cal, w, f"{y}-01-01", f"{y}-12-31", min_days=150)
            if a:
                worst = min(worst, a["total"])
        mark = ""
        if best is None or m["sharpe"] > best[1]:
            best, mark = (b, m["sharpe"]), ""
        print(f"  {b:>5}%{100-b:>6}%{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}"
              f"{m['vol']:>8.1f}%{m['mdd']:>+8.1f}%{worst:>+9.1f}%{mark}")
    if best:
        print(f"\n  샤프 최고: BTAL {best[0]}% / {hi_sym} {100-best[0]}%  (샤프 {best[1]:.2f})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))
    cal = sorted(closes(store, "SPY"))
    px = {s: closes(store, s) for s in ("BTAL", "HIBL", "SPHB", "SPY")}
    rets = daily_returns(px, cal)

    LO, HI = "2019-11-08", "2026-12-31"
    YEARS = range(2020, 2027)

    print("BTAL + HIBL\n")
    print(f"  BTAL  {min(px['BTAL'])} ~ {max(px['BTAL'])}  {len(px['BTAL'])}일"
          f"   저베타 롱 / 고베타 숏, 시장중립")
    print(f"  HIBL  {min(px['HIBL'])} ~ {max(px['HIBL'])}  {len(px['HIBL'])}일"
          f"   S&P500 고베타 바스켓 일간 3배")
    print(f"  SPHB  {min(px['SPHB'])} ~ {max(px['SPHB'])}  {len(px['SPHB'])}일"
          f"   같은 바스켓 1배. 긴 구간 확인용\n")

    print(f"  일별 수익률 상관 ({LO[:7]} ~ 현재)")
    for a, b in [("BTAL", "HIBL"), ("BTAL", "SPHB"), ("BTAL", "SPY"), ("HIBL", "SPY")]:
        c = corr(px, a, b, LO, HI)
        print(f"    {a:<5} {b:<5} {c:>+7.3f}")

    print(f"\n\n단독 보유 ({LO[:7]} ~ 현재, 6.8년)\n")
    print(f"  {'':<8}{'CAGR':>10}{'샤프':>8}{'변동성':>9}{'MDD':>9}")
    print("  " + "-" * 44)
    for s in ("BTAL", "HIBL", "SPY"):
        m = tranche(rets, cal, {s: 1.0}, LO, HI, period=0)
        print(f"  {s:<8}{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}"
              f"{m['vol']:>8.1f}%{m['mdd']:>+8.1f}%")

    print(f"\n\n비중별 (21일 트랜치 되맞춤, 비용 {COST_BP:.0f}bp)\n")
    pair_table(rets, cal, "HIBL", LO, HI, YEARS)

    print(f"\n\n되맞춤이 만든 몫 — 50:50에서\n")
    print(f"  {'되맞춤':<20}{'CAGR':>10}{'샤프':>8}{'MDD':>9}{'회전율':>10}")
    print("  " + "-" * 57)
    w = {"BTAL": 0.5, "HIBL": 0.5}
    for label, period in [("없음 (사고 방치)", 0), ("5일마다", 5),
                          ("21일마다 트랜치", 21), ("63일마다 트랜치", 63)]:
        m = tranche(rets, cal, w, LO, HI, period=period)
        if not m:
            continue
        turn = "-" if not period else f"연 {TRADING/period:.0f}회"
        print(f"  {label:<20}{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}"
              f"{m['mdd']:>+8.1f}%{turn:>10}")

    print(f"\n\n연도별 수익률 (%)\n")
    print(f"  {'조합':<22}" + "".join(f"{y:>8}" for y in YEARS))
    print("  " + "-" * 78)
    rows = [("BTAL 100%", {"BTAL": 1.0}), ("HIBL 100%", {"HIBL": 1.0}),
            ("BTAL30 / HIBL70", {"BTAL": 0.3, "HIBL": 0.7}),
            ("BTAL50 / HIBL50", {"BTAL": 0.5, "HIBL": 0.5}),
            ("BTAL70 / HIBL30", {"BTAL": 0.7, "HIBL": 0.3}),
            ("SPY 100%", {"SPY": 1.0})]
    for label, w in rows:
        cells = []
        for y in YEARS:
            a = tranche(rets, cal, w, f"{y}-01-01", f"{y}-12-31", min_days=150)
            cells.append(f"{a['total']:+.1f}" if a else "-")
        print(f"  {label:<22}" + "".join(f"{c:>8}" for c in cells))

    print(f"\n\n위기 구간 수익률 (%)\n")
    live = [c for c in CRISES if c[1] >= LO]
    print(f"  {'조합':<22}" + "".join(f"{c[0]:>14}" for c in live))
    print("  " + "-" * 52)
    for label, w in rows:
        cells = []
        for _, lo, hi in live:
            a = tranche(rets, cal, w, lo, hi, min_days=20)
            cells.append(f"{a['total']:+.1f}%" if a else "-")
        print(f"  {label:<22}" + "".join(f"{c:>14}" for c in cells))

    LO2, HI2 = "2011-05-06", "2026-12-31"
    print(f"\n\n같은 구조를 1배로 — BTAL + SPHB ({LO2[:7]} ~ 현재, 15.3년)\n")
    print(f"  상관 BTAL/SPHB {corr(px, 'BTAL', 'SPHB', LO2, HI2):+.3f}\n")
    pair_table(rets, cal, "SPHB", LO2, HI2, range(2012, 2027))

    print(f"\n  연도별 (%)\n")
    yrs2 = list(range(2012, 2027))
    rows2 = [("BTAL 100%", {"BTAL": 1.0}), ("SPHB 100%", {"SPHB": 1.0}),
             ("BTAL50 / SPHB50", {"BTAL": 0.5, "SPHB": 0.5}),
             ("SPY 100%", {"SPY": 1.0})]
    print(f"  {'':<18}" + "".join(f"{y%100:>7}" for y in yrs2))
    print("  " + "-" * 123)
    for label, w in rows2:
        cells = []
        for y in yrs2:
            a = tranche(rets, cal, w, f"{y}-01-01", f"{y}-12-31", min_days=150)
            cells.append(f"{a['total']:+.1f}" if a else "-")
        print(f"  {label:<18}" + "".join(f"{c:>7}" for c in cells))

    print(f"\n  위기 구간 (%)\n")
    print(f"  {'조합':<18}" + "".join(f"{c[0]:>14}" for c in CRISES))
    print("  " + "-" * 76)
    for label, w in rows2:
        cells = []
        for _, lo, hi in CRISES:
            a = tranche(rets, cal, w, lo, hi, min_days=20)
            cells.append(f"{a['total']:+.1f}%" if a else "-")
        print(f"  {label:<18}" + "".join(f"{c:>14}" for c in cells))

    print(f"\n\n같은 기간에서 E 조합과 나란히 ({LO[:7]} ~ 현재)\n")
    print(f"  {'조합':<24}{'CAGR':>10}{'샤프':>8}{'변동성':>9}{'MDD':>9}{'최악의 해':>10}")
    print("  " + "-" * 70)
    E = {"DBMF": 0.15, "BTAL": 0.10, "UUP": 0.10}
    for s7 in ("BTC/USD", "GLD", "TLT", "QQQ", "SPY", "069500", "VNQ"):
        E[s7] = 0.65 / 7
    extra = {s: closes(store, s) for s in E if s not in px}
    rets.update(daily_returns(extra, cal))
    for label, w in [("BTAL70 / HIBL30", {"BTAL": 0.7, "HIBL": 0.3}),
                     ("BTAL60 / HIBL40", {"BTAL": 0.6, "HIBL": 0.4}),
                     ("BTAL50 / SPHB50", {"BTAL": 0.5, "SPHB": 0.5}),
                     ("E 조합 10종", E),
                     ("SPY 100%", {"SPY": 1.0})]:
        m = tranche(rets, cal, w, LO, HI)
        worst = min(a["total"] for y in YEARS
                    if (a := tranche(rets, cal, w, f"{y}-01-01", f"{y}-12-31",
                                     min_days=150)))
        print(f"  {label:<24}{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}"
              f"{m['vol']:>8.1f}%{m['mdd']:>+8.1f}%{worst:>+9.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
