from .base import BaseLLM
from .openai_ import OpenAILLM
from .claude import ClaudeLLM
from .vllm import VLLMClient


def get_llm_client(provider: str, api_key: str, base_url: str = None) -> BaseLLM:
    if provider == "openai":
        return OpenAILLM(api_key)
    elif provider == "claude":
        return ClaudeLLM(api_key)
    elif provider == "vllm":
        return VLLMClient(api_key, base_url)
    else:
        raise ValueError(f"Unknown provider: {provider}")
