"""컨텍스트 → 라우팅 → 프로그램 실행까지 한 번에 묶는다.

여기가 판정의 실제 진입점이다. api/pipeline.py는 이 함수를 부르고
각 단계를 기록만 한다.
"""
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from . import context as context_mod
from . import programs, router
from .prices import PriceStore


@dataclass
class Decision:
    result: bool
    context: Dict[str, Any]
    route: Dict[str, Any]
    program_result: Dict[str, Any]
    duration_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result": self.result,
            "route": self.route,
            "program_result": self.program_result,
            "context": self.context,
            "duration_ms": self.duration_ms,
        }


def decide(symbol: str, as_of: str, store: Optional[PriceStore] = None,
           use_llm: bool = True) -> Decision:
    started = time.perf_counter()
    store = store or PriceStore()

    ctx = context_mod.build(store, symbol, as_of).to_dict()
    decision = router.route(ctx, use_llm=use_llm)
    program = programs.get(decision.program)
    result = program.run(ctx)

    return Decision(
        result=result.decision,
        context=ctx,
        route=decision.to_dict(),
        program_result=result.to_dict(),
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
    )
