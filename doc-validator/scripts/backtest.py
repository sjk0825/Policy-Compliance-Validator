"""슬라이스의 판정일 전체를 돌려 지평별 성적을 낸다.

날짜를 고르지 않는 것이 핵심이다. 사람이 시점을 고르면 아무리 조심해도
편향이 낀다(직접 고른 14개 케이스는 기저율 대비 단기 양수비율이 +18~25%p
높았다). 슬라이스가 정한 주간 판정일을 전부 훑으면 그럴 여지가 없다.

적중률만 보면 안 된다. 무조건 참을 뱉는 프로그램도 21일 지평에서 57%를
낸다. 그래서 같은 종목·같은 지평의 무조건부 기저율을 함께 구해 그 차이
(edge)를 본다. edge가 0 근처면 아무것도 하지 않은 것과 같다.

    python scripts/backtest.py
    python scripts/backtest.py --slice fixtures/slices/2y_.../slice.json
    python scripts/backtest.py --llm-sample 60
"""
import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore, build_context                    # noqa: E402
from engine import programs                                     # noqa: E402
from engine.router import (LLMRouter, RouterUnavailable,  # noqa: E402
                           chain_route, heuristic_route)

HORIZONS = [1, 3, 10, 21, 63]
OUT_DIR = ROOT / "fixtures" / "backtests"


def latest_slice() -> Path:
    slices = sorted((ROOT / "fixtures" / "slices").glob("*/slice.json"))
    if not slices:
        raise FileNotFoundError("슬라이스가 없습니다. scripts/make_slice.py를 실행하세요.")
    return slices[-1]


class Forward:
    """기준일 이후 N거래일 수익률과, 같은 종목의 무조건부 기저율.

    기저율은 반드시 테스트와 같은 창에서 구한다. 전체 기간으로 구하면
    상승장 구간을 테스트할 때 "참을 자주 뱉는다"는 것만으로 edge가
    생겨버린다. 비교 대상은 "그 구간에 아무 날이나 골랐을 때"여야 한다.
    """

    def __init__(self, store: PriceStore, window: Optional[tuple] = None) -> None:
        self.store = store
        self.window = window          # (start, end) 문자열
        self._idx: Dict[str, Dict[str, int]] = {}
        self._base: Dict[tuple, float] = {}

    def _index(self, symbol: str) -> Dict[str, int]:
        if symbol not in self._idx:
            bars = self.store._all_bars(symbol)
            self._idx[symbol] = {b.date: i for i, b in enumerate(bars)}
        return self._idx[symbol]

    def ret(self, symbol: str, date: str, h: int) -> Optional[float]:
        bars = self.store._all_bars(symbol)
        i = self._index(symbol).get(date)
        if i is None or i + h >= len(bars):
            return None
        return (bars[i + h].close / bars[i].close - 1) * 100

    def base_up_rate(self, symbol: str, h: int) -> float:
        """이 종목이 h거래일 뒤 오를 무조건부 확률(테스트 창 기준)."""
        key = (symbol, h)
        if key not in self._base:
            bars = self.store._all_bars(symbol)
            lo, hi = (self.window or (None, None))
            idxs = [i for i in range(len(bars) - h)
                    if (lo is None or bars[i].date >= lo)
                    and (hi is None or bars[i].date <= hi)]
            if not idxs:
                idxs = list(range(len(bars) - h))
            ups = sum(1 for i in idxs if bars[i + h].close > bars[i].close)
            self._base[key] = ups / max(1, len(idxs))
        return self._base[key]


def run(store: PriceStore, slice_meta: Dict[str, Any], router_kind: str,
        llm: Optional[LLMRouter] = None, pairs: Optional[List] = None,
        sleep: float = 0.0) -> List[Dict[str, Any]]:
    fwd = Forward(store, window=(slice_meta["start"], slice_meta["end"]))
    rows: List[Dict[str, Any]] = []

    if pairs is None:
        pairs = []
        by_market = defaultdict(list)
        for e in slice_meta["symbols"]:
            market = "crypto" if e.get("kind") == "암호화폐" else (
                "kr" if e["group"].startswith("kr_") else "us")
            by_market[market].append(e["symbol"])
        for market, grid in slice_meta["decision_grid"].items():
            for date in grid["decision_dates"]:
                for sym in by_market.get(market, []):
                    pairs.append((sym, date))

    errors = 0
    for n, (sym, date) in enumerate(pairs):
        try:
            ctx = build_context(store, sym, date).to_dict()
        except Exception:
            errors += 1
            continue

        if router_kind == "llm":
            if n and sleep:
                time.sleep(sleep)
            try:
                route = llm.route(ctx)
            except RouterUnavailable as e:
                route = heuristic_route(ctx, error=str(e))
        elif router_kind == "chain":
            route = chain_route(ctx)
        else:
            route = heuristic_route(ctx)

        res = programs.get(route.program).run(ctx)
        row = {
            "symbol": sym, "date": date, "market": ctx["meta"]["market"],
            "program": route.program, "route_source": route.source,
            "decision": res.decision, "confidence": res.confidence,
        }
        for h in HORIZONS:
            r = fwd.ret(sym, date, h)
            row[f"ret_{h}"] = r
            row[f"hit_{h}"] = None if r is None else ((r > 0) == res.decision)
            row[f"base_up_{h}"] = fwd.base_up_rate(sym, h)
        rows.append(row)

        if router_kind != "llm" and n % 500 == 0 and n:
            print(f"    … {n}/{len(pairs)}", flush=True)

    if errors:
        print(f"  (컨텍스트 실패 {errors}건 제외)")
    return rows


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"n": len(rows), "horizons": {}}
    if not rows:
        return out

    tr = sum(1 for r in rows if r["decision"])
    out["decision_true_pct"] = round(tr / len(rows) * 100, 1)
    out["program_mix"] = {
        p: round(sum(1 for r in rows if r["program"] == p) / len(rows) * 100, 1)
        for p in programs.REGISTRY
    }

    for h in HORIZONS:
        scored = [r for r in rows if r[f"hit_{h}"] is not None]
        if not scored:
            continue
        hits = sum(1 for r in scored if r[f"hit_{h}"])
        # 같은 판정을 무작위로 냈을 때 기대되는 적중률.
        # 참이면 상승확률, 거짓이면 하락확률이 기준이다.
        expected = sum(r[f"base_up_{h}"] if r["decision"] else 1 - r[f"base_up_{h}"]
                       for r in scored) / len(scored)
        actual = hits / len(scored)
        rets = [r[f"ret_{h}"] for r in scored]
        taken = [r[f"ret_{h}"] for r in scored if r["decision"]]
        out["horizons"][h] = {
            "scored": len(scored),
            "hit_rate": round(actual * 100, 2),
            "expected": round(expected * 100, 2),
            "edge_pp": round((actual - expected) * 100, 2),
            "avg_ret_all": round(sum(rets) / len(rets), 3),
            "avg_ret_when_true": round(sum(taken) / len(taken), 3) if taken else None,
        }
    return out


def print_summary(title: str, s: Dict[str, Any]) -> None:
    print(f"\n{title}  (판정 {s['n']:,}건, true 비율 {s.get('decision_true_pct')}%)")
    print(f"  프로그램 분포: " + "  ".join(f"{k} {v}%" for k, v in s["program_mix"].items()))
    print(f"\n  {'지평':<7}{'적중률':>9}{'기대치':>9}{'edge':>9}{'평균수익':>10}{'true일때':>10}")
    print("  " + "-" * 54)
    for h, v in s["horizons"].items():
        star = " *" if abs(v["edge_pp"]) >= 2 else ""
        print(f"  {h:>3}일  {v['hit_rate']:>8.2f}%{v['expected']:>8.2f}%"
              f"{v['edge_pp']:>+8.2f}p{v['avg_ret_all']:>+9.2f}%"
              f"{(v['avg_ret_when_true'] if v['avg_ret_when_true'] is not None else 0):>+9.2f}%{star}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice")
    ap.add_argument("--router", default="fitness", choices=["fitness", "chain", "both"])
    ap.add_argument("--llm-sample", type=int, default=0,
                    help="LLM 라우터로 비교할 무작위 표본 수 (0이면 안 함)")
    ap.add_argument("--sleep", type=float, default=14.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    slice_path = Path(args.slice) if args.slice else latest_slice()
    meta = json.loads(slice_path.read_text(encoding="utf-8"))
    store = PriceStore()

    print(f"슬라이스 {meta['slice_id']}  ({meta['start']} ~ {meta['end']})")
    print(f"종목 {meta['symbol_count']}개, 판정일 "
          f"{sum(len(g['decision_dates']) for g in meta['decision_grid'].values())}개(시장 합산)\n")

    kinds = ["chain", "heuristic"] if args.router == "both" else (
        ["chain"] if args.router == "chain" else ["heuristic"])
    labels = {"chain": "체인 라우터(구버전)", "heuristic": "적합도 라우터"}

    rows = None
    summaries = {}
    for kind in kinds:
        t0 = time.perf_counter()
        r = run(store, meta, kind)
        print(f"[{labels[kind]}] {len(r):,}건 / {time.perf_counter()-t0:.1f}초")
        summaries[kind] = summarize(r)
        print_summary(labels[kind], summaries[kind])
        if kind == "heuristic" or rows is None:
            rows = r
    heur = summaries.get("heuristic", summaries[kinds[0]])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = meta["slice_id"]
    (OUT_DIR / f"{tag}_heuristic.json").write_text(
        json.dumps({"summary": heur, "rows": rows}, ensure_ascii=False), encoding="utf-8")

    result = {"slice_id": tag, "horizons": HORIZONS, "routers": summaries}

    if args.llm_sample:
        rng = random.Random(args.seed)
        sample = rng.sample([(r["symbol"], r["date"]) for r in rows],
                            min(args.llm_sample, len(rows)))
        print(f"\n[LLM 라우터] 표본 {len(sample)}건 (같은 표본으로 규칙과 비교)")
        llm_rows = run(store, meta, "llm", llm=LLMRouter(), pairs=sample, sleep=args.sleep)
        pair_set = {(s, d) for s, d in sample}
        heur_sub = [r for r in rows if (r["symbol"], r["date"]) in pair_set]

        ok = sum(1 for r in llm_rows if r["route_source"] == "llm")
        print(f"  LLM 실제 응답 {ok}/{len(llm_rows)}건 (나머지는 규칙으로 폴백)")
        print_summary("LLM 라우터 표본", summarize(llm_rows))
        print_summary("같은 표본, 규칙 라우터", summarize(heur_sub))
        result["llm_sample"] = summarize(llm_rows)
        result["heuristic_same_sample"] = summarize(heur_sub)
        (OUT_DIR / f"{tag}_llm_sample.json").write_text(
            json.dumps({"rows": llm_rows}, ensure_ascii=False), encoding="utf-8")

    (OUT_DIR / f"{tag}_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: fixtures/backtests/{tag}_*.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
