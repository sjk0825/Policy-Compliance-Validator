"""fixtures/universe.json에 정의된 종목의 일봉을 받아 CSV로 저장한다.

데이터 자체는 커밋하지 않는다(재생성 가능하고 용량이 있다). 대신 어떤
종목을 언제 어디서 어디까지 받았는지를 manifest.json에 남겨 커밋한다.
그래야 "이 룰은 어떤 데이터로 만들었나"를 나중에 되짚을 수 있다.

    python scripts/fetch_fixtures.py                 # 전체 수집
    python scripts/fetch_fixtures.py --group kr_etf  # 그룹만
    python scripts/fetch_fixtures.py --force         # 기존 파일 무시하고 재수집
"""
import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE = ROOT / "fixtures" / "universe.json"
DATA_DIR = ROOT / "fixtures" / "data"
MANIFEST = ROOT / "fixtures" / "manifest.json"

SOURCE = "FinanceDataReader"
COLUMNS = ["Open", "High", "Low", "Close", "Volume"]

RETRIES = 3
BACKOFF_SEC = 2.0


def safe_name(symbol: str) -> str:
    """BTC/USD 같은 심볼을 파일명으로 쓸 수 있게 바꾼다."""
    return symbol.replace("/", "-")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(symbol: str, start: str):
    """KRX는 크롤링 기반이라 간헐적으로 실패한다. 백오프를 두고 재시도한다."""
    import FinanceDataReader as fdr

    last_err: Optional[Exception] = None
    for attempt in range(1, RETRIES + 1):
        try:
            df = fdr.DataReader(symbol, start=start)
            if df is not None and not df.empty:
                return df
            last_err = ValueError("빈 데이터")
        except Exception as exc:
            last_err = exc
        if attempt < RETRIES:
            time.sleep(BACKOFF_SEC * attempt)
    raise RuntimeError(f"{RETRIES}회 시도 실패: {last_err}")


def normalize(df):
    """컬럼명을 OHLCV로 통일하고 Date를 컬럼으로 뺀다."""
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


def collect(groups: Dict[str, Any], start: str, only: Optional[str],
            force: bool) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    failures: List[Dict[str, str]] = []

    for group, spec in groups.items():
        if only and group != only:
            continue

        out_dir = DATA_DIR / group
        out_dir.mkdir(parents=True, exist_ok=True)

        for item in spec["symbols"]:
            symbol = item["symbol"]
            path = out_dir / f"{safe_name(symbol)}.csv"

            if path.exists() and not force:
                print(f"  = {group}/{symbol} (이미 있음, 건너뜀)")
            else:
                print(f"  → {group}/{symbol} …", end=" ", flush=True)
                try:
                    df = normalize(fetch(symbol, start))
                    df.to_csv(path, index=False, encoding="utf-8")
                    print(f"{len(df)}행")
                except Exception as exc:
                    print(f"실패: {exc}")
                    failures.append({"group": group, "symbol": symbol, "error": str(exc)})
                    continue

            import pandas as pd

            df = pd.read_csv(path, dtype={"Date": str})
            entries.append({
                "group": group,
                "symbol": symbol,
                "name": item.get("name"),
                "kind": item.get("kind"),
                "file": str(path.relative_to(ROOT)),
                "rows": len(df),
                "first_date": df["Date"].iloc[0] if len(df) else None,
                "last_date": df["Date"].iloc[-1] if len(df) else None,
                "sha256": sha256_of(path),
            })

    return {"entries": entries, "failures": failures}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", help="특정 그룹만 수집")
    ap.add_argument("--start", help="시작일 (기본: universe.json의 start)")
    ap.add_argument("--force", action="store_true", help="기존 파일 무시하고 재수집")
    args = ap.parse_args()

    universe = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    start = args.start or universe["start"]

    print(f"수집 시작 (start={start}, source={SOURCE})")
    result = collect(universe["groups"], start, args.group, args.force)

    manifest = {
        "source": SOURCE,
        "requested_start": start,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "symbol_count": len(result["entries"]),
        "row_count": sum(e["rows"] for e in result["entries"]),
        "failures": result["failures"],
        "symbols": result["entries"],
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\n종목 {manifest['symbol_count']}개 / {manifest['row_count']:,}행")
    print(f"매니페스트: {MANIFEST.relative_to(ROOT)}")
    if result["failures"]:
        print(f"실패 {len(result['failures'])}건:")
        for f in result["failures"]:
            print(f"  - {f['group']}/{f['symbol']}: {f['error']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
