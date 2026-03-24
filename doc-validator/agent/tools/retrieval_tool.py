from typing import List, Tuple, Optional
from .base import BaseTool, ToolResult, ToolDefinition, ToolCapability


class RetrievalTool(BaseTool):
    def __init__(self, retriever=None):
        super().__init__()
        self._retriever = retriever
        self._documents: List[str] = []

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="retrieval",
            description="가이드라인에서 관련 내용을 검색합니다. 유사한 문서를 벡터 검색합니다.",
            capabilities=[ToolCapability.RETRIEVAL],
            parameters={
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "검색 쿼리"},
                    "top_k": {"type": "integer", "description": "반환할 결과 수", "default": 5}
                }
            }
        )

    def set_retriever(self, retriever):
        self._retriever = retriever

    def index_documents(self, documents: List[str]) -> ToolResult:
        try:
            self._documents = documents
            if self._retriever:
                self._retriever.index(documents)
            return ToolResult(
                success=True,
                data={"indexed_count": len(documents)},
                metadata={"tool": "retrieval", "action": "index"}
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def execute(self, query: str, top_k: int = 5) -> ToolResult:
        if not self._retriever or not self._documents:
            return ToolResult(
                success=False,
                error="Retriever not initialized or no documents indexed"
            )

        try:
            results: List[Tuple[int, float]] = self._retriever.retrieve(query, top_k)
            retrieved = []
            for idx, score in results:
                if idx < len(self._documents):
                    retrieved.append({
                        "index": idx,
                        "score": float(score),
                        "text": self._documents[idx]
                    })

            return ToolResult(
                success=True,
                data=retrieved,
                metadata={
                    "tool": "retrieval",
                    "action": "search",
                    "query": query,
                    "result_count": len(retrieved)
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
