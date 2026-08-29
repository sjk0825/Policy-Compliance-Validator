"""한국 종목의 기관·외국인 순매매와 외국인 보유율을 받는다.

가격에서 뽑은 지표는 소진됐다. 3분할 검증에서 방향 예측 우위가 없었고,
가장 강해 보였던 오버나이트 신호도 최종 구간에서 t가 0 근처였다.
아직 안 본 것은 가격이 아닌 데이터이고, 그중 받을 수 있는 것이 수급이다.

KRX는 이제 계정을 요구하고 pykrx의 수급 함수가 전부 막혔다(OHLCV만
로그인 없이 된다). 네이버 금융의 외국인·기관 페이지는 열려 있으므로
그쪽에서 받는다. 페이지당 20거래일이라 종목마다 여러 번 요청한다.

    python scripts/fetch_flows.py --pages 30
    python scripts/fetch_flows.py --symbols 005930,000660 --pages 60
"""
import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures" / "flows"
UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"}
RETRIES = 3


def fetch_page(code: str, page: int) -> Optional[str]:
    url = f"https://finance.naver.com/item/frgn.naver?code={code}&page={page}"
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("euc-kr", "replace")
        except Exception:
            time.sleep(0.7 * (attempt + 1))
    return None


def parse(html: str):
    import pandas as pd

    tables = pd.read_html(io.StringIO(html))
    # 날짜·순매매량이 있는 표를 고른다. 위치는 고정이 아니다.
    for tb in tables:
        cols = [str(c) for c in tb.columns.to_flat_index()] if hasattr(
            tb.columns, "to_flat_index") else [str(c) for c in tb.columns]
        joined = " ".join(cols)
        if "날짜" in joined and "순매매량" in joined:
            return tb
    return None


def collect(code: str, pages: int) -> List[Dict[str, Any]]:
    import pandas as pd

    rows: Dict[str, Dict[str, Any]] = {}
    for page in range(1, pages + 1):
        html = fetch_page(code, page)
        if html is None:
            break
        tb = parse(html)
        if tb is None:
            break
        tb = tb.dropna(how="all")
        got = 0
        for rec in tb.itertuples(index=False):
            v = list(rec)
            if len(v) < 9:
                continue
            day = str(v[0]).strip()
            if not day or day == "날짜" or "." not in day:
                continue
            try:
                rows[day.replace(".", "-")] = {
                    "Date": day.replace(".", "-"),
                    "Close": float(v[1]),
                    "Volume": float(v[4]),
                    "InstNet": float(v[5]),      # 기관 순매매량(주)
                    "ForeignNet": float(v[6]),   # 외국인 순매매량(주)
                    "ForeignShares": float(v[7]),
                    "ForeignRatio": float(str(v[8]).replace("%", "")),
                }
                got += 1
            except (TypeError, ValueError):
                continue
        if got == 0:
            break
        time.sleep(0.12)   # 예의상 간격
    return [rows[k] for k in sorted(rows)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", help="쉼표 구분. 생략하면 wide 유니버스의 한국 종목")
    ap.add_argument("--pages", type=int, default=30, help="종목당 페이지 수 (1페이지=20거래일)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    if args.symbols:
        codes = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        wide = json.loads((ROOT / "fixtures" / "wide" / "manifest.json")
                          .read_text(encoding="utf-8"))
        codes = [e["symbol"] for e in wide["symbols"]
                 if e["group"].startswith("kr_") and e["symbol"].isdigit()]

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"종목 {len(codes)}개 × 최대 {args.pages}페이지 (약 {args.pages*20}거래일)")

    import csv
    entries, failures = [], []
    t0 = time.perf_counter()

    def work(code):
        rows = collect(code, args.pages)
        if not rows:
            return code, None
        path = OUT / f"{code}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        return code, {"symbol": code, "file": str(path.relative_to(ROOT)),
                      "rows": len(rows), "first_date": rows[0]["Date"],
                      "last_date": rows[-1]["Date"]}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, c): c for c in codes}
        for n, fut in enumerate(as_completed(futs), 1):
            code, e = fut.result()
            (entries if e else failures).append(e or code)
            if n % 25 == 0:
                print(f"  … {n}/{len(codes)} ({time.perf_counter()-t0:.0f}초)", flush=True)

    entries.sort(key=lambda e: e["symbol"])
    manifest = {
        "source": "naver finance (item/frgn)",
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "fields": ["InstNet", "ForeignNet", "ForeignShares", "ForeignRatio"],
        "symbol_count": len(entries),
        "row_count": sum(e["rows"] for e in entries),
        "failures": failures,
        "symbols": entries,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n{len(entries)}종목 / {manifest['row_count']:,}행 / "
          f"{time.perf_counter()-t0:.0f}초")
    if entries:
        print(f"기간 예시: {entries[0]['symbol']} "
              f"{entries[0]['first_date']} ~ {entries[0]['last_date']} ({entries[0]['rows']}행)")
    if failures:
        print(f"실패 {len(failures)}종목: {', '.join(map(str, failures[:10]))}")
    print("저장: fixtures/flows/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
