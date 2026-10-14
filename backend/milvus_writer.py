"""Vectorize documents and write dense+sparse embeddings to Milvus."""

from embedding import EmbeddingService, embedding_service as _default_embedding_service
from milvus_client import MilvusManager


class MilvusWriter:
    """Write documents to Milvus with the active embedding model."""

    def __init__(self, embedding_service: EmbeddingService = None, milvus_manager: MilvusManager = None):
        self.embedding_service = embedding_service or _default_embedding_service
        self.milvus_manager = milvus_manager or MilvusManager()

    def write_documents(self, documents: list[dict], batch_size: int = 50):
        if not documents:
            return

        all_texts = [doc["text"] for doc in documents]
        self.embedding_service.increment_add_documents(all_texts)

        total = len(documents)
        for i in range(0, total, batch_size):
            batch = documents[i:i + batch_size]
            texts = [doc["text"] for doc in batch]
            dense_embeddings, sparse_embeddings = self.embedding_service.get_all_embeddings(texts)
            if len(dense_embeddings) != len(batch) or len(sparse_embeddings) != len(batch):
                raise RuntimeError("Embedding result count does not match document batch; indexing is incomplete")
            if dense_embeddings:
                self.milvus_manager.init_collection(dense_dim=len(dense_embeddings[0]))
            else:
                self.milvus_manager.init_collection()

            insert_data = []
            for doc, dense_emb, sparse_emb in zip(batch, dense_embeddings, sparse_embeddings):
                row = {
                    "dense_embedding": dense_emb,
                    "sparse_embedding": sparse_emb,
                    "text": doc["text"],
                    "filename": doc["filename"],
                    "file_type": doc["file_type"],
                    "file_path": doc.get("file_path", ""),
                    "page_number": doc.get("page_number", 0),
                    "chunk_idx": doc.get("chunk_idx", 0),
                    "chunk_id": doc.get("chunk_id", ""),
                    "parent_chunk_id": doc.get("parent_chunk_id", ""),
                    "root_chunk_id": doc.get("root_chunk_id", ""),
                    "chunk_level": doc.get("chunk_level", 0),
                }
                for key, value in doc.items():
                    if key not in row:
                        row[key] = value
                insert_data.append(row)

            if insert_data:
                self.milvus_manager.insert(insert_data)
