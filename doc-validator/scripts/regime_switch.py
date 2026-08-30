"""국면을 보고 헤지를 켰다 껐다 한다.

방향은 예측되지 않지만 변동성은 예측된다. 20일 블록 자기상관이 12개 칸
모두 양수(+0.21~+0.85)였다. 그러니 "지금이 위험한 국면인가"는 물어볼
여지가 있다. 오를지 내릴지를 묻는 것과 다른 질문이다.

규칙 넷을 시험한다. 전부 그날 종가까지의 정보만 쓰고 다음 날부터 적용한다.

    ma200      SPY가 200일선 아래면 위험
    vol        SPY 20일 실현변동성이 1년 중앙값의 1.3배를 넘으면 위험
    dd         SPY가 고점 대비 10% 아래면 위험
    ma_or_vol  둘 중 하나라도 걸리면 위험

위험 국면이면 위험자산 일부를 헤지로 옮긴다. 헤지는 현금(BIL)과
인버스(SH) 둘을 각각 시험한다. 평상시에는 헤지를 담지 않는다.

탐색 2010~2018 / 검증 2019~2022 / 최종 2023~2026으로 나눈다. 국면 규칙의
임계값을 탐색 구간에서 정하고 나머지는 확인만 한다.

    python scripts/regime_switch.py --data fixtures/wide
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

SEVEN = ["BTC/USD", "GLD", "TLT", "QQQ", "SPY", "069500", "VNQ"]
PERIODS = [("탐색", "2010-01-01", "2018-12-31"),
           ("검증", "2019-01-01", "2022-12-31"),
           ("최종", "2023-01-01", "2026-12-31")]
TRADING = 252
REBAL = 21
COST_BP = 10.0


def closes(store, sym):
    return {b.date: b.close for b in store._all_bars(sym)}


def regimes(spy: Dict[str, float], cal: List[str]) -> Dict[str, Dict[str, bool]]:
    """각 규칙이 그날 '위험'이라고 보는지. 그날 종가까지만 쓴다."""
    px = [spy[d] for d in cal if d in spy]
    days = [d for d in cal if d in spy]
    out = {k: {} for k in ("ma200", "vol", "dd", "ma_or_vol")}
    rets = [None] + [px[i] / px[i - 1] - 1 for i in range(1, len(px))]
    for i, d in enumerate(days):
        if i < 252:
            for k in out:
                out[k][d] = False
            continue
        ma200 = sum(px[i - 199:i + 1]) / 200
        below = px[i] < ma200
        seg = [r for r in rets[i - 19:i + 1] if r is not None]
        v20 = st.pstdev(seg) * math.sqrt(TRADING) if len(seg) > 2 else 0
        hist = []
        for j in range(i - 251, i + 1):
            s2 = [r for r in rets[max(1, j - 19):j + 1] if r is not None]
            if len(s2) > 2:
                hist.append(st.pstdev(s2) * math.sqrt(TRADING))
        med = st.median(hist) if hist else v20
        volhi = v20 > med * 1.3
        peak = max(px[max(0, i - 251):i + 1])
        ddhi = px[i] / peak - 1 < -0.10
        out["ma200"][d] = below
        out["vol"][d] = volhi
        out["dd"][d] = ddhi
        out["ma_or_vol"][d] = below or volhi
    return out


def simulate(px, cal, base, hedge, hedge_w, risk, lo, hi) -> Optional[Dict]:
    """risk가 True인 날에는 hedge_w만큼을 hedge로 돌린다."""
    days = [d for d in cal if lo <= d <= hi]
    held: Dict[str, float] = {}
    eq, peak, mdd, path, turn_tot = 1.0, 1.0, 0.0, [], 0.0
    on = False
    for k, d in enumerate(days):
        i = cal.index(d)
        prev = cal[i - 1] if i > 0 else None
        av = [s for s in base if d in px[s] and prev and prev in px[s]]
        if not av:
            continue
        if held:
            r = sum(held.get(s, 0) * (px[s][d] / px[s][prev] - 1)
                    for s in held if s in px and d in px[s] and prev in px[s])
            eq *= (1 + r)
            path.append(r)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
            g = {s: v * (1 + (px[s][d] / px[s][prev] - 1))
                 for s, v in held.items() if s in px and d in px[s] and prev in px[s]}
            t = sum(g.values())
            if t > 0:
                held = {s: v / t for s, v in g.items()}
        # 전날 종가 기준 국면으로 오늘 비중을 정한다
        want = risk.get(prev, False) if prev else False
        if not held or k % REBAL == 0 or want != on:
            hw = hedge_w if want else 0.0
            target = {s: (1 - hw) / len(av) for s in av}
            if hw > 0 and hedge in px and d in px[hedge]:
                target[hedge] = target.get(hedge, 0) + hw
            turn = sum(abs(target.get(s, 0) - held.get(s, 0))
                       for s in set(target) | set(held))
            turn_tot += turn
            eq *= (1 - turn * COST_BP / 10000)
            held = target
            on = want
    if len(path) < 200:
        return None
    sd = st.pstdev(path)
    yrs = len(path) / TRADING
    return {"cagr": (eq ** (1 / yrs) - 1) * 100 if eq > 0 else -100,
            "sharpe": st.mean(path) / sd * math.sqrt(TRADING) if sd else 0,
            "mdd": mdd * 100, "turn": turn_tot / yrs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))
    base = [s for s in SEVEN if store.has(s)]
    need = set(base) | {"SH", "BIL", "PSQ", "DBMF"}
    px = {s: closes(store, s) for s in need if store.has(s)}
    cal = sorted(px["SPY"])
    reg = regimes(px["SPY"], cal)

    for k in reg:
        on = sum(1 for d in cal if reg[k].get(d))
        print(f"  {k:<12} 위험 판정 {on:>5}일 / {len(cal)}일 ({on/len(cal)*100:.1f}%)")
    print()

    for hedge in ("BIL", "SH"):
        if hedge not in px:
            continue
        label = "현금" if hedge == "BIL" else "S&P 인버스"
        print(f"{'='*74}\n헤지 = {label} ({hedge}), 위험 국면에 40% 배정\n")
        print(f"  {'규칙':<14}" + "".join(f"{p[0]:>22}" for p in PERIODS))
        print(f"  {'':<14}" + "".join(f"{'CAGR   샤프    MDD':>22}" for _ in PERIODS))
        print("  " + "-" * 80)
        for rule in ("없음", "ma200", "vol", "dd", "ma_or_vol"):
            cells = []
            for _, lo, hi in PERIODS:
                risk = {} if rule == "없음" else reg[rule]
                m = simulate(px, cal, base, hedge, 0.40, risk, lo, hi)
                cells.append(f"{m['cagr']:>+7.1f}%{m['sharpe']:>7.2f}{m['mdd']:>+7.1f}%"
                             if m else f"{'-':>22}")
            print(f"  {rule:<14}" + "".join(cells))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
