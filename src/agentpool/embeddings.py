"""Embedding via fastembed (ONNX, no torch). Lazy-loaded singleton."""
from functools import lru_cache

MODEL_NAME = "BAAI/bge-small-en-v1.5"  # 384-dim


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(MODEL_NAME)


def embed(text: str) -> list[float]:
    """Embed a single string into a 384-dim vector."""
    vec = next(iter(_model().embed([text])))
    return [float(x) for x in vec]
