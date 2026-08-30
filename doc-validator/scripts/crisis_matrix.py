"""위기마다 무엇이 방어했는가. 헤지가 진짜인지 그 위기에만 맞은 것인지.

2022년만 보고 헤지를 고르면 그 해에 오른 것을 고르게 된다. 하락장은
원인이 매번 다르고, 원인이 다르면 오르는 것도 다르다. 여러 위기를
나란히 놓아야 구분된다.

    2020 코로나     수요 증발. 원자재가 같이 폭락했다
    2018 4분기      금리 인상 우려. 원자재도 빠졌다
    2022 인플레이션   물가와 금리 급등. 원자재가 올랐다
    2015 차이나쇼크   중국 경기. 원자재가 크게 빠졌다
    2011 유럽위기    재정 위기. 원자재가 빠졌다

에너지·원자재는 2022에만 올랐고 나머지 넷에서는 주식보다 더 빠졌다.
2022가 인플레이션이 원인인 특수한 하락장이었기 때문이다. 다음 하락장이
수요 충격이면 이들은 방어가 아니라 부담이 된다.

금·장기채·달러·고베타숏은 여러 위기에서 반복해 방어했다. 관리선물은
자료가 2019-05부터라 2020과 2022 둘뿐이지만 양쪽 다 방어했고, 하락
추세에서 숏으로 돌아선다는 구조적 이유도 있다.

    python scripts/crisis_matrix.py --data fixtures/wide
"""
import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

CRASHES: List[Tuple[str, str, str]] = [
    ("2011 유럽위기", "2011-07-01", "2011-10-03"),
    ("2015 차이나쇼크", "2015-08-01", "2016-02-11"),
    ("2018 4분기", "2018-10-01", "2018-12-24"),
    ("2020 코로나", "2020-02-19", "2020-03-23"),
    ("2022 인플레", "2022-01-01", "2022-10-12"),
]
ASSETS = [
    ("SPY", "S&P500", "기준"), ("QQQ", "나스닥", "기준"),
    ("DBMF", "관리선물", "헤지"), ("KMLM", "관리선물2", "헤지"),
    ("BTAL", "고베타숏", "헤지"), ("GLD", "금", "헤지"),
    ("TLT", "장기채", "헤지"), ("UUP", "달러", "헤지"),
    ("XLE", "에너지", "2022한정"), ("DBC", "원자재", "2022한정"),
    ("USO", "원유", "2022한정"),
]


def ret(store: PriceStore, sym: str, lo: str, hi: str) -> Optional[float]:
    bars = [b for b in store._all_bars(sym) if lo <= b.date <= hi]
    if len(bars) < 5 or not bars[0].close:
        return None
    return (bars[-1].close / bars[0].close - 1) * 100


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()
    store = PriceStore(Path(args.data))

    print("위기 구간별 수익률 (%)\n")
    print(f"  {'자산':<12}{'분류':<10}" + "".join(f"{c[0][:10]:>12}" for c in CRASHES)
          + f"{'방어 횟수':>10}")
    print("  " + "-" * 88)
    for sym, label, kind in ASSETS:
        if not store.has(sym):
            continue
        cells, wins, seen = [], 0, 0
        for _, lo, hi in CRASHES:
            v = ret(store, sym, lo, hi)
            cells.append(f"{v:+.1f}%" if v is not None else "-")
            if v is not None and kind != "기준":
                seen += 1
                wins += 1 if v > 0 else 0
        tail = f"{wins}/{seen}" if kind != "기준" else ""
        print(f"  {label:<12}{kind:<10}" + "".join(f"{c:>12}" for c in cells)
              + f"{tail:>10}")

    print("\n  분류는 사후에 붙인 것이 아니라 방어 이유가 있는지로 나눴다.")
    print("  관리선물은 하락 추세에서 숏으로 돌아선다. 금·달러·장기채는 위험회피")
    print("  자금이 몰린다. 에너지·원자재는 그런 구조가 없고 2022의 원인이")
    print("  인플레이션이었기에 올랐을 뿐이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
