from typing import List, Optional, Dict, Any
from datetime import datetime
from .base import BaseMemory, MemoryEntry, MemoryType


class ConversationMemory(BaseMemory):
    def __init__(self, storage_path: Optional[str] = None, max_history: int = 100):
        super().__init__(storage_path)
        self.max_history = max_history

    def add(self, role: str, content: str, **kwargs) -> str:
        entry_id = self._generate_id("conv")
        entry = MemoryEntry(
            id=entry_id,
            memory_type=MemoryType.CONVERSATION,
            content={"role": role, "content": content},
            metadata={
                "timestamp": datetime.now().isoformat(),
                **kwargs
            }
        )
        self._entries[entry_id] = entry
        self._enforce_max_history()
        self._save()
        return entry_id

    def add_user_message(self, content: str, **kwargs) -> str:
        return self.add("user", content, **kwargs)

    def add_assistant_message(self, content: str, **kwargs) -> str:
        return self.add("assistant", content, **kwargs)

    def get(self, id: str) -> Optional[MemoryEntry]:
        entry = self._entries.get(id)
        if entry:
            entry.accessed_at = datetime.now()
            entry.access_count += 1
        return entry

    def get_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        entries = sorted(
            self._entries.values(),
            key=lambda x: x.created_at,
            reverse=True
        )
        if limit:
            entries = entries[:limit]
        return [
            {
                "id": e.id,
                "role": e.content["role"],
                "content": e.content["content"],
                "timestamp": e.metadata.get("timestamp"),
                "access_count": e.access_count
            }
            for e in entries
        ]

    def get_messages_for_llm(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        entries = sorted(
            [e for e in self._entries.values()],
            key=lambda x: x.created_at
        )
        if limit:
            entries = entries[-limit:]
        return [
            {"role": e.content["role"], "content": e.content["content"]}
            for e in entries
        ]

    def search(self, query: str, **kwargs) -> List[MemoryEntry]:
        query_lower = query.lower()
        results = []
        for entry in self._entries.values():
            if query_lower in str(entry.content.get("content", "")).lower():
                results.append(entry)
        return sorted(results, key=lambda x: x.accessed_at, reverse=True)

    def delete(self, id: str) -> bool:
        if id in self._entries:
            del self._entries[id]
            self._save()
            return True
        return False

    def _enforce_max_history(self):
        if len(self._entries) > self.max_history:
            sorted_entries = sorted(
                self._entries.values(),
                key=lambda x: x.created_at
            )
            to_remove = len(self._entries) - self.max_history
            for entry in sorted_entries[:to_remove]:
                del self._entries[entry.id]
