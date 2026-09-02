"""원화로 받으면 결론이 달라진다. 그리고 헤지 후보를 전수로 고른다.

지금까지의 모든 측정이 달러 기준이었다. 국내 거주자가 미국 ETF 열둘을
들고 있으면 수익률에 환율이 곱해지므로, 원화로 환산하면 다른 그림이 된다.

    원화 수익률 = (1 + 달러 수익률) × (1 + 원달러 변화) − 1

신호도 원화 가격으로 계산한다. 계좌에서 보이는 것이 그것이고, 원화가
약해지는 동안 달러로 횡보한 자산은 원화로는 오르고 있기 때문이다.

헤지 후보도 함께 고른다. 기준은 둘이다. 최악의 해를 줄이면서 샤프를
깎지 않아야 한다. 대부분의 헤지 상품은 둘째를 만족하지 못한다. 매년
내는 보험료가 위기에 버는 것보다 크기 때문이다.

    python scripts/krw_basis.py
    python scripts/krw_basis.py --screen        헤지 후보 전수
"""
import argparse
import csv
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import contrarian_tilt as CT                      # noqa: E402
import regime_tilt_line as G                      # noqa: E402
from engine import PriceStore                     # noqa: E402
from btal_hibl import closes, summarize           # noqa: E402
from worst_year_push import ma_grade, daily       # noqa: E402

FX = ROOT / "fixtures" / "longrun" / "USDKRW.csv"
KRW_ASSETS = {"069500"}          # 이미 원화로 거래되는 것
LO, HI = "2012-05-07", "2026-12-31"
YEARS = range(2013, 2027)
KA, KB, PERIOD, SIG = -0.50, 0.00, 63, 21


def load_fx(cal: List[str]) -> Dict[str, float]:
    if not FX.exists():
        import FinanceDataReader as fdr
        df = fdr.DataReader("USD/KRW", start="2010-01-01")[["Close"]].dropna()
        df.index.name = "Date"
        df = df.reset_index()
        df["Date"] = df["Date"].astype(str).str.slice(0, 10)
        FX.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(FX, index=False, encoding="utf-8")
    raw = {r["Date"]: float(r["Close"])
           for r in csv.DictReader(FX.open(encoding="utf-8"))}
    out, last = {}, None
    for d in cal:                 # 휴일은 직전 고시를 쓴다
        if d in raw:
            last = raw[d]
        if last:
            out[d] = last
    return out


def to_krw(px: Dict[str, Dict[str, float]], fx) -> Dict[str, Dict[str, float]]:
    return {s: {d: (v if s in KRW_ASSETS else v * fx[d])
                for d, v in ser.items() if d in fx}
            for s, ser in px.items()}


def core_series(px, cal, fx) -> Dict[str, float]:
    """C안(14종 + ma200 + 60일선 모멘텀 기울기)의 일별 수익률."""
    rets = daily(px, cal)
    exp = {s: ma_grade(px[s], cal, ns=(200,)) for s in G.CORE}
    tr = CT.trail(px, cal)[5]
    ab = {s: G.above_ma(px[s], cal, 60) for s in G.CORE}
    G.PERIOD, G.OFFS = PERIOD, 21
    days = [d for d in cal if LO <= d <= HI and d in fx]
    ps = [G.one_path(rets, exp, tr, ab, days, KA, KB,
                     round(i * PERIOD / 21), True) for i in range(21)]
    n = min(len(p) for p in ps)
    return dict(zip(days[len(days) - n:],
                    [st.mean([p[i] for p in ps]) for i in range(n)]))


def blend(base: Dict[str, float], hedge: Dict[str, float], w: float,
          per: int = PERIOD) -> Dict[str, float]:
    out, held = {}, None
    ds = [d for d in sorted(base) if d in hedge]
    for i, d in enumerate(ds):
        if held is None or i % per == 0:
            held = [1 - w, w]
        out[d] = held[0] * base[d] + held[1] * hedge[d]
        g = [held[0] * (1 + base[d]), held[1] * (1 + hedge[d])]
        t = sum(g)
        held = [x / t for x in g]
    return out


def stat(s: Dict[str, float]) -> Dict:
    ds = sorted(s)
    m = summarize([s[d] for d in ds])
    ys: Dict[int, List[float]] = {}
    for d in ds:
        ys.setdefault(int(d[:4]), []).append(s[d])
    y = {k: (math.prod(1 + x for x in a) - 1) * 100
         for k, a in ys.items() if len(a) > 150 and k in YEARS}
    m["y"] = y
    m["worst"] = min(y.values())
    m["neg"] = sum(1 for v in y.values() if v < 0)
    m["ny"] = len(y)
    return m


def line(lab, m):
    print(f"  {lab:<22}{m['cagr']:>+8.2f}%{m['sharpe']:>7.2f}{m['vol']:>7.1f}%"
          f"{m['mdd']:>+8.1f}%{m['worst']:>+9.1f}%{m['neg']:>5}/{m['ny']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", action="store_true")
    args = ap.parse_args()
    store = PriceStore(Path("fixtures/wide"))
    cal = sorted(closes(store, "SPY"))
    fx = load_fx(cal)
    need = set(G.CORE) | {G.CASH, "UUP", "BIL"}
    pxu = {s: closes(store, s) for s in need}
    pxk = to_krw(pxu, fx)

    hdr = (f"  {'':<22}{'CAGR':>9}{'샤프':>7}{'변동성':>8}{'MDD':>9}"
           f"{'최악의해':>10}{'마이너스':>8}")
    print(f"환율 {min(fx)} {fx[min(fx)]:.0f}원 → {max(fx)} {fx[max(fx)]:.0f}원\n")
    print("달러 기준과 원화 기준\n"); print(hdr); print("  " + "-" * 70)
    keep = {}
    for tag, px in (("달러 기준", pxu), ("원화 기준", pxk)):
        C = core_series(px, cal, fx)
        rets = daily(px, cal)
        for w in (0.0, 0.2, 0.4):
            h = {d: rets["UUP"][d] for d in C if d in rets["UUP"]}
            s = C if w == 0 else blend(C, h, w)
            m = stat(s)
            keep[(tag, w)] = m
            line(f"{tag} · " + ("헤지없음" if w == 0 else f"달러{w*100:.0f}%"), m)
        print()

    print("\n연도별 (%)\n")
    ys = sorted(YEARS)
    print(f"  {'':<22}" + "".join(f"{y % 100:>7}" for y in ys))
    print("  " + "-" * (22 + 7 * len(ys)))
    for k in (("달러 기준", 0.0), ("달러 기준", 0.4),
              ("원화 기준", 0.0), ("원화 기준", 0.4)):
        y = keep[k]["y"]
        lab = f"{k[0]} · " + ("헤지없음" if k[1] == 0 else "달러40%")
        print(f"  {lab:<22}" + "".join(f"{y.get(v, float('nan')):>+7.1f}" for v in ys))

    print("\n\n원화 기준에서 달러 비중\n"); print(hdr); print("  " + "-" * 70)
    C = core_series(pxk, cal, fx)
    rets = daily(pxk, cal)
    h = {d: rets["UUP"][d] for d in C if d in rets["UUP"]}
    for w in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5):
        line(f"달러 {w*100:.0f}%", stat(C if w == 0 else blend(C, h, w)))

    if args.screen:
        print("\n\n헤지 후보 전수 (달러 기준, 20% 얹었을 때)\n")
        syms = [s for s in store._meta
                if store._meta[s].group in ("us_etf", "kr_etf")]
        P = {s: closes(store, s) for s in syms}
        Cu = core_series(pxu, cal, fx)
        ru = daily({**pxu, **P}, cal)
        rows = []
        for s in syms:
            hh = {d: ru[s][d] for d in Cu if d in ru.get(s, {})}
            if len(hh) < len(Cu) * 0.95:
                continue
            m = stat(blend(Cu, hh, 0.20))
            solo = summarize([hh[d] for d in sorted(hh)])
            cr = st.correlation([Cu[d] for d in sorted(hh)],
                                [hh[d] for d in sorted(hh)])
            rows.append((m["sharpe"], s, solo["cagr"], cr, m))
        base = stat(Cu)
        print(f"  기준 C안  샤프 {base['sharpe']:.2f}  최악 {base['worst']:+.1f}%\n")
        print(f"  {'종목':<10}{'단독CAGR':>10}{'상관':>8}{'혼합CAGR':>10}{'샤프':>7}"
              f"{'MDD':>9}{'최악의해':>10}{'마이너스':>8}")
        print("  " + "-" * 74)
        for sh, s, sc, cr, m in sorted(rows, key=lambda x: -x[4]["worst"])[:10]:
            print(f"  {s:<10}{sc:>+9.2f}%{cr:>+8.2f}{m['cagr']:>+9.2f}%{sh:>7.2f}"
                  f"{m['mdd']:>+8.1f}%{m['worst']:>+9.1f}%{m['neg']:>5}/{m['ny']}")
        print("\n  최악의 해와 샤프를 함께 개선하는 것만 쓸 수 있다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
