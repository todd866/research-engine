"""Encode claims as vectors using sentence-transformers."""

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np


def load_model(model_name: str = "all-MiniLM-L6-v2"):
    """Load a sentence-transformers model."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "'sentence-transformers' package required. "
            "Install with: pip install sentence-transformers"
        )
    return SentenceTransformer(model_name)


def embed_claims(
    claims: List[Dict],
    model=None,
    model_name: str = "all-MiniLM-L6-v2",
) -> np.ndarray:
    """Embed a list of claims as vectors.

    Args:
        claims: List of dicts with 'text' field
        model: Pre-loaded model (optional)
        model_name: Model to load if model not provided

    Returns:
        numpy array of shape (n_claims, embedding_dim)
    """
    if model is None:
        model = load_model(model_name)

    texts = [c["text"] for c in claims]
    embeddings = model.encode(texts, show_progress_bar=True)

    return np.array(embeddings)


def save_embeddings(
    embeddings: np.ndarray,
    claims: List[Dict],
    embeddings_path: Path,
    index_path: Path,
) -> None:
    """Save embeddings and their index."""
    embeddings_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(embeddings_path), embeddings)

    index = {
        "model": "all-MiniLM-L6-v2",
        "n_claims": len(claims),
        "embedding_dim": embeddings.shape[1],
        "claims": claims,
    }
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def load_embeddings(
    embeddings_path: Path,
    index_path: Path,
) -> tuple:
    """Load embeddings and index.

    Returns:
        (embeddings array, index dict)
    """
    embeddings = np.load(str(embeddings_path))
    with open(index_path) as f:
        index = json.load(f)
    return embeddings, index
