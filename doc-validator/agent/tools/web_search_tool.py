from typing import List, Dict, Any
from .base import BaseTool, ToolResult, ToolDefinition, ToolCapability
from ddgs import DDGS


class WebSearchTool(BaseTool):
    def __init__(self, api_key: str | None = None):
        super().__init__()
        self._api_key = api_key

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_search",
            description="웹 검색을 통해 최신 정보를 조회합니다.",
            capabilities=[ToolCapability.WEB_SEARCH],
            parameters={
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "검색 쿼리"},
                    "num_results": {"type": "integer", "description": "결과 수", "default": 5}
                }
            }
        )

    def execute(self, query: str, num_results: int = 5) -> ToolResult:
        try:
            results = self._search(query, num_results)
            return ToolResult(
                success=True,
                data={"results": results, "query": query},
                metadata={
                    "tool": "web_search",
                    "action": "search",
                    "result_count": len(results)
                }
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _search(self, query: str, num_results: int) -> List[Dict[str, Any]]:
        results = []
        with DDGS() as ddgs:
            for result in ddgs.text(query, max_results=num_results):
                results.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("body", "")
                })
        return results
