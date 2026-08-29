"""프로그램 레지스트리.

라우터는 이 목록에서 이름 하나를 고른다. 프로그램을 추가하려면 여기
등록만 하면 되고, 라우터 쪽은 건드리지 않는다.
"""
from typing import Dict, List

from .base import Program, ProgramResult, Signal
from .cross_momentum import CrossMomentum
from .defensive import Defensive
from .laggard import Laggard
from .overnight_reversal import OvernightReversal
from .low_vol_steady import LowVolSteady
from .short_reversal import ShortReversal
from .mean_reversion import MeanReversion
from .trend_following import TrendFollowing

REGISTRY: Dict[str, Program] = {
    p.name: p for p in (TrendFollowing(), MeanReversion(), CrossMomentum(),
                        ShortReversal(), LowVolSteady(), Laggard(),
                        OvernightReversal(), Defensive())
}

# 라우터가 못 고르거나 LLM을 못 쓸 때의 최종 안전판.
DEFAULT_PROGRAM = "defensive"


def get(name: str) -> Program:
    if name not in REGISTRY:
        raise KeyError(f"'{name}'은 등록되지 않은 프로그램입니다. 가능: {list(REGISTRY)}")
    return REGISTRY[name]


def menu() -> List[Dict[str, str]]:
    """라우터에게 보여줄 프로그램 목록."""
    return [
        {"name": p.name, "title": p.title, "when_to_use": p.when_to_use}
        for p in REGISTRY.values()
    ]


__all__ = ["Program", "ProgramResult", "Signal", "REGISTRY",
           "DEFAULT_PROGRAM", "get", "menu"]
