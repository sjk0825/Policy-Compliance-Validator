"""완전 랜덤인 두 자산 사이에서 무엇이 되고 무엇이 안 되는가.

두 자산이 각각 독립 랜덤워크라고 두고 알고리즘들을 붙여본다. 예측이
불가능하다는 가정을 지키면서 확률적으로 이득을 낼 수 있는 것과 없는 것을
가른다.

  1. 그냥 보유            비중이 흘러가게 둔다
  2. 고정비중 되맞춤        매 회 50:50으로 되돌린다
  3. 최적 고정비중         사후에 가장 좋았던 비중. 실행 불가, 상한 확인용
  4. 유니버설 포트폴리오     모든 고정비중에 분산 투자하고 성과대로 가중치를
                        옮긴다. 사전 지식 없이 최적 고정비중에 수렴한다는
                        것이 증명돼 있다(Cover 1991)
  5. 페어 트레이딩         가격 비율이 벌어지면 진 쪽을 사고 이긴 쪽을 판다

1~4는 비중 배분이고 5는 스프레드 예측이다. 랜덤워크의 스프레드도
랜덤워크이므로 5는 되돌아올 이유가 없다. 그것을 확인하는 것이 목적이다.

    python scripts/two_asset_algos.py
"""
import argparse
import math
import random
import statistics as st
import sys
from typing import Callable, Dict, List, Tuple

GRID = [i / 20 for i in range(21)]      # 고정비중 후보 0.00~1.00


def make_path(rng: random.Random, n: int, sigma: float, mu: float = 0.0) -> List[float]:
    """로그수익률이 정규분포인 랜덤워크. 기대 로그성장은 mu."""
    return [math.exp(rng.gauss(mu, sigma)) - 1 for _ in range(n)]


def crp(a: List[float], b: List[float], w: float) -> float:
    """고정비중 w를 매 회 되맞춘 최종 배수."""
    eq = 1.0
    for x, y in zip(a, b):
        eq *= (1 + w * x + (1 - w) * y)
        if eq <= 0:
            return 0.0
    return eq


def buy_and_hold(a: List[float], b: List[float]) -> float:
    w = [0.5, 0.5]
    eq = 1.0
    for x, y in zip(a, b):
        eq *= (1 + w[0] * x + w[1] * y)
        g = [w[0] * (1 + x), w[1] * (1 + y)]
        tot = sum(g)
        if tot <= 0:
            return 0.0
        w = [v / tot for v in g]
    return eq


def universal(a: List[float], b: List[float]) -> float:
    """모든 고정비중에 균등 배분하고 각자의 성과대로 가중치가 옮겨가게 둔다."""
    caps = [1.0 / len(GRID)] * len(GRID)
    eq = 1.0
    for x, y in zip(a, b):
        rets = [w * x + (1 - w) * y for w in GRID]
        port = sum(c * r for c, r in zip(caps, rets))
        eq *= (1 + port)
        if eq <= 0:
            return 0.0
        grown = [c * (1 + r) for c, r in zip(caps, rets)]
        tot = sum(grown)
        caps = [g / tot for g in grown] if tot > 0 else caps
    return eq


def pairs(a: List[float], b: List[float], lookback: int = 60,
          entry: float = 1.5) -> float:
    """가격 비율의 z점수가 벌어지면 진 쪽을 사고 이긴 쪽을 판다."""
    pa = pb = 1.0
    hist: List[float] = []
    eq = 1.0
    pos = 0     # +1이면 a 매수/b 매도
    for x, y in zip(a, b):
        if pos != 0:
            eq *= (1 + pos * (x - y) / 2)
            if eq <= 0:
                return 0.0
        pa *= (1 + x)
        pb *= (1 + y)
        if pb > 0:
            hist.append(math.log(pa / pb))
        if len(hist) > lookback:
            seg = hist[-lookback:]
            m, sd = st.mean(seg), st.pstdev(seg)
            if sd > 0:
                z = (hist[-1] - m) / sd
                if z > entry:
                    pos = -1        # a가 너무 올랐다 → a 매도
                elif z < -entry:
                    pos = +1
                elif abs(z) < 0.3:
                    pos = 0
    return eq


def growth(mult: float, n: int) -> float:
    return math.log(mult) / n * 100 if mult > 0 else float("-inf")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=2000)
    ap.add_argument("--rounds", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20260829)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    for sigma, label in [(0.02, "일간 변동성 2% (연 32%, 실제 주식 수준)"),
                         (0.10, "일간 변동성 10% (연 159%, 시뮬레이션 수준)")]:
        print("=" * 76)
        print(f"[{label}]  두 자산 모두 기대 로그성장 0, 서로 독립")
        print(f"경로 {args.paths:,}개 × {args.rounds}회\n")
        res: Dict[str, List[float]] = {k: [] for k in
                                       ("보유", "50:50 되맞춤", "최적 고정비중",
                                        "유니버설", "페어 트레이딩")}
        for _ in range(args.paths):
            a = make_path(rng, args.rounds, sigma)
            b = make_path(rng, args.rounds, sigma)
            res["보유"].append(buy_and_hold(a, b))
            res["50:50 되맞춤"].append(crp(a, b, 0.5))
            res["최적 고정비중"].append(max(crp(a, b, w) for w in GRID))
            res["유니버설"].append(universal(a, b))
            res["페어 트레이딩"].append(pairs(a, b))

        print(f"  {'알고리즘':<18}{'중앙값 배수':>14}{'회당 성장률':>14}"
              f"{'손실 경로 비율':>15}")
        print("  " + "-" * 62)
        for k, vals in res.items():
            med = st.median(vals)
            lose = sum(1 for v in vals if v < 1) / len(vals) * 100
            print(f"  {k:<18}{med:>14.4g}{growth(med, args.rounds):>13.4f}%"
                  f"{lose:>14.1f}%")
        theory = sigma * sigma * 100 / 4 * 2      # σ²(1-ρ)/4, ρ=0, 회당 %
        print(f"\n  이론 상한(σ²(1-ρ)/4, 회당) = {theory/2:.4f}%"
              f"   되맞춤 실측 = {growth(st.median(res['50:50 되맞춤']), args.rounds):.4f}%")
        print()

    print("=" * 76)
    print("정리")
    print("  비중 배분(보유·되맞춤·유니버설)은 랜덤에서도 성장을 만든다.")
    print("  페어 트레이딩은 만들지 못한다. 스프레드가 되돌아올 이유가 없기")
    print("  때문이다. 독립 랜덤워크의 차이도 랜덤워크다.")
    print("  유니버설은 사전 지식 없이 최적 고정비중에 근접한다. 다만 그")
    print("  최적치 자체가 σ²/4에 묶여 있으므로 넘어설 수는 없다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
