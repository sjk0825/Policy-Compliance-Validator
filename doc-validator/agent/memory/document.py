from typing import List, Optional, Dict, Any
from datetime import datetime
from .base import BaseMemory, MemoryEntry, MemoryType


class DocumentMemory(BaseMemory):
    def __init__(self, storage_path: Optional[str] = None):
        super().__init__(storage_path)

    def add(self, content: str, doc_type: str = "unknown", **kwargs) -> str:
        entry_id = self._generate_id("doc")
        entry = MemoryEntry(
            id=entry_id,
            memory_type=MemoryType.DOCUMENT,
            content=content,
            metadata={
                "doc_type": doc_type,
                "char_count": len(content),
                "timestamp": datetime.now().isoformat(),
                **kwargs
            }
        )
        self._entries[entry_id] = entry
        self._save()
        return entry_id

    def add_guideline(self, content: str, name: str = "guideline", **kwargs) -> str:
        return self.add(content, doc_type="guideline", name=name, **kwargs)

    def add_document(self, content: str, name: str, **kwargs) -> str:
        return self.add(content, doc_type="document", name=name, **kwargs)

    def get(self, id: str) -> Optional[MemoryEntry]:
        entry = self._entries.get(id)
        if entry:
            entry.accessed_at = datetime.now()
            entry.access_count += 1
        return entry

    def get_latest(self, doc_type: Optional[str] = None) -> Optional[MemoryEntry]:
        entries = sorted(
            self._entries.values(),
            key=lambda x: x.created_at,
            reverse=True
        )
        if doc_type:
            entries = [e for e in entries if e.metadata.get("doc_type") == doc_type]
        return entries[0] if entries else None

    def get_all_guidelines(self) -> List[MemoryEntry]:
        return [
            e for e in self._entries.values()
            if e.metadata.get("doc_type") == "guideline"
        ]

    def search(self, query: str, **kwargs) -> List[MemoryEntry]:
        query_lower = query.lower()
        results = []
        for entry in self._entries.values():
            if query_lower in entry.content.lower():
                results.append(entry)
        return sorted(results, key=lambda x: x.accessed_at, reverse=True)

    def delete(self, id: str) -> bool:
        if id in self._entries:
            del self._entries[id]
            self._save()
            return True
        return False

    def get_summary(self) -> Dict[str, Any]:
        total_docs = len(self._entries)
        guidelines = [e for e in self._entries.values() if e.metadata.get("doc_type") == "guideline"]
        documents = [e for e in self._entries.values() if e.metadata.get("doc_type") == "document"]

        return {
            "total_documents": total_docs,
            "guidelines_count": len(guidelines),
            "documents_count": len(documents),
            "total_chars": sum(e.metadata.get("char_count", 0) for e in self._entries.values()),
            "latest_guideline": guidelines[0].metadata.get("name") if guidelines else None,
            "latest_document": documents[0].metadata.get("name") if documents else None
        }
