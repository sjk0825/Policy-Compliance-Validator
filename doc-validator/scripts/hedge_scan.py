"""위기에 실제로 오르는 자산을 찾는다. 이름이 아니라 폭락일 성적으로.

리밸런싱으로 낙폭이 줄지 않는 이유는 담은 것들이 위기에 같이 빠지기
때문이다. 평상시 상관이 낮아도 폭락장에서 함께 무너지면 소용이 없다.
그래서 평상시 상관과 폭락일 성적을 따로 잰다.

    상관(전체)      평상시를 포함한 전 구간
    상관(폭락일)     SPY가 하위 5% 하락한 날만
    폭락일 평균수익   그 날들의 평균. 이것이 실제 방어력이다
    장기 CAGR      보험료. 평소에 얼마를 잃고 있는가

인버스와 변동성 상품은 방어력이 크지만 장기 수익이 크게 음수다. 방어를
사는 값이 있고, 그 값이 얼마인지가 이 표의 핵심이다.

    python scripts/hedge_scan.py --data fixtures/wide
"""
import argparse
import json
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

TRADING_DAYS = 252
CRASH_PCT = 0.05      # SPY 하위 5% 하락일을 위기로 본다
MIN_ROWS = 1000


def rets(store: PriceStore, sym: str) -> Dict[str, float]:
    b = store._all_bars(sym)
    return {b[i].date: b[i].close / b[i - 1].close - 1
            for i in range(1, len(b)) if b[i - 1].close}


def corr(a: List[float], b: List[float]) -> float:
    if len(a) < 30:
        return 0.0
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))
    manifest = json.loads((Path(args.data) / "manifest.json").read_text(encoding="utf-8"))

    spy = rets(store, "SPY")
    cal = sorted(spy)
    vals = sorted(spy.values())
    thr = vals[int(len(vals) * CRASH_PCT)]
    crash = {d for d in cal if spy[d] <= thr}
    print(f"기준: SPY 하위 {CRASH_PCT:.0%} 하락일 = 일간 {thr*100:.2f}% 이하")
    print(f"위기일 {len(crash)}일 / 전체 {len(cal)}일")
    print(f"그날 SPY 평균 {st.mean([spy[d] for d in crash])*100:+.2f}%\n")

    pool = [e["symbol"] for e in manifest["symbols"]
            if e["group"].endswith("_etf") and e["rows"] >= MIN_ROWS]
    pool = sorted(set(pool) | {"BTC/USD", "GLD", "TLT"})

    rows = []
    for s in pool:
        if not store.has(s) or s == "SPY":
            continue
        r = rets(store, s)
        common = [d for d in cal if d in r]
        if len(common) < MIN_ROWS:
            continue
        cd = [d for d in common if d in crash]
        if len(cd) < 40:
            continue
        eq = 1.0
        for d in common:
            eq *= (1 + r[d])
        yrs = len(common) / TRADING_DAYS
        rows.append({
            "sym": s,
            "corr_all": corr([spy[d] for d in common], [r[d] for d in common]),
            "corr_crash": corr([spy[d] for d in cd], [r[d] for d in cd]),
            "crash_ret": st.mean([r[d] for d in cd]) * 100,
            "cagr": ((eq ** (1 / yrs) - 1) * 100) if eq > 0 and yrs > 0 else -100,
            "n": len(common),
        })

    rows.sort(key=lambda x: -x["crash_ret"])
    print("위기일 평균수익 상위 (방어력 순)\n")
    print(f"  {'종목':<9}{'위기일 평균':>11}{'상관(전체)':>11}{'상관(위기)':>11}"
          f"{'장기 CAGR':>11}{'표본':>7}")
    print("  " + "-" * 62)
    for r in rows[:14]:
        print(f"  {r['sym']:<9}{r['crash_ret']:>+10.2f}%{r['corr_all']:>+11.2f}"
              f"{r['corr_crash']:>+11.2f}{r['cagr']:>+10.2f}%{r['n']:>7}")

    print("\n하위 (위기에 같이 빠지는 것들)\n")
    print(f"  {'종목':<9}{'위기일 평균':>11}{'상관(전체)':>11}{'상관(위기)':>11}"
          f"{'장기 CAGR':>11}{'표본':>7}")
    print("  " + "-" * 62)
    for r in rows[-6:]:
        print(f"  {r['sym']:<9}{r['crash_ret']:>+10.2f}%{r['corr_all']:>+11.2f}"
              f"{r['corr_crash']:>+11.2f}{r['cagr']:>+10.2f}%{r['n']:>7}")

    print("\n\n방어력을 사는 값. 위기일 +1%를 얻는 데 평소 얼마를 내는가\n")
    print(f"  {'종목':<9}{'위기일 평균':>11}{'장기 CAGR':>11}{'값(연 %/위기 %p)':>18}")
    print("  " + "-" * 52)
    ref = next((r for r in rows if r["sym"] == "GLD"), None)
    for r in rows[:12]:
        if r["crash_ret"] <= 0:
            continue
        # SPY 장기 CAGR을 기회비용으로 본다.
        spy_eq = 1.0
        for d in cal:
            spy_eq *= (1 + spy[d])
        spy_cagr = (spy_eq ** (252 / len(cal)) - 1) * 100
        cost = (spy_cagr - r["cagr"]) / r["crash_ret"]
        print(f"  {r['sym']:<9}{r['crash_ret']:>+10.2f}%{r['cagr']:>+10.2f}%"
              f"{cost:>17.2f}")
    print("\n  값이 작을수록 싸게 방어를 산다. 음수면 방어를 사면서 수익도 났다는 뜻이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
