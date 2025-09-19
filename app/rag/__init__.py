"""RAG utilities using LlamaIndex and Qdrant."""

from __future__ import annotations

import os
from typing import Optional, Tuple, Dict, Any

from dotenv import load_dotenv
from llama_index.callbacks.openinference import OpenInferenceCallbackHandler
from llama_index.core import SimpleDirectoryReader, VectorStoreIndex, StorageContext
from llama_index.core.callbacks import LlamaDebugHandler
from llama_index.core import Settings
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    SparseVectorParams,
    SparseIndexParams,
)
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
from phoenix.otel import register

from .ParagraphSplitter import ParagraphSplitter

load_dotenv()

# Default directory containing documents for the RAG index. The path is
# resolved relative to the package so it works regardless of the current
# working directory.
RAG_COLLECTION = os.getenv("RAG_COLLECTION")
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL")
OPENAI_EMBEDDING_SIZE = int(os.getenv("OPENAI_EMBEDDING_SIZE"))
FASTEMBED_SPARSE_MODEL = os.getenv("FASTEMBED_SPARSE_MODEL")
# Qdrant connection settings. Prefer URL if provided, otherwise fall back to
# host/port defaults that work with the docker-compose setup.
QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
_grpc_port_env = os.getenv("QDRANT_GRPC_PORT")
QDRANT_GRPC_PORT = int(_grpc_port_env) if _grpc_port_env else None
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
# Toggle hybrid search (dense + sparse) in Qdrant. When disabled the sparse
# fastembed model is not loaded and only dense semantic search is performed.
# Enable Qdrant hybrid search when set to "true". Any other value disables it.
RAG_ENABLE_HYBRID = os.getenv("RAG_ENABLE_HYBRID", "false").lower() == "true"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAG_DOCS_DIR = os.path.join(BASE_DIR, os.getenv("RAG_DOCS_DIR"))

print("RAG_DOCS_DIR: ", RAG_DOCS_DIR)

_index: Optional[VectorStoreIndex] = None
_qdrant_client: Optional[QdrantClient] = None
_qdrant_async_client: Optional[AsyncQdrantClient] = None


def _build_qdrant_client_kwargs() -> Dict[str, Any]:
    """Prepare keyword arguments for Qdrant clients based on configuration."""

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
    """Lazily create and cache Qdrant clients."""

    global _qdrant_client, _qdrant_async_client

    if _qdrant_client is None or _qdrant_async_client is None:
        client_kwargs = _build_qdrant_client_kwargs()
        _qdrant_client = QdrantClient(**client_kwargs)
        _qdrant_async_client = AsyncQdrantClient(**client_kwargs)

    return _qdrant_client, _qdrant_async_client


def get_index() -> VectorStoreIndex:
    """Load or create the RAG index."""
    global _index
    if _index is not None:
        return _index

    docs = SimpleDirectoryReader(input_dir=RAG_DOCS_DIR,
                                 required_exts=[".txt"],
                                 filename_as_id=True).load_data()

    splitter = ParagraphSplitter(separator=r"(?:\r?\n){2,}")
    nodes = splitter.get_nodes_from_documents(docs)
    print("Nodes: ", len(nodes))


    # see: https://docs.llamaindex.ai/en/stable/examples/vector_stores/qdrant_hybrid/
    client, aclient = _get_qdrant_clients()

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
    embed_model = OpenAIEmbedding(model=OPENAI_EMBEDDING_MODEL,
                                  dimensions=OPENAI_EMBEDDING_SIZE)
    # Callback handlers
    llama_debug = LlamaDebugHandler(print_trace_on_end=True)
    inference_handler = OpenInferenceCallbackHandler()
    Settings.callback_manager.set_handlers([llama_debug, inference_handler])

    # Arize Phoenix Instrumentor
    tracer_provider = register()
    LlamaIndexInstrumentor().instrument(tracer_provider=tracer_provider)

    _index = VectorStoreIndex(nodes,
                              storage_context=storage,
                              embed_model=embed_model,
                              show_progress=True,
                              use_async=False)
    return _index

# Autoload index when the module is imported
get_index()
