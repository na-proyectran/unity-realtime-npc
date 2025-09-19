"""RAG utilities using LlamaIndex and Qdrant."""

from __future__ import annotations

import os
from typing import Optional, Tuple, Dict, Any

from dotenv import load_dotenv
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex, StorageContext
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    SparseVectorParams,
    SparseIndexParams,
)

from app.rag.ParagraphSplitter import ParagraphSplitter

# Cargar variables de entorno
load_dotenv()

# Configuración
RAG_COLLECTION = os.getenv("RAG_COLLECTION")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL")
OPENAI_EMBEDDING_SIZE = int(os.getenv("OPENAI_EMBEDDING_SIZE"))
FASTEMBED_SPARSE_MODEL = os.getenv("FASTEMBED_SPARSE_MODEL")

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
_grpc_port_env = os.getenv("QDRANT_GRPC_PORT")
QDRANT_GRPC_PORT = int(_grpc_port_env) if _grpc_port_env else None
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

RAG_ENABLE_HYBRID = os.getenv("RAG_ENABLE_HYBRID", "false").lower() == "true"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAG_DOCS_DIR = os.path.join(BASE_DIR, os.getenv("RAG_DOCS_DIR"))

print("RAG_DOCS_DIR:", RAG_DOCS_DIR)

# Cachés globales
_index: Optional[VectorStoreIndex] = None
_qdrant_client: Optional[QdrantClient] = None
_qdrant_async_client: Optional[AsyncQdrantClient] = None


def _build_qdrant_client_kwargs() -> Dict[str, Any]:
    """Preparar kwargs para inicializar QdrantClient."""

    kwargs: Dict[str, Any] = {}
    if QDRANT_API_KEY:
        kwargs["api_key"] = QDRANT_API_KEY

    if QDRANT_URL:
        kwargs["url"] = QDRANT_URL
    else:
        kwargs.update({
            "host": QDRANT_HOST,
            "port": QDRANT_PORT,
        })

    if QDRANT_GRPC_PORT is not None:
        kwargs["grpc_port"] = QDRANT_GRPC_PORT

    return kwargs


def _get_qdrant_clients() -> Tuple[QdrantClient, AsyncQdrantClient]:
    """Crear (lazy) clientes sync y async para Qdrant."""
    global _qdrant_client, _qdrant_async_client

    if _qdrant_client is None or _qdrant_async_client is None:
        client_kwargs = _build_qdrant_client_kwargs()
        _qdrant_client = QdrantClient(**client_kwargs)
        _qdrant_async_client = AsyncQdrantClient(**client_kwargs)

    return _qdrant_client, _qdrant_async_client


def get_index() -> VectorStoreIndex:
    """Cargar o crear el índice RAG."""
    global _index
    if _index is not None:
        return _index

    # Leer documentos
    docs = SimpleDirectoryReader(
        input_dir=RAG_DOCS_DIR,
        required_exts=[".txt"],
        filename_as_id=True
    ).load_data()

    splitter = ParagraphSplitter(separator=r"(?:\r?\n){2,}")
    nodes = splitter.get_nodes_from_documents(docs)
    print("Nodes:", len(nodes))

    # Inicializar clientes Qdrant
    client, aclient = _get_qdrant_clients()

    # Crear colección si no existe
    if not client.collection_exists(RAG_COLLECTION):
        create_collection_kwargs = {
            "collection_name": RAG_COLLECTION,
            "vectors_config": {
                "text-dense": VectorParams(
                    size=OPENAI_EMBEDDING_SIZE,
                    distance=Distance.COSINE,
                )
            },
        }
        if RAG_ENABLE_HYBRID:
            create_collection_kwargs["sparse_vectors_config"] = {
                "text-sparse": SparseVectorParams(index=SparseIndexParams())
            }
        client.create_collection(**create_collection_kwargs)

    # Configurar VectorStore
    vector_store_kwargs = {
        "client": client,
        "aclient": aclient,
        "collection_name": RAG_COLLECTION,
    }
    if RAG_ENABLE_HYBRID:
        vector_store_kwargs.update(
            {
                "enable_hybrid": True,
                "fastembed_sparse_model": FASTEMBED_SPARSE_MODEL,
            }
        )
    vector_store = QdrantVectorStore(**vector_store_kwargs)
    storage = StorageContext.from_defaults(vector_store=vector_store)

    # Embeddings
    embed_model = OpenAIEmbedding(
        model=OPENAI_EMBEDDING_MODEL,
        dimensions=OPENAI_EMBEDDING_SIZE
    )

    # Crear índice
    _index = VectorStoreIndex(
        nodes,
        storage_context=storage,
        embed_model=embed_model,
        show_progress=True,
        use_async=True,
    )
    return _index
