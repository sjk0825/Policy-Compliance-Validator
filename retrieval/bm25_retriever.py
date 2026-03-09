from rank_bm25 import BM25Okapi
from typing import List, Tuple
from .base import BaseRetriever


class BM25Retriever(BaseRetriever):
    def __init__(self):
        self.bm25 = None
        self.documents = []

    def index(self, documents: List[str]) -> None:
        self.documents = documents
        tokenized_docs = [doc.split() for doc in documents]
        self.bm25 = BM25Okapi(tokenized_docs)

    def retrieve(self, query: str, top_k: int = 5) -> List[Tuple[int, float]]:
        if not self.bm25:
            return []

        tokenized_query = query.split()
        scores = self.bm25.get_scores(tokenized_query)
        
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        results = [(int(idx), float(scores[idx])) for idx in top_indices if scores[idx] > 0]
        
        return results
