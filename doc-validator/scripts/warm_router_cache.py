"""LLM 라우팅 캐시 채우기.

백테스트 도중에 호출하면 순차 실행이라 너무 느리다. 국면 서명은
616개뿐이므로 미리 병렬로 채워두고, 백테스트는 캐시만 읽는다.
답이 파일로 남으니 나중에 프롬프트를 바꿔 비교할 수도 있다.
"""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

for line in open(ROOT / ".env", encoding="utf-8"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"'))

import methodology_backtest as m                                  # noqa: E402
from engine import portfolio_router as pr                         # noqa: E402

CACHE = ROOT / "fixtures" / "router_inputs" / "methodology_cache.json"
LO, HI = "2010-01-01", "2026-12-31"

uniq = {}
for o in m.TRANCHES:
    days = [d for d in m.CAL if LO <= d <= HI]
    for k, d in enumerate(days):
        if (k - o) % m.PERIOD:
            continue
        av = [s for s in m.UNIVERSE if m.px(s, d) is not None]
        if not any(s in m.pp.CORE for s in av):
            continue
        ctx = m.build_ctx(d, av)
        uniq.setdefault(json.dumps(pr.signature(ctx), default=str), ctx)

router = pr.MethodologyRouter(cache_path=str(CACHE))
todo = [k for k in uniq if k not in router.cache]
print(f"고유 국면 {len(uniq)}개 · 이미 캐시됨 {len(uniq)-len(todo)} · 호출 대상 {len(todo)}")

lock = threading.Lock()
done = [0]


def work(key):
    ctx = uniq[key]
    try:
        route = router.route(ctx)
    except Exception as exc:                                      # noqa: BLE001
        route = pr.Route("", "", "error", str(exc))
    with lock:
        done[0] += 1
        if done[0] % 25 == 0:
            # 중간 저장. 오래 걸리는 작업이라 중간에 끊겨도 다시 이어가야 한다.
            router.save()
            print(f"  {done[0]}/{len(todo)}  llm={router.calls} err={router.errors}",
                  flush=True)
    return route.source


t0 = time.time()
with ThreadPoolExecutor(max_workers=6) as ex:
    sources = list(ex.map(work, todo))
router.save()
from collections import Counter                                   # noqa: E402
print(f"완료 {time.time()-t0:.0f}s · {Counter(sources)} · 캐시 {len(router.cache)}개")
