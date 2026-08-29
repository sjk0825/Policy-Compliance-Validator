"""10개 자산의 전날 정보를 전부 넣어 다음날 방향을 학습한다.

지금까지는 지표를 하나씩 봤거나(IC), 상태를 격자로 갈랐다(조건부 표,
전수 셀). 변수들 사이의 상호작용을 모델이 알아서 찾게 하는 것은 하지
않았다. 그 자리를 메운다.

특징은 10개 자산 각각에서 다섯 개씩 뽑는다. 1일·5일·20일 수익률,
20일 실현변동성, 20일선 이격. 자산 하나를 예측할 때도 열 개 전부의
특징을 준다. 어느 자산의 무엇이 다른 자산의 내일과 이어지는지는 모델이
정한다.

모델은 셋을 쓴다. 로지스틱 회귀, 랜덤 포레스트, 히스토그램 부스팅.
탐색 구간에서 학습하고 검증 구간에서 고르고 최종 구간은 한 번만 쓴다.

비교 기준은 정확도 50%가 아니라 그 구간의 상승 비율이다. 시장이 오르는
구간에서는 "무조건 상승"만 찍어도 55%가 나온다. 그것을 넘어야 의미가 있다.

    python scripts/daily_ml.py --data fixtures/wide
"""
import argparse
import math
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore   # noqa: E402

ASSETS = ["SPY", "QQQ", "IWM", "EEM", "GLD", "SLV", "TLT", "UUP", "069500", "BTC/USD"]
TRAIN = ("2010-01-01", "2018-12-31")
VALID = ("2019-01-01", "2022-12-31")
TEST = ("2023-01-01", "2026-12-31")


def build_matrix(store: PriceStore) -> Tuple[List[str], List[List[float]], Dict[str, List[int]], List[str]]:
    import numpy as np

    syms = [s for s in ASSETS if store.has(s)]
    closes: Dict[str, Dict[str, float]] = {}
    for s in syms:
        b = store._all_bars(s)
        closes[s] = {x.date: x.close for x in b}

    cal = sorted(closes["SPY"])
    rows, dates = [], []
    labels: Dict[str, List[int]] = {s: [] for s in syms}

    hist = {s: [] for s in syms}
    for i, d in enumerate(cal):
        for s in syms:
            if d in closes[s]:
                hist[s].append(closes[s][d])
        if i < 25 or i + 1 >= len(cal):
            continue
        feat, ok = [], True
        for s in syms:
            h = hist[s]
            if len(h) < 25:
                ok = False
                break
            r1 = h[-1] / h[-2] - 1
            r5 = h[-1] / h[-6] - 1
            r20 = h[-1] / h[-21] - 1
            sma20 = sum(h[-20:]) / 20
            rr = [h[k] / h[k - 1] - 1 for k in range(len(h) - 20, len(h))]
            vol = (sum(x * x for x in rr) / len(rr)) ** 0.5
            feat += [r1, r5, r20, h[-1] / sma20 - 1, vol]
        if not ok:
            continue
        nxt = cal[i + 1]
        lab = {}
        for s in syms:
            if d in closes[s] and nxt in closes[s]:
                lab[s] = 1 if closes[s][nxt] > closes[s][d] else 0
            else:
                lab[s] = -1
        rows.append(feat)
        dates.append(d)
        for s in syms:
            labels[s].append(lab[s])
    return syms, rows, labels, dates


def slice_idx(dates: List[str], lo: str, hi: str) -> List[int]:
    return [i for i, d in enumerate(dates) if lo <= d <= hi]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="fixtures/wide")
    args = ap.parse_args()

    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline

    store = PriceStore(Path(args.data))
    syms, rows, labels, dates = build_matrix(store)
    X = np.array(rows, dtype=float)
    print(f"자산 {len(syms)}개, 특징 {X.shape[1]}개 (자산당 5개), 표본 {X.shape[0]:,}일")
    print(f"학습 {TRAIN[0][:7]}~{TRAIN[1][:7]} / 검증 {VALID[0][:7]}~{VALID[1][:7]} "
          f"/ 최종 {TEST[0][:7]}~{TEST[1][:7]}\n")

    tr, va, te = (slice_idx(dates, *TRAIN), slice_idx(dates, *VALID), slice_idx(dates, *TEST))

    MODELS = {
        "로지스틱": lambda: make_pipeline(StandardScaler(),
                                     LogisticRegression(max_iter=2000, C=0.05)),
        "랜덤포레스트": lambda: RandomForestClassifier(
            n_estimators=300, max_depth=5, min_samples_leaf=50, random_state=7, n_jobs=-1),
        "부스팅": lambda: HistGradientBoostingClassifier(
            max_depth=3, max_iter=200, learning_rate=0.05, random_state=7),
    }

    print(f"  {'자산':<10}{'모델':<12}{'기준(상승률)':>12}{'학습':>8}{'검증':>8}{'검증-기준':>10}")
    print("  " + "-" * 62)
    picks: Dict[str, str] = {}
    for s in syms:
        y = np.array(labels[s])
        m_tr = [i for i in tr if y[i] >= 0]
        m_va = [i for i in va if y[i] >= 0]
        if len(m_tr) < 500 or len(m_va) < 200:
            continue
        base_va = y[m_va].mean() * 100
        best, best_gain = None, -99
        for name, mk in MODELS.items():
            mdl = mk()
            mdl.fit(X[m_tr], y[m_tr])
            a_tr = (mdl.predict(X[m_tr]) == y[m_tr]).mean() * 100
            a_va = (mdl.predict(X[m_va]) == y[m_va]).mean() * 100
            gain = a_va - base_va
            print(f"  {s:<10}{name:<12}{base_va:>11.1f}%{a_tr:>7.1f}%{a_va:>7.1f}%"
                  f"{gain:>+9.1f}p")
            if gain > best_gain:
                best, best_gain = name, gain
        picks[s] = best
        print()

    print("=" * 66)
    print("최종 구간. 검증에서 고른 모델로 한 번만 잰다\n")
    print(f"  {'자산':<10}{'고른 모델':<12}{'기준(상승률)':>12}{'정확도':>9}{'차이':>9}")
    print("  " + "-" * 56)
    gains = []
    for s in syms:
        if s not in picks:
            continue
        y = np.array(labels[s])
        m_tr = [i for i in tr + va if y[i] >= 0]
        m_te = [i for i in te if y[i] >= 0]
        if len(m_te) < 200:
            continue
        mdl = MODELS[picks[s]]()
        mdl.fit(X[m_tr], y[m_tr])
        base_te = y[m_te].mean() * 100
        acc = (mdl.predict(X[m_te]) == y[m_te]).mean() * 100
        gains.append(acc - base_te)
        print(f"  {s:<10}{picks[s]:<12}{base_te:>11.1f}%{acc:>8.1f}%{acc - base_te:>+8.1f}p")
    if gains:
        print(f"\n  평균 차이 {sum(gains)/len(gains):+.2f}p   "
              f"기준을 넘은 자산 {sum(1 for g in gains if g > 0)}/{len(gains)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
