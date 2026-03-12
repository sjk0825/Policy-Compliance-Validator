from openai import OpenAI
from typing import List
import numpy as np


class OpenAIEmbedding:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", base_url: str = None):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.dimension = 1536 if model == "text-embedding-ada-002" else 1536

    def encode(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        
        response = self.client.embeddings.create(
            model=self.model,
            input=texts
        )
        
        return [item.embedding for item in response.data]

    def encode_single(self, text: str) -> List[float]:
        return self.encode([text])[0]
