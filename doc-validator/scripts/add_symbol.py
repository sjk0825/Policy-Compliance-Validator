"""fixture에 종목 하나를 더한다.

fetch_wide.py는 유니버스 전체를 다시 구성하면서 manifest를 새로 쓴다.
지수 구성종목 목록에 없는 ETF를 나중에 끼워 넣은 경우 그 재작성에
쓸려 나가므로, 한 종목만 받아 manifest에 덧붙이는 경로를 따로 둔다.

    python scripts/add_symbol.py HIBL --name "Direxion 고베타 3배" --group us_etf
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures" / "wide"
COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--name", default=None)
    ap.add_argument("--group", default="us_etf")
    ap.add_argument("--kind", default=None)
    ap.add_argument("--start", default="2010-01-01")
    args = ap.parse_args()

    import FinanceDataReader as fdr
    import pandas as pd

    path = OUT / args.group / f"{args.symbol.replace('/', '-')}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    df = normalize(fdr.DataReader(args.symbol, start=args.start))
    if df.empty:
        print(f"{args.symbol}: 빈 데이터")
        return 1
    df.to_csv(path, index=False, encoding="utf-8")

    mpath = OUT / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    entry = {"symbol": args.symbol, "name": args.name or args.symbol,
             "group": args.group, "kind": args.kind,
             "file": str(path.relative_to(ROOT)), "rows": len(df),
             "first_date": df["Date"].iloc[0], "last_date": df["Date"].iloc[-1],
             "sha256": sha256_of(path)}
    others = [e for e in manifest["symbols"] if e["symbol"] != args.symbol]
    manifest["symbols"] = sorted(others + [entry],
                                 key=lambda e: (e["group"], e["symbol"]))
    manifest["symbol_count"] = len(manifest["symbols"])
    manifest["row_count"] = sum(e["rows"] for e in manifest["symbols"])
    manifest["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    print(f"{args.symbol}  {len(df)}행  {entry['first_date']} ~ {entry['last_date']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
