"""베타를 맞춘 저베타-고베타 스프레드. BAB.

BTAL은 저베타를 사고 고베타를 파는데 금액을 중립으로 맞춘다. 저베타
다리의 베타가 0.6~0.7, 고베타 다리가 1.4~1.5이므로 금액이 같아도 베타가
-0.8쯤 남는다. 실측 -0.51. 그래서 BTAL은 시장중립이 아니라 순 숏 베타이고,
위기에 오르는 것도 강세장에서 연 -9%씩 잃는 것도 같은 이유다.

베타로 중립을 맞추면 다르다. 저베타 다리를 1/beta_L배로 키우고 고베타
다리를 1/beta_H배로 줄이면 순 베타가 0이 된다.

    r_BAB = (1/beta_L)(r_L - r_f) - (1/beta_H)(r_H - r_f)

남는 것은 시장 방향이 아니라 "저베타가 위험 대비 더 낫다"는 스프레드뿐이다.
이것이 실제로 0 베타인지, 그 상태에서도 수익이 플러스인지, 플러스라면
E 조합에서 BTAL을 대신할 수 있는지를 본다.

베타는 직전 252거래일로만 추정한다. 판정일 당일은 보지 않는다.

    python scripts/bab_factor.py --data fixtures/wide
    python scripts/bab_factor.py --spread-bp 50 --cost-bp 10
"""
import argparse
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import PriceStore                          # noqa: E402
from btal_hibl import closes, daily_returns, summarize, tranche, CRISES  # noqa: E402

TRADING = 252
LOOKBACK = 252
LEV_CAP = (0.25, 4.0)


def rolling_beta(rets, sym: str, mkt: str, cal: List[str]) -> Dict[str, float]:
    """직전 LOOKBACK 거래일로 추정한 베타. 당일은 표본에 넣지 않는다."""
    pairs = [(d, rets[sym][d], rets[mkt][d]) for d in cal
             if d in rets[sym] and d in rets[mkt]]
    out: Dict[str, float] = {}
    for i in range(LOOKBACK, len(pairs)):
        w = pairs[i - LOOKBACK:i]          # i는 제외 = 당일 미포함
        xs = [a for _, a, _ in w]
        ys = [b for _, _, b in w]
        var = st.pvariance(ys)
        if var > 0:
            out[pairs[i][0]] = st.covariance(xs, ys) * (len(ys) - 1) / len(ys) / var
    return out


def clamp(x: float) -> float:
    return max(LEV_CAP[0], min(LEV_CAP[1], x))


def build_bab(rets, cal, low: str, high: str, rf_sym: str,
              spread_bp: float, cost_bp: float,
              beta_neutral: bool = True) -> Tuple[Dict[str, float], Dict]:
    """일별 BAB 수익률과 진단값.

    beta_neutral=False면 금액 중립(BTAL과 같은 방식)이 된다.
    """
    bl = rolling_beta(rets, low, "SPY", cal)
    bh = rolling_beta(rets, high, "SPY", cal)
    out: Dict[str, float] = {}
    levs: List[Tuple[float, float]] = []
    turns: List[float] = []
    prev: Optional[Tuple[float, float]] = None
    daily_spread = spread_bp / 10000 / TRADING
    for d in cal:
        if not all(d in x for x in (rets[low], rets[high], rets[rf_sym], bl, bh)):
            continue
        if bl[d] <= 0 or bh[d] <= 0:
            continue
        wl = clamp(1 / bl[d]) if beta_neutral else 1.0
        wh = clamp(1 / bh[d]) if beta_neutral else 1.0
        rf = rets[rf_sym][d]
        r = wl * (rets[low][d] - rf) - wh * (rets[high][d] - rf)
        # 순 차입(롱 다리가 1을 넘는 만큼)에 조달 스프레드를 물린다
        r -= max(0.0, wl - 1.0) * daily_spread
        if prev:
            turn = abs(wl - prev[0]) + abs(wh - prev[1])
            turns.append(turn)
            r -= turn * cost_bp / 10000
        prev = (wl, wh)
        levs.append((wl, wh))
        out[d] = r + rf              # 현금 담보로 100% 깔았을 때의 총수익
    diag = {"lev_low": st.mean([a for a, _ in levs]) if levs else 0,
            "lev_high": st.mean([b for _, b in levs]) if levs else 0,
            "beta_low": st.mean(list(bl.values())) if bl else 0,
            "beta_high": st.mean(list(bh.values())) if bh else 0,
            "turnover": st.mean(turns) * TRADING if turns else 0}
    return out, diag


def realized_beta(rets, sym: str, days) -> float:
    xs = [(rets[sym][d], rets["SPY"][d]) for d in days
          if d in rets[sym] and d in rets["SPY"]]
    ys = [b for _, b in xs]
    var = st.pvariance(ys)
    return (st.covariance([a for a, _ in xs], ys) * (len(ys) - 1) / len(ys) / var
            if var else 0.0)


def line(rets, cal, label: str, sym: str, lo: str, hi: str) -> None:
    days = [d for d in cal if lo <= d <= hi]
    r = [rets[sym][d] for d in days if d in rets[sym]]
    if len(r) < 200:
        print(f"  {label:<22}{'표본 부족':>50}")
        return
    m = summarize(r)
    b = realized_beta(rets, sym, days)
    c = st.correlation([rets[sym][d] for d in days
                        if d in rets[sym] and d in rets["SPY"]],
                       [rets["SPY"][d] for d in days
                        if d in rets[sym] and d in rets["SPY"]])
    print(f"  {label:<22}{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}{m['vol']:>8.1f}%"
          f"{m['mdd']:>+9.1f}%{b:>+9.2f}{c:>+9.2f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    ap.add_argument("--low", default="SPLV")
    ap.add_argument("--high", default="SPHB")
    ap.add_argument("--spread-bp", type=float, default=50.0,
                    help="차입 조달 스프레드 (연, bp)")
    ap.add_argument("--cost-bp", type=float, default=10.0)
    args = ap.parse_args()

    store = PriceStore(Path(args.data))
    cal = sorted(closes(store, "SPY"))
    SYMS = ["SPY", "BIL", "BTAL", args.low, args.high, "USMV", "SPHB",
            "DBMF", "UUP", "GLD", "TLT", "QQQ", "VNQ", "BTC/USD", "069500"]
    px = {s: closes(store, s) for s in dict.fromkeys(SYMS)}
    rets = daily_returns(px, cal)

    bab, diag = build_bab(rets, cal, args.low, args.high, "BIL",
                          args.spread_bp, args.cost_bp, beta_neutral=True)
    dn, _ = build_bab(rets, cal, args.low, args.high, "BIL",
                      0.0, args.cost_bp, beta_neutral=False)
    rets["BAB"] = bab
    rets["DN"] = dn

    LO = min(bab)
    HI = "2026-12-31"
    print(f"저베타 다리 {args.low} / 고베타 다리 {args.high}"
          f" / 무위험 BIL / 조달 +{args.spread_bp:.0f}bp / 비용 {args.cost_bp:.0f}bp")
    print(f"기간 {LO} ~ {max(bab)}  ({len(bab)/TRADING:.1f}년)\n")
    print(f"  직전 252일 베타 평균   {args.low} {diag['beta_low']:.2f}"
          f"   {args.high} {diag['beta_high']:.2f}")
    print(f"  그래서 곱한 배율       {args.low} {diag['lev_low']:.2f}배"
          f"   {args.high} {diag['lev_high']:.2f}배")
    print(f"  연 회전율             {diag['turnover']*100:.0f}%")

    print(f"\n\n1. 베타가 실제로 0이 되는가\n")
    print(f"  {'':<22}{'CAGR':>10}{'샤프':>8}{'변동성':>8}{'MDD':>10}"
          f"{'SPY 베타':>9}{'SPY 상관':>9}")
    print("  " + "-" * 76)
    for label, s in [("BTAL (실제 상품)", "BTAL"),
                     (f"금액 중립 {args.low}-{args.high}", "DN"),
                     ("베타 중립 BAB", "BAB"),
                     ("SPY", "SPY")]:
        line(rets, cal, label, s, LO, HI)

    print(f"\n\n2. 연도별 수익률 (%)\n")
    years = list(range(int(LO[:4]) + 1, 2027))
    print(f"  {'':<20}" + "".join(f"{y%100:>7}" for y in years))
    print("  " + "-" * (20 + 7 * len(years)))
    for label, s in [("BTAL", "BTAL"), ("금액 중립", "DN"),
                     ("베타 중립 BAB", "BAB"), ("SPY", "SPY")]:
        cells = []
        for y in years:
            r = [rets[s][d] for d in cal
                 if f"{y}-01-01" <= d <= f"{y}-12-31" and d in rets[s]]
            cells.append(f"{summarize(r)['total']:+.1f}" if len(r) > 150 else "-")
        print(f"  {label:<20}" + "".join(f"{c:>7}" for c in cells))

    print(f"\n\n3. 위기 구간 (%)\n")
    print(f"  {'':<20}" + "".join(f"{c[0]:>14}" for c in CRISES))
    print("  " + "-" * 78)
    for label, s in [("BTAL", "BTAL"), ("금액 중립", "DN"),
                     ("베타 중립 BAB", "BAB"), ("SPY", "SPY")]:
        cells = []
        for _, lo, hi in CRISES:
            r = [rets[s][d] for d in cal if lo <= d <= hi and d in rets[s]]
            cells.append(f"{summarize(r)['total']:+.1f}%" if len(r) > 15 else "-")
        print(f"  {label:<20}" + "".join(f"{c:>14}" for c in cells))

    print(f"\n\n4. E 조합에서 BTAL을 대신할 수 있는가"
          f"  (21일 트랜치, {LO[:7]} ~)\n")
    SEVEN = ["BTC/USD", "GLD", "TLT", "QQQ", "SPY", "069500", "VNQ"]

    def mix(hedges: Dict[str, float]) -> Dict[str, float]:
        w = {s: (1 - sum(hedges.values())) / len(SEVEN) for s in SEVEN}
        for s, v in hedges.items():
            w[s] = w.get(s, 0) + v
        return w

    cands = [("7종만", mix({})),
             ("E  DBMF15 BTAL10 UUP10", mix({"DBMF": .15, "BTAL": .10, "UUP": .10})),
             ("E' BTAL -> BAB", mix({"DBMF": .15, "BAB": .10, "UUP": .10})),
             ("F  DBMF15 BAB20 UUP10", mix({"DBMF": .15, "BAB": .20, "UUP": .10})),
             ("G  DBMF15 BAB30", mix({"DBMF": .15, "BAB": .30})),
             ("H  BAB30", mix({"BAB": .30}))]
    print(f"  {'조합':<26}{'CAGR':>10}{'샤프':>8}{'변동성':>8}{'MDD':>10}{'최악의 해':>10}")
    print("  " + "-" * 72)
    for label, w in cands:
        m = tranche(rets, cal, w, LO, HI)
        if not m:
            continue
        worst = min(a["total"] for y in years
                    if (a := tranche(rets, cal, w, f"{y}-01-01", f"{y}-12-31",
                                     min_days=150)))
        print(f"  {label:<26}{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}"
              f"{m['vol']:>7.1f}%{m['mdd']:>+9.1f}%{worst:>+9.1f}%")

    print(f"\n  연도별 (%)\n")
    print(f"  {'':<26}" + "".join(f"{y%100:>7}" for y in years))
    print("  " + "-" * (26 + 7 * len(years)))
    for label, w in cands:
        cells = []
        for y in years:
            a = tranche(rets, cal, w, f"{y}-01-01", f"{y}-12-31", min_days=150)
            cells.append(f"{a['total']:+.1f}" if a else "-")
        print(f"  {label:<26}" + "".join(f"{c:>7}" for c in cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
