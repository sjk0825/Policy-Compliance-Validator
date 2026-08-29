"""라우팅 프로파일들을 같은 컨텍스트로 비교한다.

어느 프로그램을 자주 태울지는 "무엇이 맞는가"가 아니라 "무엇을 원하는가"의
문제다. 그래서 정답을 고르는 대신 프로파일별로 무엇이 달라지는지 나란히
보여준다.

컨텍스트 생성이 병목이므로 한 번만 만들고 프로파일마다 라우팅만 다시 한다.
프로파일을 따로 돌리면 같은 계산을 N번 반복하게 된다.

    python scripts/routing_compare.py --slice ... --data fixtures/wide
"""
import argparse
import json
import statistics as st
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore, build_context      # noqa: E402
from engine import programs                       # noqa: E402
from engine.router import ROUTING_PROFILES, heuristic_route   # noqa: E402

HORIZONS = [21, 63]
OUT = ROOT / "fixtures" / "backtests"


def profile_stats(vals: List[float]) -> Dict[str, Any]:
    if len(vals) < 30:
        return {}
    wins = [v for v in vals if v > 0]
    losses = [-v for v in vals if v < 0]
    m, sd = st.mean(vals), st.pstdev(vals)
    return {
        "n": len(vals),
        "win_rate": round(len(wins) / len(vals) * 100, 2),
        "median": round(st.median(vals), 3),
        "mean": round(m, 3),
        "skew": round(sum((v - m) ** 3 for v in vals) / len(vals) / sd ** 3, 3) if sd else None,
        "win_loss": round(st.mean(wins) / st.mean(losses), 3) if wins and losses else None,
        # 이 표본에서 판정일 단위로 얼마나 꾸준했는지
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", required=True)
    ap.add_argument("--data")
    args = ap.parse_args()

    meta = json.loads(Path(args.slice).read_text(encoding="utf-8"))
    store = PriceStore(Path(args.data) if args.data else None)

    by_market = defaultdict(list)
    for e in meta["symbols"]:
        market = "crypto" if e.get("kind") == "암호화폐" else (
            "kr" if e["group"].startswith("kr_") else "us")
        by_market[market].append(e["symbol"])
    pairs = [(s, d) for market, grid in meta["decision_grid"].items()
             for d in grid["decision_dates"] for s in by_market.get(market, [])]

    print(f"슬라이스 {meta['slice_id']}  판정 {len(pairs):,}건  "
          f"프로파일 {len(ROUTING_PROFILES)}개\n")

    idx = {}
    def fwd(sym, date, h):
        if sym not in idx:
            idx[sym] = {b.date: i for i, b in enumerate(store._all_bars(sym))}
        bars = store._all_bars(sym)
        i = idx[sym].get(date)
        return None if i is None or i + h >= len(bars) else (
            bars[i + h].close / bars[i].close - 1) * 100

    # 프로파일별 결과. 같은 컨텍스트를 공유한다.
    rows = {p: [] for p in ROUTING_PROFILES}
    t0 = time.perf_counter()
    for n, (sym, date) in enumerate(pairs, 1):
        try:
            ctx = build_context(store, sym, date).to_dict()
        except Exception:
            continue
        rets = {h: fwd(sym, date, h) for h in HORIZONS}
        for pname in ROUTING_PROFILES:
            route = heuristic_route(ctx, profile=pname)
            res = programs.get(route.program).run(ctx)
            rows[pname].append({"symbol": sym, "date": date,
                                "market": ctx["meta"]["market"],
                                "program": route.program, "decision": res.decision,
                                **{f"ret_{h}": rets[h] for h in HORIZONS}})
        if n % 10000 == 0:
            print(f"  … {n:,}/{len(pairs):,}  ({time.perf_counter()-t0:.0f}초)", flush=True)

    # 동료 중앙값 대비 상대 성과
    for pname, rs in rows.items():
        grouped = defaultdict(list)
        for r in rs:
            grouped[(r["market"], r["date"])].append(r)
        for group in grouped.values():
            for h in HORIZONS:
                vals = sorted(x[f"ret_{h}"] for x in group if x[f"ret_{h}"] is not None)
                if len(vals) < 5:
                    for x in group:
                        x[f"rel_{h}"] = None
                    continue
                mid = (vals[len(vals) // 2] if len(vals) % 2
                       else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2)
                for x in group:
                    v = x[f"ret_{h}"]
                    x[f"rel_{h}"] = None if v is None else v - mid

    summary = {}
    for h in HORIZONS:
        print(f"\n=== {h}거래일 · true 판정의 동료 대비 초과수익")
        print(f"  {'프로파일':<16}{'true%':>8}{'건수':>9}{'승률':>9}{'중앙값':>10}"
              f"{'평균':>10}{'왜도':>9}{'이익/손실':>11}")
        print("  " + "-" * 74)
        for pname in ROUTING_PROFILES:
            rs = rows[pname]
            taken = [r[f"rel_{h}"] for r in rs
                     if r["decision"] and r.get(f"rel_{h}") is not None]
            s = profile_stats(taken)
            if not s:
                print(f"  {pname:<16} (표본 부족)")
                continue
            tp = sum(1 for r in rs if r["decision"]) / len(rs) * 100
            summary.setdefault(pname, {})[h] = {**s, "true_pct": round(tp, 1)}
            print(f"  {pname:<16}{tp:>7.1f}%{s['n']:>9,}{s['win_rate']:>8.2f}%"
                  f"{s['median']:>+9.2f}%{s['mean']:>+9.2f}%{s['skew']:>+9.2f}"
                  f"{s['win_loss']:>11.2f}")

    print(f"\n프로그램 분포")
    for pname in ROUTING_PROFILES:
        mix = defaultdict(int)
        for r in rows[pname]:
            mix[r["program"]] += 1
        tot = len(rows[pname])
        print(f"  {pname:<16}" + "  ".join(
            f"{k} {v/tot*100:.0f}%" for k, v in sorted(mix.items(), key=lambda kv: -kv[1])))

    # 프로그램 자체의 성질도 본다. 라우팅이 무엇을 고르든, 각 프로그램이
    # 어떤 수익 분포를 내는지가 재료의 성질이다.
    print(f"\n프로그램별 성질 (balanced 기준, 21일)")
    print(f"  {'프로그램':<18}{'건수':>9}{'승률':>9}{'중앙값':>10}{'평균':>10}{'왜도':>9}")
    print("  " + "-" * 65)
    byprog = defaultdict(list)
    for r in rows["balanced"]:
        if r["decision"] and r.get("rel_21") is not None:
            byprog[r["program"]].append(r["rel_21"])
    for prog, vals in sorted(byprog.items(), key=lambda kv: -len(kv[1])):
        s = profile_stats(vals)
        if not s:
            print(f"  {prog:<18}{len(vals):>9}   (표본 부족)")
            continue
        print(f"  {prog:<18}{s['n']:>9,}{s['win_rate']:>8.2f}%"
              f"{s['median']:>+9.2f}%{s['mean']:>+9.2f}%{s['skew']:>+9.2f}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{meta['slice_id']}_routing_profiles.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: fixtures/backtests/{meta['slice_id']}_routing_profiles.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
