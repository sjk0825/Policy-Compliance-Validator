"""라우터 입력을 케이스별로 굳혀 fixture로 저장한다.

프롬프트나 모델을 바꿨을 때 "같은 입력"으로 비교하려면 입력이 고정돼
있어야 한다. 컨텍스트는 시세에서 매번 다시 계산되므로, 계산 결과를
한 번 굳혀두고 그 위에서 라우터만 갈아끼운다.

케이스 정의(종목·날짜)는 커밋하고, 생성된 입력 데이터는 커밋하지 않는다.
해시를 매니페스트에 남겨 재생성본이 같은 입력인지 확인한다.

    python scripts/make_router_cases.py
"""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import PriceStore, build_context           # noqa: E402
from engine.router import SYSTEM_PROMPT, build_prompt, digest  # noqa: E402

CASES = ROOT / "fixtures" / "router_cases.json"
OUT_DIR = ROOT / "fixtures" / "router_inputs"
MANIFEST = OUT_DIR / "manifest.json"


def main() -> int:
    spec = json.loads(CASES.read_text(encoding="utf-8"))
    store = PriceStore()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    entries, failures = [], []
    for case in spec["cases"]:
        cid, sym, as_of = case["id"], case["symbol"], case["as_of"]
        try:
            ctx = build_context(store, sym, as_of).to_dict()
        except Exception as exc:
            print(f"  ! {cid:<20} 실패: {exc}")
            failures.append({"id": cid, "error": str(exc)})
            continue

        dg = digest(ctx)
        payload = {
            "case": case,
            # 라우터에 실제로 나가는 것
            "digest": dg,
            "prompt": {"system": SYSTEM_PROMPT, "user": build_prompt(dg)},
            # 프로그램이 보는 것 (라우팅 결과 검증용)
            "context": ctx,
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        path = OUT_DIR / f"{cid}.json"
        path.write_text(body + "\n", encoding="utf-8")

        # digest만 해싱한다. 라우터 입력이 바뀌었는지가 관심사다.
        dg_hash = hashlib.sha256(
            json.dumps(dg, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

        print(f"  → {cid:<20} {sym:<9} {as_of}  낙폭 {_f(dg['drawdown_pct'])}%  "
              f"변동성비 {_f(dg['vol_ratio_20_60'], 2)}  [{case['regime']}]")
        entries.append({
            "id": cid, "symbol": sym, "as_of": as_of, "regime": case["regime"],
            "file": str(path.relative_to(ROOT)),
            "digest_sha256": dg_hash,
            "prompt_chars": len(payload["prompt"]["user"]),
        })

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "case_count": len(entries),
        "failures": failures,
        "cases": entries,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\n케이스 {len(entries)}개 저장 → fixtures/router_inputs/")
    if failures:
        print(f"실패 {len(failures)}건")
        return 1
    return 0


def _f(x, n=1):
    return "-" if x is None else f"{x:.{n}f}"


if __name__ == "__main__":
    sys.exit(main())
