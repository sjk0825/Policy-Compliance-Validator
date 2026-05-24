from typing import List


class OpenAIEmbedding:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", base_url: str = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def encode(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError("OpenAIEmbedding is not yet activated.")

    def encode_single(self, text: str) -> List[float]:
        raise NotImplementedError("OpenAIEmbedding is not yet activated.")
