from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ToolCapability(Enum):
    RETRIEVAL = "retrieval"
    FILE_PROCESSING = "file_processing"
    WEB_SEARCH = "web_search"
    CALCULATION = "calculation"
    DOCUMENT_VALIDATION = "document_validation"


@dataclass
class ToolResult:
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class ToolDefinition:
    name: str
    description: str
    capabilities: list[ToolCapability]
    parameters: Dict[str, Any] = field(default_factory=dict)
    is_async: bool = False


class BaseTool(ABC):
    def __init__(self):
        self._definition = self.get_definition()

    @abstractmethod
    def get_definition(self) -> ToolDefinition:
        pass

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        pass

    def validate_params(self, params: Dict[str, Any]) -> bool:
        required = self._definition.parameters.get("required", [])
        return all(key in params for key in required)

    @property
    def name(self) -> str:
        return self._definition.name

    @property
    def description(self) -> str:
        return self._definition.description

    @property
    def capabilities(self) -> list[ToolCapability]:
        return self._definition.capabilities
