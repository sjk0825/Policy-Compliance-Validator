from typing import Optional, List, Dict, Any, Union
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration
import os
import logging

logger = logging.getLogger(__name__)


class LangChainBrain:
    def __init__(
        self,
        provider: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3
    ):
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self._llm = self._initialize_llm(api_key, base_url)

    def _initialize_llm(self, api_key: Optional[str], base_url: Optional[str]):
        if self.provider == "openai":
            return ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                api_key=api_key or os.getenv("OPENAI_API_KEY")
            )
        elif self.provider == "claude":
            return ChatAnthropic(
                model="claude-sonnet-4-20250514",
                temperature=self.temperature,
                api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
                max_tokens=4096
            )
        elif self.provider == "vllm":
            return ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                api_key=api_key or "dummy",
                base_url=base_url or os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1")
            )
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def _convert_messages(self, messages: List[Dict[str, str]]) -> List[BaseMessage]:
        result = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                result.append(SystemMessage(content=content))
            elif role == "user":
                result.append(HumanMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(content=content))
            else:
                result.append(HumanMessage(content=content))
        return result

    def complete(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 4096
    ) -> "LLMResponse":
        all_messages = self._convert_messages(messages)
        
        if system_prompt:
            all_messages.insert(0, SystemMessage(content=system_prompt))

        try:
            if temperature is not None and hasattr(self._llm, 'temperature'):
                self._llm.temperature = temperature

            response = self._llm.invoke(all_messages)
            
            return LLMResponse(
                content=response.content,
                raw_response=response,
                model=self.model
            )
        except Exception as e:
            logger.error(f"LLM completion error: {e}")
            raise

    def validate(self, text: str, guidelines: str) -> str:
        from .prompts import format_prompt
        system, user = format_prompt(
            "validation",
            text=text,
            guidelines=guidelines
        )
        response = self.complete([{"role": "user", "content": user}], system)
        return response.content

    def plan(self, text: str, guidelines: str) -> str:
        from .prompts import format_prompt
        system, user = format_prompt(
            "plan",
            text=text,
            guidelines=guidelines
        )
        response = self.complete([{"role": "user", "content": user}], system)
        return response.content

    def chat(self, message: str, guidelines: str, history: List[Dict] = None) -> str:
        from .prompts import format_prompt
        system, user = format_prompt(
            "chat",
            message=message,
            guidelines=guidelines
        )
        messages = list(history) if history else []
        messages.append({"role": "user", "content": user})
        response = self.complete(messages, system)
        return response.content

    @property
    def provider_name(self) -> str:
        return self.provider

    def bind_tools(self, tools: List[Any]):
        self._llm = self._llm.bind_tools(tools)
        return self


class LLMResponse:
    content: str
    raw_response: Any = None
    model: str = ""

    def __init__(self, content: str, raw_response: Any = None, model: str = ""):
        self.content = content
        self.raw_response = raw_response
        self.model = model


Brain = LangChainBrain