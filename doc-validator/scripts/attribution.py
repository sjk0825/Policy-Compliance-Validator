"""초과수익이 어디서 나왔는지 분해한다.

평균 초과수익이 양수라도 종목 한둘이 끌었다면 전략이 아니라 그 종목을
맞춘 것이다. 종목별 기여도와 하나씩 빼본 결과를 같이 본다.

평균과 중앙값을 나란히 본다. 둘이 크게 다르면 소수의 큰 값이 평균을
만들고 있다는 뜻이다.

    python scripts/attribution.py
    python scripts/attribution.py --horizon 21
"""
import argparse
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BT = ROOT / "fixtures" / "backtests"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def analyze(rows, h: int, label: str) -> None:
    taken = [r for r in rows
             if r["decision"] and r.get(f"rel_{h}") is not None]
    if not taken:
        print(f"\n[{label}] {h}일: true 판정 표본 없음")
        return

    vals = [r[f"rel_{h}"] for r in taken]
    overall_mean, overall_med = st.mean(vals), st.median(vals)
    print(f"\n[{label}]  {h}거래일  true 판정 {len(taken):,}건")
    print(f"  전체   평균 초과수익 {overall_mean:+.3f}%   중앙값 {overall_med:+.3f}%   "
          f"양수 비율 {sum(1 for v in vals if v>0)/len(vals)*100:.1f}%")

    by_sym = defaultdict(list)
    for r in taken:
        by_sym[r["symbol"]].append(r[f"rel_{h}"])

    # 총 초과수익 합에서 각 종목이 차지하는 몫
    total = sum(vals)
    contrib = sorted(((s, sum(v), len(v), st.mean(v)) for s, v in by_sym.items()),
                     key=lambda x: -x[1])

    print(f"\n  {'종목':<10}{'건수':>6}{'평균':>10}{'합계':>11}{'총합 대비':>11}"
          f"{'이 종목 빼면':>13}")
    print("  " + "-" * 61)
    for s, tot, n, avg in contrib[:5] + [("...", 0, 0, 0)] + contrib[-3:]:
        if s == "...":
            print("  " + "." * 20)
            continue
        rest = [v for sym, vs in by_sym.items() if sym != s for v in vs]
        loo = st.mean(rest) if rest else 0.0
        share = tot / total * 100 if total else 0
        print(f"  {s:<10}{n:>6}{avg:>+9.2f}%{tot:>+10.1f}%{share:>10.1f}%{loo:>+12.3f}%")

    # 가장 크게 기여한 종목들을 순서대로 빼면서 평균이 언제 무너지는지 본다
    print(f"\n  누적 제외:")
    dropped = []
    for s, _, _, _ in contrib[:5]:
        dropped.append(s)
        rest = [v for sym, vs in by_sym.items() if sym not in dropped for v in vs]
        if not rest:
            break
        print(f"    상위 {len(dropped)}종목 제외({', '.join(dropped)})  "
              f"평균 {st.mean(rest):+.3f}%  중앙값 {st.median(rest):+.3f}%  "
              f"n={len(rest):,}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=63)
    args = ap.parse_args()

    files = sorted(BT.glob("*_heuristic.json"))
    if not files:
        print("백테스트 결과가 없습니다. scripts/backtest.py를 먼저 실행하세요.")
        return 1
    for f in files:
        analyze(load(f), args.horizon, f.stem.replace("_heuristic", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
