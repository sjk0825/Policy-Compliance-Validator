"""판단 프로그램의 공통 규약.

프로그램은 전부 같은 질문에 답한다. "이 종목을 이 시점에 잡을 만한가."
다르게 답하는 게 아니라 다른 논리로 답한다. 그래서 입출력이 같고,
라우터는 이름만 고르면 된다.

프로그램 안에서는 LLM을 쓰지 않는다. 판단은 결정론적이어야 같은 입력에
같은 답이 나오고, 그래야 백테스트가 의미를 갖는다.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Signal:
    """프로그램이 본 개별 근거 하나."""
    name: str
    passed: Optional[bool]      # None이면 데이터가 없어 판단 불가
    detail: str
    value: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "passed": self.passed,
                "detail": self.detail, "value": self.value}


@dataclass
class ProgramResult:
    program: str
    version: str
    decision: bool
    confidence: float
    summary: str
    signals: List[Signal] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "program": self.program,
            "version": self.version,
            "decision": self.decision,
            "confidence": self.confidence,
            "summary": self.summary,
            "signals": [s.to_dict() for s in self.signals],
        }


def ramp(value: Optional[float], zero_at: float, one_at: float) -> Optional[float]:
    """zero_at에서 0, one_at에서 1이 되는 선형 램프. 구간 밖은 잘라낸다.

    임계값 하나로 참·거짓을 가르면 경계에서 답이 튄다. 낙폭 -7.9%와
    -8.1%가 다른 프로그램으로 가는 것은 데이터가 아니라 임계값이 만든
    차이다. 램프를 쓰면 경계 부근이 완만해진다.
    """
    if value is None:
        return None
    span = one_at - zero_at
    if span == 0:
        return 1.0 if value >= one_at else 0.0
    return max(0.0, min(1.0, (value - zero_at) / span))


class Program(ABC):
    name: str = ""
    title: str = ""
    version: str = "v1"
    # 라우터에게 보여줄 설명. 이 문장이 라우팅 품질을 좌우한다.
    when_to_use: str = ""
    # 적합도가 같을 때의 우선순위. 높을수록 먼저다.
    # 이것이 없으면 동점 시 등록 순서가 결과를 정한다. 우선순위 체인을
    # 없앴는데 동점 처리에 순서 의존이 남아 있으면 같은 문제가 반복된다.
    priority: int = 0
    # 보유 가정. 대부분 종가 기준 N거래일이지만 그렇지 않은 것도 있다.
    holding: str = "close_to_close"

    @abstractmethod
    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        ...

    def fitness(self, ctx: Dict[str, Any]) -> float:
        """이 국면이 이 프로그램의 영역에 얼마나 맞는가. 0~1.

        판정이 아니라 적합도다. 라우터는 이 점수가 가장 높은 프로그램을
        고른다. 우선순위 체인과 달리 순서가 결과를 바꾸지 않는다.
        """
        return 0.0

    @staticmethod
    def mean_fit(parts: List[Optional[float]]) -> float:
        """데이터가 없어 None인 항목은 평균에서 뺀다."""
        vals = [p for p in parts if p is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    # ---- 하위 클래스가 쓰는 도구 --------------------------------------

    @staticmethod
    def decide_by_majority(signals: List[Signal], need: int) -> tuple:
        """판단 가능한 신호 중 need개 이상 통과하면 참으로 본다.

        데이터가 없어 None인 신호는 분모에서 뺀다. 그래야 지표가 덜 잡히는
        종목에서 무조건 거짓이 나오는 일이 없다.
        """
        judged = [s for s in signals if s.passed is not None]
        if not judged:
            return False, 0.0
        passed = sum(1 for s in judged if s.passed)
        decision = passed >= min(need, len(judged))
        return decision, round(passed / len(judged), 3)
