import pytest

from zalo_bot.modules.opensearch.search import OpenSearchRetriever, build_hybrid_query


def test_build_hybrid_query_shape():
    q = build_hybrid_query(
        query_text="hỏi gì đó", query_vector=[0.1, 0.2],
        top_k=3, text_field="text", vector_field="vector",
    )
    assert q["size"] == 3
    hybrid = q["query"]["hybrid"]["queries"]
    assert hybrid[0] == {"match": {"text": {"query": "hỏi gì đó"}}}
    assert hybrid[1] == {"knn": {"vector": {"vector": [0.1, 0.2], "k": 3}}}
    assert q["_source"] == ["text", "metadata"]


class _FakeClient:
    def __init__(self, hits):
        self._hits = hits
        self.last_call = None

    async def search(self, **kwargs):
        self.last_call = kwargs
        return {"hits": {"hits": self._hits}}


@pytest.mark.asyncio
async def test_hybrid_search_maps_hits_and_filters_min_score():
    fake = _FakeClient(
        [
            {"_id": "a", "_score": 0.9, "_source": {"text": "A", "metadata": {}}},
            {"_id": "b", "_score": 0.1, "_source": {"text": "B", "metadata": {}}},
        ]
    )
    retriever = OpenSearchRetriever(
        client=fake, index_pattern="open_webui_file-*", search_pipeline="hp",
        text_field="text", vector_field="vector", min_score=0.5,
    )
    hits = await retriever.hybrid_search("q", [0.1], top_k=5)
    assert [h.id for h in hits] == ["a"]  # b filtered out by min_score
    assert hits[0].text == "A"
    assert fake.last_call["index"] == "open_webui_file-*"
    assert fake.last_call["params"] == {"search_pipeline": "hp"}


@pytest.mark.asyncio
async def test_hybrid_search_reads_configured_text_field():
    # Regression: prompt builder must still get text when the field is not "text".
    fake = _FakeClient(
        [{"_id": "a", "_score": 0.9, "_source": {"content": "hello", "metadata": {}}}]
    )
    retriever = OpenSearchRetriever(
        client=fake, index_pattern="open_webui_file-*", search_pipeline="hp",
        text_field="content", vector_field="vector", min_score=0.0,
    )
    hits = await retriever.hybrid_search("q", [0.1], top_k=5)
    assert hits[0].text == "hello"
