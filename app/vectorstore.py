"""
Vector store using FAISS + Ollama embeddings.
Persists index and metadata to disk.
"""

import os
import json
import logging
import asyncio
import aiohttp
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class VectorChunk:
    text: str
    source: str
    page: int
    chunk_idx: int


class VectorStore:
    def __init__(self, store_path: str, ollama_url: str, embed_model: str):
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)
        self.ollama_url = ollama_url.rstrip("/")
        self.embed_model = embed_model

        self.index = None          # faiss index
        self.chunks: List[VectorChunk] = []
        self.dimension: Optional[int] = None

        self._index_file = self.store_path / "faiss.index"
        self._meta_file = self.store_path / "metadata.json"

    # ------------------------------------------------------------------ #
    # Embeddings                                                           #
    # ------------------------------------------------------------------ #

    async def embed_text(self, text: str) -> Optional[np.ndarray]:
        """Get embedding from Ollama."""
        url = f"{self.ollama_url}/api/embeddings"
        payload = {"model": self.embed_model, "prompt": text}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"Ollama embedding error {resp.status}: {body}")
                        return None
                    data = await resp.json()
                    return np.array(data["embedding"], dtype=np.float32)
        except Exception as e:
            logger.error(f"Ollama embedding request failed: {e}")
            return None

    async def embed_batch(self, texts: List[str], batch_size: int = 16) -> List[Optional[np.ndarray]]:
        """Embed a list of texts with concurrency control."""
        results = []
        sem = asyncio.Semaphore(4)

        async def _embed(text):
            async with sem:
                return await self.embed_text(text)

        tasks = [_embed(t) for t in texts]
        results = await asyncio.gather(*tasks)
        return list(results)

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def save(self):
        try:
            import faiss
            if self.index is not None:
                faiss.write_index(self.index, str(self._index_file))
            meta = {
                "chunks": [asdict(c) for c in self.chunks],
                "dimension": self.dimension,
            }
            self._meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
            logger.info(f"VectorStore saved: {len(self.chunks)} chunks")
        except Exception as e:
            logger.error(f"Failed to save vector store: {e}")

    def load(self) -> bool:
        try:
            import faiss
            if not self._index_file.exists() or not self._meta_file.exists():
                return False
            self.index = faiss.read_index(str(self._index_file))
            meta = json.loads(self._meta_file.read_text())
            self.chunks = [VectorChunk(**c) for c in meta["chunks"]]
            self.dimension = meta.get("dimension")
            logger.info(f"VectorStore loaded: {len(self.chunks)} chunks")
            return True
        except Exception as e:
            logger.error(f"Failed to load vector store: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Indexing                                                             #
    # ------------------------------------------------------------------ #

    async def add_chunks(self, chunks: List[VectorChunk]):
        """Embed and add chunks to the FAISS index."""
        import faiss

        if not chunks:
            return

        texts = [c.text for c in chunks]
        logger.info(f"Embedding {len(texts)} chunks...")
        embeddings_list = await self.embed_batch(texts)

        valid = [(emb, chunk) for emb, chunk in zip(embeddings_list, chunks) if emb is not None]
        if not valid:
            logger.error("No valid embeddings returned!")
            return

        embeddings = np.stack([e for e, _ in valid]).astype(np.float32)
        valid_chunks = [c for _, c in valid]

        dim = embeddings.shape[1]
        if self.index is None:
            self.dimension = dim
            self.index = faiss.IndexFlatIP(dim)  # Inner product (cosine after normalize)
        
        # L2 normalize for cosine similarity
        faiss.normalize_L2(embeddings)
        self.index.add(embeddings)
        self.chunks.extend(valid_chunks)
        logger.info(f"Added {len(valid_chunks)} chunks to index (total: {len(self.chunks)})")

    def clear(self):
        self.index = None
        self.chunks = []
        self.dimension = None
        if self._index_file.exists():
            self._index_file.unlink()
        if self._meta_file.exists():
            self._meta_file.unlink()

    # ------------------------------------------------------------------ #
    # Search                                                               #
    # ------------------------------------------------------------------ #

    async def search(self, query: str, top_k: int = 5) -> List[Tuple[VectorChunk, float]]:
        """Search for similar chunks. Returns (chunk, score) pairs."""
        import faiss

        if self.index is None or len(self.chunks) == 0:
            logger.warning("Vector store is empty!")
            return []

        query_emb = await self.embed_text(query)
        if query_emb is None:
            return []

        query_emb = query_emb.reshape(1, -1).astype(np.float32)
        faiss.normalize_L2(query_emb)

        k = min(top_k, len(self.chunks))
        scores, indices = self.index.search(query_emb, k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx >= 0 and idx < len(self.chunks):
                results.append((self.chunks[idx], float(score)))
        return results

    def get_indexed_sources(self) -> List[str]:
        return list({c.source for c in self.chunks})
