"""자산마다 각자의 추세를 보고 현금으로 뺀다.

regime_switch.py는 SPY 하나로 국면을 판정해 헤지 전체를 켜고 껐다.
그 방식은 SPY가 버티는 동안 다른 자산이 무너지는 해를 놓친다. 2022년이
그랬다. TLT는 1월부터, QQQ는 2월부터, VNQ는 4월부터 각자 다른 시점에
추세를 깼다. 하나의 스위치로는 이 어긋남을 표현할 수 없다.

여기서는 자산마다 독립적으로 판정한다. 어떤 자산이 자기 추세 아래로
내려가면 그 몫만 현금(BIL)으로 옮기고 나머지는 그대로 둔다. 예측이 아니라
"지금 오르고 있는 것만 들고 간다"는 규칙이고, 방향을 맞히지 못해도
성립한다는 점에서 이 프로젝트가 지금까지 확인한 것과 어긋나지 않는다.

규칙은 셋. 전부 전일 종가까지만 쓰고 당일부터 적용한다.

    ma{N}     종가가 N일 이동평균 위
    mom{M}    최근 M개월 수익률이 0 위
    dual{N}   둘 다 만족

탐색 2010~2018 / 검증 2019~2022 / 최종 2023~2026으로 나눈다. 파라미터는
탐색에서만 고르고 나머지는 확인만 한다. 국면 규칙이 파라미터에 민감했던
전례가 있으므로, 격자 전체를 세 구간에 나란히 놓고 본다.

    python scripts/trend_overlay.py --data fixtures/wide
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

from engine import PriceStore                     # noqa: E402
from btal_hibl import closes, daily_returns, summarize   # noqa: E402

SEVEN = ["BTC/USD", "GLD", "TLT", "QQQ", "SPY", "069500", "VNQ"]
CASH = "BIL"
PERIODS = [("탐색", "2010-01-01", "2018-12-31"),
           ("검증", "2019-01-01", "2022-12-31"),
           ("최종", "2023-01-01", "2026-12-31")]
CRISES = [("2020 코로나", "2020-02-19", "2020-03-23"),
          ("2022 인플레", "2022-01-01", "2022-10-12"),
          ("2018 4분기", "2018-10-01", "2018-12-24")]
TRADING = 252
PERIOD = 21
COST_BP = 10.0


def sma_signal(px: Dict[str, float], cal: List[str], n: int) -> Dict[str, bool]:
    """전일 종가가 전일까지의 n일 이동평균 위인가. 당일 값은 안 쓴다."""
    ds = [d for d in cal if d in px]
    out: Dict[str, bool] = {}
    run = 0.0
    for i, d in enumerate(ds):
        run += px[d]
        if i >= n:
            run -= px[ds[i - n]]
        if i >= n - 1 and i + 1 < len(ds):
            out[ds[i + 1]] = px[d] > run / n     # i까지로 판정 -> i+1에 적용
    return out


def mom_signal(px: Dict[str, float], cal: List[str], months: int) -> Dict[str, bool]:
    n = months * 21
    ds = [d for d in cal if d in px]
    out: Dict[str, bool] = {}
    for i in range(n, len(ds) - 1):
        out[ds[i + 1]] = px[ds[i]] > px[ds[i - n]]
    return out


def build_signals(px, cal, rule: str) -> Dict[str, Dict[str, bool]]:
    sig: Dict[str, Dict[str, bool]] = {}
    for s in px:
        if rule == "none":
            sig[s] = {}
            continue
        if rule.startswith("ma"):
            sig[s] = sma_signal(px[s], cal, int(rule[2:]))
        elif rule.startswith("mom"):
            sig[s] = mom_signal(px[s], cal, int(rule[3:]))
        elif rule.startswith("dual"):
            n = int(rule[4:])
            a = sma_signal(px[s], cal, n)
            b = mom_signal(px[s], cal, 12)
            sig[s] = {d: a[d] and b.get(d, False) for d in a}
    return sig


def one_path(rets, sig, days, base: Dict[str, float],
             period: int, offset: int, on: bool) -> List[float]:
    held: Dict[str, float] = {}
    out: List[float] = []
    for k, d in enumerate(days):
        avail = [s for s in list(base) + [CASH] if d in rets.get(s, {})]
        aset = set(avail)
        if not avail:
            continue
        if held:
            out.append(sum(w * rets[s][d] for s, w in held.items() if s in aset))
            g = {s: (w * (1 + rets[s][d]) if s in aset else w)
                 for s, w in held.items()}
            t = sum(g.values())
            if t > 0:
                held = {s: v / t for s, v in g.items()}
        if not held or (k - offset) % period == 0:
            tgt: Dict[str, float] = {}
            for s, w in base.items():
                if s not in aset:
                    continue
                # 신호가 아직 없는 자산(표본 부족)은 보유로 본다
                keep = (not on) or sig.get(s, {}).get(d, True)
                if keep:
                    tgt[s] = tgt.get(s, 0) + w
                elif CASH in aset:
                    tgt[CASH] = tgt.get(CASH, 0) + w
            tw = sum(tgt.values())
            tgt = {s: v / tw for s, v in tgt.items()} if tw > 0 else {}
            turn = sum(abs(tgt.get(s, 0) - held.get(s, 0))
                       for s in set(tgt) | set(held))
            if out:
                out[-1] -= turn * COST_BP / 10000
            held = tgt
    return out


def run(rets, sig, cal, base, lo, hi, on=True, min_days=60) -> Optional[Dict]:
    days = [d for d in cal if lo <= d <= hi]
    paths = [p for p in (one_path(rets, sig, days, base, PERIOD, o, on)
                         for o in range(PERIOD)) if len(p) >= min_days]
    if not paths:
        return None
    n = min(len(p) for p in paths)
    return summarize([st.mean([p[i] for p in paths]) for i in range(n)])


def worst_year(rets, sig, cal, base, lo, hi, on) -> Optional[float]:
    ys = [int(lo[:4]), int(hi[:4])]
    vals = []
    for y in range(ys[0], ys[1] + 1):
        a = run(rets, sig, cal, base, f"{y}-01-01", f"{y}-12-31", on, min_days=150)
        if a:
            vals.append(a["total"])
    return min(vals) if vals else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))
    cal = sorted(closes(store, "SPY"))
    E_HEDGE = {"DBMF": 0.15, "BTAL": 0.10, "UUP": 0.10}
    syms = list(dict.fromkeys(SEVEN + list(E_HEDGE) + [CASH]))
    px = {s: closes(store, s) for s in syms}
    rets = daily_returns(px, cal)

    base7 = {s: 1 / len(SEVEN) for s in SEVEN}
    baseE = {s: (1 - sum(E_HEDGE.values())) / len(SEVEN) for s in SEVEN}
    for s, v in E_HEDGE.items():
        baseE[s] = v

    RULES = ["none", "ma100", "ma150", "ma200", "ma250",
             "mom6", "mom12", "dual200"]
    sigs = {r: build_signals(px, cal, r) for r in RULES}

    print("자산별 추세 필터. 자기 추세 아래로 내려간 자산의 몫만 현금으로.\n")
    print(f"기준 포트폴리오 = 7종 균등 (BTC GLD TLT QQQ SPY KODEX200 VNQ)")
    print(f"되맞춤 21일 트랜치 / 비용 {COST_BP:.0f}bp / 현금 {CASH}\n")

    print("1. 세 구간에 나란히 — 샤프\n")
    head = "".join(f"{p[0]:>10}" for p in PERIODS)
    print(f"  {'규칙':<10}{head}{'  |':>4}" + "".join(f"{p[0]+' MDD':>12}" for p in PERIODS))
    print("  " + "-" * 80)
    for r in RULES:
        row, mdds = [], []
        for _, lo, hi in PERIODS:
            m = run(rets, sigs[r], cal, base7, lo, hi)
            row.append(f"{m['sharpe']:.2f}" if m else "-")
            mdds.append(f"{m['mdd']:+.1f}%" if m else "-")
        print(f"  {r:<10}" + "".join(f"{c:>10}" for c in row) + f"{'  |':>4}"
              + "".join(f"{c:>12}" for c in mdds))

    print("\n\n2. 전 구간 (2010~2026, 7종 균등)\n")
    print(f"  {'규칙':<10}{'CAGR':>10}{'샤프':>8}{'변동성':>8}{'MDD':>10}"
          f"{'최악의 해':>10}{'현금 비중':>10}")
    print("  " + "-" * 68)
    for r in RULES:
        m = run(rets, sigs[r], cal, base7, "2010-01-01", "2026-12-31")
        w = worst_year(rets, sigs[r], cal, base7, "2011-01-01", "2026-12-31", True)
        # 평균 현금 비중
        days = [d for d in cal if "2010-01-01" <= d <= "2026-12-31"]
        if r == "none":
            cashw = 0.0
        else:
            offs = [sum(0 if sigs[r].get(s, {}).get(d, True) else base7[s]
                        for s in SEVEN) for d in days[::5]]
            cashw = st.mean(offs) * 100
        print(f"  {r:<10}{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}{m['vol']:>7.1f}%"
              f"{m['mdd']:>+9.1f}%{w:>+9.1f}%{cashw:>9.1f}%")

    print("\n\n3. 연도별 (7종 균등, %)\n")
    years = list(range(2011, 2027))
    print(f"  {'':<10}" + "".join(f"{y%100:>7}" for y in years))
    print("  " + "-" * (10 + 7 * len(years)))
    for r in ["none", "ma200", "mom12", "dual200"]:
        cells = []
        for y in years:
            a = run(rets, sigs[r], cal, base7, f"{y}-01-01", f"{y}-12-31",
                    min_days=150)
            cells.append(f"{a['total']:+.1f}" if a else "-")
        print(f"  {r:<10}" + "".join(f"{c:>7}" for c in cells))

    print("\n\n4. 위기 구간 (7종 균등, %)\n")
    print(f"  {'':<10}" + "".join(f"{c[0]:>14}" for c in CRISES))
    print("  " + "-" * 52)
    for r in ["none", "ma200", "mom12", "dual200"]:
        cells = []
        for _, lo, hi in CRISES:
            a = run(rets, sigs[r], cal, base7, lo, hi, min_days=20)
            cells.append(f"{a['total']:+.1f}%" if a else "-")
        print(f"  {r:<10}" + "".join(f"{c:>14}" for c in cells))

    print("\n\n5. E 조합에 얹으면 (DBMF 상장 이후 2019-06~)\n")
    print(f"  {'조합':<22}{'CAGR':>10}{'샤프':>8}{'변동성':>8}{'MDD':>10}{'최악의 해':>10}")
    print("  " + "-" * 68)
    for label, base, r in [("7종만", base7, "none"),
                           ("7종 + ma200", base7, "ma200"),
                           ("E 조합", baseE, "none"),
                           ("E + ma200", baseE, "ma200"),
                           ("E + mom12", baseE, "mom12"),
                           ("E + dual200", baseE, "dual200")]:
        m = run(rets, sigs[r], cal, base, "2019-06-01", "2026-12-31")
        w = worst_year(rets, sigs[r], cal, base, "2020-01-01", "2026-12-31",
                       r != "none")
        print(f"  {label:<22}{m['cagr']:>+9.2f}%{m['sharpe']:>8.2f}{m['vol']:>7.1f}%"
              f"{m['mdd']:>+9.1f}%{w:>+9.1f}%")

    print(f"\n  연도별 (%)\n")
    ys = list(range(2020, 2027))
    print(f"  {'':<22}" + "".join(f"{y:>8}" for y in ys))
    print("  " + "-" * (22 + 8 * len(ys)))
    for label, base, r in [("E 조합", baseE, "none"),
                           ("E + ma200", baseE, "ma200"),
                           ("E + mom12", baseE, "mom12"),
                           ("E + dual200", baseE, "dual200")]:
        cells = []
        for y in ys:
            a = run(rets, sigs[r], cal, base, f"{y}-01-01", f"{y}-12-31",
                    min_days=150)
            cells.append(f"{a['total']:+.1f}" if a else "-")
        print(f"  {label:<22}" + "".join(f"{c:>8}" for c in cells))
    return 0


if __name__ == "__main__":
    sys.exit(main())
