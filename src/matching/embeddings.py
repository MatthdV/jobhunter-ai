"""Optional embedding-based similarity matching for fast pre-filtering."""

from src.storage.models import Job


class EmbeddingMatcher:
    """Pre-filter job offers using vector similarity before LLM scoring.

    Embeds the candidate profile and job descriptions using a sentence
    transformer or the Anthropic embeddings API, then computes cosine
    similarity. Use as a cheap first pass to reduce LLM API calls.

    Usage::

        matcher = EmbeddingMatcher()
        await matcher.build_profile_vector()
        candidates = await matcher.filter(jobs, threshold=0.6)
        # Only send candidates to Scorer
    """

    def __init__(self) -> None:
        """Load profile and initialise embedding model."""
        raise NotImplementedError

    async def build_profile_vector(self) -> None:
        """Compute and cache the embedding of the candidate profile."""
        raise NotImplementedError

    async def filter(self, jobs: list[Job], threshold: float = 0.6) -> list[Job]:
        """Return only jobs whose description is above the similarity threshold.

        Args:
            jobs: Candidate job offers.
            threshold: Cosine similarity cut-off (0–1).

        Returns:
            Subset of jobs above the threshold, sorted by similarity descending.
        """
        raise NotImplementedError

    async def _embed(self, text: str) -> list[float]:
        """Return the embedding vector for a text string."""
        raise NotImplementedError

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        raise NotImplementedError
