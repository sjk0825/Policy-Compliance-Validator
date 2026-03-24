from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class AgentState(Enum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    RESPONDING = "responding"
    ERROR = "error"


@dataclass
class ExecutionContext:
    user_message: str
    state: AgentState = AgentState.IDLE
    current_plan: Optional[str] = None
    tool_results: Dict[str, Any] = field(default_factory=dict)
    retrieved_context: str = ""
    conversation_id: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_message": self.user_message,
            "state": self.state.value,
            "current_plan": self.current_plan,
            "tool_results": self.tool_results,
            "retrieved_context": self.retrieved_context[:200] + "..." if len(self.retrieved_context) > 200 else self.retrieved_context,
            "conversation_id": self.conversation_id,
            "started_at": self.started_at.isoformat(),
            "elapsed_seconds": (datetime.now() - self.started_at).total_seconds(),
            "metadata": self.metadata
        }


@dataclass
class AgentResponse:
    success: bool
    content: str
    state: AgentState
    context: ExecutionContext
    error: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "content": self.content,
            "state": self.state.value,
            "error": self.error,
            "tool_calls": self.tool_calls,
            "context": self.context.to_dict()
        }
