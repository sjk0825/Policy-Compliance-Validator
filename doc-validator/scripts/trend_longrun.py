"""추세 필터를 2008년까지 밀어 본다.

fixtures/wide의 미국 ETF는 2009-12-31부터고 crisis2008은 2007-01부터라,
200일선을 쓰려면 워밍업이 모자라 2008년을 제대로 판정할 수 없다. 추세
필터의 값어치는 정확히 그런 해에 드러나므로 따로 받는다.

2004년부터 있는 것만 쓴다. BTC와 KODEX 200은 빠지고 5종이 남는다.
7종 결과와 직접 비교할 수는 없지만, 묻는 것은 수익률의 크기가 아니라
"자산별 추세 필터가 2008년에도 작동하는가"다.

    python scripts/trend_longrun.py
    python scripts/trend_longrun.py --refetch
"""
import argparse
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from btal_hibl import summarize                          # noqa: E402
from trend_overlay import build_signals, one_path, PERIOD, CASH  # noqa: E402

OUT = ROOT / "fixtures" / "longrun"
CORE = ["SPY", "QQQ", "TLT", "GLD", "VNQ"]
START = "2004-01-01"
CRISES = [("2008 금융위기", "2007-10-09", "2009-03-09"),
          ("2011 유럽", "2011-04-29", "2011-10-03"),
          ("2020 코로나", "2020-02-19", "2020-03-23"),
          ("2022 인플레", "2022-01-01", "2022-10-12")]


def fetch(refetch: bool) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    import FinanceDataReader as fdr
    for s in CORE + ["SHY"]:
        p = OUT / f"{s}.csv"
        if p.exists() and not refetch:
            continue
        df = fdr.DataReader(s, start=START)[["Open", "High", "Low", "Close", "Volume"]]
        df.index.name = "Date"
        df = df.reset_index()
        df["Date"] = df["Date"].astype(str).str.slice(0, 10)
        df.dropna(subset=["Close"]).to_csv(p, index=False, encoding="utf-8")
        print(f"  {s} 저장")


def load() -> Dict[str, Dict[str, float]]:
    import csv
    px: Dict[str, Dict[str, float]] = {}
    for p in sorted(OUT.glob("*.csv")):
        s = p.stem
        d: Dict[str, float] = {}
        with p.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["Close"]:
                    d[row["Date"]] = float(row["Close"])
        px[s] = d
    return px


def daily(px, cal) -> Dict[str, Dict[str, float]]:
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


def run(rets, sig, cal, base, lo, hi, on=True, min_days=60):
    days = [d for d in cal if lo <= d <= hi]
    paths = [p for p in (one_path(rets, sig, days, base, PERIOD, o, on)
                         for o in range(PERIOD)) if len(p) >= min_days]
    if not paths:
        return None
    n = min(len(p) for p in paths)
    return summarize([st.mean([p[i] for p in paths]) for i in range(n)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refetch", action="store_true")
    args = ap.parse_args()
    fetch(args.refetch)
    px = load()
    px[CASH] = px.pop("SHY")          # 2004년에 BIL이 없다. SHY로 대신한다
    cal = sorted(px["SPY"])
    rets = daily(px, cal)
    base = {s: 1 / len(CORE) for s in CORE}

    RULES = ["none", "ma100", "ma150", "ma200", "ma250", "mom6", "mom12", "dual200"]
    sigs = {r: build_signals({s: px[s] for s in CORE}, cal, r) for r in RULES}
    LO, HI = "2005-01-03", "2026-12-31"
    years = list(range(2005, 2027))

    print(f"5종 균등 (SPY QQQ TLT GLD VNQ) / 현금 SHY / {LO} ~ {max(cal)}\n")
    print(f"  {'규칙':<10}{'CAGR':>10}{'샤프':>8}{'변동성':>8}{'MDD':>10}"
          f"{'최악의 해':>10}{'마이너스 해':>12}")
    print("  " + "-" * 68)
    for r in RULES:
        m = run(rets, sigs[r], cal, base, LO, HI)
        ys = [a["total"] for y in years
              if (a := run(rets, sigs[r], cal, base, f"{y}-01-01", f"{y}-12-31",
                           min_days=150))]
        neg = sum(1 for v in ys if v < 0)
        print(f"  {r:<10}{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}{m['vol']:>7.1f}%"
              f"{m['mdd']:>+9.1f}%{min(ys):>+9.1f}%{neg:>7}/{len(ys)}회")

    print(f"\n\n연도별 (%)\n")
    print(f"  {'':<10}" + "".join(f"{y%100:>7}" for y in years))
    print("  " + "-" * (10 + 7 * len(years)))
    for r in ["none", "ma200", "mom12", "dual200"]:
        cells = []
        for y in years:
            a = run(rets, sigs[r], cal, base, f"{y}-01-01", f"{y}-12-31",
                    min_days=150)
            cells.append(f"{a['total']:+.1f}" if a else "-")
        print(f"  {r:<10}" + "".join(f"{c:>7}" for c in cells))

    print(f"\n\n위기 구간 (%)\n")
    print(f"  {'':<10}" + "".join(f"{c[0]:>16}" for c in CRISES))
    print("  " + "-" * 74)
    for r in ["none", "ma200", "mom12", "dual200"]:
        cells = []
        for _, lo, hi in CRISES:
            a = run(rets, sigs[r], cal, base, lo, hi, min_days=20)
            cells.append(f"{a['total']:+.1f}%" if a else "-")
        print(f"  {r:<10}" + "".join(f"{c:>16}" for c in cells))

    print(f"\n\n회전율과 현금 비중 (ma200)\n")
    days = [d for d in cal if LO <= d <= HI]
    flips, cashw = 0, []
    prev = None
    for d in days:
        on = {s: sigs["ma200"][s].get(d, True) for s in CORE}
        if prev:
            flips += sum(1 for s in CORE if on[s] != prev[s])
        prev = on
        cashw.append(sum(1 for s in CORE if not on[s]) / len(CORE))
    yrs = len(days) / 252
    print(f"  신호 전환      연 {flips/yrs:.1f}회 (자산 5개 합계)")
    print(f"  평균 현금 비중  {st.mean(cashw)*100:.1f}%")
    print(f"  현금 100%인 날  {sum(1 for c in cashw if c == 1)/len(cashw)*100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
