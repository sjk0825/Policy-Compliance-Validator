"""되맞춤 날짜를 흩뜨린다. 트랜치.

월 1회 되맞춤은 21일마다 한 번 손대는데, 그 한 번을 언제 하느냐에 따라
결과가 달라진다. 특정 날짜에 되맞춘 결과가 좋게 나왔다면 그것이 실력인지
그날의 운인지 구분되지 않는다.

트랜치는 자금을 21등분해 각각 다른 날에 월 1회 되맞춘다. 매일 전체의
1/21씩 손대므로 회전율은 월 1회와 같고, 시작일 선택의 운이 평균으로
씻긴다.

세 가지를 나란히 본다.

    시작일별 월 1회   21개 시작일 각각. 흩어진 정도가 곧 날짜 운의 크기다
    트랜치           21개를 균등하게 합친 것
    매일 전량 되맞춤   비교용. 회전율이 21배다

    python scripts/tranching.py --data fixtures/wide
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
TRADING = 252
COST_BP = 10.0


def closes(store: PriceStore, sym: str) -> Dict[str, float]:
    return {b.date: b.close for b in store._all_bars(sym)}


def path_of(px, cal, weights, lo, hi, period: int, offset: int) -> Optional[List[float]]:
    """offset일부터 period마다 되맞추는 경로의 일별 수익률."""
    days = [d for d in cal if lo <= d <= hi]
    held: Dict[str, float] = {}
    out: List[float] = []
    for k, d in enumerate(days):
        i = cal.index(d)
        prev = cal[i - 1] if i > 0 else None
        avail = [s for s in weights if d in px[s] and prev and prev in px[s]]
        avail_set = set(avail)
        if not avail:
            continue
        if held:
            r = sum(held.get(s, 0) * (px[s][d] / px[s][prev] - 1) for s in avail)
            out.append(r)
            # 휴장 종목은 보유를 유지한다. avail만 순회하면 그날 시장이
            # 닫힌 자산을 전량 매도해 나머지에 분배하는 셈이 된다.
            g = {s: (w * (px[s][d] / px[s][prev]) if s in avail_set else w)
                 for s, w in held.items()}
            tot = sum(g.values())
            if tot > 0:
                held = {s: v / tot for s, v in g.items()}
        if not held or (k - offset) % period == 0:
            w = {s: weights[s] for s in avail}
            tw = sum(w.values())
            target = {s: v / tw for s, v in w.items()} if tw > 0 else {}
            turn = sum(abs(target.get(s, 0) - held.get(s, 0))
                       for s in set(target) | set(held))
            if out:
                out[-1] -= turn * COST_BP / 10000
            held = target
    return out if len(out) > 200 else None


def stats(path: List[float]) -> Dict[str, float]:
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in path:
        eq *= (1 + x)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    sd = st.pstdev(path)
    yrs = len(path) / TRADING
    return {"cagr": (eq ** (1 / yrs) - 1) * 100 if eq > 0 else -100,
            "sharpe": st.mean(path) / sd * math.sqrt(TRADING) if sd else 0,
            "mdd": mdd * 100}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    ap.add_argument("--period", type=int, default=21)
    args = ap.parse_args()

    store = PriceStore(Path(args.data))
    base = [s for s in SEVEN if store.has(s)]
    hedged = dict({s: 0.65 / len(base) for s in base}, **{"DBMF": 0.15, "BTAL": 0.10, "UUP": 0.10})
    plain = {s: 1.0 / len(base) for s in base}
    cal = sorted(closes(store, "SPY"))

    for label, weights, lo, hi in [
            ("7종 균등", plain, "2010-01-01", "2026-12-31"),
            ("7종 + DBMF·BTAL·UUP", hedged, "2019-06-01", "2026-12-31")]:
        px = {s: closes(store, s) for s in weights if store.has(s)}
        print(f"\n{'='*70}\n[{label}]  {lo[:7]} ~ {hi[:7]}\n")

        paths = []
        for off in range(args.period):
            p = path_of(px, cal, weights, lo, hi, args.period, off)
            if p:
                paths.append(p)
        if not paths:
            continue
        res = [stats(p) for p in paths]
        cg = [r["cagr"] for r in res]
        sh = [r["sharpe"] for r in res]
        md = [r["mdd"] for r in res]

        print(f"  시작일 {len(paths)}개 각각 (월 1회 되맞춤)")
        print(f"    CAGR   최저 {min(cg):+.2f}%  중앙 {st.median(cg):+.2f}%  "
              f"최고 {max(cg):+.2f}%   폭 {max(cg)-min(cg):.2f}%p")
        print(f"    샤프   최저 {min(sh):.2f}   중앙 {st.median(sh):.2f}   "
              f"최고 {max(sh):.2f}    폭 {max(sh)-min(sh):.2f}")
        print(f"    MDD    최저 {min(md):+.1f}%  중앙 {st.median(md):+.1f}%  "
              f"최고 {max(md):+.1f}%")

        n = min(len(p) for p in paths)
        tranche = [st.mean([p[i] for p in paths]) for i in range(n)]
        t = stats(tranche)
        d1 = path_of(px, cal, weights, lo, hi, 1, 0)
        print(f"\n  {'방식':<24}{'CAGR':>9}{'샤프':>8}{'MDD':>9}")
        print("  " + "-" * 50)
        print(f"  {'월1회 (시작일 중앙값)':<24}{st.median(cg):>+8.2f}%"
              f"{st.median(sh):>8.2f}{st.median(md):>+8.1f}%")
        print(f"  {'트랜치 (21개 균등)':<24}{t['cagr']:>+8.2f}%{t['sharpe']:>8.2f}"
              f"{t['mdd']:>+8.1f}%  ←")
        if d1:
            s1 = stats(d1)
            print(f"  {'매일 전량 되맞춤':<24}{s1['cagr']:>+8.2f}%{s1['sharpe']:>8.2f}"
                  f"{s1['mdd']:>+8.1f}%")
    print("\n  트랜치는 회전율이 월 1회와 같다. 매일 전체의 1/21만 손대기 때문이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
