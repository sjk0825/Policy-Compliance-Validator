"""포트폴리오 알고리즘 여러 개와 라우터. 방향은 보지 않는다.

방향 예측 프로그램을 라우팅해도 소용이 없다. 재료가 전부 0이면 조합도
0이다. 그래서 예측이 아니라 추정에 기대는 것만 쓴다.

    μ (기대수익)   예측 불가. 3분할에서 확인했다.
    σ (변동성)     추정 가능. 20일 블록 자기상관이 12개 칸 전부 양수였다.
    ρ (상관)       추정 가능. 같은 성질을 가진다.

알고리즘 넷 모두 σ와 ρ만 입력으로 받는다. 어느 자산이 오를지는 묻지 않는다.

    equal        1/N 고정비중
    inv_vol      변동성 역수 비중. 위험을 균등하게 나눈다
    min_var      분산이 최소가 되는 비중
    max_premium  리밸런싱 프리미엄 wᵀdiag(Σ)w − wᵀΣw 를 최대로 하는 비중.
                 σ²(1−ρ)/4 를 포트폴리오로 일반화한 값이다

라우터 둘을 붙인다.

    rule         측정된 평균 상관이 높으면 min_var, 낮으면 max_premium
    adaptive     최근 250일 동안 가장 잘한 알고리즘을 고른다

전부 직전 120일까지만 보고 결정하고 다음 달에 적용한다. 탐색·검증·최종
세 구간에서 각각 잰다.

    python scripts/portfolio_router.py --data fixtures/wide
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
LOOKBACK = 120
REBAL = 21
COST_BP = 10.0
TRADING_DAYS = 252


def invert(m: List[List[float]]) -> Optional[List[List[float]]]:
    """가우스-조던. 특이행렬이면 None."""
    n = len(m)
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(a[r][c]))
        if abs(a[p][c]) < 1e-12:
            return None
        a[c], a[p] = a[p], a[c]
        piv = a[c][c]
        a[c] = [v / piv for v in a[c]]
        for r in range(n):
            if r == c:
                continue
            f = a[r][c]
            if f:
                a[r] = [v - f * w for v, w in zip(a[r], a[c])]
    return [row[n:] for row in a]


def cov(rets: List[List[float]]) -> List[List[float]]:
    n = len(rets)
    mu = [st.mean(r) for r in rets]
    m = len(rets[0])
    return [[sum((rets[i][k] - mu[i]) * (rets[j][k] - mu[j]) for k in range(m)) / (m - 1)
             for j in range(n)] for i in range(n)]


def normalize(w: List[float]) -> List[float]:
    w = [max(0.0, x) for x in w]
    s = sum(w)
    return [x / s for x in w] if s > 1e-9 else [1.0 / len(w)] * len(w)


def w_equal(S, n): return [1.0 / n] * n


def w_inv_vol(S, n):
    v = [math.sqrt(max(S[i][i], 1e-12)) for i in range(n)]
    return normalize([1.0 / x for x in v])


def w_min_var(S, n):
    # 대각을 살짝 키워 수치 안정성을 확보한다.
    R = [[S[i][j] + (1e-6 if i == j else 0) for j in range(n)] for i in range(n)]
    inv = invert(R)
    if inv is None:
        return w_inv_vol(S, n)
    raw = [sum(inv[i][j] for j in range(n)) for i in range(n)]
    return normalize(raw)


def w_max_premium(S, n):
    """wᵀdiag(Σ)w − wᵀΣw 를 키우는 방향으로 좌표 갱신.

    앞 항은 개별 자산의 변동성 손실, 뒤는 포트폴리오의 변동성 손실이다.
    차이가 리밸런싱으로 회수되는 몫이다.
    """
    w = [1.0 / n] * n
    for _ in range(200):
        grad = []
        for i in range(n):
            g = 2 * S[i][i] * w[i] - 2 * sum(S[i][j] * w[j] for j in range(n))
            grad.append(g)
        gm = st.mean(grad)
        w = normalize([w[i] + 0.05 * (grad[i] - gm) for i in range(n)])
    return w


ALGOS = {"equal": w_equal, "inv_vol": w_inv_vol,
         "min_var": w_min_var, "max_premium": w_max_premium}


def metrics(rets: List[float]) -> Dict[str, float]:
    eq, peak, mdd = 1.0, 1.0, 0.0
    for x in rets:
        eq *= (1 + x)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    sd = st.pstdev(rets)
    yrs = len(rets) / TRADING_DAYS
    return {"cagr": (eq ** (1 / yrs) - 1) * 100 if yrs > 0 and eq > 0 else -100,
            "sharpe": st.mean(rets) / sd * math.sqrt(TRADING_DAYS) if sd else 0,
            "mdd": mdd * 100}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    ap.add_argument("--assets",
                    default="SPY,QQQ,IWM,EEM,GLD,SLV,TLT,UUP,069500,BTC/USD")
    args = ap.parse_args()

    store = PriceStore(Path(args.data))
    syms = [s for s in args.assets.split(",") if store.has(s)]
    series = []
    for s in syms:
        b = store._all_bars(s)
        series.append({b[i].date: b[i].close / b[i - 1].close - 1
                       for i in range(1, len(b)) if b[i - 1].close})
    days = sorted(set.intersection(*[set(x) for x in series]))
    n = len(syms)
    print(f"자산 {n}개: {', '.join(syms)}")
    print(f"공통 거래일 {len(days):,}일  ({days[0]} ~ {days[-1]})")
    print(f"직전 {LOOKBACK}일로 추정, {REBAL}일마다 재조정, 비용 {COST_BP:.0f}bp\n")

    names = list(ALGOS) + ["route_rule", "route_adaptive"]
    paths: Dict[str, List[Tuple[str, float]]] = {k: [] for k in names}
    held: Dict[str, List[float]] = {k: [1.0 / n] * n for k in names}
    recent: Dict[str, List[float]] = {k: [] for k in ALGOS}

    for t in range(LOOKBACK, len(days) - 1):
        day = days[t]
        r_next = [series[i][days[t + 1]] for i in range(n)]

        if (t - LOOKBACK) % REBAL == 0:
            window = [[series[i][days[k]] for k in range(t - LOOKBACK, t)]
                      for i in range(n)]
            S = cov(window)
            cand = {k: fn(S, n) for k, fn in ALGOS.items()}

            # 라우터 1. 평균 상관이 높으면 분산 최소화, 낮으면 프리미엄 최대화.
            off = [S[i][j] / math.sqrt(max(S[i][i] * S[j][j], 1e-18))
                   for i in range(n) for j in range(n) if i != j]
            rho = st.mean(off)
            cand["route_rule"] = cand["min_var"] if rho > 0.35 else cand["max_premium"]

            # 라우터 2. 최근 250일 성적이 가장 좋았던 알고리즘을 고른다.
            best = max(ALGOS, key=lambda k: sum(recent[k][-250:]) if recent[k] else 0)
            cand["route_adaptive"] = cand[best]

            for k in names:
                turn = sum(abs(cand[k][i] - held[k][i]) for i in range(n))
                paths[k].append((day, -turn * COST_BP / 10000))
                held[k] = cand[k][:]

        for k in names:
            port = sum(held[k][i] * r_next[i] for i in range(n))
            paths[k].append((days[t + 1], port))
            # 비중은 수익률을 따라 흘러간다
            grown = [held[k][i] * (1 + r_next[i]) for i in range(n)]
            tot = sum(grown)
            if tot > 0:
                held[k] = [g / tot for g in grown]
        for k in ALGOS:
            recent[k].append(paths[k][-1][1])

    bench = {}
    for i, s in enumerate(syms):
        bench[s] = [(d, series[i][d]) for d in days[LOOKBACK:]]

    for pname, lo, hi in PERIODS:
        print(f"=== {pname} ({lo[:7]}~{hi[:7]})")
        print(f"  {'전략':<18}{'CAGR':>9}{'샤프':>8}{'MDD':>9}")
        print("  " + "-" * 44)
        for k in names:
            seg = [v for d, v in paths[k] if lo <= d <= hi]
            if len(seg) < 200:
                continue
            m = metrics(seg)
            tag = "  ←" if k.startswith("route") else ""
            print(f"  {k:<18}{m['cagr']:>+8.2f}%{m['sharpe']:>8.2f}{m['mdd']:>+8.1f}%{tag}")
        for s in ("SPY", "QQQ", "069500"):
            if s not in bench:
                continue
            seg = [v for d, v in bench[s] if lo <= d <= hi]
            if len(seg) < 200:
                continue
            m = metrics(seg)
            print(f"  {'(참고) ' + s:<18}{m['cagr']:>+8.2f}%{m['sharpe']:>8.2f}{m['mdd']:>+8.1f}%")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
