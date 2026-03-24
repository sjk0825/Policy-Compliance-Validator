from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import os


class MemoryType(Enum):
    CONVERSATION = "conversation"
    DOCUMENT = "document"
    VALIDATION = "validation"


@dataclass
class MemoryEntry:
    id: str
    memory_type: MemoryType
    content: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    accessed_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "accessed_at": self.accessed_at.isoformat(),
            "access_count": self.access_count
        }


class BaseMemory(ABC):
    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = storage_path
        self._entries: Dict[str, MemoryEntry] = {}
        if storage_path and os.path.exists(storage_path):
            self._load()

    @abstractmethod
    def add(self, content: Any, **kwargs) -> str:
        pass

    @abstractmethod
    def get(self, id: str) -> Optional[MemoryEntry]:
        pass

    @abstractmethod
    def search(self, query: str, **kwargs) -> List[MemoryEntry]:
        pass

    @abstractmethod
    def delete(self, id: str) -> bool:
        pass

    def _generate_id(self, prefix: str = "mem") -> str:
        import uuid
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def _save(self):
        if not self.storage_path:
            return
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            data = {k: v.to_dict() for k, v in self._entries.items()}
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        if not self.storage_path or not os.path.exists(self.storage_path):
            return
        with open(self.storage_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for k, v in data.items():
                v["created_at"] = datetime.fromisoformat(v["created_at"])
                v["accessed_at"] = datetime.fromisoformat(v["accessed_at"])
                self._entries[k] = MemoryEntry(**v)

    def clear(self):
        self._entries.clear()
        if self.storage_path and os.path.exists(self.storage_path):
            os.remove(self.storage_path)
