from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    raw_response: Any = None
    model: str = ""
    usage: Dict[str, int] = None

    def __post_init__(self):
        if self.usage is None:
            self.usage = {}


class Brain:
    def __init__(
        self,
        provider: str,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self._client = self._initialize_client()

    def _initialize_client(self):
        if self.provider == "openai":
            from openai import OpenAI
            return OpenAI(api_key=self.api_key)
        elif self.provider == "claude":
            return self._create_claude_client()
        elif self.provider == "vllm":
            return self._create_vllm_client()
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def _create_claude_client(self):
        try:
            from anthropic import Anthropic
            return Anthropic(api_key=self.api_key)
        except ImportError:
            logger.warning("Anthropic not installed, Claude will use OpenAI fallback")
            from openai import OpenAI
            return OpenAI(api_key=self.api_key)

    def _create_vllm_client(self):
        from openai import OpenAI
        return OpenAI(api_key=self.api_key, base_url=self.base_url or "http://localhost:8000/v1")

    def complete(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: int = 4096
    ) -> LLMResponse:
        temp = temperature if temperature is not None else self.temperature

        if self.provider == "claude":
            return self._claude_complete(messages, system_prompt, temp, max_tokens)
        else:
            return self._openai_complete(messages, system_prompt, temp, max_tokens)

    def _openai_complete(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int
    ) -> LLMResponse:
        all_messages = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=all_messages,
                temperature=temperature,
                max_tokens=max_tokens
            )

            return LLMResponse(
                content=response.choices[0].message.content,
                raw_response=response,
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            )
        except Exception as e:
            logger.error(f"OpenAI completion error: {e}")
            raise

    def _claude_complete(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: int
    ) -> LLMResponse:
        try:
            user_content = "\n".join(
                f"{m['role']}: {m['content']}" for m in messages
            )

            response = self._client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt or "",
                messages=[{"role": "user", "content": user_content}]
            )

            return LLMResponse(
                content=response.content[0].text,
                raw_response=response,
                model=response.model,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens
                }
            )
        except Exception as e:
            logger.error(f"Claude completion error: {e}")
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
        messages = history or []
        messages.append({"role": "user", "content": user})
        response = self.complete(messages, system)
        return response.content

    @property
    def provider_name(self) -> str:
        return self.provider
