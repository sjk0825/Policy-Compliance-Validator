"""측정된 상관으로 자산을 고른다. 이름이 아니라 데이터로.

자산군 이름을 늘리는 것과 상관을 낮추는 것은 다른 일이었다. 부동산·
에너지·하이일드를 넣었더니 평균 상관이 0.10에서 0.19로 올랐다. 이름만
다르고 같이 움직였기 때문이다.

그래서 이름을 버리고 측정값으로 고른다. 매 재선정 시점에 직전 252일
상관만 보고, 이미 고른 것들과 가장 덜 닮은 자산을 하나씩 더한다.
수익률은 보지 않는다. 무엇이 오를지는 묻지 않고 무엇이 다르게 움직이는지만
묻는다. 상관은 추정 가능하고 방향은 아니라는 앞선 측정에 근거한다.

    시작   변동성이 가장 낮은 자산
    반복   이미 고른 집합과의 평균 상관이 가장 낮은 자산을 추가
    비중   균등, 21일마다 되맞춤

선정 자체를 과거 데이터로만 하므로 미래를 쓰지 않는다.

    python scripts/decorrelated_select.py --data fixtures/wide --n 10
"""
import argparse
import json
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
LOOKBACK = 252
RESELECT = 63      # 분기마다 다시 고른다
REBAL = 21
COST_BP = 10.0
MIN_HISTORY = 300

FIXED10 = ["SPY", "QQQ", "IWM", "EEM", "GLD", "SLV", "TLT", "UUP", "069500", "BTC/USD"]


def rets(store: PriceStore, sym: str) -> Dict[str, float]:
    b = store._all_bars(sym)
    return {b[i].date: b[i].close / b[i - 1].close - 1
            for i in range(1, len(b)) if b[i - 1].close}


def corr_of(x: List[float], y: List[float]) -> float:
    mx, my = st.mean(x), st.mean(y)
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = math.sqrt(sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y))
    return num / den if den else 0.0


def select(window: Dict[str, List[float]], n: int) -> List[str]:
    """가장 덜 닮은 n개를 탐욕적으로 고른다. 수익률은 쓰지 않는다."""
    syms = list(window)
    if len(syms) <= n:
        return syms
    C: Dict[Tuple[str, str], float] = {}

    def c(a: str, b: str) -> float:
        key = (a, b) if a < b else (b, a)
        if key not in C:
            C[key] = corr_of(window[a], window[b])
        return C[key]

    # 첫 자산은 변동성이 가장 낮은 것. 수익률과 무관한 기준이다.
    chosen = [min(syms, key=lambda s: st.pstdev(window[s]))]
    while len(chosen) < n:
        best, best_v = None, None
        for s in syms:
            if s in chosen:
                continue
            v = st.mean([c(s, t) for t in chosen])
            if best_v is None or v < best_v:
                best, best_v = s, v
        if best is None:
            break
        chosen.append(best)
    return chosen


def simulate(series: Dict[str, Dict[str, float]], calendar: List[str],
             lo: str, hi: str, n: int, pool: Optional[List[str]] = None,
             fixed: Optional[List[str]] = None) -> Optional[Dict]:
    days = [d for d in calendar if lo <= d <= hi]
    if len(days) < 200:
        return None
    start = calendar.index(days[0])
    held: Dict[str, float] = {}
    chosen: List[str] = fixed or []
    eq, peak, mdd, path, rhos = 1.0, 1.0, 0.0, [], []

    for k, d in enumerate(days):
        t = start + k
        if fixed is None and (k % RESELECT == 0 or not chosen):
            if t < LOOKBACK:
                continue
            hist = calendar[t - LOOKBACK:t]
            window = {}
            for s in pool:
                vals = [series[s][x] for x in hist if x in series[s]]
                if len(vals) >= LOOKBACK * 0.9:
                    window[s] = vals
            if len(window) >= n:
                chosen = select(window, n)
                cs = [corr_of(window[a], window[b])
                      for i, a in enumerate(chosen) for b in chosen[i + 1:]]
                rhos.append(st.mean(cs) if cs else 0.0)
        avail = [s for s in chosen if d in series[s]]
        avail_set = set(avail)
        if not avail:
            continue
        if not held or k % REBAL == 0:
            target = {s: 1.0 / len(avail) for s in avail}
            turn = sum(abs(target.get(s, 0) - held.get(s, 0))
                       for s in set(target) | set(held))
            eq *= (1 - turn * COST_BP / 10000)
            held = target
        port = sum(held.get(s, 0) * series[s][d] for s in avail)
        eq *= (1 + port)
        path.append(port)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
        # 휴장 종목은 보유를 유지한다. avail만 순회하면 그날 시장이
        # 닫힌 자산을 전량 매도해 나머지에 분배하는 셈이 되는데,
        # 실제로는 평가액이 그대로일 뿐 계속 들고 있다.
        grown = {s: (w * (1 + series[s][d]) if s in avail_set else w)
                 for s, w in held.items()}
        tot = sum(grown.values())
        if tot > 0:
            held = {s: v / tot for s, v in grown.items()}

    if len(path) < 200:
        return None
    sd = st.pstdev(path)
    yrs = len(path) / TRADING_DAYS
    return {"cagr": (eq ** (1 / yrs) - 1) * 100 if eq > 0 else -100,
            "sharpe": st.mean(path) / sd * math.sqrt(TRADING_DAYS) if sd else 0,
            "mdd": mdd * 100, "rho": st.mean(rhos) if rhos else None,
            "last": chosen}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--drift-filter", action="store_true",
                    help="구조적으로 기대수익이 0이거나 음수인 것을 뺀다. "
                         "인버스·레버리지·현금성·통화가 대상이다. 이것은 예측이 "
                         "아니라 상품 구조에서 나오는 사실이다.")
    args = ap.parse_args()

    store = PriceStore(Path(args.data))
    manifest = json.loads((Path(args.data) / "manifest.json").read_text(encoding="utf-8"))
    # 후보는 ETF와 지수형만. 개별주 500개를 넣으면 서로 닮은 것들이라
    # 상관 최소화가 유동성 낮은 이상치를 고르는 쪽으로 흐른다.
    pool = [e["symbol"] for e in manifest["symbols"]
            if e["group"].endswith("_etf") and e["rows"] >= MIN_HISTORY]
    pool = sorted(set(pool) | {"BTC/USD"})
    pool = [s for s in pool if store.has(s)]
    # 인버스는 장기 기대수익이 음수이고, 초단기채·통화는 0에 가깝다.
    # 상관만 최소화하면 이런 것들로 채워져 복리로 불어날 것이 남지 않는다.
    NO_DRIFT = {"114800",            # KODEX 인버스
                "122630",            # KODEX 레버리지 (변동성 손실이 크다)
                "BIL", "SHY",        # 현금성
                "UUP", "FXE", "FXY"} # 통화
    if args.drift_filter:
        pool = [s for s in pool if s not in NO_DRIFT]
        print(f"[필터] 인버스·레버리지·현금성·통화 제외 → 후보 {len(pool)}개")

    series = {s: rets(store, s) for s in set(pool) | set(FIXED10) | {"SPY", "QQQ"}
              if store.has(s)}
    calendar = sorted(series["SPY"])
    print(f"후보 {len(pool)}개 (ETF·지수형), 재선정 {RESELECT}일, 상관 창 {LOOKBACK}일")
    print(f"선정은 직전 {LOOKBACK}일 상관만 본다. 수익률은 쓰지 않는다.\n")

    for pname, lo, hi in PERIODS:
        print(f"  === {pname} ({lo[:7]}~{hi[:7]})")
        print(f"  {'전략':<24}{'CAGR':>9}{'샤프':>8}{'MDD':>9}{'평균 ρ':>9}")
        print("  " + "-" * 60)
        m = simulate(series, calendar, lo, hi, args.n, pool=pool)
        if m:
            print(f"  {f'상관최소 {args.n}개 (자동)':<24}{m['cagr']:>+8.2f}%"
                  f"{m['sharpe']:>8.2f}{m['mdd']:>+8.1f}%"
                  f"{(m['rho'] if m['rho'] is not None else 0):>+9.2f}  ←")
        f10 = [s for s in FIXED10 if s in series]
        m2 = simulate(series, calendar, lo, hi, len(f10), fixed=f10)
        if m2:
            print(f"  {'고정 10자산':<24}{m2['cagr']:>+8.2f}%{m2['sharpe']:>8.2f}"
                  f"{m2['mdd']:>+8.1f}%{'':>9}")
        for s, label in (("SPY", "(참고) SPY"), ("QQQ", "(참고) QQQ")):
            m3 = simulate(series, calendar, lo, hi, 1, fixed=[s])
            if m3:
                print(f"  {label:<24}{m3['cagr']:>+8.2f}%{m3['sharpe']:>8.2f}"
                      f"{m3['mdd']:>+8.1f}%{'':>9}")
        if m and m.get("last"):
            print(f"    마지막 선정: {', '.join(m['last'])}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
