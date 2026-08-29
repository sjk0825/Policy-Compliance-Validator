"""선행 시장별로 한국 장중 되돌림 효과를 비교한다.

시차가 핵심이다. 한국이 닫힌 뒤에 닫는 시장만 밤사이 새 정보를 만든다.

    미국·유럽   한국 마감 후 거래  →  진짜 선행. 전일 종가가 새 정보다.
    일본·중국·홍콩  한국과 같은 시간대  →  전일 종가는 한국도 이미 반영했다.
                                        새 정보가 거의 없어야 정상이다.

측정 대상은 한국 시가 매수 → 당일 종가 매도다. 전날 종가에는 살 수 없으므로
종가-종가 수익률은 체결 가능한 성과가 아니다.

    python scripts/leader_scan.py
"""
import argparse
import csv
import json
import math
import statistics as st
import sys
from bisect import bisect_left
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LEADERS = ROOT / "fixtures" / "leaders"

# 같은 시간대에 열리는 시장. 새 정보를 기대할 수 없다.
SAME_SESSION = {"N225", "SSEC", "HSI", "KS11", "KQ11"}


def load(path: Path) -> Tuple[List[str], List[Optional[float]], List[Optional[float]]]:
    dates, close, open_ = [], [], []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            try:
                c = float(r["Close"])
            except (KeyError, TypeError, ValueError):
                continue
            dates.append(r["Date"])
            close.append(c)
            try:
                open_.append(float(r["Open"]))
            except (KeyError, TypeError, ValueError):
                open_.append(None)
    return dates, close, open_


def daily_change(close: List[float]) -> List[Optional[float]]:
    return [None] + [(close[i] / close[i - 1] - 1) * 100 if close[i - 1] else None
                     for i in range(1, len(close))]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=1.0,
                    help="선행 시장이 이 % 이상 움직인 날만 신호로 본다")
    args = ap.parse_args()

    manifest = json.loads((LEADERS / "manifest.json").read_text(encoding="utf-8"))
    by_symbol = {e["symbol"]: e for e in manifest["leaders"]}

    kd, kc, ko = load(LEADERS / "KS11.csv")
    intraday = [((kc[i] / ko[i] - 1) * 100) if ko[i] else None for i in range(len(kd))]
    base = [v for v in intraday if v is not None]
    base_up = sum(1 for v in base if v > 0) / len(base) * 100

    print(f"대상: 코스피 지수(KS11) 시가매수 → 당일종가매도")
    print(f"기간 {kd[0]} ~ {kd[-1]}  거래일 {len(base):,}일")
    print(f"기준(무조건 매수) 평균 {st.mean(base):+.3f}%  상승 {base_up:.1f}%\n")

    print(f"선행 시장이 {args.threshold:.0f}% 이상 하락한 다음 날")
    print(f"  {'선행':<10}{'구분':<8}{'신호일':>7}{'평균':>9}{'상승%':>8}{'기준대비':>9}{'t':>7}")
    print("  " + "-" * 60)

    rows = []
    for sym, e in by_symbol.items():
        if sym in ("KS11", "KQ11"):
            continue
        ld, lc, _ = load(Path(e["file"]))
        lr = daily_change(lc)

        for direction in ("down", "up"):
            picked = []
            for i, day in enumerate(kd):
                if intraday[i] is None:
                    continue
                j = bisect_left(ld, day) - 1
                if not (0 <= j < len(lr)) or lr[j] is None:
                    continue
                v = lr[j]
                if (direction == "down" and v <= -args.threshold) or \
                   (direction == "up" and v >= args.threshold):
                    picked.append(intraday[i])
            if len(picked) < 40:
                continue
            m, sd = st.mean(picked), st.stdev(picked)
            up = sum(1 for x in picked if x > 0) / len(picked) * 100
            t = m / sd * math.sqrt(len(picked))
            rows.append((sym, e["label"], direction, len(picked), m, up, up - base_up, t))

    kind = lambda s: "동시장" if s in SAME_SESSION else "선행"
    for direction, title in (("down", "하락 후"), ("up", "상승 후")):
        print(f"\n  [{title}]")
        sel = [r for r in rows if r[2] == direction]
        for sym, label, _, n, m, up, diff, t in sorted(sel, key=lambda r: -abs(r[7])):
            mark = " *" if abs(t) >= 2 else ""
            print(f"  {label:<10}{kind(sym):<8}{n:>7}{m:>+8.2f}%{up:>7.1f}%"
                  f"{diff:>+8.1f}p{t:>+7.2f}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
