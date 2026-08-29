"""방향이 랜덤일 때도 남는 것이 있는지 재본다.

지금까지 확인된 것은 "방향을 못 맞힌다"이지 "기회가 없다"가 아니다.
방향과 무관하게 성립하는 것이 둘 있고, 둘 다 예측을 요구하지 않는다.

1. 변동성은 예측된다.
   수익률의 부호는 자기상관이 없지만 크기는 강하게 뭉친다. 조용한 날
   뒤에는 조용한 날이, 시끄러운 날 뒤에는 시끄러운 날이 온다. 방향을
   몰라도 위험의 크기는 알 수 있다는 뜻이다.

2. 변동성 자체가 복리 수익을 갉아먹는다.
   산술평균이 같아도 변동이 크면 기하평균이 낮다. 그래서 변동을 줄이면
   맞히는 것 없이 복리 성과가 올라간다. 리밸런싱이 여기서 나온다.

전부 탐색·검증·최종 세 구간에서 따로 잰다. 한 구간에서만 되는 것은
앞서 여러 번 겪었다.

    python scripts/randomness_edge.py --data fixtures/wide
"""
import argparse
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

PERIODS = [("탐색", "2010-01-01", "2018-12-31"),
           ("검증", "2019-01-01", "2022-12-31"),
           ("최종", "2023-01-01", "2026-12-31")]
TRADING_DAYS = 252


def rets_of(store: PriceStore, sym: str) -> Tuple[List[str], List[float]]:
    bars = store._all_bars(sym)
    d, r = [], []
    for i in range(1, len(bars)):
        if bars[i - 1].close:
            d.append(bars[i].date)
            r.append(bars[i].close / bars[i - 1].close - 1)
    return d, r


def corr(a: List[float], b: List[float]) -> Optional[float]:
    if len(a) < 30:
        return None
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else None


def realized_vol(r: List[float]) -> float:
    if len(r) < 2:
        return 0.0
    return st.pstdev(r) * math.sqrt(TRADING_DAYS)


def part1(store: PriceStore, symbols: List[Tuple[str, str]], w: int = 20) -> None:
    """부호는 안 이어지고 크기는 이어지는지."""
    print(f"\n{'='*78}\n[1] 방향은 예측되지 않는데 변동성은 예측되는가 ({w}일 단위)\n")
    print(f"  {'종목':<16}{'구간':<6}{'표본':>6}"
          f"{'수익률 자기상관':>16}{'변동성 자기상관':>16}")
    print("  " + "-" * 62)
    for sym, label in symbols:
        if not store.has(sym):
            continue
        d, r = rets_of(store, sym)
        for pname, lo, hi in PERIODS:
            idx = [i for i, x in enumerate(d) if lo <= x <= hi]
            if len(idx) < 3 * w:
                continue
            lo_i, hi_i = idx[0], idx[-1]
            blocks = [(sum(r[i:i + w]), realized_vol(r[i:i + w]))
                      for i in range(lo_i, hi_i - w + 1, w)]
            if len(blocks) < 12:
                continue
            ret_now = [b[0] for b in blocks[:-1]]
            ret_nxt = [b[0] for b in blocks[1:]]
            vol_now = [b[1] for b in blocks[:-1]]
            vol_nxt = [b[1] for b in blocks[1:]]
            cr, cv = corr(ret_now, ret_nxt), corr(vol_now, vol_nxt)
            print(f"  {label:<16}{pname:<6}{len(blocks):>6}"
                  f"{(cr if cr is not None else 0):>+15.3f}"
                  f"{(cv if cv is not None else 0):>+15.3f}")
        print()


def sharpe(r: List[float]) -> Optional[float]:
    if len(r) < 60:
        return None
    sd = st.pstdev(r)
    return (st.mean(r) / sd * math.sqrt(TRADING_DAYS)) if sd else None


def cagr(r: List[float]) -> float:
    eq = 1.0
    for x in r:
        eq *= (1 + x)
    years = len(r) / TRADING_DAYS
    return (eq ** (1 / years) - 1) * 100 if years > 0 and eq > 0 else -100.0


def max_dd(r: List[float]) -> float:
    eq, peak, worst = 1.0, 1.0, 0.0
    for x in r:
        eq *= (1 + x)
        peak = max(peak, eq)
        worst = min(worst, eq / peak - 1)
    return worst * 100


def part2(store: PriceStore, symbols: List[Tuple[str, str]],
          target: float = 0.15, w: int = 20, cap: float = 2.0) -> None:
    """변동성을 맞춰 비중을 조절하면 위험조정 성과가 나아지는가."""
    print(f"\n{'='*78}\n[2] 변동성 목표제 — 방향을 맞히지 않고 비중만 조절한다")
    print(f"    비중 = 목표변동성 {target*100:.0f}% / 최근 {w}일 실현변동성 (최대 {cap:.0f}배)")
    print(f"    비중은 과거 {w}일만 보고 정한다. 미래를 쓰지 않는다.\n")
    print(f"  {'종목':<16}{'구간':<6}"
          f"{'보유 CAGR':>11}{'샤프':>7}{'MDD':>8}   "
          f"{'목표제 CAGR':>12}{'샤프':>7}{'MDD':>8}")
    print("  " + "-" * 80)
    for sym, label in symbols:
        if not store.has(sym):
            continue
        d, r = rets_of(store, sym)
        for pname, lo, hi in PERIODS:
            bh, vt = [], []
            for i, day in enumerate(d):
                if not (lo <= day <= hi) or i < w:
                    continue
                rv = realized_vol(r[i - w:i])          # 직전 w일까지만 쓴다
                lev = min(cap, target / rv) if rv > 1e-9 else cap
                bh.append(r[i])
                vt.append(lev * r[i])
            if len(bh) < 120:
                continue
            print(f"  {label:<16}{pname:<6}"
                  f"{cagr(bh):>+10.2f}%{(sharpe(bh) or 0):>7.2f}{max_dd(bh):>+7.1f}%   "
                  f"{cagr(vt):>+11.2f}%{(sharpe(vt) or 0):>7.2f}{max_dd(vt):>+7.1f}%")
        print()


def part3(store: PriceStore, pairs: List[Tuple[str, str, str]], w: int = 21) -> None:
    """서로 다르게 움직이는 둘을 주기적으로 되맞추면 남는 것이 있는가."""
    print(f"\n{'='*78}\n[3] 리밸런싱 프리미엄 — 예측 없이 비중만 되맞춘다")
    print(f"    50:50 유지, {w}거래일마다 재조정. 비교 대상은 같은 둘을 그냥 보유.\n")
    print(f"  {'조합':<22}{'구간':<6}{'상관':>7}"
          f"{'보유 CAGR':>11}{'리밸 CAGR':>11}{'차이':>9}{'보유 샤프':>10}{'리밸 샤프':>10}")
    print("  " + "-" * 88)
    for a, b, label in pairs:
        if not (store.has(a) and store.has(b)):
            continue
        da, ra = rets_of(store, a)
        db, rb = rets_of(store, b)
        mb = dict(zip(db, rb))
        joint = [(d, x, mb[d]) for d, x in zip(da, ra) if d in mb]
        for pname, lo, hi in PERIODS:
            seg = [(d, x, y) for d, x, y in joint if lo <= d <= hi]
            if len(seg) < 120:
                continue
            xs = [x for _, x, _ in seg]
            ys = [y for _, _, y in seg]
            bh_w = [0.5, 0.5]
            hold, rebal = [], []
            for i, (_, x, y) in enumerate(seg):
                # 그냥 보유: 비중이 수익률에 따라 흘러간다
                port = bh_w[0] * x + bh_w[1] * y
                tot = bh_w[0] * (1 + x) + bh_w[1] * (1 + y)
                bh_w = [bh_w[0] * (1 + x) / tot, bh_w[1] * (1 + y) / tot]
                hold.append(port)
                # 리밸런싱: 매 구간 50:50으로 되맞춘다
                rebal.append(0.5 * x + 0.5 * y)
            c = corr(xs, ys)
            ch, cr_ = cagr(hold), cagr(rebal)
            print(f"  {label:<22}{pname:<6}{(c or 0):>+6.2f}"
                  f"{ch:>+10.2f}%{cr_:>+10.2f}%{cr_-ch:>+8.2f}p"
                  f"{(sharpe(hold) or 0):>10.2f}{(sharpe(rebal) or 0):>10.2f}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data")
    args = ap.parse_args()
    store = PriceStore(Path(args.data) if args.data else None)

    singles = [("SPY", "SPY 미국"), ("QQQ", "QQQ 나스닥"),
               ("069500", "KODEX 200"), ("005930", "삼성전자")]
    pairs = [("SPY", "TLT", "SPY + 장기채"), ("SPY", "GLD", "SPY + 금"),
             ("QQQ", "GLD", "QQQ + 금"), ("069500", "GLD", "KODEX200 + 금")]

    part1(store, singles)
    part2(store, singles)
    part3(store, pairs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
