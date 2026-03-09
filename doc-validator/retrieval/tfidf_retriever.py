import math
from typing import List, Tuple
from .base import BaseRetriever


class TfidfRetriever(BaseRetriever):
    def __init__(self):
        self.doc_vectors = None
        self.documents = []
        self.doc_freq = {}
        self.total_docs = 0

    def _tokenize(self, text: str) -> List[str]:
        return text.lower().split()

    def _compute_idf(self):
        idf = {}
        for word, freq in self.doc_freq.items():
            idf[word] = math.log((self.total_docs - freq + 0.5) / (freq + 0.5) + 1)
        return idf

    def _compute_tf(self, tokens: List[str]) -> dict:
        tf = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        for token in tf:
            tf[token] = 1 + math.log(tf[token])
        return tf

    def index(self, documents: List[str]) -> None:
        self.documents = documents
        self.total_docs = len(documents)
        
        for doc in documents:
            tokens = set(self._tokenize(doc))
            for token in tokens:
                self.doc_freq[token] = self.doc_freq.get(token, 0) + 1
        
        self.idf = self._compute_idf()

    def retrieve(self, query: str, top_k: int = 5) -> List[Tuple[int, float]]:
        if not self.documents:
            return []

        query_tokens = self._tokenize(query)
        query_tf = self._compute_tf(query_tokens)
        
        scores = []
        for doc_idx, doc in enumerate(self.documents):
            doc_tokens = self._tokenize(doc)
            doc_tf = self._compute_tf(doc_tokens)
            
            score = 0
            for token in query_tf:
                if token in doc_tf:
                    tf_val = doc_tf[token]
                    idf_val = self.idf.get(token, 0)
                    score += tf_val * idf_val
            
            if score > 0:
                scores.append((doc_idx, score))
        
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
