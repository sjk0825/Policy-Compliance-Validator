"""미래 데이터 차단 검증.

컨텍스트가 기준일 이후를 보지 않는다는 것을 두 방향으로 확인한다.
1. 기준일 이후 봉이 결과에 섞이지 않는다.
2. 뒤쪽 데이터를 물리적으로 잘라낸 fixture로 만든 컨텍스트와
   전체 fixture로 만든 컨텍스트가 완전히 같다.
"""
import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import PriceStore, build_context  # noqa: E402

AS_OF = "2024-06-14"
SYMBOLS = ["QQQ", "DBMF", "005930", "BTC/USD"]


def truncated_copy(store: PriceStore, cutoff: str, dest: Path) -> Path:
    """cutoff 이후 행을 실제로 지운 fixture 사본을 만든다."""
    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    root = store.manifest_path.parent

    for e in manifest["symbols"]:
        src = Path(store._files[e["symbol"]])
        rel = src.relative_to(root)
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        with src.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        kept = [r for r in rows if r["Date"] <= cutoff]
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(kept)
        e["file"] = str(out.resolve())

    (dest / store.manifest_path.name).write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return dest


def main() -> int:
    store = PriceStore()
    print(f"fixture: {store.manifest_path.parent.name}  (창 {store.window[0]} ~ {store.window[1]})")
    print(f"기준일 : {AS_OF}\n")

    failures = []

    # 1. 봉 자체에 미래가 섞이지 않는가
    for sym in SYMBOLS:
        if not store.has(sym):
            continue
        bars = store.bars(sym, AS_OF)
        future = [b.date for b in bars if b.date > AS_OF]
        total = len(store._all_bars(sym))
        status = "OK" if not future else f"실패 (미래 봉 {len(future)}개)"
        print(f"  {sym:<9} 전체 {total:>4}봉 → 기준일까지 {len(bars):>4}봉   {status}")
        if future:
            failures.append(f"{sym}: 미래 봉 유출")

    # 2. 뒤를 물리적으로 잘라낸 fixture와 결과가 동일한가
    print()
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "cut"
        truncated_copy(store, AS_OF, dest)
        cut_store = PriceStore(dest)

        for sym in SYMBOLS:
            if not store.has(sym):
                continue
            full = build_context(store, sym, AS_OF).to_dict()
            cut = build_context(cut_store, sym, AS_OF).to_dict()
            for key in ("coverage", "warnings"):   # 출처·경고는 다를 수 있다
                full.pop(key); cut.pop(key)
            same = full == cut
            print(f"  {sym:<9} 전체 fixture vs 절단 fixture 컨텍스트 일치: "
                  f"{'OK' if same else '불일치'}")
            if not same:
                diff = [k for k in full if full[k] != cut[k]]
                failures.append(f"{sym}: 불일치 필드 {diff}")

    print()
    if failures:
        print("실패:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("미래 데이터 유출 없음.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
