from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import asdict
from .base import BaseMemory, MemoryEntry, MemoryType


class ValidationResult:
    def __init__(
        self,
        document_id: str,
        guideline_id: str,
        status: str,
        issues: List[Dict[str, Any]] = None,
        summary: str = "",
        score: float = 0.0,
        metadata: Dict[str, Any] = None
    ):
        self.document_id = document_id
        self.guideline_id = guideline_id
        self.status = status
        self.issues = issues or []
        self.summary = summary
        self.score = score
        self.metadata = metadata or {}
        self.created_at = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "guideline_id": self.guideline_id,
            "status": self.status,
            "issues": self.issues,
            "summary": self.summary,
            "score": self.score,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat()
        }


class ValidationMemory(BaseMemory):
    def __init__(self, storage_path: Optional[str] = None):
        super().__init__(storage_path)

    def add(self, result: ValidationResult, **kwargs) -> str:
        entry_id = self._generate_id("val")
        entry = MemoryEntry(
            id=entry_id,
            memory_type=MemoryType.VALIDATION,
            content=result.to_dict(),
            metadata={
                "document_id": result.document_id,
                "guideline_id": result.guideline_id,
                "status": result.status,
                "score": result.score,
                **kwargs
            }
        )
        self._entries[entry_id] = entry
        self._save()
        return entry_id

    def add_result(
        self,
        document_id: str,
        guideline_id: str,
        status: str,
        issues: List[Dict[str, Any]] = None,
        summary: str = "",
        score: float = 0.0,
        **kwargs
    ) -> str:
        result = ValidationResult(
            document_id=document_id,
            guideline_id=guideline_id,
            status=status,
            issues=issues,
            summary=summary,
            score=score,
            metadata=kwargs
        )
        return self.add(result)

    def get(self, id: str) -> Optional[MemoryEntry]:
        entry = self._entries.get(id)
        if entry:
            entry.accessed_at = datetime.now()
            entry.access_count += 1
        return entry

    def get_by_document(self, document_id: str) -> List[MemoryEntry]:
        return [
            e for e in self._entries.values()
            if e.metadata.get("document_id") == document_id
        ]

    def get_by_guideline(self, guideline_id: str) -> List[MemoryEntry]:
        return [
            e for e in self._entries.values()
            if e.metadata.get("guideline_id") == guideline_id
        ]

    def get_latest(self, limit: int = 10) -> List[MemoryEntry]:
        return sorted(
            self._entries.values(),
            key=lambda x: x.created_at,
            reverse=True
        )[:limit]

    def get_statistics(self) -> Dict[str, Any]:
        total = len(self._entries)
        if total == 0:
            return {"total_validations": 0}

        statuses = {}
        total_score = 0.0
        for entry in self._entries.values():
            status = entry.metadata.get("status", "unknown")
            statuses[status] = statuses.get(status, 0) + 1
            total_score += entry.metadata.get("score", 0.0)

        return {
            "total_validations": total,
            "statuses": statuses,
            "average_score": total_score / total,
            "highest_score": max(e.metadata.get("score", 0) for e in self._entries.values()),
            "lowest_score": min(e.metadata.get("score", 0) for e in self._entries.values())
        }

    def search(self, query: str, **kwargs) -> List[MemoryEntry]:
        query_lower = query.lower()
        results = []
        for entry in self._entries.values():
            content_str = str(entry.content).lower()
            if query_lower in content_str:
                results.append(entry)
        return sorted(results, key=lambda x: x.created_at, reverse=True)

    def delete(self, id: str) -> bool:
        if id in self._entries:
            del self._entries[id]
            self._save()
            return True
        return False
