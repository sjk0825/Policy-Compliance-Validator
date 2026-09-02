"""되맞춤과 추세 필터는 반대 국면에서 번다.

두 장치를 같은 말로 뭉뚱그리면 모순처럼 보인다. "되맞춤은 횡보에서 벌고
추세에서 잃는다"고 해놓고 "추세 필터는 횡보에서 깎인다"고 하면 앞뒤가
안 맞는 것처럼 들린다. 서로 다른 두 장치이고, 국면 노출이 정확히 반대다.

    되맞춤     목표 비중으로 되돌린다. 싸진 것을 사고 비싸진 것을 판다.
              값이 오르내리면 벌고, 한 방향으로 밀리면 잃는다.
    추세 필터   추세 아래면 현금으로 뺀다. 하락 추세를 통째로 피한다.
              한 방향으로 밀리면 벌고, 오르내리면 헛방을 친다.

조건 변수를 각 장치에 맞게 따로 잡아야 한다. 되맞춤이 수확하는 것은 두
자산의 상대가격이 오르내리는 정도이므로 비율의 효율비로 가른다. 추세
필터가 피하는 것은 시장 자체의 하락 추세이므로 방향까지 함께 본다.

    효율비 = |구간 순변화| / 구간 일별 변화 절댓값 합
    1에 가까우면 한 방향, 0에 가까우면 오르내림

사후 귀속이다. 신호가 아니라 "번 돈이 어느 국면에서 나왔는가"를 묻는다.

    python scripts/chop_vs_trend.py
"""
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from engine import PriceStore                                  # noqa: E402
from btal_hibl import closes, daily_returns                    # noqa: E402
from trend_overlay import build_signals, one_path, PERIOD, CASH  # noqa: E402
from trend_longrun import load, daily                          # noqa: E402

CORE = ["SPY", "QQQ", "TLT", "GLD", "VNQ"]
WIN = 21


def eff_and_dir(px: Dict[str, float], cal: List[str]) -> Dict[str, Tuple[float, float]]:
    """각 날이 끝인 직전 21일 구간의 (효율비, 순변화)."""
    ds = [d for d in cal if d in px]
    out: Dict[str, Tuple[float, float]] = {}
    for i in range(WIN, len(ds)):
        w = ds[i - WIN:i + 1]
        net = px[w[-1]] / px[w[0]] - 1
        tot = sum(abs(px[w[k + 1]] / px[w[k]] - 1) for k in range(len(w) - 1))
        if tot > 0:
            out[ds[i]] = (abs(net) / tot, net)
    return out


def series_of(rets, sig, cal, base, lo, hi, on, period) -> Dict[str, float]:
    days = [d for d in cal if lo <= d <= hi]
    if period >= 10 ** 5:
        p = one_path(rets, sig, days, base, period, 0, on)
        return dict(zip(days[len(days) - len(p):], p))
    paths = [one_path(rets, sig, days, base, period, o, on) for o in range(period)]
    n = min(len(p) for p in paths)
    avg = [st.mean([p[i] for p in paths]) for i in range(n)]
    return dict(zip(days[len(days) - n:], avg))


def ann(rs: List[float]) -> Optional[float]:
    if len(rs) < 30:
        return None
    e = 1.0
    for r in rs:
        e *= (1 + r)
    return (e ** (252 / len(rs)) - 1) * 100


def show(title: str, rows, buckets, total: int) -> None:
    print(f"\n{title}\n")
    print(f"  {'국면':<26}{'일수':>7}{'비중':>8}"
          + "".join(f"{h:>13}" for h, _ in rows) + f"{'차이':>11}")
    print("  " + "-" * (41 + 13 * len(rows) + 11))
    for label, keep in buckets:
        vals = []
        for _, s in rows:
            vals.append(ann([v for d, v in s.items() if keep(d)]))
        n = sum(1 for d in rows[0][1] if keep(d))
        cells = "".join(f"{v:>+12.2f}%" if v is not None else f"{'-':>13}"
                        for v in vals)
        diff = (f"{vals[1]-vals[0]:>+10.2f}%p"
                if None not in vals[:2] else f"{'-':>11}")
        print(f"  {label:<26}{n:>7}{n/total*100:>7.1f}%{cells}{diff}")


def main() -> int:
    # ---- A. 되맞춤: BTAL/HIBL 상대가격의 오르내림으로 가른다 ----
    store = PriceStore(Path("fixtures/wide"))
    cal_w = sorted(closes(store, "SPY"))
    pw = {s: closes(store, s) for s in ("BTAL", "HIBL", "SPY", "BIL")}
    rw = daily_returns(pw, cal_w)
    ratio = {d: pw["HIBL"][d] / pw["BTAL"][d]
             for d in cal_w if d in pw["HIBL"] and d in pw["BTAL"]}
    ed = eff_and_dir(ratio, cal_w)
    LO_A, HI_A = "2019-11-08", "2026-12-31"
    W = {"BTAL": 0.5, "HIBL": 0.5}
    none_w = {s: {} for s in W}
    reb = series_of(rw, none_w, cal_w, W, LO_A, HI_A, False, PERIOD)
    hold = series_of(rw, none_w, cal_w, W, LO_A, HI_A, False, 10 ** 6)
    n_a = sum(1 for d in reb if d in ed)
    show("A. 되맞춤 — BTAL/HIBL 50:50, 상대가격의 국면별 (2019-11~)",
         [("방치", hold), ("21일 되맞춤", reb)],
         [("오르내림 (효율비 <0.2)", lambda d: d in ed and ed[d][0] < 0.2),
          ("중간      (0.2~0.4)", lambda d: d in ed and 0.2 <= ed[d][0] < 0.4),
          ("한 방향   (>0.4)", lambda d: d in ed and ed[d][0] >= 0.4)],
         n_a)
    print("\n  되맞춤은 상대가격이 오르내릴 때 벌고 한 방향으로 밀릴 때 잃는다.")

    # ---- B. 추세 필터: 시장의 방향까지 함께 본다 ----
    px = load()
    px[CASH] = px.pop("SHY")
    cal = sorted(px["SPY"])
    px = {s: px[s] for s in CORE + [CASH]}
    rets = daily(px, cal)
    base = {s: 1 / len(CORE) for s in CORE}
    ed2 = eff_and_dir(px["SPY"], cal)
    LO_B, HI_B = "2005-01-03", "2026-12-31"
    none = build_signals({s: px[s] for s in CORE}, cal, "none")
    ma200 = build_signals({s: px[s] for s in CORE}, cal, "ma200")
    plain = series_of(rets, none, cal, base, LO_B, HI_B, False, PERIOD)
    filt = series_of(rets, ma200, cal, base, LO_B, HI_B, True, PERIOD)
    n_b = sum(1 for d in plain if d in ed2)
    show("B. 추세 필터 — 5종 균등, SPY 국면별 (2005~2026)",
         [("필터 없음", plain), ("+ ma200", filt)],
         [("하락 추세 (효율>0.4, 순-)",
           lambda d: d in ed2 and ed2[d][0] > 0.4 and ed2[d][1] < 0),
          ("상승 추세 (효율>0.4, 순+)",
           lambda d: d in ed2 and ed2[d][0] > 0.4 and ed2[d][1] > 0),
          ("횡보      (효율 <0.2)", lambda d: d in ed2 and ed2[d][0] < 0.2)],
         n_b)
    print("\n  추세 필터는 하락 추세에서 벌고 횡보에서 잃는다. 되맞춤과 반대다.")
    print("  둘을 같이 쓰는 것이 모순이 아니라 서로 다른 국면을 맡는 짝이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
