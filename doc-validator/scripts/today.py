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
import statistics as st
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "fixtures" / "live"
CORE = ["SPY", "QQQ", "069500", "VNQ", "TLT", "IEF", "GLD", "SLV",
        "DBC", "XLE", "XLU", "EFA", "EEM", "BTC/USD"]
HEDGE = {"DBMF": 0.15, "BTAL": 0.10, "UUP": 0.10}
CASH = "BIL"
NAMES = {"SPY": "S&P500", "QQQ": "나스닥100", "069500": "KODEX 200",
         "VNQ": "미국 리츠", "TLT": "미국 20년+ 국채", "IEF": "미국 7-10년 국채",
         "GLD": "금", "SLV": "은", "DBC": "원자재", "XLE": "에너지",
         "XLU": "유틸리티", "EFA": "선진국(미국 외)", "EEM": "신흥국",
         "BTC/USD": "비트코인", "DBMF": "관리선물", "BTAL": "고베타 숏",
         "UUP": "달러", "BIL": "현금(단기 국채)"}
MA = 200


def fetch(refresh: bool) -> Dict[str, List[tuple]]:
    CACHE.mkdir(parents=True, exist_ok=True)
    import csv
    out: Dict[str, List[tuple]] = {}
    syms = CORE + list(HEDGE) + [CASH]
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
            out[s] = [(r["Date"], float(r["Close"])) for r in csv.DictReader(f)]
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
    print(f"규칙  {MA}일선 위면 보유, 아래면 그 몫만 현금. 신호는 21거래일마다.")
    print(f"      비중 되맞춤은 126거래일 트랜치 (매일 목표와의 차이를 1/126씩)\n")

    print(f"  {'종목':<10}{'설명':<16}{'종가':>12}{'200일선':>12}"
          f"{'괴리':>9}  신호")
    print("  " + "-" * 68)
    on: Dict[str, bool] = {}
    for s in universe:
        rows = px[s]
        if len(rows) < MA:
            print(f"  {s:<10}{NAMES.get(s, ''):<16}{'표본 부족':>33}")
            on[s] = True
            continue
        last = rows[-1][1]
        ma = st.mean(v for _, v in rows[-MA:])
        on[s] = last > ma
        gap = (last / ma - 1) * 100
        mark = "○ 보유" if on[s] else "● 현금"
        print(f"  {s:<10}{NAMES.get(s, ''):<16}{last:>12,.2f}{ma:>12,.2f}"
              f"{gap:>+8.1f}%  {mark}")

    tgt: Dict[str, float] = {}
    for s, w in base.items():
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
           "rule": {"signal": f"ma{MA}, 21거래일마다 재판정",
                    "rebalance": "126거래일 트랜치",
                    "cash": CASH},
           "base_weights": base, "signal_on": on, "target_weights": tgt}
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
