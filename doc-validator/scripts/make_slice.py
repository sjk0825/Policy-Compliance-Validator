"""수집한 시세에서 임의의 2년 구간을 잘라 개발용 슬라이스를 만든다.

로직을 짤 때 전체 16년을 다 보면 눈으로 과최적화하게 된다. 좁은 구간
하나로 짜고, 나중에 다른 구간으로 검증하는 편이 낫다. 그래서 구간을
무작위로 뽑되 seed를 남겨 언제든 같은 슬라이스를 복원할 수 있게 한다.

종목마다 상장일이 달라 커버리지는 제각각이다. 전 종목이 덮는 창만
고르면 가장 늦게 상장한 종목 하나가 창 전체를 묶어버리므로, 그렇게 하지
않는다. 창 안에 데이터가 있는 종목은 모두 담고 커버리지를 기록만 한다.

    python scripts/make_slice.py                      # 무작위 seed
    python scripts/make_slice.py --seed 13102146      # 특정 슬라이스 복원
    python scripts/make_slice.py --start 2021-09-05   # 구간 직접 지정
    python scripts/make_slice.py --years 3
"""
import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "fixtures" / "manifest.json"
SLICES_DIR = ROOT / "fixtures" / "slices"


def d(s: str) -> date:
    return date.fromisoformat(s)


def week_key(day: date) -> str:
    y, w, _ = day.isocalendar()
    return f"{y}-W{w:02d}"


def decision_dates(dates: List[str]) -> List[str]:
    """주 1회 판정 기준일 = 각 주의 마지막 거래일."""
    last_of_week: Dict[str, str] = {}
    for s in dates:
        last_of_week[week_key(d(s))] = s
    return [last_of_week[k] for k in sorted(last_of_week)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, help="생략하면 무작위로 뽑고 결과에 기록한다")
    ap.add_argument("--years", type=int, default=2)
    ap.add_argument("--start", help="시작일을 직접 지정한다 (지정 시 seed는 쓰지 않는다)")
    ap.add_argument("--label", help="슬라이스 이름 접미사")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print("manifest.json이 없습니다. 먼저 scripts/fetch_fixtures.py를 실행하세요.")
        return 1

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    symbols = manifest["symbols"]

    span = timedelta(days=int(365.25 * args.years))
    # 종목별 상장일에 맞추지 않는다. 전체 가용 범위에서 창을 뽑고,
    # 그 안에 데이터가 있는 종목을 담는다.
    earliest = min(d(e["first_date"]) for e in symbols)
    latest = max(d(e["last_date"]) for e in symbols)
    if earliest + span > latest:
        print(f"{args.years}년 창을 뽑을 수 없습니다. 가용 범위: {earliest} ~ {latest}")
        return 1

    seed = None
    if args.start:
        start = d(args.start)
        if start < earliest or start + span > latest:
            print(f"구간이 가용 범위를 벗어납니다: {earliest} ~ {latest}")
            return 1
    else:
        seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1, 10**8)
        rng = random.Random(seed)
        start = earliest + timedelta(days=rng.randrange((latest - span - earliest).days + 1))
    end = start + span

    slice_id = f"{args.years}y_{start:%Y%m%d}" + (f"_seed{seed}" if seed is not None else "")
    if args.label:
        slice_id += f"_{args.label}"
    out_root = SLICES_DIR / slice_id

    print(f"슬라이스 {slice_id}")
    print(f"  구간   {start} ~ {end}  ({args.years}년)")
    print(f"  seed   {seed if seed is not None else '(--start 직접 지정)'}"
          f"   (가용 범위 {earliest} ~ {latest})\n")

    import pandas as pd

    entries: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    for e in symbols:
        src = ROOT / e["file"]
        if not src.exists():
            print(f"  ! {e['symbol']} 원본 없음: {e['file']}")
            continue

        df = pd.read_csv(src, dtype={"Date": str})
        win = df[(df["Date"] >= start.isoformat()) & (df["Date"] <= end.isoformat())]
        if win.empty:
            print(f"  - {e['symbol']:<9} {e['name'][:16]:<18} 구간 내 데이터 없음 "
                  f"(원본 {e['first_date']}~)")
            missing.append({"symbol": e["symbol"], "name": e.get("name"),
                            "group": e["group"], "source_first_date": e["first_date"]})
            continue

        dst = out_root / e["group"] / f"{e['symbol'].replace('/', '-')}.csv"
        dst.parent.mkdir(parents=True, exist_ok=True)
        win.to_csv(dst, index=False, encoding="utf-8")

        dates = win["Date"].tolist()
        entries.append({
            "group": e["group"],
            "symbol": e["symbol"],
            "name": e.get("name"),
            "kind": e.get("kind"),
            "file": str(dst.relative_to(ROOT)),
            "rows": len(win),
            "first_date": dates[0],
            "last_date": dates[-1],
            # 창 시작 시점에 아직 상장 전이라 앞부분이 잘렸는지.
            # 창 시작일이 휴장일이어서 첫 거래일이 밀린 경우와 구분해야 하므로
            # 거래일이 아니라 원본 시작일과 비교한다.
            "starts_late": d(e["first_date"]) > start,
        })

    # 판정 기준일은 시장별 거래일 달력이 다르므로 따로 뽑는다.
    # 암호화폐는 주말에도 거래돼 주식 달력을 오염시키므로 분리한다.
    # (섞으면 "그 주의 마지막 거래일"이 금요일이 아니라 일요일이 된다.)
    def is_crypto(entry: Dict[str, Any]) -> bool:
        return entry.get("kind") == "암호화폐"

    markets = {
        "kr": lambda e: e["group"] in ("kr_stock", "kr_etf") and not is_crypto(e),
        "us": lambda e: e["group"] in ("us_stock", "us_etf") and not is_crypto(e),
        "crypto": is_crypto,
    }

    grids: Dict[str, Any] = {}
    for market, belongs in markets.items():
        members = [e for e in entries if belongs(e)]
        if not members:
            continue
        pool = sorted({
            day
            for e in members
            for day in pd.read_csv(ROOT / e["file"], dtype={"Date": str})["Date"].tolist()
        })
        weekly = decision_dates(pool)
        grids[market] = {
            "symbols": [e["symbol"] for e in members],
            "trading_days": len(pool),
            "decision_dates": weekly,
        }
        print(f"  {market:<7}: 종목 {len(members):>2}개  거래일 {len(pool):>4}일"
              f"  → 주간 판정 기준일 {len(weekly)}개")

    meta = {
        "slice_id": slice_id,
        "seed": seed,
        "years": args.years,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "source_manifest_fetched_at": manifest["fetched_at"],
        "symbol_count": len(entries),
        "row_count": sum(e["rows"] for e in entries),
        "missing_symbols": missing,
        "partial_symbols": [e["symbol"] for e in entries if e["starts_late"]],
        "decision_grid": grids,
        "symbols": entries,
    }
    (out_root / "slice.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"\n종목 {meta['symbol_count']}개 / {meta['row_count']:,}행", end="")
    if meta["partial_symbols"]:
        print(f"  (구간 중간부터 시작: {', '.join(meta['partial_symbols'])})", end="")
    if missing:
        print(f"  (제외 {len(missing)}종목)", end="")
    print()
    print(f"출력: fixtures/slices/{slice_id}/")
    restore = (f"--seed {seed}" if seed is not None else f"--start {start}")
    print(f"복원: python scripts/make_slice.py {restore} --years {args.years}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
