"""규칙을 많이 만들어 고르면 어떻게 되는지 재본다.

"규칙을 엄청 많이 만들고 데이터가 고르게 한다"는 방향은 자연스럽다.
문제는 고르는 행위 자체가 결과를 만든다는 것이다. 아무 의미 없는 규칙도
수백 개 중에서 가장 좋은 것을 뽑으면 통계적으로 유의해 보인다.

무작위 규칙을 만들어 앞구간에서 성적순으로 고른 뒤, 뒷구간에서 다시
재본다. 앞구간 성적이 뒷구간에 남는지가 관심사다.

비교를 위해 실제로 쓰고 있는 규칙(직전 미국 -1% 이하)도 같이 넣는다.
이 규칙은 탐색으로 찾은 것이 아니라 시차 가설에서 나왔다.

    python scripts/overfit_check.py --rules 200
"""
import argparse
import csv
import json
import math
import random
import statistics as st
import sys
from bisect import bisect_left
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
LEADERS = ROOT / "fixtures" / "leaders"

SPLIT = "2019-01-01"          # 앞구간 / 뒷구간 경계
LOOKBACKS = [1, 2, 3, 5, 10]
THRESHOLDS = [0.3, 0.5, 0.8, 1.0, 1.5, 2.0]


def load(path: Path):
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


def n_day_return(close: List[float], n: int) -> List[Optional[float]]:
    return [None] * n + [(close[i] / close[i - n] - 1) * 100 if close[i - n] else None
                         for i in range(n, len(close))]


def evaluate(fires: List[float]) -> Optional[Tuple[float, float, int]]:
    """규칙이 발동한 날들의 평균, t값, 건수."""
    if len(fires) < 40:
        return None
    m, sd = st.mean(fires), st.stdev(fires)
    if not sd:
        return None
    return m, m / sd * math.sqrt(len(fires)), len(fires)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260829)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--placebo", action="store_true",
                    help="날짜와 수익률의 연결을 끊는다. 실제 관계가 모두 사라지므로 "
                         "여기서 나오는 유의성은 전부 고르는 행위가 만든 것이다.")
    args = ap.parse_args()

    manifest = json.loads((LEADERS / "manifest.json").read_text(encoding="utf-8"))
    leaders = {e["symbol"]: e for e in manifest["leaders"]}

    kd, kc, ko = load(LEADERS / "KS11.csv")
    target = {kd[i]: (kc[i] / ko[i] - 1) * 100 for i in range(len(kd)) if ko[i]}

    if args.placebo:
        # 수익률 값은 그대로 두고 날짜에만 무작위로 다시 붙인다. 분포와
        # 자기상관 구조는 유지되고 선행 시장과의 관계만 사라진다.
        days = list(target)
        vals = list(target.values())
        random.Random(args.seed + 1).shuffle(vals)
        target = dict(zip(days, vals))
        print("[플라시보] 날짜와 수익률의 연결을 끊었다. 진짜 관계는 없다.\n")

    # 선행 시장별 N일 수익률을 미리 만들어 둔다.
    series: Dict[str, Dict[int, Dict[str, float]]] = {}
    for sym, e in leaders.items():
        ld, lc, _ = load(Path(e["file"]))
        series[sym] = {}
        for n in LOOKBACKS:
            r = n_day_return(lc, n)
            series[sym][n] = {ld[i]: r[i] for i in range(len(ld)) if r[i] is not None}

    def fires_for(sym: str, n: int, thr: float, side: str) -> Dict[str, List[float]]:
        """규칙이 발동한 날의 코스피 장중 수익률을 앞/뒤 구간으로 나눠 돌려준다."""
        ld = sorted(series[sym][n])
        out = {"train": [], "test": []}
        for day, intraday in target.items():
            j = bisect_left(ld, day) - 1
            if j < 0:
                continue
            v = series[sym][n][ld[j]]
            hit = v <= -thr if side == "down" else v >= thr
            if hit:
                out["train" if day < SPLIT else "test"].append(intraday)
        return out

    rng = random.Random(args.seed)
    symbols = [s for s in leaders if s not in ("KS11", "KQ11")]

    results = []
    seen = set()
    while len(results) < args.rules:
        sym = rng.choice(symbols)
        n = rng.choice(LOOKBACKS)
        thr = rng.choice(THRESHOLDS)
        side = rng.choice(["down", "up"])
        key = (sym, n, thr, side)
        if key in seen:
            continue
        seen.add(key)
        f = fires_for(*key)
        tr, te = evaluate(f["train"]), evaluate(f["test"])
        if tr is None or te is None:
            continue
        results.append({"rule": f"{leaders[sym]['label']} {n}일 {side} {thr}%",
                        "train_mean": tr[0], "train_t": tr[1], "train_n": tr[2],
                        "test_mean": te[0], "test_t": te[1], "test_n": te[2]})

    print(f"무작위 규칙 {len(results)}개  (앞구간 ~{SPLIT}, 뒷구간 {SPLIT}~)")
    print(f"대상: 코스피 지수 시가매수 → 당일종가매도\n")

    best = sorted(results, key=lambda r: -r["train_t"])[:args.top]
    print(f"앞구간 성적 상위 {args.top}개를 골라 뒷구간에서 다시 재면")
    print(f"  {'규칙':<26}{'앞 평균':>9}{'앞 t':>8}{'뒤 평균':>10}{'뒤 t':>8}")
    print("  " + "-" * 62)
    for r in best:
        print(f"  {r['rule']:<26}{r['train_mean']:>+8.3f}%{r['train_t']:>+8.2f}"
              f"{r['test_mean']:>+9.3f}%{r['test_t']:>+8.2f}")

    tr_t = [r["train_t"] for r in best]
    te_t = [r["test_t"] for r in best]
    print(f"\n  상위 {args.top}개 평균 t:  앞구간 {st.mean(tr_t):+.2f}  →  뒷구간 {st.mean(te_t):+.2f}")

    allt = [r["train_t"] for r in results]
    sig = sum(1 for t in allt if abs(t) >= 2)
    print(f"\n  전체 {len(results)}개 중 앞구간 |t|>=2: {sig}개 ({sig/len(results)*100:.0f}%)")
    print(f"  앞구간 t 최댓값 {max(allt):+.2f}  (아무 규칙이나 많이 만들면 이 정도는 나온다)")

    # 탐색이 아니라 가설에서 나온 규칙과 비교한다.
    print("\n  비교: 탐색이 아니라 시차 가설에서 나온 규칙")
    for sym, n, thr, side, label in [("US500", 1, 1.0, "down", "S&P500 1일 -1% 이하"),
                                     ("DJI", 1, 1.0, "down", "다우 1일 -1% 이하"),
                                     ("IXIC", 1, 1.0, "up", "나스닥 1일 +1% 이상")]:
        f = fires_for(sym, n, thr, side)
        tr, te = evaluate(f["train"]), evaluate(f["test"])
        if tr and te:
            print(f"  {label:<26}{tr[0]:>+8.3f}%{tr[1]:>+8.2f}{te[0]:>+9.3f}%{te[1]:>+8.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
