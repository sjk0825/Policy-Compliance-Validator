"""언제 떨어진 것을 사고 언제 오른 것을 사는가. 국면으로 고른다.

앞선 측정에서 최적 기울기 k가 구간마다 반대로 나왔다. 전반에는 모멘텀이
좋고 후반에는 역추세가 좋았다. 그렇다면 고정하지 말고 국면을 보고 고르면
된다는 물음이 남는다.

이번에는 근거가 있다. 국면 분해에서 되맞춤은 오르내리는 구간에서 벌고
추세 필터는 한 방향 구간에서 벌었다. 되맞춤은 떨어진 것을 사는 규칙이고
추세는 오른 것을 사는 규칙이므로, 국면과 기울기를 이렇게 잇는 것이
자연스럽다.

    횡보  ->  k > 0  떨어진 것을 더 산다
    추세  ->  k < 0  오른 것을 더 산다

주기 라우팅(rebal_router.py)이 실패한 것은 고를 근거가 없었기 때문이다.
여기서는 근거가 있으므로 다시 묻는 값어치가 있다. 다만 같은 잣대를 댄다.
라우팅이 값어치가 있으려면 고정 k=0을 이겨야 한다.

셋을 잰다.

    1. 국면이 실제로 승자를 가르는가   사후 귀속. 갈리지 않으면 끝이다
    2. 국면 신호가 다음 구간을 맞히는가  직전까지만 보고 판정
    3. 라우팅 성적                고정 k들과 나란히

    python scripts/tilt_router.py
"""
import argparse
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import PriceStore                        # noqa: E402
from btal_hibl import closes, summarize              # noqa: E402
from worst_year_push import ma_grade, daily          # noqa: E402
import contrarian_tilt as CT                         # noqa: E402

LO, HI = "2012-05-07", "2026-12-31"
SPLIT = "2019-12-31"
TRADING = 252
KS = [-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0]


def eff_ratio(px: Dict[str, float], cal: List[str], win: int) -> Dict[str, float]:
    """직전 win일의 효율비. 당일은 안 쓴다."""
    ds = [d for d in cal if d in px]
    out = {}
    for i in range(win, len(ds) - 1):
        w = ds[i - win:i + 1]
        net = abs(px[w[-1]] / px[w[0]] - 1)
        tot = sum(abs(px[w[j + 1]] / px[w[j]] - 1) for j in range(len(w) - 1))
        if tot > 0:
            out[ds[i + 1]] = net / tot
    return out


def series_for(rets, exp, tr, cal, k) -> Dict[str, float]:
    days = [d for d in cal if LO <= d <= HI]
    offs = [round(i * 126 / CT.OFFSETS) for i in range(CT.OFFSETS)]
    paths = [CT.one_path(rets, exp, tr, days, k, 126, 21, o) for o in offs]
    n = min(len(p) for p in paths)
    return dict(zip(days[len(days) - n:],
                    [st.mean([p[i] for p in paths]) for i in range(n)]))


def stats(series, cal, lo=LO, hi=HI) -> Dict:
    ds = [d for d in cal if lo <= d <= hi and d in series]
    m = summarize([series[d] for d in ds])
    ys = {}
    for y in range(int(lo[:4]) + 1, 2027):
        r = [series[d] for d in ds if f"{y}-01-01" <= d <= f"{y}-12-31"]
        if len(r) > 150:
            e = 1.0
            for x in r:
                e *= (1 + x)
            ys[y] = (e - 1) * 100
    m["worst"] = min(ys.values()) if ys else None
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tilt-window", type=int, default=5)
    args = ap.parse_args()
    store = PriceStore(Path("fixtures/wide"))
    cal = sorted(closes(store, "SPY"))
    px = {s: closes(store, s) for s in CT.CORE + [CT.CASH]}
    rets = daily(px, cal)
    exp = {s: ma_grade(px[s], cal, ns=(200,)) for s in CT.CORE}
    TR = CT.trail(px, cal)[args.tilt_window]

    print(f"14종 + ma200 / 신호21 / 되맞춤126,  기울기 기준 {args.tilt_window}일\n")
    print("변형 만드는 중 …", flush=True)
    ser = {k: series_for(rets, exp, TR, cal, k) for k in KS}
    days = sorted(set.intersection(*(set(s) for s in ser.values())))
    effs = {w: eff_ratio(px["SPY"], cal, w) for w in (21, 63)}

    print(f"\n1. 국면이 실제로 승자를 가르는가 (사후 귀속, 효율비 21일)\n")
    print(f"  {'국면':<22}{'일수':>7}" + "".join(f"{f'k={k:+.2f}':>10}" for k in KS))
    print("  " + "-" * (29 + 10 * len(KS)))
    BUCK = [("횡보  (효율비 <0.2)", 0.0, 0.2), ("중간  (0.2~0.4)", 0.2, 0.4),
            ("추세  (>0.4)", 0.4, 1.01)]
    ann = lambda rs: ((math.prod(1 + r for r in rs)) ** (TRADING / len(rs)) - 1) * 100 \
        if len(rs) > 30 else None
    for label, lo_, hi_ in BUCK:
        sel = [d for d in days if lo_ <= effs[21].get(d, -1) < hi_]
        cells = []
        for k in KS:
            v = ann([ser[k][d] for d in sel if d in ser[k]])
            cells.append(f"{v:+.2f}%" if v is not None else "-")
        print(f"  {label:<22}{len(sel):>7}" + "".join(f"{c:>10}" for c in cells))
    print("\n  국면마다 최적 k가 갈리면 라우팅에 근거가 있는 것이다.")

    print(f"\n\n2. 국면 신호가 다음 구간을 맞히는가"
          f"  (직전 효율비로 판정, 21일 앞)\n")
    print(f"  {'효율비 창':<12}{'판정':>7}{'횡보에서 역추세 우세':>22}"
          f"{'추세에서 모멘텀 우세':>22}{'초과/21일':>12}{'t':>7}")
    print("  " + "-" * 84)
    for w in (21, 63):
        gains, chop_hit, chop_n, tr_hit, tr_n = [], 0, 0, 0, 0
        for i in range(0, len(days) - 21, 21):
            d = days[i]
            e = effs[w].get(d)
            if e is None:
                continue
            fwd = days[i:i + 21]
            up = sum(ser[0.5][x] for x in fwd if x in ser[0.5])
            dn = sum(ser[-0.5][x] for x in fwd if x in ser[-0.5])
            if e < 0.25:                       # 횡보 -> 역추세가 이겨야
                chop_n += 1
                chop_hit += up > dn
                gains.append((up - dn) * 100)
            elif e > 0.4:                      # 추세 -> 모멘텀이 이겨야
                tr_n += 1
                tr_hit += dn > up
                gains.append((dn - up) * 100)
        se = st.pstdev(gains) / math.sqrt(len(gains))
        print(f"  {w:<12}{chop_n+tr_n:>7}{f'{chop_hit}/{chop_n} ({chop_hit/chop_n*100:.0f}%)':>22}"
              f"{f'{tr_hit}/{tr_n} ({tr_hit/tr_n*100:.0f}%)':>22}"
              f"{st.mean(gains):>+11.3f}%p{st.mean(gains)/se:>7.2f}")

    print(f"\n\n3. 라우팅 성적\n")
    rows: List[Tuple[str, Dict]] = []
    for k in KS:
        rows.append((f"고정 k={k:+.2f}" + ("  ← 지금" if k == 0 else ""),
                     stats(ser[k], cal)))
    for w in (21, 63):
        for amp in (0.5, 1.0):
            out = {}
            cur = 0.0
            for i, d in enumerate(days):
                if i % 21 == 0:
                    e = effs[w].get(d)
                    cur = 0.0 if e is None else (amp if e < 0.25
                                                 else (-amp if e > 0.4 else 0.0))
                kk = min(KS, key=lambda x: abs(x - cur))
                if d in ser[kk]:
                    out[d] = ser[kk][d]
            rows.append((f"라우팅 효율비{w} / ±{amp:.1f}", stats(out, cal)))
    print(f"  {'':<26}{'CAGR':>9}{'샤프':>7}{'MDD':>9}{'최악의 해':>10}"
          f"{'│전반 샤프':>13}{'후반 샤프':>11}")
    print("  " + "-" * 86)
    for label, m in rows:
        s1 = stats({d: v for d, v in
                    (ser[0.0] if label.startswith("고정 k=+0.00") else {}).items()}, cal) \
            if False else None
        print(f"  {label:<26}{m['cagr']:>+8.2f}%{m['sharpe']:>7.2f}"
              f"{m['mdd']:>+8.1f}%{m['worst']:>+9.1f}%", end="")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
