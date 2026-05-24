import logging
import re
from typing import Optional, Dict, Any, List, Type

logger = logging.getLogger(__name__)
from .state import AgentState, ExecutionContext, AgentResponse
from .brain import Brain
from .memory import ConversationMemory, DocumentMemory, ValidationMemory
from .tools import BaseTool, ToolResult, ToolCapability


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

            stock_context = ""

            comp_result = self._try_stock_comparison(message)
            if comp_result:
                context.state = AgentState.TOOL_CALLING
                context.tool_results["stock_comparison"] = comp_result
                context.metadata["has_chart"] = comp_result.success
                if comp_result.success:
                    stock_context = f"\n\n[주가 비교 데이터]\n{comp_result.data['summary']}"
            else:
                stock_result = self._try_stock_chart(message)
                if stock_result:
                    context.state = AgentState.TOOL_CALLING
                    context.tool_results["stock_chart"] = stock_result
                    context.metadata["has_chart"] = stock_result.success
                    if stock_result.success:
                        stock_context = f"\n\n[주식 차트 데이터]\n{stock_result.data['summary']}"

            context.state = AgentState.RESPONDING

            conversation_history = self.conversation_memory.get_messages_for_llm()
            augmented_message = message + stock_context

            response = self.brain.chat(
                message=augmented_message,
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

    def _try_stock_chart(self, message: str) -> Optional[ToolResult]:
        stock_tool = self.tools.get("stock_chart")
        if not stock_tool:
            return None

        has_stock_intent = bool(re.search(
            r'(주식|차트|주가|stock|chart|주가차트|증시)', message, re.IGNORECASE
        ))
        if not has_stock_intent:
            return None

        code_patterns = [
            r'([A-Z]{1,6}\d{0,4})',      # AAPL, 005930, TSLA, MSFT
            r'\b(\d{6})\b',               # 6-digit Korean stock codes
        ]
        code = None
        for pat in code_patterns:
            m = re.search(pat, message)
            if m:
                code = m.group(1).upper()
                break

        KNOWN_TICKERS = {
            '삼성전자': '005930', '삼성': '005930', 'SAMSUNG': '005930',
            '애플': 'AAPL', 'APPLE': 'AAPL',
            'SK하이닉스': '000660', 'SK': '000660',
            'LG': '003550', 'LG전자': '066570',
            '네이버': '035420', 'NAVER': '035420',
            '카카오': '035720', 'KAKAO': '035720',
            '현대차': '005380', '현대': '005380',
            '기아': '000270', 'KIA': '000270',
            '셀트리온': '068270',
            'TSLA': 'TSLA', '테슬라': 'TSLA',
            'MSFT': 'MSFT', '마이크로소프트': 'MSFT',
            'GOOGL': 'GOOGL', '구글': 'GOOGL',
            'AMZN': 'AMZN', '아마존': 'AMZN',
            'META': 'META', '메타': 'META',
            'NVIDIA': 'NVDA', '엔비디아': 'NVDA',
        }

        name = code or ""
        for keyword, ticker in KNOWN_TICKERS.items():
            if keyword.lower() in message.lower():
                code = ticker
                name = keyword
                break

        if not code:
            return None

        return stock_tool.execute(stock_code=code, stock_name=name)

    def _resolve_stock_code(self, token: str) -> tuple:
        token = token.strip().upper()
        KNOWN = {
            '삼성전자': ('005930', '삼성전자'), '삼성': ('005930', '삼성전자'), 'SAMSUNG': ('005930', '삼성전자'),
            '애플': ('AAPL', '애플'), 'APPLE': ('AAPL', '애플'),
            'SK하이닉스': ('000660', 'SK하이닉스'), 'SK': ('000660', 'SK하이닉스'),
            'LG': ('003550', 'LG'), 'LG전자': ('066570', 'LG전자'),
            '네이버': ('035420', '네이버'), 'NAVER': ('035420', '네이버'),
            '카카오': ('035720', '카카오'), 'KAKAO': ('035720', '카카오'),
            '현대차': ('005380', '현대차'), '현대': ('005380', '현대차'),
            '기아': ('000270', '기아'), 'KIA': ('000270', '기아'),
            '셀트리온': ('068270', '셀트리온'),
            '테슬라': ('TSLA', '테슬라'), 'TSLA': ('TSLA', 'TSLA'),
            'MSFT': ('MSFT', 'MSFT'), '마이크로소프트': ('MSFT', 'MSFT'),
            'GOOGL': ('GOOGL', 'GOOGL'), '구글': ('GOOGL', '구글'),
            'AMZN': ('AMZN', 'AMZN'), '아마존': ('AMZN', '아마존'),
            'META': ('META', 'META'), '메타': ('META', 'META'),
            '엔비디아': ('NVDA', '엔비디아'), 'NVIDIA': ('NVDA', 'NVIDIA'),
        }
        if token in KNOWN:
            return KNOWN[token]
        if re.match(r'^[A-Z]{1,6}\d{0,4}$', token):
            return (token, token)
        if re.match(r'^\d{6}$', token):
            return (token, token)
        return (None, None)

    def _try_stock_comparison(self, message: str) -> Optional[ToolResult]:
        tool = self.tools.get("stock_comparison")
        if not tool:
            return None

        has_compare_intent = bool(re.search(
            r'(비교|compare|vs\.?|대비|랑\s|과\s|와\s|차이)', message, re.IGNORECASE
        ))
        if not has_compare_intent:
            return None

        codes, names = [], []
        SKIP_WORDS = {'VS', 'V', 'S', 'A', '비교', 'COMPARE', '대비', '차이'}

        tokens = re.split(r'[,;&\s]+', message)
        for token in tokens:
            clean = re.sub(r'(랑|이랑|과|와|는|은|을|를|이|가|의|도|만|부터|까지|에서)$', '', token)
            if clean.upper() in SKIP_WORDS:
                continue
            code, name = self._resolve_stock_code(clean)
            if code:
                codes.append(code)
                names.append(name)

        seen = set()
        unique = []
        for c, n in zip(codes, names):
            if c not in seen:
                seen.add(c)
                unique.append((c, n))
        codes = [c for c, _ in unique]
        names = [n for _, n in unique]

        if len(codes) < 2:
            return None

        comp_days = 90
        day_match = re.search(r'(\d+)\s*(일|주|개월|월|day|days)', message, re.IGNORECASE)
        if day_match:
            num = int(day_match.group(1))
            unit = day_match.group(2)
            if unit in ('주',):
                comp_days = num * 7
            elif unit in ('개월', '월'):
                comp_days = num * 30
            else:
                comp_days = num

        return tool.execute(stock_codes=codes, stock_names=names, days=comp_days)

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
