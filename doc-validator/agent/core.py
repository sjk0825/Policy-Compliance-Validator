from typing import Optional, Dict, Any, List, Type
from .state import AgentState, ExecutionContext, AgentResponse
from .brain import Brain
from .memory import ConversationMemory, DocumentMemory, ValidationMemory
from .tools import BaseTool, ToolResult


class AgentOrchestrator:
    def __init__(
        self,
        brain: Brain,
        tools: Optional[List[BaseTool]] = None,
        conversation_memory: Optional[ConversationMemory] = None,
        document_memory: Optional[DocumentMemory] = None,
        validation_memory: Optional[ValidationMemory] = None
    ):
        self.brain = brain
        self.tools: Dict[str, BaseTool] = {t.name: t for t in (tools or [])}
        self.conversation_memory = conversation_memory or ConversationMemory()
        self.document_memory = document_memory or DocumentMemory()
        self.validation_memory = validation_memory or ValidationMemory()
        self._guidelines: str = ""
        self._guideline_chunks: List[str] = []

    def add_tool(self, tool: BaseTool) -> None:
        self.tools[tool.name] = tool

    def remove_tool(self, name: str) -> bool:
        if name in self.tools:
            del self.tools[name]
            return True
        return False

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self.tools.get(name)

    def set_guidelines(self, text: str, chunks: Optional[List[str]] = None) -> None:
        self._guidelines = text
        self._guideline_chunks = chunks or self._chunk_text(text)

        self.document_memory.add_guideline(text, name="current_guideline")

        self._index_guidelines()

    def _chunk_text(self, text: str, chunk_size: int = 500) -> List[str]:
        words = text.split()
        chunks = []
        for i in range(0, len(words), chunk_size):
            chunks.append(" ".join(words[i:i + chunk_size]))
        return chunks

    def _index_guidelines(self) -> None:
        retrieval_tool = self.tools.get("retrieval")
        if retrieval_tool and self._guideline_chunks:
            retrieval_tool.index_documents(self._guideline_chunks)

    def _retrieve_context(self, query: str, top_k: int = 5) -> str:
        retrieval_tool = self.tools.get("retrieval")
        if not retrieval_tool or not self._guideline_chunks:
            return ""

        result = retrieval_tool.execute(query, top_k)
        if result.success:
            return self._format_retrieval_results(result.data)
        return ""

    def _format_retrieval_results(self, data: Any) -> str:
        if not data:
            return ""
        results = []
        for item in data:
            results.append(f"[{item.get('score', 0):.3f}] {item.get('text', '')}")
        return "\n---\n".join(results)

    def execute(self, message: str, enable_retrieval: bool = False) -> AgentResponse:
        context = ExecutionContext(user_message=message)

        try:
            context.state = AgentState.THINKING

            if enable_retrieval:
                context.state = AgentState.TOOL_CALLING
                context.retrieved_context = self._retrieve_context(message)
                context.tool_results["retrieval"] = context.retrieved_context

            context.state = AgentState.RESPONDING

            conversation_history = self.conversation_memory.get_messages_for_llm()

            response = self.brain.chat(
                message=message,
                guidelines=self._guidelines,
                history=conversation_history
            )

            self.conversation_memory.add_user_message(message)
            self.conversation_memory.add_assistant_message(response)

            context.state = AgentState.IDLE

            return AgentResponse(
                success=True,
                content=response,
                state=context.state,
                context=context
            )

        except Exception as e:
            logger.error(f"Agent execution error: {e}", exc_info=True)
            context.state = AgentState.ERROR
            return AgentResponse(
                success=False,
                content="",
                state=AgentState.ERROR,
                context=context,
                error=str(e)
            )

    def validate(self, text: str) -> AgentResponse:
        context = ExecutionContext(user_message="Validate document")
        context.state = AgentState.THINKING

        try:
            if not self._guidelines:
                return AgentResponse(
                    success=False,
                    content="가이드라인이 설정되지 않았습니다.",
                    state=AgentState.ERROR,
                    context=context,
                    error="No guidelines set"
                )

            context.state = AgentState.RESPONDING
            result = self.brain.validate(text, self._guidelines)

            guideline_entry = self.document_memory.get_latest(doc_type="guideline")
            guideline_id = guideline_entry.id if guideline_entry else "unknown"

            self.validation_memory.add_result(
                document_id="current",
                guideline_id=guideline_id,
                status="completed",
                summary=result[:500],
                score=1.0 if "문제점 없" in result else 0.5
            )

            context.state = AgentState.IDLE

            return AgentResponse(
                success=True,
                content=result,
                state=context.state,
                context=context
            )

        except Exception as e:
            logger.error(f"Validation error: {e}", exc_info=True)
            context.state = AgentState.ERROR
            return AgentResponse(
                success=False,
                content="",
                state=AgentState.ERROR,
                context=context,
                error=str(e)
            )

    def plan(self, text: str) -> AgentResponse:
        context = ExecutionContext(user_message="Generate plan")
        context.state = AgentState.THINKING

        try:
            if not self._guidelines:
                return AgentResponse(
                    success=False,
                    content="가이드라인이 설정되지 않았습니다.",
                    state=AgentState.ERROR,
                    context=context,
                    error="No guidelines set"
                )

            context.state = AgentState.RESPONDING
            result = self.brain.plan(text, self._guidelines)
            context.current_plan = result

            context.state = AgentState.IDLE

            return AgentResponse(
                success=True,
                content=result,
                state=context.state,
                context=context
            )

        except Exception as e:
            logger.error(f"Planning error: {e}", exc_info=True)
            context.state = AgentState.ERROR
            return AgentResponse(
                success=False,
                content="",
                state=AgentState.ERROR,
                context=context,
                error=str(e)
            )

    def clear_conversation(self) -> None:
        self.conversation_memory.clear()

    def get_statistics(self) -> Dict[str, Any]:
        return {
            "conversation": {
                "total_messages": len(self.conversation_memory._entries),
                "history": self.conversation_memory.get_summary()
            },
            "documents": self.document_memory.get_summary(),
            "validation": self.validation_memory.get_statistics(),
            "tools": {
                "available": list(self.tools.keys()),
                "count": len(self.tools)
            },
            "brain": {
                "provider": self.brain.provider_name,
                "model": self.brain.model
            }
        }
