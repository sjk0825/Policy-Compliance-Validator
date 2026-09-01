"""되맞춤이 만든 돈은 어디서 나온 돈인가.

50:50 BTAL/HIBL은 방치하면 CAGR +8.9%, 21일마다 되맞추면 +20.7%다.
이 +11.9%p를 되맞춤이라는 행위가 만들어낸 것으로 읽으면, 더 자주 더
열심히 되맞추면 더 벌어야 한다. 그렇지 않다.

되맞춤 보너스에는 닫힌 형태의 근사식이 있다.

    보너스 ≈ ½ ( Σ wᵢσᵢ²  −  σₚ² )

우변은 전부 분산이다. 즉 보너스의 재료는 되맞춤의 부지런함이 아니라
자산의 변동성이고, 그 변동성은 낙폭을 만드는 재료와 같은 것이다.
이 스크립트는 그 등식이 실측과 맞는지, 보너스가 어느 다리에서 나왔는지,
빈도를 올리면 늘어나는지를 확인한다.

    python scripts/rebal_source.py --data fixtures/wide
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

from engine import PriceStore                       # noqa: E402
from btal_hibl import closes, daily_returns, tranche  # noqa: E402

LO, HI = "2019-11-08", "2026-12-31"
TRADING = 252


def rets_of(rets, syms, days) -> List[List[float]]:
    keep = [d for d in days if all(d in rets[s] for s in syms)]
    return [[rets[s][d] for d in keep] for s in syms]


def vol(r: List[float]) -> float:
    return st.pstdev(r) * math.sqrt(TRADING)


def theoretical(rets, weights: Dict[str, float], days) -> Dict[str, float]:
    syms = list(weights)
    rs = rets_of(rets, syms, days)
    port = [sum(weights[s] * r[i] for s, r in zip(syms, rs))
            for i in range(len(rs[0]))]
    terms = {s: weights[s] * vol(r) ** 2 for s, r in zip(syms, rs)}
    return {"terms": terms, "sum_wv": sum(terms.values()),
            "port_var": vol(port) ** 2,
            "bonus": 0.5 * (sum(terms.values()) - vol(port) ** 2) * 100}


def drift(rets, weights: Dict[str, float], days) -> Dict[str, float]:
    """방치했을 때 끝에서의 비중."""
    syms = list(weights)
    keep = [d for d in days if all(d in rets[s] for s in syms)]
    held = dict(weights)
    for d in keep:
        held = {s: v * (1 + rets[s][d]) for s, v in held.items()}
    t = sum(held.values())
    return {s: v / t * 100 for s, v in held.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))
    cal = sorted(closes(store, "SPY"))
    SYMS = ("BTAL", "HIBL", "SPHB", "SPY", "GLD", "TLT", "DBMF", "UUP",
            "QQQ", "VNQ", "BTC/USD", "069500")
    px = {s: closes(store, s) for s in SYMS}
    rets = daily_returns(px, cal)
    days = [d for d in cal if LO <= d <= HI]

    W = {"BTAL": 0.5, "HIBL": 0.5}

    print("1. 보너스의 근사식이 실측과 맞는가 (50:50, 2019-11~)\n")
    th = theoretical(rets, W, days)
    bh = tranche(rets, cal, W, LO, HI, period=0)
    rb = tranche(rets, cal, W, LO, HI, period=21)
    print(f"  Σ wᵢσᵢ²          {th['sum_wv']:.4f}")
    print(f"  σₚ²              {th['port_var']:.4f}")
    print(f"  ½(차)  이론 보너스  {th['bonus']:+.2f}%/년")
    print(f"         실측 보너스  {rb['cagr'] - bh['cagr']:+.2f}%/년"
          f"   (방치 {bh['cagr']:+.2f}% → 되맞춤 {rb['cagr']:+.2f}%)")

    print(f"\n\n2. 그 보너스는 어느 다리에서 나왔나\n")
    tot = th["sum_wv"]
    for s, v in sorted(th["terms"].items(), key=lambda x: -x[1]):
        r = rets_of(rets, [s], days)[0]
        print(f"  {s:<6} w{W[s]*100:.0f}%  σ {vol(r)*100:>5.1f}%   "
              f"wσ² = {v:.4f}   재료의 {v/tot*100:>5.1f}%")
    print(f"\n  → 되맞춤이 수확한 분산은 사실상 전부 HIBL의 것이다.")
    print(f"     그리고 HIBL의 σ 92%는 MDD -88%를 만든 바로 그 숫자다.")

    print(f"\n\n3. 방치하면 비중이 어디로 가나\n")
    d = drift(rets, W, days)
    print(f"  시작   BTAL 50.0%   HIBL 50.0%")
    print(f"  끝     BTAL {d['BTAL']:.1f}%   HIBL {d['HIBL']:.1f}%")
    print(f"\n  → 방치의 +8.9%는 '50:50을 들고 있었다'가 아니라 "
          f"'HIBL {d['HIBL']:.0f}%를 들고")
    print(f"     2020·2022를 정통으로 맞았다'의 결과다. 되맞춤의 몫 중 큰")
    print(f"     부분은 이 쏠림을 막은 것이지 새로 벌어온 돈이 아니다.")

    print(f"\n\n4. 더 열심히 하면 더 버나 (50:50)\n")
    print(f"  {'되맞춤 주기':<16}{'CAGR':>10}{'샤프':>8}{'MDD':>9}"
          f"{'연 회전율':>11}{'보너스':>10}")
    print("  " + "-" * 64)
    for label, p in [("매일 전량", 1), ("3일", 3), ("5일", 5), ("10일", 10),
                     ("21일", 21), ("63일", 63), ("126일", 126),
                     ("없음(방치)", 0)]:
        m = tranche(rets, cal, W, LO, HI, period=p)
        if not m:
            continue
        turn = f"{TRADING/p:.0f}회" if p else "-"
        bonus = f"{m['cagr'] - bh['cagr']:+.2f}%p" if p else "-"
        print(f"  {label:<16}{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}"
              f"{m['mdd']:>+8.1f}%{turn:>11}{bonus:>10}")
    print(f"\n  → 5일과 63일이 사실상 같다. 빈도는 다이얼이 아니다.")
    print(f"     보너스는 되맞춤 횟수가 아니라 자산의 분산이 정한다.")

    print(f"\n\n5. 보너스와 낙폭은 같이 움직인다 (비중별)\n")
    print(f"  {'BTAL':>6}{'HIBL':>7}{'이론 보너스':>13}{'실측 보너스':>13}"
          f"{'샤프':>8}{'MDD':>9}")
    print("  " + "-" * 57)
    for b in (0, 20, 40, 50, 60, 70, 80, 90):
        w = {k: v for k, v in {"BTAL": b / 100, "HIBL": 1 - b / 100}.items() if v > 0}
        if len(w) < 2:
            continue
        t = theoretical(rets, w, days)
        h = tranche(rets, cal, w, LO, HI, period=0)
        r = tranche(rets, cal, w, LO, HI, period=21)
        print(f"  {b:>5}%{100-b:>6}%{t['bonus']:>+12.2f}%"
              f"{r['cagr']-h['cagr']:>+12.2f}%{r['sharpe']:>8.2f}{r['mdd']:>+8.1f}%")
    print(f"\n  → 보너스가 큰 칸이 낙폭도 크다. 둘의 재료가 같기 때문이다.")

    print(f"\n\n6. 연도별 — 보너스는 변동성이 큰 해에 나온다\n")
    print(f"  {'':<10}" + "".join(f"{y:>9}" for y in range(2020, 2027)))
    print("  " + "-" * 73)
    for label, fn in [("HIBL σ", None), ("보너스", None)]:
        cells = []
        for y in range(2020, 2027):
            dd = [d for d in cal if f"{y}-01-01" <= d <= f"{y}-12-31"]
            if label == "HIBL σ":
                r = [rets["HIBL"][d] for d in dd if d in rets["HIBL"]]
                cells.append(f"{vol(r)*100:.0f}%" if len(r) > 150 else "-")
            else:
                a = tranche(rets, cal, W, f"{y}-01-01", f"{y}-12-31",
                            period=21, min_days=150)
                c = tranche(rets, cal, W, f"{y}-01-01", f"{y}-12-31",
                            period=0, min_days=150)
                cells.append(f"{a['total']-c['total']:+.1f}%p" if a and c else "-")
        print(f"  {label:<10}" + "".join(f"{c:>9}" for c in cells))

    print(f"\n\n7. E 조합에서는 되맞춤이 얼마나 버나\n")
    E = {"DBMF": 0.15, "BTAL": 0.10, "UUP": 0.10}
    for s in ("BTC/USD", "GLD", "TLT", "QQQ", "SPY", "069500", "VNQ"):
        E[s] = 0.65 / 7
    print(f"  {'조합':<20}{'방치':>10}{'21일 되맞춤':>13}{'보너스':>10}"
          f"{'샤프':>8}{'MDD':>9}")
    print("  " + "-" * 62)
    for label, w in [("BTAL50/HIBL50", W), ("E 조합 10종", E),
                     ("SPY 100%", {"SPY": 1.0})]:
        h = tranche(rets, cal, w, LO, HI, period=0)
        r = tranche(rets, cal, w, LO, HI, period=21)
        print(f"  {label:<20}{h['cagr']:>+9.2f}%{r['cagr']:>+12.2f}%"
              f"{r['cagr']-h['cagr']:>+9.2f}%{r['sharpe']:>8.2f}{r['mdd']:>+8.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
