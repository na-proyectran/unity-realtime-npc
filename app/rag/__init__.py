""""RAG subpackage."""
from .rag_tool import query_rag, aquery_rag
from .rag_utils import get_index

__all__ = ["query_rag", "aquery_rag", "get_index"]

# Autoload opcional
try:
    _index = get_index()
except Exception as e:
    _index = None
    print(f"⚠️ No se pudo cargar el índice automáticamente: {e}")
