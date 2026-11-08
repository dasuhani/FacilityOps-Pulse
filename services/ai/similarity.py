"""
services/ai/similarity.py
--------------------------
Semantic duplicate and similar-request detection using Sentence Transformers.

How it works:
1. When a request is submitted, its title + description are encoded into a
   dense embedding vector using a pre-trained Sentence Transformer model.
2. The embedding is stored as a comma-separated float string in
   ServiceRequest.embedding_str (portable, no pgvector required).
3. At query time, the new request's embedding is compared against all open
   requests using cosine similarity.
4. Requests above the SIMILARITY_THRESHOLD are returned as potential duplicates.

The model is downloaded from HuggingFace on first use (~90 MB) and cached.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from core.config import settings

logger = logging.getLogger(__name__)

# Cosine similarity threshold above which two requests are "similar"
SIMILARITY_THRESHOLD = 0.82

# Default number of similar requests to return (spec: top 3)
DEFAULT_TOP_K = 3

# Module-level model cache — loaded once per process
_model = None


def _get_model():
    """Lazy-load the Sentence Transformer model."""
    global _model
    if _model is not None:
        return _model

    if not settings.semantic_search_enabled:
        raise RuntimeError(
            "Semantic search is disabled. "
            "Set ENABLE_SEMANTIC_SEARCH=true in your .env file."
        )

    try:
        from sentence_transformers import SentenceTransformer

        model_name = settings.EMBEDDING_MODEL
        logger.info("Loading Sentence Transformer model '%s'…", model_name)
        _model = SentenceTransformer(model_name)
        logger.info("Sentence Transformer model loaded.")
        return _model

    except ImportError:
        raise RuntimeError(
            "The 'sentence-transformers' package is not installed. "
            "Run: pip install sentence-transformers"
        )


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------

def encode_request(title: str, description: str) -> Optional[np.ndarray]:
    """
    Encode title + description into a 1-D numpy embedding vector.
    Returns None if semantic search is disabled or the model fails to load.
    """
    if not settings.semantic_search_enabled:
        return None

    text = f"{title.strip()} — {description.strip()}"
    try:
        model = _get_model()
        vector = model.encode(text, normalize_embeddings=True)
        return vector.astype(np.float32)
    except Exception as exc:
        logger.error("Embedding failed: %s", exc)
        return None


def vector_to_str(vector: np.ndarray) -> str:
    """Serialise a numpy vector to a comma-separated string for DB storage."""
    return ",".join(f"{v:.8f}" for v in vector.tolist())


def str_to_vector(embedding_str: str) -> Optional[np.ndarray]:
    """Deserialise a stored embedding string back to a numpy array."""
    if not embedding_str:
        return None
    try:
        return np.array([float(v) for v in embedding_str.split(",")], dtype=np.float32)
    except (ValueError, TypeError) as exc:
        logger.warning("Failed to parse embedding string: %s", exc)
        return None


def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """
    Compute cosine similarity between two normalised vectors.
    Since encode_request uses normalize_embeddings=True, this is a dot product.
    """
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))


# ---------------------------------------------------------------------------
# Duplicate / similar request detection
# ---------------------------------------------------------------------------

@dataclass
class SimilarRequest:
    request_id: int
    reference_number: str
    title: str
    status: str
    similarity_score: float


def find_similar_requests(
    new_title: str,
    new_description: str,
    candidate_requests: list,  # list of ServiceRequest ORM objects
    threshold: float = SIMILARITY_THRESHOLD,
    top_k: int = DEFAULT_TOP_K,
) -> list[SimilarRequest]:
    """
    Find the most semantically similar open requests to a new submission.

    Parameters
    ----------
    new_title : str
        Title of the new (unsaved) request.
    new_description : str
        Description of the new request.
    candidate_requests : list[ServiceRequest]
        Open requests with embeddings already stored (from DB query).
    threshold : float
        Minimum cosine similarity to include in results.
    top_k : int
        Maximum number of similar requests to return (default: 3).

    Returns
    -------
    list[SimilarRequest]
        Sorted by similarity descending. Empty list if none exceed threshold
        or if semantic search is unavailable.

    Caching note:
        The Sentence Transformer model is loaded once per process via the
        module-level ``_model`` singleton.  In a Streamlit app, this means
        the model is loaded on first use and cached for all subsequent
        reruns.  Do NOT use ``@st.cache_resource`` on ``_get_model`` itself
        — the module-level singleton already prevents repeated downloads.
    """
    if not settings.semantic_search_enabled:
        return []

    if not candidate_requests:
        return []

    new_vector = encode_request(new_title, new_description)
    if new_vector is None:
        return []

    results: list[SimilarRequest] = []

    for req in candidate_requests:
        if not req.embedding_str:
            continue
        stored_vector = str_to_vector(req.embedding_str)
        if stored_vector is None:
            continue

        score = cosine_similarity(new_vector, stored_vector)
        if score >= threshold:
            results.append(
                SimilarRequest(
                    request_id=req.id,
                    reference_number=req.reference_number,
                    title=req.title,
                    status=req.status.value,
                    similarity_score=round(score, 4),
                )
            )

    results.sort(key=lambda r: r.similarity_score, reverse=True)
    return results[:top_k]


def generate_and_store_embedding(
    title: str,
    description: str,
    request_id: int,
    session,  # SQLAlchemy Session
) -> bool:
    """
    Compute an embedding for a newly created request and persist it to the DB.
    Returns True on success, False if embedding is unavailable.

    Called from the business layer after request creation.
    """
    if not settings.semantic_search_enabled:
        return False

    vector = encode_request(title, description)
    if vector is None:
        return False

    from database.crud.request_crud import update_request_ai_fields

    try:
        update_request_ai_fields(
            session=session,
            request_id=request_id,
            embedding_str=vector_to_str(vector),
        )
        logger.debug("Embedding stored for request id=%s", request_id)
        return True
    except Exception as exc:
        logger.error("Failed to store embedding for request id=%s: %s", request_id, exc)
        return False
