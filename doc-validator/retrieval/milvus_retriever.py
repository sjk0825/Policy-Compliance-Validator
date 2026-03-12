from typing import List, Tuple
from .base import BaseRetriever
from .openai_embedding import OpenAIEmbedding
from pymilvus import MilvusClient, DataType


class MilvusRetriever(BaseRetriever):
    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        db_path: str = "./milvus.db",
        collection_name: str = "documents"
    ):
        self.embedding = OpenAIEmbedding(api_key, model)
        self.client = MilvusClient(db_path)
        self.collection_name = collection_name
        self.documents = []
        
        self._schema = [
            {"name": "id", "dtype": DataType.INT64, "is_primary": True, "auto_id": True},
            {"name": "text", "dtype": DataType.VARCHAR, "max_length": 65535},
            {"name": "chunk_index", "dtype": DataType.INT64},
        ]

    def index(self, documents: List[str]) -> None:
        self.documents = documents
        
        if self.client.has_collection(self.collection_name):
            self.client.drop_collection(self.collection_name)
        
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=self._schema,
            dimension=1536
        )
        
        texts = documents
        embeddings = self.embedding.encode(texts)
        
        data = [
            {"text": text, "chunk_index": i, "vector": emb}
            for i, (text, emb) in enumerate(zip(texts, embeddings))
        ]
        
        self.client.insert(collection_name=self.collection_name, data=data)

    def retrieve(self, query: str, top_k: int = 5) -> List[Tuple[int, float]]:
        query_embedding = self.embedding.encode_single(query)
        
        results = self.client.search(
            collection_name=self.collection_name,
            data=[query_embedding],
            limit=top_k,
            output_fields=["chunk_index", "text", "distance"]
        )
        
        output = []
        if results and len(results) > 0:
            for hit in results[0]:
                chunk_idx = hit["entity"]["chunk_index"]
                distance = hit["distance"]
                output.append((int(chunk_idx), float(distance)))
        
        return output

    def reset(self):
        if self.client.has_collection(self.collection_name):
            self.client.drop_collection(self.collection_name)
        self.documents = []
