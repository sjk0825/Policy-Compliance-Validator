"""승자를 자르는 되맞춤과 승자를 더 사는 되맞춤.

균등 되맞춤은 오른 것을 팔고 내린 것을 산다. 자산들의 기대수익이 같으면
이것이 프리미엄을 만들지만, 앞선 측정에서 7종의 개별 CAGR 격차가
40.7%p였고 그 상태에서는 되맞춤이 손해였다.

그렇다면 반대로 오른 것을 더 사는 방식은 어떤가. 다섯을 나란히 놓는다.

    equal      매번 1/N로 되돌린다. 승자를 자른다
    hold       손대지 않는다. 비중이 흘러가게 둔다
    momentum   직전 12개월 수익률 순위에 비례해 담는다
    top3       직전 12개월 상위 3개만 균등하게 담는다
    amplify    흘러간 비중을 제곱해 승자 쪽으로 더 기울인다

momentum과 top3는 과거 수익률을 쓰므로 예측에 해당한다. 횡단면 모멘텀은
앞서 700종목에서 재현되지 않았지만 자산군 7개 수준에서는 다를 수 있어
그대로 잰다. 판단은 결과가 한다.

hold는 새로 상장한 자산을 편입할 때만 손댄다. 그러지 않으면 비트코인이
평생 편입되지 않아 비교가 성립하지 않는다.

    python scripts/rebal_direction.py --data fixtures/wide
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
           ("최종", "2023-01-01", "2026-12-31"),
           ("전체", "2010-01-01", "2026-12-31")]
TRADING_DAYS = 252
REBAL = 21
LOOKBACK = 252
COST_BP = 10.0


def closes(store: PriceStore, sym: str) -> Dict[str, float]:
    return {b.date: b.close for b in store._all_bars(sym)}


def target_weights(mode: str, avail: List[str], drifted: Dict[str, float],
                   mom: Dict[str, Optional[float]]) -> Dict[str, float]:
    n = len(avail)
    if mode == "equal":
        return {s: 1.0 / n for s in avail}
    if mode == "hold":
        # 이미 담고 있는 것은 그대로 두고 새 자산만 1/N로 편입한다.
        cur = {s: drifted.get(s, 0.0) for s in avail}
        fresh = [s for s in avail if cur[s] <= 0]
        if not fresh:
            return cur
        room = 1.0 / n * len(fresh)
        scale = (1 - room) / sum(cur.values()) if sum(cur.values()) > 0 else 0
        w = {s: cur[s] * scale for s in avail}
        for s in fresh:
            w[s] = room / len(fresh)
        return w
    if mode in ("momentum", "top3"):
        scored = [(s, mom.get(s)) for s in avail if mom.get(s) is not None]
        if len(scored) < 3:
            return {s: 1.0 / n for s in avail}
        scored.sort(key=lambda x: -x[1])
        if mode == "top3":
            k = min(3, len(scored))
            top = [s for s, _ in scored[:k]]
            return {s: (1.0 / k if s in top else 0.0) for s in avail}
        # 순위 가중. 1등이 가장 많이, 꼴등이 가장 적게.
        m = len(scored)
        ranks = {s: m - i for i, (s, _) in enumerate(scored)}
        tot = sum(ranks.values())
        return {s: ranks.get(s, 0) / tot for s in avail}
    if mode == "amplify":
        cur = {s: max(drifted.get(s, 0.0), 1e-6) for s in avail}
        sq = {s: v ** 2 for s, v in cur.items()}
        tot = sum(sq.values())
        return {s: v / tot for s, v in sq.items()}
    raise ValueError(mode)


def simulate(px: Dict[str, Dict[str, float]], calendar: List[str], syms: List[str],
             lo: str, hi: str, mode: str) -> Optional[Dict]:
    days = [d for d in calendar if lo <= d <= hi]
    start = calendar.index(days[0]) if days else 0
    held: Dict[str, float] = {}
    eq, peak, mdd, path, turnover = 1.0, 1.0, 0.0, [], 0.0

    for k, d in enumerate(days):
        t = start + k
        avail = [s for s in syms if d in px[s]]
        if not avail:
            continue
        prev = calendar[t - 1] if t > 0 else None

        # 1. 어제 정한 비중을 오늘 수익률에 먼저 적용한다.
        #    순서를 바꾸면 오늘 종가를 보고 비중을 정한 뒤 그 비중으로
        #    오늘 수익을 먹는 셈이 된다. 그렇게 재면 룩백 1일·매일 조정에서
        #    샤프 9.79, CAGR +260%가 나온다. 있을 수 없는 값이고 미래를
        #    본 결과다.
        if held:
            port = 0.0
            for s in avail:
                if prev and prev in px[s] and px[s][prev]:
                    port += held.get(s, 0) * (px[s][d] / px[s][prev] - 1)
            eq *= (1 + port)
            path.append(port)
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
            grown = {}
            for s in avail:
                r = ((px[s][d] / px[s][prev] - 1)
                     if prev and prev in px[s] and px[s][prev] else 0.0)
                grown[s] = held.get(s, 0) * (1 + r)
            tot = sum(grown.values())
            if tot > 0:
                held = {s: v / tot for s, v in grown.items()}

        # 2. 그다음에 오늘 종가까지의 정보로 내일부터 쓸 비중을 정한다.
        if not held or k % REBAL == 0:
            mom: Dict[str, Optional[float]] = {}
            if t >= LOOKBACK:
                past = calendar[t - LOOKBACK]
                for s in avail:
                    if past in px[s] and px[s][past]:
                        mom[s] = px[s][d] / px[s][past] - 1
            target = target_weights(mode, avail, held, mom)
            turn = sum(abs(target.get(s, 0) - held.get(s, 0))
                       for s in set(target) | set(held))
            turnover += turn
            eq *= (1 - turn * COST_BP / 10000)
            held = target

    if len(path) < 200:
        return None
    sd = st.pstdev(path)
    yrs = len(path) / TRADING_DAYS
    return {"cagr": (eq ** (1 / yrs) - 1) * 100 if eq > 0 else -100,
            "sharpe": st.mean(path) / sd * math.sqrt(TRADING_DAYS) if sd else 0,
            "mdd": mdd * 100, "turn": turnover / yrs, "final": eq}


MODES = [("equal", "균등 되맞춤 (승자 자름)"), ("hold", "안 건드림"),
         ("momentum", "모멘텀 순위 가중"), ("top3", "상위 3개만"),
         ("amplify", "승자 증폭 (제곱)")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))
    syms = [s for s in SEVEN if store.has(s)]
    px = {s: closes(store, s) for s in syms}
    calendar = sorted(closes(store, "SPY"))

    print(f"자산 {len(syms)}개: {', '.join(syms)}   21일마다 조정, 비용 10bp\n")
    for pname, lo, hi in PERIODS:
        print(f"  === {pname} ({lo[:7]}~{hi[:7]})")
        print(f"  {'방식':<22}{'CAGR':>9}{'샤프':>8}{'MDD':>9}{'회전율':>9}{'배수':>9}")
        print("  " + "-" * 66)
        for mode, label in MODES:
            m = simulate(px, calendar, syms, lo, hi, mode)
            if m:
                print(f"  {label:<22}{m['cagr']:>+8.2f}%{m['sharpe']:>8.2f}"
                      f"{m['mdd']:>+8.1f}%{m['turn']:>8.1f}회{m['final']:>8.2f}배")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
