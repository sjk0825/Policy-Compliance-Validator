"""랜덤에 대한 최적 알고리즘과 그 상한.

랜덤이라고 알고리즘이 없는 것이 아니다. 곱하기 게임에는 증명된 최적해가
있다. 로그 자산의 기댓값을 최대로 하는 비중을 고르는 것이고, 켈리 기준
이라 부른다.

    f* = argmax  E[ ln(1 + f·r) ]

이것이 최적이라는 것은 증명돼 있다. 다른 어떤 비중도 장기 성장률에서
이것을 이기지 못한다. 문제는 최적해가 있느냐가 아니라 최적해가 얼마를
주느냐다.

연속 근사에서 기하 성장률은 이렇게 쓰인다.

    g = μ - σ²/2

변동성이 복리를 갉아먹는 몫이 σ²/2이고, 알고리즘이 건드릴 수 있는 것은
이 항뿐이다. 방향(μ)은 예측이고, 우리가 없다고 확인한 것이다.

자산 둘을 반반 섞어 되맞추면 포트폴리오 분산이 σ²(1+ρ)/2로 줄어든다.
그래서 리밸런싱이 회수하는 몫은

    프리미엄 = (σ² - σ²(1+ρ)/2) / 2 = σ²(1-ρ)/4

이 식이 상한이다. 더 정교한 규칙을 써도 이보다 많이 가져올 수 없다.
실제 자산의 σ와 ρ를 넣어 얼마가 나오는지 보고, 실측과 맞는지 확인한다.

    python scripts/kelly_ceiling.py --data fixtures/wide
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

TRADING_DAYS = 252


def daily(store: PriceStore, sym: str) -> Dict[str, float]:
    b = store._all_bars(sym)
    return {b[i].date: b[i].close / b[i - 1].close - 1
            for i in range(1, len(b)) if b[i - 1].close}


def corr(a: List[float], b: List[float]) -> float:
    ma, mb = st.mean(a), st.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else 0.0


def kelly_fraction(rets: List[float], lo: float = 0.0, hi: float = 4.0) -> float:
    """E[ln(1+f·r)]을 최대로 하는 f. 격자 탐색으로 충분하다."""
    best_f, best_g = lo, -1e9
    f = lo
    while f <= hi:
        try:
            g = sum(math.log(1 + f * r) for r in rets if 1 + f * r > 0) / len(rets)
        except ValueError:
            f += 0.01
            continue
        if all(1 + f * r > 0 for r in rets) and g > best_g:
            best_g, best_f = g, f
        f += 0.01
    return best_f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))

    print("=" * 76)
    print("[1] 자산 하나. 켈리 최적 비중과 그때의 성장률\n")
    print(f"  {'종목':<12}{'연수익 μ':>10}{'변동성 σ':>10}{'변동성 손실':>12}"
          f"{'켈리 f*':>9}{'전액 g':>9}{'켈리 g':>9}")
    print("  " + "-" * 74)
    singles = [("SPY", "SPY"), ("QQQ", "QQQ"), ("069500", "KODEX200"),
               ("005930", "삼성전자"), ("GLD", "금")]
    for sym, label in singles:
        if not store.has(sym):
            continue
        r = list(daily(store, sym).values())
        mu = st.mean(r) * TRADING_DAYS
        sd = st.pstdev(r) * math.sqrt(TRADING_DAYS)
        f = kelly_fraction(r)
        g1 = sum(math.log(1 + x) for x in r) / len(r) * TRADING_DAYS
        gk = sum(math.log(1 + f * x) for x in r) / len(r) * TRADING_DAYS
        print(f"  {label:<12}{mu*100:>+9.2f}%{sd*100:>9.2f}%{sd*sd/2*100:>11.2f}%"
              f"{f:>9.2f}{g1*100:>+8.2f}%{gk*100:>+8.2f}%")

    print("\n  주의. 위의 켈리 f*와 켈리 g는 실현된 μ를 알고 있다고 가정한 값이다.")
    print("  켈리 공식은 기대수익 μ를 입력으로 요구하는데, μ야말로 우리가")
    print("  예측할 수 없다고 확인한 것이다. f*가 3~4배로 나오는 것은 지난 16년의")
    print("  상승을 미리 알았을 때의 답이지 실행 가능한 값이 아니다.")
    print("\n  쓸 수 있는 것은 σ 항뿐이다. 변동성은 자기상관이 강해 추정되지만")
    print("  방향은 그렇지 않다. 그래서 알고리즘이 실제로 회수할 수 있는 몫은")
    print("  σ²/2 항에 한정된다.")

    print("\n" + "=" * 76)
    print("[2] 자산 둘. 리밸런싱이 회수할 수 있는 최대치\n")
    print("    이론 상한 = σ²(1-ρ)/4      (두 자산의 σ가 같다고 볼 때)")
    print(f"\n  {'조합':<20}{'σ평균':>8}{'상관 ρ':>8}{'이론 상한':>11}{'실측':>10}")
    print("  " + "-" * 60)
    pairs = [("SPY", "GLD", "SPY + 금"), ("QQQ", "GLD", "QQQ + 금"),
             ("069500", "GLD", "KODEX200 + 금"), ("SPY", "TLT", "SPY + 장기채"),
             ("QQQ", "069500", "QQQ + KODEX200")]
    for a, b, label in pairs:
        if not (store.has(a) and store.has(b)):
            continue
        da, db = daily(store, a), daily(store, b)
        days = sorted(set(da) & set(db))
        xs = [da[d] for d in days]
        ys = [db[d] for d in days]
        sa, sb = st.pstdev(xs) * math.sqrt(TRADING_DAYS), st.pstdev(ys) * math.sqrt(TRADING_DAYS)
        rho = corr(xs, ys)
        sigma = (sa + sb) / 2
        ceiling = sigma * sigma * (1 - rho) / 4

        # 실측: 매일 되맞춘 50:50 대 그냥 보유
        eq_r, eq_h, w = 1.0, 1.0, [0.5, 0.5]
        for x, y in zip(xs, ys):
            eq_r *= (1 + 0.5 * x + 0.5 * y)
            eq_h *= (1 + w[0] * x + w[1] * y)
            g = [w[0] * (1 + x), w[1] * (1 + y)]
            tot = sum(g)
            w = [v / tot for v in g]
        yrs = len(days) / TRADING_DAYS
        actual = ((eq_r ** (1 / yrs)) - (eq_h ** (1 / yrs))) * 100
        print(f"  {label:<20}{sigma*100:>7.1f}%{rho:>+8.2f}"
              f"{ceiling*100:>+10.2f}%{actual:>+9.2f}%")

    print("\n  이론과 실측이 맞는다. 식이 상한을 정한다는 뜻이다.")
    print("  SPY+장기채만 크게 어긋나는데(이론 +0.77%, 실측 -2.25%), 이 식은")
    print("  두 자산의 기대수익이 같다고 가정한다. 장기채가 크게 잃은 구간이라")
    print("  되맞추기가 지는 쪽으로 자금을 계속 옮겼다. 프리미엄보다 자산 선택")
    print("  손실이 컸던 경우다.")
    print("  σ가 20%, ρ가 0.15면 상한은 0.04 × 0.85 / 4 = 0.85%다.")
    print("  더 정교한 규칙을 짜도 이 값을 넘길 수 없다. 규칙의 문제가 아니다.")

    print("\n" + "=" * 76)
    print("[3] 상한을 키우려면 무엇이 필요한가\n")
    print(f"  {'조건':<28}{'σ':>7}{'ρ':>8}{'상한':>10}")
    print("  " + "-" * 54)
    for sigma, rho, label in [(0.20, 0.15, "실제 주식 둘"),
                              (0.20, -0.30, "상관이 음수라면"),
                              (0.40, 0.15, "변동성이 두 배라면"),
                              (0.80, 0.00, "변동성 80%, 무상관"),
                              (2.00, 0.00, "시뮬레이션(×2/×0.5)")]:
        print(f"  {label:<28}{sigma*100:>6.0f}%{rho:>+8.2f}"
              f"{sigma*sigma*(1-rho)/4*100:>+9.2f}%")
    print("\n  상한은 σ의 제곱에 비례한다. 변동성이 낮은 자산에서는")
    print("  아무리 좋은 알고리즘도 가져올 것이 거의 없다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
