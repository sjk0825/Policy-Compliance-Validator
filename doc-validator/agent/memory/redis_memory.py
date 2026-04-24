import os
import json
import redis
from typing import Any, Dict, List, Optional
from datetime import datetime
from .base import BaseMemory, MemoryEntry, MemoryType


class RedisMemory(BaseMemory):
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, key_prefix: str = "memory"):
        self.host = host
        self.port = port
        self.db = db
        self.key_prefix = key_prefix
        self._client = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.storage_path = None

    def _get_key(self, entry_id: str) -> str:
        return f"{self.key_prefix}:{entry_id}"

    def _get_all_ids_key(self) -> str:
        return f"{self.key_prefix}:ids"

    def add(self, content: Any, **kwargs) -> str:
        entry_id = self._generate_id(self.key_prefix)
        entry = MemoryEntry(
            id=entry_id,
            memory_type=MemoryType.CONVERSATION,
            content=content,
            metadata={
                "timestamp": datetime.now().isoformat(),
                **kwargs
            }
        )
        self._client.set(self._get_key(entry_id), json.dumps(entry.to_dict()))
        self._client.sadd(self._get_all_ids_key(), entry_id)
        return entry_id

    def get(self, id: str) -> Optional[MemoryEntry]:
        data = self._client.get(self._get_key(id))
        if not data:
            return None
        return self._deserialize_entry(json.loads(data))

    def search(self, query: str, **kwargs) -> List[MemoryEntry]:
        results = []
        query_lower = query.lower()
        for entry_id in self._client.smembers(self._get_all_ids_key()):
            entry = self.get(entry_id)
            if entry and query_lower in str(entry.content).lower():
                results.append(entry)
        return sorted(results, key=lambda x: x.accessed_at, reverse=True)

    def delete(self, id: str) -> bool:
        deleted = self._client.delete(self._get_key(id))
        self._client.srem(self._get_all_ids_key(), id)
        return deleted > 0

    def clear(self):
        for entry_id in self._client.smembers(self._get_all_ids_key()):
            self._client.delete(self._get_key(entry_id))
        self._client.delete(self._get_all_ids_key())

    def _deserialize_entry(self, data: Dict) -> MemoryEntry:
        return MemoryEntry(
            id=data["id"],
            memory_type=MemoryType(data["memory_type"]),
            content=data["content"],
            metadata=data["metadata"],
            created_at=datetime.fromisoformat(data["created_at"]),
            accessed_at=datetime.fromisoformat(data["accessed_at"]),
            access_count=data["access_count"]
        )


class RedisConversationMemory(RedisMemory):
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, max_history: int = 100):
        super().__init__(host=host, port=port, db=db, key_prefix="conversation")
        self.max_history = max_history

    def add_user_message(self, content: str, **kwargs) -> str:
        return self.add({"role": "user", "content": content}, **kwargs)

    def add_assistant_message(self, content: str, **kwargs) -> str:
        return self.add({"role": "assistant", "content": content}, **kwargs)

    def get_messages_for_llm(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        entries = []
        for entry_id in self._client.smembers(self._get_all_ids_key()):
            entry = self.get(entry_id)
            if entry:
                entries.append(entry)

        entries = sorted(entries, key=lambda x: x.created_at)
        if limit:
            entries = entries[-limit:]

        return [
            {"role": e.content["role"], "content": e.content["content"]}
            for e in entries
        ]

    def get_history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        entries = []
        for entry_id in self._client.smembers(self._get_all_ids_key()):
            entry = self.get(entry_id)
            if entry:
                entries.append(entry)

        entries = sorted(entries, key=lambda x: x.created_at, reverse=True)
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

    def clear_conversation(self) -> None:
        self.clear()


class RedisDocumentMemory(RedisMemory):
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        super().__init__(host=host, port=port, db=db, key_prefix="document")

    def add_guideline(self, content: str, name: str = "guideline", **kwargs) -> str:
        return self.add({"type": "guideline", "content": content, "name": name}, **kwargs)

    def add_document(self, content: str, doc_type: str = "unknown", **kwargs) -> str:
        return self.add({"type": doc_type, "content": content}, **kwargs)

    def get_latest(self, doc_type: Optional[str] = None) -> Optional[MemoryEntry]:
        entries = []
        for entry_id in self._client.smembers(self._get_all_ids_key()):
            entry = self.get(entry_id)
            if entry:
                if doc_type is None or entry.content.get("type") == doc_type:
                    entries.append(entry)

        if not entries:
            return None
        return max(entries, key=lambda x: x.created_at)


class RedisValidationMemory(RedisMemory):
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        super().__init__(host=host, port=port, db=db, key_prefix="validation")

    def add_result(
        self,
        document_id: str,
        guideline_id: str,
        status: str,
        summary: str,
        score: float = 0.0,
        **kwargs
    ) -> str:
        return self.add({
            "document_id": document_id,
            "guideline_id": guideline_id,
            "status": status,
            "summary": summary,
            "score": score
        }, **kwargs)

    def get_statistics(self) -> Dict[str, Any]:
        entries = []
        for entry_id in self._client.smembers(self._get_all_ids_key()):
            entry = self.get(entry_id)
            if entry:
                entries.append(entry)

        total = len(entries)
        scores = [e.content.get("score", 0.0) for e in entries if e.content.get("score")]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        return {
            "total_validations": total,
            "average_score": avg_score,
            "passed": len([s for s in scores if s >= 0.8]),
            "failed": len([s for s in scores if s < 0.8])
        }