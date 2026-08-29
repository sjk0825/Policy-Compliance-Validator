"""완전한 랜덤에서 베팅 방식이 결과를 바꾸는가.

두 경우를 나눠 본다. 이 구분이 지금까지 나온 결과 전부를 설명한다.

[가법] 홀짝. 이기면 +1, 지면 -1. 판돈이 더해진다.
       기댓값은 선형이므로 어떻게 걸든 합의 기댓값은 0이다. 베팅 방식은
       분포의 모양만 바꾼다. 마틴게일은 자주 이기고 가끔 파산하고,
       역마틴게일은 자주 잃고 가끔 크게 딴다. 평균은 그대로다.

[승법] 자산. 오르면 ×2, 내리면 ×0.5. 수익률이 곱해진다.
       여기서는 다르다. 한 번 반토막 나면 두 배가 돼야 본전이므로
       변동 자체가 복리 성장을 갉아먹는다. 그래서 변동을 줄이면
       맞히는 것 없이 성장률이 올라간다.

승법에서 자산 하나의 기대 로그성장은 0이다(0.5·ln2 + 0.5·ln0.5 = 0).
그런데 현금과 반반 섞어 매 회 되맞추면 +0.059가 된다. 아무것도 예측하지
않고 랜덤성에서 성장이 나온다. 섀넌의 도깨비라 불리는 현상이다.

    python scripts/coinflip.py
"""
import argparse
import math
import random
import statistics as st
import sys
from typing import Callable, Dict, List, Tuple


def additive(rng: random.Random, n: int, system: str,
             bankroll: float = 100.0, unit: float = 1.0) -> Tuple[float, bool]:
    """홀짝. 이기면 +건 만큼, 지면 -건 만큼. 파산하면 멈춘다."""
    money, bet, ruined = bankroll, unit, False
    for _ in range(n):
        if system == "flat":
            bet = unit
        elif system == "proportional":       # 항상 자산의 2%
            bet = money * 0.02
        bet = min(bet, money)
        if bet <= 0:
            ruined = True
            break
        win = rng.random() < 0.5
        money += bet if win else -bet
        if system == "martingale":           # 지면 두 배
            bet = unit if win else bet * 2
        elif system == "anti_martingale":    # 이기면 두 배
            bet = bet * 2 if win else unit
        if money <= 0:
            ruined = True
            break
    return max(0.0, money), ruined


def multiplicative(rng: random.Random, n: int, frac: float,
                   up: float = 2.0, down: float = 0.5) -> float:
    """자산. frac만큼만 투자하고 나머지는 현금. 매 회 비율을 되맞춘다."""
    eq = 1.0
    for _ in range(n):
        r = (up - 1) if rng.random() < 0.5 else (down - 1)
        eq *= (1 + frac * r)
        if eq <= 0:
            return 0.0
    return eq


def two_assets(rng: random.Random, n: int, rebalance: bool,
               up: float = 2.0, down: float = 0.5) -> float:
    """서로 무관한 자산 둘. 되맞추기를 하느냐 마느냐만 다르다."""
    w = [0.5, 0.5]
    eq = 1.0
    for _ in range(n):
        rs = [(up - 1) if rng.random() < 0.5 else (down - 1) for _ in range(2)]
        port = w[0] * rs[0] + w[1] * rs[1]
        eq *= (1 + port)
        if eq <= 0:
            return 0.0
        if rebalance:
            w = [0.5, 0.5]
        else:
            grown = [w[0] * (1 + rs[0]), w[1] * (1 + rs[1])]
            tot = sum(grown)
            w = [g / tot for g in grown] if tot > 0 else [0.5, 0.5]
    return eq


def summarize(vals: List[float]) -> Dict[str, float]:
    return {"mean": st.mean(vals), "median": st.median(vals),
            "p10": sorted(vals)[len(vals) // 10],
            "p90": sorted(vals)[len(vals) * 9 // 10]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=20000)
    ap.add_argument("--rounds", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20260829)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    print(f"경로 {args.paths:,}개 × {args.rounds}회, 승률 정확히 50%\n")
    print("=" * 74)
    print("[가법] 홀짝. 이기면 +1, 지면 -1. 시작 자금 100\n")
    print(f"  {'베팅 방식':<20}{'평균':>10}{'중앙값':>10}{'하위10%':>10}"
          f"{'상위10%':>10}{'파산률':>9}")
    print("  " + "-" * 69)
    for system, label in [("flat", "정액"), ("martingale", "마틴게일(지면 2배)"),
                          ("anti_martingale", "역마틴게일(이기면 2배)"),
                          ("proportional", "정률(자산의 2%)")]:
        res = [additive(rng, args.rounds, system) for _ in range(args.paths)]
        vals = [r[0] for r in res]
        ruin = sum(1 for r in res if r[1]) / len(res) * 100
        s = summarize(vals)
        print(f"  {label:<20}{s['mean']:>9.1f}{s['median']:>10.1f}"
              f"{s['p10']:>10.1f}{s['p90']:>10.1f}{ruin:>8.1f}%")
    print("\n  → 평균은 전부 시작 자금 근처다. 베팅 방식은 분포의 모양만 바꾼다.")
    print("     기댓값은 선형이라 더하는 게임에서는 배분으로 만들 것이 없다.")

    print("\n" + "=" * 74)
    print("[승법] 자산. 오르면 ×2, 내리면 ×0.5. 매 회 비율을 되맞춘다\n")
    print(f"  {'투자 비율':<20}{'중앙값 배수':>12}{'연 성장률 근사':>16}")
    print("  " + "-" * 50)
    for frac, label in [(1.0, "전액 (100%)"), (0.75, "75%"), (0.5, "반반 (50%)"),
                        (0.25, "25%"), (0.0, "현금 (0%)")]:
        vals = [multiplicative(rng, args.rounds, frac) for _ in range(args.paths)]
        med = st.median(vals)
        g = (math.log(med) / args.rounds * 100) if med > 0 else float("-inf")
        print(f"  {label:<20}{med:>12.4g}{g:>15.3f}%")
    print("\n  → 전액 투자는 기대 로그성장이 0인데 실제로는 자산이 사라진다.")
    print("     반반으로 되맞추면 같은 랜덤에서 성장이 나온다. 예측은 없다.")

    print("\n" + "=" * 74)
    print("[승법·두 자산] 서로 무관한 자산 둘. 되맞추기만 다르다\n")
    print(f"  {'방식':<20}{'중앙값 배수':>12}{'연 성장률 근사':>16}")
    print("  " + "-" * 50)
    for rebal, label in [(False, "그냥 보유"), (True, "매 회 50:50 되맞춤")]:
        vals = [two_assets(rng, args.rounds, rebal) for _ in range(args.paths)]
        med = st.median(vals)
        g = (math.log(med) / args.rounds * 100) if med > 0 else float("-inf")
        print(f"  {label:<20}{med:>12.4g}{g:>15.3f}%")
    print("\n  → 되맞추기가 만드는 차이가 리밸런싱 프리미엄이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
