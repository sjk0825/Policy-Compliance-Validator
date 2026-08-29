"""승률과 성과의 관계. 60%가 왜 없는 숫자인지.

매일 같은 크기로 방향에 베팅한다고 보면 일간 승률 p와 연 샤프는 이렇게
이어진다.

    edge = 2p - 1
    Sharpe = edge / sqrt(1 - edge²) × sqrt(252)

    승률 50%  →  샤프 0.00
    승률 51%  →  샤프 0.32
    승률 55%  →  샤프 1.60
    승률 60%  →  샤프 3.24

샤프 3.24는 르네상스 메달리온 수준이다. 60%가 흔한 숫자로 들리지만
그 자리에는 세계에서 가장 유명한 몇 곳뿐이다. 그리고 그런 우위는 알려지는
순간 사라지므로, 공개 데이터로 찾을 수 있는 곳에 남아 있을 이유가 없다.

이 프로젝트에서 측정한 모든 예측 지표는 48~52% 안에 있었다.

한편 우리가 만든 포트폴리오의 승률은 54.7%로 SPY의 54.7%와 같다.
승률은 그대로인데 샤프만 1.11 대 0.73이다. 이기는 축이 승률이 아니다.

    python scripts/win_rate_math.py
"""
import math
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

CASES = [
    (0.50, "동전. 이 프로젝트에서 측정한 모든 예측 지표"),
    (0.51, "측정된 최대치. 그나마 갭에 들어 있어 못 쓴다"),
    (0.52, ""),
    (0.55, "헤지펀드 상위권"),
    (0.60, "르네상스 메달리온급. 공개 데이터에는 없다"),
    (0.65, "존재하지 않는다"),
]
ASSETS = ["SPY", "QQQ", "IWM", "EEM", "GLD", "SLV", "TLT", "UUP", "069500", "BTC/USD"]


def sharpe_from_winrate(p: float) -> float:
    edge = 2 * p - 1
    return edge / math.sqrt(1 - edge * edge) * math.sqrt(252)


def main() -> int:
    print("승률이 얼마면 어느 정도인가 (매일 같은 크기로 방향에 베팅할 때)\n")
    print(f"  {'일간 승률':<11}{'연 샤프':>9}   설명")
    print("  " + "-" * 62)
    for p, note in CASES:
        print(f"  {p*100:>7.0f}%    {sharpe_from_winrate(p):>8.2f}   {note}")

    print("\n  60%는 흔한 숫자로 들리지만 샤프 3.24다.")
    print("  그런 우위는 알려지면 사라지므로 공개 데이터에 남아 있을 이유가 없다.\n")

    store = PriceStore(ROOT / "fixtures" / "wide")
    syms = [s for s in ASSETS if store.has(s)]
    series = []
    for s in syms:
        b = store._all_bars(s)
        series.append({b[i].date: b[i].close / b[i - 1].close - 1
                       for i in range(1, len(b)) if b[i - 1].close})
    days = sorted(set.intersection(*[set(x) for x in series]))
    port = [st.mean([series[i][d] for i in range(len(syms))]) for d in days]

    print("=" * 68)
    print("실제 측정. 승률은 같은데 샤프만 다르다\n")
    print(f"  {'전략':<22}{'일간 승률':>10}{'연 샤프':>10}")
    print("  " + "-" * 44)

    def line(label, v):
        wr = sum(1 for x in v if x > 0) / len(v) * 100
        sh = st.mean(v) / st.pstdev(v) * math.sqrt(252) if st.pstdev(v) else 0
        print(f"  {label:<22}{wr:>9.1f}%{sh:>10.2f}")

    line("1/N 포트폴리오", port)
    for s, label in (("SPY", "SPY"), ("QQQ", "QQQ"), ("069500", "KODEX200")):
        if s in syms:
            line(label, [series[syms.index(s)][d] for d in days])

    print("\n  승률을 올려 이긴 것이 아니다. 같은 승률에서 지는 폭을 줄여 이겼다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
