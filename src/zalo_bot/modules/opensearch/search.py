from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchHit:
    id: str
    score: float
    source: dict[str, Any]


def build_hybrid_query(
    *, query_text: str, query_vector: list[float], top_k: int, text_field: str, vector_field: str
) -> dict[str, Any]:
    return {
        "size": top_k,
        "query": {
            "hybrid": {
                "queries": [
                    {"match": {text_field: {"query": query_text}}},
                    {"knn": {vector_field: {"vector": query_vector, "k": top_k}}},
                ]
            }
        },
        "_source": [text_field, "metadata"],
    }


class OpenSearchRetriever:
    def __init__(
        self, *, client: Any, index_pattern: str, search_pipeline: str,
        text_field: str, vector_field: str, min_score: float = 0.0,
    ) -> None:
        self._client = client
        self._index_pattern = index_pattern
        self._search_pipeline = search_pipeline
        self._text_field = text_field
        self._vector_field = vector_field
        self._min_score = min_score

    async def hybrid_search(
        self, query_text: str, query_vector: list[float], *, top_k: int
    ) -> list[SearchHit]:
        body = build_hybrid_query(
            query_text=query_text, query_vector=query_vector, top_k=top_k,
            text_field=self._text_field, vector_field=self._vector_field,
        )
        params = {"search_pipeline": self._search_pipeline} if self._search_pipeline else {}
        resp = await self._client.search(index=self._index_pattern, body=body, params=params)
        hits = []
        for h in resp["hits"]["hits"]:
            score = float(h.get("_score") or 0.0)
            if score < self._min_score:
                continue
            hits.append(SearchHit(id=h["_id"], score=score, source=h.get("_source", {})))
        return hits
