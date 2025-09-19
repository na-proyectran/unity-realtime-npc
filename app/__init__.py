"""Application package for the realtime NPC demo."""
from __future__ import annotations

from .agent import get_starting_agent
__all__ = ["get_starting_agent"]

from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
from llama_index.callbacks.openinference import OpenInferenceCallbackHandler
from llama_index.core.callbacks import LlamaDebugHandler
from llama_index.core import Settings
from phoenix.otel import register

# Handlers y trazas
llama_debug = LlamaDebugHandler(print_trace_on_end=True)
inference_handler = OpenInferenceCallbackHandler()
Settings.callback_manager.set_handlers([llama_debug, inference_handler])

# Arize Phoenix Instrumentor
tracer_provider = register()
LlamaIndexInstrumentor().instrument(tracer_provider=tracer_provider)
