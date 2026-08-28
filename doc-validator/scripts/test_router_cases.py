"""굳혀둔 라우터 입력으로 라우팅을 돌려 비교한다.

같은 입력에 대해 규칙 라우터와 LLM 라우터가 무엇을 고르고, 그 선택이
최종 판정을 어떻게 바꾸는지 본다. 정답표가 없으므로 통과/실패를 매기지
않는다. 갈리는 지점을 드러내는 것이 목적이다.

    python scripts/test_router_cases.py            # 규칙만 (무료, 즉시)
    python scripts/test_router_cases.py --llm      # LLM까지
    python scripts/test_router_cases.py --llm --sleep 20
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import programs                                   # noqa: E402
from engine.router import LLMRouter, RouterUnavailable, heuristic_route  # noqa: E402

MANIFEST = ROOT / "fixtures" / "router_inputs" / "manifest.json"


def run_program(name, ctx):
    r = programs.get(name).run(ctx)
    return r.decision, r.confidence


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--sleep", type=float, default=0, help="LLM 호출 간 대기(초)")
    ap.add_argument("--model")
    args = ap.parse_args()

    if not MANIFEST.exists():
        print("입력 fixture가 없습니다. scripts/make_router_cases.py를 먼저 실행하세요.")
        return 1

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    router = LLMRouter(model=args.model) if args.llm else None
    if router:
        print(f"모델: {router.model}\n")

    head = f"{'케이스':<20}{'국면':<18}{'규칙':<17}{'판정':<7}"
    if args.llm:
        head += f"{'LLM':<17}{'판정':<7}"
    print(head)
    print("-" * (len(head) + 20))

    agree = llm_ok = flip = 0
    rows = []
    for i, c in enumerate(manifest["cases"]):
        payload = json.loads((ROOT / c["file"]).read_text(encoding="utf-8"))
        ctx, dg = payload["context"], payload["digest"]

        h = heuristic_route(ctx)
        hd, _ = run_program(h.program, ctx)
        line = f"{c['id']:<20}{c['regime'][:16]:<18}{h.program:<17}{str(hd):<7}"

        if args.llm:
            if i and args.sleep:
                time.sleep(args.sleep)
            try:
                l = router.route_digest(dg)
                ld, _ = run_program(l.program, ctx)
                llm_ok += 1
                agree += (l.program == h.program)
                flip += (ld != hd)
                line += f"{l.program:<17}{str(ld):<7}"
                rows.append((c, h.program, hd, l.program, ld, l.reason))
            except RouterUnavailable as e:
                line += f"{'(실패)':<17}{'-':<7}"
                rows.append((c, h.program, hd, None, None, str(e)[:80]))
        print(line)

    if args.llm and llm_ok:
        print(f"\nLLM 성공 {llm_ok}/{len(manifest['cases'])}  "
              f"선택 일치 {agree}/{llm_ok}  최종 판정이 뒤집힌 케이스 {flip}건")
        for c, hp, hd, lp, ld, reason in rows:
            if lp and lp != hp:
                print(f"\n  [{c['id']}] {c['regime']}")
                print(f"    규칙 {hp} → {hd}   /   LLM {lp} → {ld}")
                print(f"    LLM 근거: {reason[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
