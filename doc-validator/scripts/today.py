"""오늘 무엇을 들고 있어야 하는가.

정의는 둘로 나뉜다.

    비중   14종 균등. 되맞춤은 126거래일(반년) 트랜치로 흩뜨린다.
    신호   자산마다 200일선 위면 그 자산, 아래면 그 몫만 현금(BIL).
          21거래일마다 다시 본다.

트랜치는 자금을 N등분해 각각 다른 날에 되맞추는 것이므로, 실무에서는
매일 목표와의 차이를 1/N만큼 좁히면 같다. 그래서 아래 목표 비중은
"오늘 당장 이 비중을 맞춰라"가 아니라 "이쪽으로 1/N씩 좁혀라"다.

    python scripts/today.py
    python scripts/today.py --refresh --held portfolios/held.json
"""
import argparse
import json
import math
import statistics as st
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "fixtures" / "live"
CORE = ["SPY", "QQQ", "069500", "VNQ", "TLT", "IEF", "GLD", "SLV",
        "DBC", "XLE", "XLU", "EFA", "EEM", "BTC/USD"]
KRW_ASSETS = {"069500"}   # 이미 원화로 거래된다. 나머지는 환율을 곱한다
HEDGE = {"DBMF": 0.15, "BTAL": 0.10, "UUP": 0.10}
CASH = "BIL"        # 백테스트 대용물. 실제로는 원화 예금/CMA로 둔다
NAMES = {"SPY": "S&P500", "QQQ": "나스닥100", "069500": "KODEX 200",
         "VNQ": "미국 리츠", "TLT": "미국 20년+ 국채", "IEF": "미국 7-10년 국채",
         "GLD": "금", "SLV": "은", "DBC": "원자재", "XLE": "에너지",
         "XLU": "유틸리티", "EFA": "선진국(미국 외)", "EEM": "신흥국",
         "BTC/USD": "비트코인", "DBMF": "관리선물", "BTAL": "고베타 숏",
         "UUP": "달러", "BIL": "현금 (원화 예금·CMA)"}
MA = 200          # 보유/현금을 가르는 선
DD_WIN = 504      # 고점을 찾는 창 (2년)
DD_THR = 0.20     # 그 고점 대비 -20% 이내여야 보유
# 낙폭 조건은 초고변동성 자산에만 건다. 변동성이 크면 이동평균이 한참
# 아래로 처져서 -40%를 빠져도 '추세 위'로 판정되는 사각지대가 생긴다.
# 그 성질이 없는 자산에 걸면 급락장에서 너무 일찍 빠져 손해다(2008 검증).
DD_ASSETS = {"BTC/USD"}
MA_REGIME = 60    # 기울기를 바꾸는 선
TILT_L = 5        # 기울기 기준이 되는 최근 수익률 기간
K_ABOVE = -0.50   # 선 위: 오른 것을 더 산다
K_BELOW = 0.00    # 선 아래: 기울이지 않는다 (기여가 없어 뺀다)


def fetch(refresh: bool) -> Dict[str, List[tuple]]:
    """원화 환산 종가. 국내 거주자가 계좌에서 보는 값이 이것이다."""
    CACHE.mkdir(parents=True, exist_ok=True)
    import csv
    raw: Dict[str, List[tuple]] = {}
    syms = CORE + list(HEDGE) + [CASH, "USD/KRW"]
    need = [s for s in syms
            if refresh or not (CACHE / f"{s.replace('/', '-')}.csv").exists()]
    if need:
        import FinanceDataReader as fdr
        for s in need:
            df = fdr.DataReader(s, start="2024-01-01")
            df = df[["Close"]].dropna()
            p = CACHE / f"{s.replace('/', '-')}.csv"
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["Date", "Close"])
                for d, v in zip(df.index, df["Close"]):
                    w.writerow([str(d)[:10], float(v)])
    for s in syms:
        p = CACHE / f"{s.replace('/', '-')}.csv"
        with p.open(encoding="utf-8") as f:
            raw[s] = [(r["Date"], float(r["Close"])) for r in csv.DictReader(f)]

    fx = dict(raw.pop("USD/KRW"))
    dates = sorted({d for rows in raw.values() for d, _ in rows})
    filled, last = {}, None
    for d in dates:                      # 휴일은 직전 고시를 쓴다
        if d in fx:
            last = fx[d]
        if last:
            filled[d] = last
    out: Dict[str, List[tuple]] = {}
    for s, rows in raw.items():
        out[s] = [(d, v if s in KRW_ASSETS else v * filled[d])
                  for d, v in rows if d in filled]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--hedge", action="store_true",
                    help="DBMF/BTAL/UUP 35%를 얹은 안정형")
    ap.add_argument("--held", default=None, help="현재 보유 비중 JSON")
    args = ap.parse_args()

    px = fetch(args.refresh)
    universe = list(CORE)
    base = {s: 1.0 / len(CORE) for s in CORE}
    if args.hedge:
        h = sum(HEDGE.values())
        base = {s: (1 - h) / len(CORE) for s in CORE}
        base.update(HEDGE)
        universe = CORE + list(HEDGE)

    print(f"판정일 기준  {max(px['SPY'])[0]}   (오늘 {datetime.now():%Y-%m-%d})")
    print(f"기준통화  원화 — 미국 자산은 환율을 곱해 계산한다")
    print(f"규칙  ① {MA}일선 위면 보유. 단 {'·'.join(sorted(DD_ASSETS))}는")
    print(f"         {DD_WIN}일 최고 대비 -{DD_THR*100:.0f}% 이내도 함께 만족해야 함")
    print(f"         아니면 그 몫만 현금 (21거래일마다 재판정)")
    print(f"      ② {MA_REGIME}일선 위 자산은 최근 {TILT_L}일 강세 쪽으로 k={K_ABOVE:+.2f},")
    print(f"         아래 자산은 약세 쪽으로 k={K_BELOW:+.2f} 만큼 비중을 기울인다")
    print(f"      ③ 되맞춤은 21거래일 트랜치 (매일 목표와의 차이를 1/21씩)\n")

    on: Dict[str, bool] = {}
    hot: Dict[str, bool] = {}
    mom: Dict[str, float] = {}
    for s in universe:
        rows = px[s]
        if len(rows) < MA:
            on[s], hot[s] = True, True
            continue
        last = rows[-1][1]
        ok = last > st.mean(v for _, v in rows[-MA:])
        if s in DD_ASSETS:
            peak = max(v for _, v in rows[-DD_WIN:]) if len(rows) >= DD_WIN \
                else max(v for _, v in rows)
            ok = ok and last / peak - 1 > -DD_THR
        on[s] = ok
        hot[s] = last > st.mean(v for _, v in rows[-MA_REGIME:])
        if len(rows) > TILT_L:
            mom[s] = last / rows[-1 - TILT_L][1] - 1

    # 기울기: 최근 TILT_L일 수익률을 자산들 사이에서 표준화한 뒤
    #         60일선 위/아래에 따라 다른 부호로 기울인다
    core = [s for s in universe if s in mom]
    mu = st.mean(mom[s] for s in core)
    sd = st.pstdev([mom[s] for s in core]) or 1.0
    raw = {}
    for s in universe:
        z = (mom.get(s, mu) - mu) / sd
        k = K_ABOVE if hot.get(s, True) else K_BELOW
        raw[s] = base[s] * math.exp(max(-3.0, min(3.0, -k * z)))
    tot = sum(raw.values())
    sleeve = {s: v / tot for s, v in raw.items()}

    print(f"  {'종목':<10}{'설명':<15}{'원화종가':>13}{'200일선':>9}{'고점대비':>9}{'60일선':>9}"
          f"{'5일':>8}{'기울기':>8}  신호")
    print("  " + "-" * 84)
    for s in universe:
        rows = px[s]
        last = rows[-1][1]
        g200 = (last / st.mean(v for _, v in rows[-MA:]) - 1) * 100
        peak = max(v for _, v in rows[-DD_WIN:]) if len(rows) >= DD_WIN \
            else max(v for _, v in rows)
        gdd = (last / peak - 1) * 100
        g60 = (last / st.mean(v for _, v in rows[-MA_REGIME:]) - 1) * 100
        tilt = (sleeve[s] / base[s] - 1) * 100
        mark = "○ 보유" if on[s] else "● 현금"
        print(f"  {s:<10}{NAMES.get(s, ''):<15}{last:>13,.0f}{g200:>+8.1f}%"
              f"{gdd:>+8.1f}%{g60:>+8.1f}%{mom.get(s,0)*100:>+7.1f}%{tilt:>+7.1f}%  {mark}")

    tgt: Dict[str, float] = {}
    for s in universe:
        w = sleeve[s]
        if on.get(s, True):
            tgt[s] = tgt.get(s, 0) + w
        else:
            tgt[CASH] = tgt.get(CASH, 0) + w

    print(f"\n\n목표 비중\n")
    for s, w in sorted(tgt.items(), key=lambda x: -x[1]):
        print(f"  {s:<10}{NAMES.get(s, ''):<18}{w*100:>7.2f}%")
    print(f"  {'':<28}{'-'*8}")
    print(f"  {'합계':<28}{sum(tgt.values())*100:>7.2f}%")
    print(f"\n  위험자산 {(1-tgt.get(CASH, 0))*100:.1f}%  /  현금 {tgt.get(CASH, 0)*100:.1f}%")

    out = {"id": "final_t_hedge" if args.hedge else "final_t",
           "name": ("14종 + 헤지3종, 추세 필터" if args.hedge
                    else "14종 균등, 추세 필터"),
           "decided_at": f"{datetime.now():%Y-%m-%d}",
           "as_of_close": max(px["SPY"])[0],
           "rule": {"signal": (f"ma{MA}; {sorted(DD_ASSETS)}만 추가로 "
                               f"고점({DD_WIN}일) 대비 -{DD_THR*100:.0f}% 이내"),
                    "regime": f"ma{MA_REGIME}",
                    "tilt": {"lookback": TILT_L, "k_above": K_ABOVE,
                             "k_below": K_BELOW},
                    "rebalance": "21거래일 트랜치",
                    "cash": CASH, "basis": "KRW"},
           "base_weights": base, "signal_on": on, "regime_above": hot,
           "sleeve_weights": sleeve, "target_weights": tgt}
    p = ROOT / "portfolios" / f"{out['id']}.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    print(f"\n  저장: portfolios/{p.name}")

    if args.held:
        held = json.loads(Path(args.held).read_text(encoding="utf-8"))
        print(f"\n\n현재 보유에서의 차이\n")
        print(f"  {'종목':<10}{'현재':>9}{'목표':>9}{'조정':>10}")
        print("  " + "-" * 40)
        for s in sorted(set(held) | set(tgt),
                        key=lambda x: -(tgt.get(x, 0) - held.get(x, 0))):
            d = tgt.get(s, 0) - held.get(s, 0)
            if abs(d) < 0.0005:
                continue
            print(f"  {s:<10}{held.get(s,0)*100:>8.2f}%{tgt.get(s,0)*100:>8.2f}%"
                  f"{d*100:>+9.2f}%p")
    return 0


if __name__ == "__main__":
    sys.exit(main())
