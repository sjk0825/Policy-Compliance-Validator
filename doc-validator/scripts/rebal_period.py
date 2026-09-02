"""되맞춤 주기를 늘린다. 신호 주기와 분리해서.

되맞춤은 추세 구간에서 역풍이다. 그렇다면 주기를 늘려 덜 손대는 쪽이
나을 수 있다. 회전율이 줄어 세금도 덜 낸다. 다만 한 가지를 분리해야 한다.

지금까지의 코드는 되맞춤 날에만 목표 비중을 다시 계산했다. 그 목표에는
추세 신호가 들어 있으므로, 주기를 1년으로 늘리면 신호도 1년에 한 번만
반영된다. 추세 필터는 늦으면 값어치가 없다. 두 주기는 다른 것이다.

    신호 주기    자산과 현금 사이를 오가는 속도. 빨라야 한다.
    되맞춤 주기   자산끼리의 비중을 되돌리는 속도. 느려도 된다.

자산마다 제 몫(슬리브)을 준다. 슬리브 안에서는 매일 신호대로 자산과
현금을 오가고, 슬리브 크기 자체는 되맞춤 주기마다 균등으로 되돌린다.
되맞춤은 트랜치로 흩뜨린다. 주기가 길면 오프셋을 균등 표집한다.

    python scripts/rebal_period.py
    python scripts/rebal_period.py --data wide
"""
import argparse
import math
import statistics as st
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from btal_hibl import summarize                     # noqa: E402
from worst_year_push import ma_grade, daily, TEN    # noqa: E402
from trend_longrun import load                      # noqa: E402

TRADING = 252
COST_BP = 10.0
MAX_OFFSETS = 42


def ma200(px, cal) -> Dict[str, float]:
    return ma_grade(px, cal, ns=(200,))


def one_path(rets, exp, days, base, cash: str,
             rebal: int, sig_every: int, offset: int) -> tuple:
    """슬리브 구조. 반환은 (일별수익률, 일별회전율)."""
    sleeve: Dict[str, float] = {}          # 자산별 몫 (현금 포함한 크기)
    inner: Dict[str, float] = {}           # 슬리브 안 자산 비중 (나머지는 현금)
    out: List[float] = []
    turns: List[float] = []
    for k, d in enumerate(days):
        avail = [s for s in base if d in rets.get(s, {})]
        has_cash = d in rets.get(cash, {})
        if not avail or not has_cash:
            continue
        aset = set(avail)
        if sleeve:
            r = 0.0
            grow: Dict[str, float] = {}
            for s, w in sleeve.items():
                if s in aset:
                    a = inner.get(s, 1.0)
                    rr = a * rets[s][d] + (1 - a) * rets[cash][d]
                    r += w * rr
                    grow[s] = w * (1 + rr)
                    # 슬리브 안에서 자산이 커진 만큼 내부 비중도 흐른다
                    if 1 + rr != 0:
                        inner[s] = a * (1 + rets[s][d]) / (1 + rr)
                else:
                    grow[s] = w
            out.append(r)
            t = sum(grow.values())
            if t > 0:
                sleeve = {s: v / t for s, v in grow.items()}
        traded = 0.0        # 매매 금액. 판 쪽과 산 쪽을 모두 더한다 (레포 관행)
        # 1) 신호: 슬리브 안 자산/현금 비율을 목표로 되돌린다
        if not sleeve or k % sig_every == 0:
            for s in avail:
                tgt = exp.get(s, {}).get(d, 1.0)
                traded += 2 * sleeve.get(s, 0) * abs(tgt - inner.get(s, tgt))
                inner[s] = tgt
        # 2) 되맞춤: 슬리브 크기를 균등으로 되돌린다.
        #    나중에 상장된 자산은 처음 나타난 날 편입한다. 이걸 빼면
        #    주기가 긴 판에서 BTC 같은 후발 자산이 영원히 안 들어온다.
        newcomer = bool(aset - set(sleeve))
        if not sleeve or newcomer or (k - offset) % rebal == 0:
            w = {s: base[s] for s in avail}
            tw = sum(w.values())
            tgt = {s: v / tw for s, v in w.items()}
            traded += sum(abs(tgt.get(s, 0) - sleeve.get(s, 0))
                          for s in set(tgt) | set(sleeve))
            sleeve = tgt
            for s in avail:
                inner.setdefault(s, exp.get(s, {}).get(d, 1.0))
        if traded and out:
            out[-1] -= traded * COST_BP / 10000
        turns.append(traded)
    return out, turns


def run(rets, exp, cal, base, cash, lo, hi, rebal, sig_every,
        min_days=60) -> Optional[Dict]:
    days = [d for d in cal if lo <= d <= hi]
    n_off = min(rebal, MAX_OFFSETS)
    offs = [round(i * rebal / n_off) for i in range(n_off)]
    res = [one_path(rets, exp, days, base, cash, rebal, sig_every, o)
           for o in offs]
    paths = [p for p, _ in res if len(p) >= min_days]
    if not paths:
        return None
    n = min(len(p) for p in paths)
    m = summarize([st.mean([p[i] for p in paths]) for i in range(n)])
    m["turnover"] = st.mean([sum(t) / (len(t) / TRADING) for _, t in res]) * 50
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="longrun", choices=["longrun", "wide"])
    args = ap.parse_args()

    if args.data == "longrun":
        px = load()
        cash = "SHY"
        uni = TEN
        cal = sorted(px["SPY"])
        LO, HI = "2005-01-03", "2026-12-31"
        years = range(2005, 2027)
        title = "10종 (SPY QQQ TLT GLD VNQ IEF DBC UUP EFA EEM), 현금 SHY, 2005~2026"
    else:
        from engine import PriceStore
        from btal_hibl import closes
        store = PriceStore(Path("fixtures/wide"))
        cal = sorted(closes(store, "SPY"))
        uni = ["BTC/USD", "GLD", "TLT", "QQQ", "SPY", "069500", "VNQ",
               "DBC", "XLE", "IEF", "EFA", "EEM", "SLV", "XLU"]
        cash = "BIL"
        px = {s: closes(store, s) for s in uni + [cash]}
        LO, HI = "2012-05-07", "2026-12-31"
        years = range(2013, 2027)
        title = "14종 + 현금 BIL, 2012-05~2026"

    rets = daily(px, cal)
    base = {s: 1 / len(uni) for s in uni}
    none = {s: {} for s in uni}
    filt = {s: ma200(px[s], cal) for s in uni}

    print(f"{title}\n")
    print(f"트랜치 오프셋은 최대 {MAX_OFFSETS}개를 균등 표집한다. 비용 {COST_BP:.0f}bp\n")

    def block(exp, label, sig_every):
        print(f"\n{label}\n")
        print(f"  {'되맞춤 주기':<14}{'CAGR':>9}{'샤프':>7}{'변동성':>8}{'MDD':>9}"
              f"{'최악의 해':>10}{'마이너스 해':>12}{'연 회전율(편도)':>14}")
        print("  " + "-" * 82)
        for name, p in [("21일 (월)", 21), ("63일 (분기)", 63),
                        ("126일 (반년)", 126), ("252일 (1년)", 252),
                        ("방치", 10 ** 6)]:
            se = p if sig_every is None else sig_every
            m = run(rets, exp, cal, base, cash, LO, HI, p, se)
            if not m:
                continue
            ys = [a["total"] for y in years
                  if (a := run(rets, exp, cal, base, cash, f"{y}-01-01",
                               f"{y}-12-31", p, se, min_days=150))]
            neg = sum(1 for v in ys if v < 0)
            print(f"  {name:<14}{m['cagr']:>+8.2f}%{m['sharpe']:>7.2f}"
                  f"{m['vol']:>7.1f}%{m['mdd']:>+8.1f}%{min(ys):>+9.1f}%"
                  f"{neg:>7}/{len(ys)}회{m['turnover']:>10.0f}%")

    block(none, "A. 추세 필터 없이 — 되맞춤 주기만", 10 ** 6)
    block(filt, "B. ma200 + 신호 매일", 1)
    block(filt, "C. ma200 + 신호 21일마다 (되맞춤과 분리)", 21)
    block(filt, "D. ma200 + 신호를 되맞춤 날에만 (묶임)", None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
