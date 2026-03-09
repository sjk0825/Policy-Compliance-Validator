from abc import ABC, abstractmethod
from typing import Optional


class BaseLLM(ABC):
    @abstractmethod
    def validate(self, text: str, guidelines: str) -> str:
        pass

    @abstractmethod
    def plan(self, text: str, guidelines: str) -> str:
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        pass
