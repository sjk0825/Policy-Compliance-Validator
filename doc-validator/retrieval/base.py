from abc import ABC, abstractmethod
from typing import List, Tuple


class BaseRetriever(ABC):
    @abstractmethod
    def index(self, documents: List[str]) -> None:
        pass

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> List[Tuple[int, float]]:
        pass
