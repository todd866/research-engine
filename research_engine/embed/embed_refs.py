"""Embed references using abstracts and/or full text.

Creates a vector index over the literature database, allowing semantic
search across all 62K+ references. Uses abstracts where available (most
refs), and full text for papers we've acquired.

Embedding strategy:
  - Abstract only: embed the abstract directly (fast, good for search)
  - Full text: chunk into ~500-word passages, embed each, store all
  - Title only: fallback for refs with no abstract or text
"""

import json
import sqlite3
from pathlib import Path
from typing import List, Optional

import numpy as np


def _get_embeddable_text(row: tuple) -> Optional[str]:
    """Extract the best available text for embedding from a DB row.

    Row columns: cite_key, doi, title, abstract, full_text, depth
    Returns text to embed, or None if nothing useful.
    """
    cite_key, doi, title, abstract, full_text, depth = row

    if abstract:
        # Abstract is the best single-vector representation
        return abstract

    if full_text:
        # Use first ~2000 chars of full text as pseudo-abstract
        return full_text[:2000]

    if title and len(title) > 20:
        # Title-only embedding (low quality but better than nothing)
        return title

    return None


def embed_refs(
    data_dir: Path,
    model_name: str = "all-MiniLM-L6-v2",
    batch_size: int = 256,
    verbose: bool = True,
) -> int:
    """Embed all references with available text into a vector index.

    Reads from literature.db, embeds abstracts/text, saves to embeddings/.

    Args:
        data_dir: Path to literature-data directory
        model_name: sentence-transformers model name
        batch_size: Batch size for encoding
        verbose: Print progress
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "'sentence-transformers' package required. "
            "Install with: pip install sentence-transformers"
        )

    db_path = data_dir / "literature.db"
    if not db_path.exists():
        raise FileNotFoundError(f"No literature.db found at {db_path}")

    if verbose:
        print(f"\n{'='*60}")
        print("Reference Embedding")
        print(f"{'='*60}")
        print(f"  Model: {model_name}")

    # Load refs from DB
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT cite_key, doi, title, abstract, full_text, depth FROM refs"
    )
    rows = cursor.fetchall()
    conn.close()

    if verbose:
        print(f"  Total refs in DB: {len(rows)}")

    # Filter to embeddable refs
    embeddable = []
    texts = []
    for row in rows:
        text = _get_embeddable_text(row)
        if text:
            embeddable.append({
                "cite_key": row[0],
                "doi": row[1] or "",
                "title": row[2] or "",
                "depth": row[5],
                "source": "abstract" if row[3] else ("text" if row[4] else "title"),
            })
            texts.append(text)

    if verbose:
        sources = {"abstract": 0, "text": 0, "title": 0}
        for e in embeddable:
            sources[e["source"]] += 1
        print(f"  Embeddable refs: {len(embeddable)}")
        print(f"    From abstract: {sources['abstract']}")
        print(f"    From text:     {sources['text']}")
        print(f"    From title:    {sources['title']}")

    if not texts:
        print("  No texts to embed!")
        return 0

    # Load model and encode
    if verbose:
        print(f"\n  Loading model...")
    model = SentenceTransformer(model_name)

    if verbose:
        print(f"  Encoding {len(texts)} texts...")
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=verbose,
        normalize_embeddings=True,  # Pre-normalize for cosine similarity
    )
    embeddings = np.array(embeddings)

    # Save
    embed_dir = data_dir / "embeddings"
    embed_dir.mkdir(parents=True, exist_ok=True)

    np.save(str(embed_dir / "refs.npy"), embeddings)

    index = {
        "model": model_name,
        "n_refs": len(embeddable),
        "embedding_dim": int(embeddings.shape[1]),
        "refs": embeddable,
    }
    with open(embed_dir / "ref_index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    if verbose:
        print(f"\n  Saved {len(embeddable)} embeddings to {embed_dir}")
        print(f"  Embedding shape: {embeddings.shape}")
        print(f"  Index: {embed_dir / 'ref_index.json'}")
        file_size = (embed_dir / "refs.npy").stat().st_size / 1024 / 1024
        print(f"  File size: {file_size:.1f} MB")

    return len(embeddable)


def search_refs(
    query: str,
    data_dir: Path,
    k: int = 20,
    model_name: str = "all-MiniLM-L6-v2",
    depth_filter: Optional[int] = None,
) -> List[dict]:
    """Search the reference embedding index.

    Args:
        query: Search query text
        data_dir: Path to literature-data directory
        k: Number of results
        model_name: Must match the model used for embedding
        depth_filter: Only return refs at this depth (1 or 2)

    Returns:
        List of dicts with cite_key, title, doi, similarity, source, depth
    """
    from sentence_transformers import SentenceTransformer

    embed_dir = data_dir / "embeddings"
    embeddings = np.load(str(embed_dir / "refs.npy"))
    with open(embed_dir / "ref_index.json") as f:
        index = json.load(f)

    model = SentenceTransformer(model_name)
    query_emb = model.encode([query], normalize_embeddings=True)[0]

    # Cosine similarity (embeddings already normalized)
    similarities = embeddings @ query_emb

    # Apply depth filter
    if depth_filter is not None:
        for i, ref in enumerate(index["refs"]):
            if ref["depth"] != depth_filter:
                similarities[i] = -1

    top_k = np.argsort(similarities)[-k:][::-1]

    results = []
    for idx in top_k:
        if similarities[idx] < 0:
            continue
        ref = index["refs"][idx]
        results.append({
            **ref,
            "similarity": float(similarities[idx]),
        })

    return results
