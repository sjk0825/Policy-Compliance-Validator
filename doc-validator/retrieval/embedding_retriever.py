from typing import List, Tuple
from .base import BaseRetriever


# from sentence_transformers import SentenceTransformer
# from sklearn.metrics.pairwise import cosine_similarity


class EmbeddingRetriever(BaseRetriever):
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model = None
        self.model_name = model_name
        self.doc_embeddings = None
        self.documents = []
        self._loaded = False

    def _ensure_model(self):
        if not self._loaded:
            # from sentence_transformers import SentenceTransformer
            # self.model = SentenceTransformer(self.model_name)
            # self._loaded = True
            raise NotImplementedError("Embedding retriever is not yet activated. Uncomment the import and model loading to enable.")

    def index(self, documents: List[str]) -> None:
        self._ensure_model()
        self.documents = documents
        # self.doc_embeddings = self.model.encode(documents)

    def retrieve(self, query: str, top_k: int = 5) -> List[Tuple[int, float]]:
        self._ensure_model()
        
        # query_embedding = self.model.encode([query])
        # similarities = cosine_similarity(query_embedding, self.doc_embeddings).flatten()
        
        # top_indices = similarities.argsort()[-top_k:][::-1]
        # results = [(int(idx), float(similarities[idx])) for idx in top_indices if similarities[idx] > 0]
        
        # return results
        raise NotImplementedError("Embedding retriever is not yet activated.")
