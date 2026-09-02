"""상대평가인데 왜 몇 년씩 마이너스가 나는가.

BAB는 저베타를 사고 고베타를 파는 자세를 계속 유지한다. "둘 중 나은
쪽을 고르는" 것이 아니라 방향이 고정된 베팅이다. 그러니 고베타가 이기는
국면이 오면 그 기간 내내 잃는다. 상대평가의 결과가 0을 중심으로
오르내려야 할 이유는 없다. 어느 한쪽이 몇 년씩 이기는 것이 정상이다.

세 가지를 보인다.

    1. 두 다리의 연도별 성적과 그 차이. 마이너스가 어디서 나오는지
    2. 레버리지가 그 차이를 얼마나 키우는지
    3. 방향을 고정하지 않고 추세를 따라가면 어떻게 되는지

3번이 형님이 떠올린 "상대평가"에 더 가까운 형태다. 스프레드 자체에
추세 필터를 걸어 오르고 있을 때만 들고, 아니면 현금으로 빠진다.
2005~2026에 자산별 추세 필터가 통했으므로 같은 규칙을 여기에도 건다.

    python scripts/spread_trend.py
"""
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import PriceStore                                  # noqa: E402
from btal_hibl import closes, daily_returns, summarize         # noqa: E402
from bab_factor import rolling_beta, clamp                     # noqa: E402

LOW, HIGH, MKT, RF = "SPLV", "SPHB", "SPY", "BIL"
LO, HI = "2012-05-07", "2026-12-31"
TRADING = 252
MA = 200
COST_BP = 10.0


def cum(rs: List[float]) -> float:
    e = 1.0
    for r in rs:
        e *= (1 + r)
    return (e - 1) * 100


def year_slice(rets, sym, cal, y) -> List[float]:
    return [rets[sym][d] for d in cal
            if f"{y}-01-01" <= d <= f"{y}-12-31" and d in rets[sym]]


def main() -> int:
    store = PriceStore(Path("fixtures/wide"))
    cal = sorted(closes(store, MKT))
    px = {s: closes(store, s) for s in (LOW, HIGH, MKT, RF)}
    rets = daily_returns(px, cal)
    bl = rolling_beta(rets, LOW, MKT, cal)
    bh = rolling_beta(rets, HIGH, MKT, cal)

    # 베타 중립 BAB (조달 스프레드 50bp, 비용 10bp)
    bab: Dict[str, float] = {}
    levs = []
    prev = None
    for d in cal:
        if not all(d in x for x in (rets[LOW], rets[HIGH], rets[RF], bl, bh)):
            continue
        if bl[d] <= 0 or bh[d] <= 0:
            continue
        wl, wh = clamp(1 / bl[d]), clamp(1 / bh[d])
        rf = rets[RF][d]
        r = wl * (rets[LOW][d] - rf) - wh * (rets[HIGH][d] - rf)
        r -= max(0.0, wl - 1.0) * 50 / 10000 / TRADING
        if prev:
            r -= (abs(wl - prev[0]) + abs(wh - prev[1])) * COST_BP / 10000
        prev = (wl, wh)
        levs.append((wl, wh))
        bab[d] = r + rf
    rets["BAB"] = bab
    # 레버리지 없는 순수 차이 (금액 중립)
    rets["DIFF"] = {d: rets[LOW][d] - rets[HIGH][d]
                    for d in cal if d in rets[LOW] and d in rets[HIGH]}

    years = list(range(2013, 2027))
    print("1. 두 다리와 그 차이 (%)\n")
    print(f"  {'':<22}" + "".join(f"{y % 100:>7}" for y in years))
    print("  " + "-" * (22 + 7 * len(years)))
    for label, s in [("SPLV  저베타", LOW), ("SPHB  고베타", HIGH),
                     ("차이  저-고", "DIFF"), ("BAB   베타중립", "BAB")]:
        cells = [f"{cum(year_slice(rets, s, cal, y)):+.1f}" for y in years]
        print(f"  {label:<22}" + "".join(f"{c:>7}" for c in cells))
    print("\n  '차이'가 음수인 해가 고베타가 이긴 해다. BAB는 그 해에 잃는다.")
    print("  둘 중 나은 쪽을 고르는 것이 아니라 저베타 쪽에 고정돼 있기 때문이다.")

    print("\n\n2. 구간을 나누면\n")
    print(f"  {'':<22}{'2012~2019':>14}{'2020~2026':>14}{'전체':>12}")
    print("  " + "-" * 64)
    for label, s in [("SPLV  누적", LOW), ("SPHB  누적", HIGH),
                     ("차이  연율", "DIFF"), ("BAB   연율", "BAB")]:
        a = [rets[s][d] for d in cal if "2012-05-07" <= d <= "2019-12-31" and d in rets[s]]
        b = [rets[s][d] for d in cal if "2020-01-01" <= d <= "2026-12-31" and d in rets[s]]
        c = [rets[s][d] for d in cal if LO <= d <= HI and d in rets[s]]
        if "누적" in label:
            print(f"  {label:<22}{cum(a):>+13.1f}%{cum(b):>+13.1f}%{cum(c):>+11.1f}%")
        else:
            f = lambda r: (summarize(r)["cagr"])
            print(f"  {label:<22}{f(a):>+13.2f}%{f(b):>+13.2f}%{f(c):>+11.2f}%")

    print(f"\n  레버리지: 저베타 다리 평균 {st.mean(a for a, _ in levs):.2f}배, "
          f"고베타 다리 {st.mean(b for _, b in levs):.2f}배")
    print(f"  둘을 합친 총노출이 {st.mean(a for a, _ in levs)+st.mean(b for _, b in levs):.2f}배다. "
          f"차이가 그만큼 증폭된다.")

    print("\n\n3. 방향을 고정하지 않으면 — 스프레드에 추세 필터\n")
    ds = [d for d in cal if d in bab]
    eq, idx = 1.0, {}
    for d in ds:
        eq *= (1 + bab[d])
        idx[d] = eq
    # 전일까지의 200일 평균으로 판정해 당일 적용
    sig: Dict[str, str] = {}
    run = 0.0
    for i, d in enumerate(ds):
        run += idx[d]
        if i >= MA:
            run -= idx[ds[i - MA]]
        if i >= MA - 1 and i + 1 < len(ds):
            sig[ds[i + 1]] = "long" if idx[d] > run / MA else "off"

    for label, on_off in [("항상 롱 (지금의 BAB)", None),
                          ("추세 위일 때만 롱, 아니면 현금", "cash"),
                          ("추세 위면 롱, 아래면 숏", "short")]:
        out = []
        prev_pos = 0
        for d in ds:
            if d not in sig:
                continue
            s = sig[d]
            pos = 1 if on_off is None else (1 if s == "long"
                                            else (0 if on_off == "cash" else -1))
            r = pos * (bab[d] - rets[RF][d]) + rets[RF][d]
            if pos != prev_pos:
                r -= abs(pos - prev_pos) * 20 / 10000   # 전환 20bp
            prev_pos = pos
            out.append((d, r))
        rr = [r for _, r in out]
        m = summarize(rr)
        ys = {}
        for y in years:
            v = [r for d, r in out if f"{y}-01-01" <= d <= f"{y}-12-31"]
            if len(v) > 150:
                ys[y] = cum(v)
        if not out:
            continue
        if label.startswith("항상"):
            print(f"  {'':<32}{'CAGR':>9}{'샤프':>7}{'MDD':>9}"
                  f"{'최악의 해':>10}{'마이너스 해':>12}")
            print("  " + "-" * 80)
        print(f"  {label:<32}{m['cagr']:>+8.2f}%{m['sharpe']:>7.2f}"
              f"{m['mdd']:>+8.1f}%{min(ys.values()):>+9.1f}%"
              f"{sum(1 for v in ys.values() if v < 0):>7}/{len(ys)}회")
    return 0


if __name__ == "__main__":
    sys.exit(main())
