"""3종목 상태 조합을 전수로 훑어 다음날 방향을 맞힐 수 있는지 본다.

각 종목의 최근 2일 등락 패턴(상상/상하/하상/하하)을 상태로 잡으면
3종목이면 4의 세제곱인 64칸이 된다. 요일을 넣으면 320칸이다. 모든 칸을
세어 가장 좋은 칸을 고르고, 그 칸이 뒷구간에서도 유지되는지 본다.

핵심은 비교 대상이다. 칸을 많이 만들수록 그중 가장 좋은 칸은 우연히도
크게 벗어난다. 그 크기는 계산할 수 있다.

    칸 하나의 표준오차   se = 50 / sqrt(n)         (%p 단위, 승률 50% 가정)
    N칸 중 최댓값 기대치  ≈ se · sqrt(2 · ln N)

이 값보다 크지 않다면 찾은 것이 아니라 고른 것이다. 실측·이론·플라시보
셋을 나란히 놓는다.

    python scripts/exhaustive_cells.py --data fixtures/wide
"""
import argparse
import math
import random
import statistics as st
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

SPLIT = "2019-01-01"


def updown(store: PriceStore, sym: str) -> Dict[str, bool]:
    b = store._all_bars(sym)
    return {b[i].date: b[i].close > b[i - 1].close
            for i in range(1, len(b)) if b[i - 1].close}


def state2(seq: List[bool]) -> int:
    """최근 2일 패턴을 0~3으로. (어제, 그제)"""
    return (1 if seq[-1] else 0) * 2 + (1 if seq[-2] else 0)


def analyze(cells_tr: Dict[int, List[bool]], cells_te: Dict[int, List[bool]],
            min_n: int, label: str) -> Optional[Tuple[float, float, int, int]]:
    tr_all = [v for vs in cells_tr.values() for v in vs]
    te_all = [v for vs in cells_te.values() for v in vs]
    if not tr_all or not te_all:
        return None
    base_tr = sum(tr_all) / len(tr_all) * 100
    base_te = sum(te_all) / len(te_all) * 100

    best = None
    for key, vs in cells_tr.items():
        if len(vs) < min_n:
            continue
        rate = sum(vs) / len(vs) * 100
        dev = rate - base_tr
        if best is None or abs(dev) > abs(best[1]):
            best = (key, dev, rate, len(vs))
    if best is None:
        return None

    key, dev_tr, rate_tr, n_tr = best
    te = cells_te.get(key, [])
    dev_te = (sum(te) / len(te) * 100 - base_te) if len(te) >= 30 else None

    used = sum(1 for vs in cells_tr.values() if len(vs) >= min_n)
    avg_n = st.mean([len(vs) for vs in cells_tr.values() if len(vs) >= min_n])
    se = 50 / math.sqrt(avg_n)
    expected_max = se * math.sqrt(2 * math.log(max(2, used)))

    print(f"  {label}")
    print(f"    칸 {used}개 (칸당 평균 {avg_n:.0f}건), 기준 승률 앞 {base_tr:.1f}% / 뒤 {base_te:.1f}%")
    print(f"    최고 칸 앞구간 {rate_tr:.1f}%  편차 {dev_tr:+.1f}p  (n={n_tr})")
    if dev_te is None:
        print(f"    같은 칸 뒷구간  표본 부족 (n={len(te)})")
    else:
        keep = "유지" if dev_tr * dev_te > 0 and abs(dev_te) >= 2 else "사라짐"
        print(f"    같은 칸 뒷구간  편차 {dev_te:+.1f}p  (n={len(te)})   {keep}")
    print(f"    우연히 기대되는 최대 편차 = {expected_max:+.1f}p"
          f"   → 실측 {dev_tr:+.1f}p는 {'그 안' if abs(dev_tr) <= expected_max else '그 밖'}")
    return dev_tr, (dev_te if dev_te is not None else 0.0), used, n_tr


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    ap.add_argument("--target", default="069500")
    ap.add_argument("--assets", default="SPY,QQQ,GLD")
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--placebo", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    store = PriceStore(Path(args.data))
    syms = [s for s in args.assets.split(",") if store.has(s)]
    if not store.has(args.target) or len(syms) < 3:
        print("자산이 부족합니다.")
        return 1

    ud = {s: updown(store, s) for s in syms}
    tgt = updown(store, args.target)
    days = sorted(set.intersection(*[set(v) for v in ud.values()]) & set(tgt))
    if len(days) < 1000:
        print("표본이 부족합니다.")
        return 1

    rng = random.Random(args.seed)
    nxt = {days[i]: tgt[days[i + 1]] for i in range(len(days) - 1)}
    if args.placebo:
        vals = [nxt[d] for d in days[:-1]]
        rng.shuffle(vals)
        nxt = dict(zip(days[:-1], vals))

    print(f"대상 {args.target} 다음날 방향   조건 자산 {', '.join(syms)}")
    print(f"거래일 {len(days):,}일, 앞구간 ~{SPLIT} / 뒷구간 {SPLIT}~")
    if args.placebo:
        print("[플라시보] 다음날 방향을 무작위로 다시 붙였다.")
    print()

    hist = {s: [] for s in syms}
    cells: Dict[str, Dict[int, List[bool]]] = {
        "s3_tr": defaultdict(list), "s3_te": defaultdict(list),
        "dow_tr": defaultdict(list), "dow_te": defaultdict(list),
        "one_tr": defaultdict(list), "one_te": defaultdict(list),
    }
    for i, d in enumerate(days[:-1]):
        for s in syms:
            hist[s].append(ud[s][d])
        if i < 2:
            continue
        st3 = tuple(state2(hist[s]) for s in syms)
        key3 = st3[0] * 16 + st3[1] * 4 + st3[2]
        dow = date.fromisoformat(d).weekday()
        suffix = "tr" if d < SPLIT else "te"
        cells[f"one_{suffix}"][st3[0]].append(nxt[d])
        cells[f"s3_{suffix}"][key3].append(nxt[d])
        cells[f"dow_{suffix}"][key3 * 5 + dow].append(nxt[d])

    print("전수 탐색 결과\n")
    analyze(cells["one_tr"], cells["one_te"], args.min_n,
            f"[1] {syms[0]} 최근 2일 패턴만 (4칸)")
    print()
    analyze(cells["s3_tr"], cells["s3_te"], args.min_n,
            "[2] 3종목 최근 2일 패턴 조합 (64칸)")
    print()
    analyze(cells["dow_tr"], cells["dow_te"], args.min_n,
            "[3] 위에 요일까지 (320칸)")
    print("\n  칸을 늘릴수록 최고 칸의 편차가 커지지만 기대 최댓값도 같이 커진다.")
    print("  둘이 함께 커지면 찾은 것이 아니라 고른 것이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
