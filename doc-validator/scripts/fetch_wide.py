"""확장 유니버스를 수집한다. S&P500 + KOSPI 시총 상위 + 기존 ETF.

종목 19개로는 횡단면 순위가 의미를 갖지 못한다. 상위 10%를 뽑아도 2개뿐이고,
실제로 초과수익의 65%가 NVDA 한 종목에서 나왔다. 순위가 소수 대형 승자의
존재 여부에 좌우되지 않으려면 수백 종목이 필요하다.

기존 curated 유니버스(37종목)도 함께 담는다. 국면 판단에 쓰는 SPY·TLT·
GLD·DBMF 같은 ETF는 지수 구성종목 목록에 없기 때문이다.

    python scripts/fetch_wide.py
    python scripts/fetch_wide.py --kr-top 200 --start 2015-01-01
"""
import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures" / "wide"
COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
RETRIES = 3


def safe_name(symbol: str) -> str:
    return symbol.replace("/", "-")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_universe(kr_top: int) -> List[Dict[str, Any]]:
    import FinanceDataReader as fdr

    items: List[Dict[str, Any]] = []
    seen = set()

    def add(symbol, name, group, kind=None):
        if symbol in seen:
            return
        seen.add(symbol)
        items.append({"symbol": symbol, "name": name, "group": group, "kind": kind})

    # 기존 curated 유니버스를 먼저 넣는다. 국면 자산이 여기 있다.
    curated = json.loads((ROOT / "fixtures" / "universe.json").read_text(encoding="utf-8"))
    for group, spec in curated["groups"].items():
        for s in spec["symbols"]:
            add(s["symbol"], s.get("name"), group, s.get("kind"))

    sp = fdr.StockListing("S&P500")
    for r in sp.to_dict("records"):
        add(str(r["Symbol"]).strip(), r.get("Name"), "us_stock")
    print(f"  S&P500 {len(sp)}종목")

    kospi = fdr.StockListing("KOSPI")
    kospi = kospi[kospi["Marcap"].notna()].sort_values("Marcap", ascending=False)
    for r in kospi.head(kr_top).to_dict("records"):
        add(str(r["Code"]).strip(), r.get("Name"), "kr_stock")
    print(f"  KOSPI 시총 상위 {kr_top}종목 (전체 {len(kospi)})")

    return items


def normalize(df):
    df = df.copy()
    rename = {}
    for c in df.columns:
        key = str(c).lower().strip().replace(" ", "")
        if key in ("open", "high", "low", "close", "volume"):
            rename[c] = key.capitalize()
    df = df.rename(columns=rename)
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[COLUMNS]
    df.index.name = "Date"
    df = df.reset_index()
    df["Date"] = df["Date"].astype(str).str.slice(0, 10)
    return df.dropna(subset=["Close"])


def fetch_one(item: Dict[str, Any], start: str, force: bool) -> Optional[Dict[str, Any]]:
    import FinanceDataReader as fdr
    import pandas as pd

    path = OUT / item["group"] / f"{safe_name(item['symbol'])}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.exists() or force:
        last = None
        for attempt in range(RETRIES):
            try:
                df = fdr.DataReader(item["symbol"], start=start)
                if df is not None and not df.empty:
                    normalize(df).to_csv(path, index=False, encoding="utf-8")
                    last = None
                    break
                last = "빈 데이터"
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
        if last:
            return {"symbol": item["symbol"], "error": last[:120]}

    df = pd.read_csv(path, dtype={"Date": str})
    if df.empty:
        return {"symbol": item["symbol"], "error": "행 없음"}
    return {
        **item,
        "file": str(path.relative_to(ROOT)),
        "rows": len(df),
        "first_date": df["Date"].iloc[0],
        "last_date": df["Date"].iloc[-1],
        "sha256": sha256_of(path),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--kr-top", type=int, default=200)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    print("유니버스 구성")
    universe = build_universe(args.kr_top)
    print(f"  합계 {len(universe)}종목 (중복 제거 후)\n")

    OUT.mkdir(parents=True, exist_ok=True)
    entries, failures = [], []
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(fetch_one, it, args.start, args.force): it for it in universe}
        for n, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            if r is None or "error" in r:
                failures.append(r or {"symbol": "?", "error": "unknown"})
            else:
                entries.append(r)
            if n % 100 == 0:
                print(f"  … {n}/{len(universe)}  ({time.perf_counter()-t0:.0f}초)", flush=True)

    entries.sort(key=lambda e: (e["group"], e["symbol"]))
    manifest = {
        "source": "FinanceDataReader",
        "requested_start": args.start,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "symbol_count": len(entries),
        "row_count": sum(e["rows"] for e in entries),
        "failures": failures,
        "symbols": entries,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    by_group: Dict[str, int] = {}
    for e in entries:
        by_group[e["group"]] = by_group.get(e["group"], 0) + 1
    print(f"\n{len(entries)}종목 / {manifest['row_count']:,}행 / {time.perf_counter()-t0:.0f}초")
    print("  " + "  ".join(f"{k} {v}" for k, v in sorted(by_group.items())))
    if failures:
        print(f"  실패 {len(failures)}종목: "
              + ", ".join(f["symbol"] for f in failures[:12])
              + (" …" if len(failures) > 12 else ""))
    print(f"저장: fixtures/wide/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
