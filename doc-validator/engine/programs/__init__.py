"""프로그램 레지스트리.

라우터는 이 목록에서 이름 하나를 고른다. 프로그램을 추가하려면 여기
등록만 하면 되고, 라우터 쪽은 건드리지 않는다.
"""
from typing import Dict, List, Optional

from .base import Program, ProgramResult, Signal
from .cross_momentum import CrossMomentum
from .defensive import Defensive
from .laggard import Laggard
from .overnight_reversal import OvernightReversal
from .low_vol_steady import LowVolSteady
from .short_reversal import ShortReversal
from .mean_reversion import MeanReversion
from .trend_following import TrendFollowing
from .vol_target import VolTarget, VolTargetNoLeverage

REGISTRY: Dict[str, Program] = {
    p.name: p for p in (TrendFollowing(), MeanReversion(), CrossMomentum(),
                        ShortReversal(), LowVolSteady(), Laggard(),
                        OvernightReversal(), Defensive(),
                        VolTarget(), VolTargetNoLeverage())
}

# 라우터가 못 고르거나 LLM을 못 쓸 때의 최종 안전판.
DEFAULT_PROGRAM = "defensive"

# 비중을 답하는 프로그램들. 방향 프로그램과 섞어 채점하면 안 된다.
SIZING = [p.name for p in REGISTRY.values() if p.kind == "sizing"]


def get(name: str) -> Program:
    if name not in REGISTRY:
        raise KeyError(f"'{name}'은 등록되지 않은 프로그램입니다. 가능: {list(REGISTRY)}")
    return REGISTRY[name]


def menu(allowed: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """라우터에게 보여줄 프로그램 목록.

    allowed를 주면 그 안의 것만 보여준다. 프로파일이 눌러둔 프로그램을
    LLM에게 보여주면 프로파일이 무력해진다. 규칙 라우터는 가중치 0으로
    거르지만 LLM은 메뉴에 있으면 고른다.
    """
    names = allowed if allowed is not None else list(REGISTRY)
    return [
        {"name": REGISTRY[n].name, "title": REGISTRY[n].title,
         "when_to_use": REGISTRY[n].when_to_use}
        for n in names if n in REGISTRY
    ]


__all__ = ["Program", "ProgramResult", "Signal", "REGISTRY",
           "DEFAULT_PROGRAM", "get", "menu"]
