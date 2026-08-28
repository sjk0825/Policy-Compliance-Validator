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


class Program(ABC):
    name: str = ""
    title: str = ""
    version: str = "v1"
    # 라우터에게 보여줄 설명. 이 문장이 라우팅 품질을 좌우한다.
    when_to_use: str = ""

    @abstractmethod
    def run(self, ctx: Dict[str, Any]) -> ProgramResult:
        ...

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
