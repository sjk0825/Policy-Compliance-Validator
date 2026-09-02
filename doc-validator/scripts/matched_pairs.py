"""베타가 맞는 짝을 찾는다.

SPLV/SPHB는 애초에 기울어진 짝이었다. 베타가 0.64와 1.42로 0.78이나
벌어진다. 금액을 반반 넣으면 순 베타가 -0.78 남고, 그것을 레버리지로
메우면 총노출이 2.4배가 된다. 게다가 고베타는 정의상 시장 프리미엄을
더 먹으므로 상승장이 길면 구조적으로 진다. 상대평가가 아니라 시장을
거스르는 베팅에 가까웠다.

베타가 서로 같은 둘을 고르면 다르다. 금액 중립이 곧 베타 중립이라
레버리지가 필요 없고, 어느 쪽도 시장 프리미엄을 더 먹지 않는다. 남는
것은 순수한 상대 성적뿐이다.

다만 그것만으로 돈이 되지는 않는다. 기대수익이 0에 가까워질 뿐이다.
값어치가 있으려면 그 스프레드가 한 방향으로 밀리지 않고 오르내려야 한다.
오르내리는 짝은 되맞춤으로 수확할 수 있다. 이 세션에서 확인한 대로
되맞춤이 버는 국면이 바로 그것이다.

그래서 짝마다 넷을 잰다.

    베타차     |beta_A - beta_B|. 작아야 기울어지지 않는다
    표류      스프레드 연율. 0에서 멀면 한쪽이 계속 이긴 것이다
    되맞춤 보너스  50:50 되맞춤에서 방치를 뺀 값
    회귀      21일 스프레드 수익률과 다음 21일의 상관. 음수면 되돌린다

    python scripts/matched_pairs.py
    python scripts/matched_pairs.py --max-dbeta 0.05
"""
import argparse
import math
import statistics as st
import sys
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import PriceStore                                 # noqa: E402
from btal_hibl import closes, daily_returns, summarize, tranche  # noqa: E402

LO, HI = "2012-01-03", "2026-12-31"
TRADING = 252
MIN_DAYS = 2500
# 구조적 감쇠가 있는 상품은 뺀다. 이 세션에서 이미 확인했다.
EXCLUDE = {"UVXY", "SVXY", "SVIX", "ZIVB", "VIXY", "VIXM", "TAIL",
           "SH", "PSQ", "DOG", "BITO", "HIBL"}


def beta(rets, sym: str, days) -> Optional[float]:
    xs = [(rets[sym][d], rets["SPY"][d]) for d in days
          if d in rets[sym] and d in rets["SPY"]]
    if len(xs) < MIN_DAYS:
        return None
    ys = [b for _, b in xs]
    v = st.pvariance(ys)
    return st.covariance([a for a, _ in xs], ys) * (len(ys) - 1) / len(ys) / v if v else None


def ann(rs: List[float]) -> float:
    e = 1.0
    for r in rs:
        e *= (1 + r)
    return (e ** (TRADING / len(rs)) - 1) * 100 if len(rs) > 200 else 0.0


def reversion(spread: List[float]) -> Optional[float]:
    """21일 스프레드 수익률과 다음 21일의 상관. 음수면 되돌린다."""
    blocks = [sum(spread[i:i + 21]) for i in range(0, len(spread) - 21, 21)]
    if len(blocks) < 30:
        return None
    return st.correlation(blocks[:-1], blocks[1:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-dbeta", type=float, default=0.10)
    ap.add_argument("--top", type=int, default=18)
    args = ap.parse_args()

    store = PriceStore(Path("fixtures/wide"))
    cal = sorted(closes(store, "SPY"))
    days = [d for d in cal if LO <= d <= HI]
    syms = [e for e in store._meta
            if store._meta[e].group in ("us_etf", "kr_etf")
            and e not in EXCLUDE]
    px = {s: closes(store, s) for s in syms + ["SPY"]}
    rets = daily_returns(px, cal)

    betas: Dict[str, float] = {}
    vols: Dict[str, float] = {}
    for s in syms:
        b = beta(rets, s, days)
        if b is None:
            continue
        r = [rets[s][d] for d in days if d in rets[s]]
        betas[s] = b
        vols[s] = st.pstdev(r) * math.sqrt(TRADING) * 100

    print(f"후보 {len(betas)}종 (2012~2026, {MIN_DAYS}일 이상)\n")
    print("1. 지금 쓰던 짝이 얼마나 기울어져 있었나\n")
    print(f"  {'짝':<20}{'베타 A':>9}{'베타 B':>9}{'베타차':>9}"
          f"{'스프레드 연율':>14}")
    print("  " + "-" * 62)
    for a, b in [("SPLV", "SPHB"), ("BTAL", "SPY")]:
        if a in betas and b in betas:
            sp = [rets[a][d] - rets[b][d] for d in days
                  if d in rets[a] and d in rets[b]]
            print(f"  {a+' - '+b:<20}{betas[a]:>9.2f}{betas[b]:>9.2f}"
                  f"{abs(betas[a]-betas[b]):>9.2f}{ann(sp):>+13.2f}%")
    print("\n  베타차 0.78. 금액을 반반 넣으면 순 베타가 그만큼 남는다.")
    print("  게다가 고베타는 정의상 시장 프리미엄을 더 먹는다. 상승장이")
    print("  길면 구조적으로 진다. 상대평가가 아니라 시장을 거스른 셈이다.")

    print(f"\n\n2. 베타가 맞는 짝 (베타차 <= {args.max_dbeta:.2f})\n")
    rows = []
    for a, b in combinations(sorted(betas), 2):
        db = abs(betas[a] - betas[b])
        if db > args.max_dbeta:
            continue
        common = [d for d in days if d in rets[a] and d in rets[b]]
        if len(common) < MIN_DAYS:
            continue
        sp = [rets[a][d] - rets[b][d] for d in common]
        drift = ann(sp)
        rev = reversion(sp)
        W = {a: 0.5, b: 0.5}
        rb = tranche(rets, cal, W, LO, HI, period=21)
        hd = tranche(rets, cal, W, LO, HI, period=0)
        if not rb or not hd:
            continue
        rows.append({"a": a, "b": b, "db": db, "drift": drift,
                     "rev": rev if rev is not None else 0.0,
                     "spvol": st.pdev if False else st.pstdev(sp) * math.sqrt(TRADING) * 100,
                     "bonus": rb["cagr"] - hd["cagr"],
                     "cagr": rb["cagr"], "sharpe": rb["sharpe"],
                     "mdd": rb["mdd"]})
    print(f"  짝 {len(rows)}개\n")
    print(f"  {'짝':<18}{'베타차':>8}{'표류':>9}{'스프레드σ':>11}{'회귀':>8}"
          f"{'되맞춤보너스':>13}{'50:50 샤프':>11}{'MDD':>9}")
    print("  " + "-" * 88)
    for r in sorted(rows, key=lambda x: -x["bonus"])[:args.top]:
        print(f"  {r['a']+'-'+r['b']:<18}{r['db']:>8.3f}{r['drift']:>+8.2f}%"
              f"{r['spvol']:>10.1f}%{r['rev']:>+8.2f}{r['bonus']:>+12.2f}%"
              f"{r['sharpe']:>11.2f}{r['mdd']:>+8.1f}%")

    print(f"\n\n3. 표류가 가장 작은 짝 — 어느 쪽도 이기지 않은 것들\n")
    print(f"  {'짝':<18}{'베타차':>8}{'표류':>9}{'스프레드σ':>11}{'회귀':>8}"
          f"{'되맞춤보너스':>13}{'50:50 샤프':>11}")
    print("  " + "-" * 80)
    for r in sorted(rows, key=lambda x: abs(x["drift"]))[:args.top]:
        print(f"  {r['a']+'-'+r['b']:<18}{r['db']:>8.3f}{r['drift']:>+8.2f}%"
              f"{r['spvol']:>10.1f}%{r['rev']:>+8.2f}{r['bonus']:>+12.2f}%"
              f"{r['sharpe']:>11.2f}")

    revs = [r["rev"] for r in rows if r["rev"]]
    print(f"\n\n  회귀 계수 분포: 최소 {min(revs):+.2f}  중앙 {st.median(revs):+.2f}"
          f"  최대 {max(revs):+.2f}   0보다 작은 것 "
          f"{sum(1 for v in revs if v < 0)}/{len(revs)}")
    print("  음수여야 '오르내린다'인데, 0 근처면 다음 구간을 알 수 없다는 뜻이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
