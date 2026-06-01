from functools import lru_cache

from opensearchpy import AsyncOpenSearch
from redis.asyncio import Redis

from zalo_bot.config.settings import get_settings
from zalo_bot.modules.llm_gateway.client import LlmGateway
from zalo_bot.modules.opensearch.search import OpenSearchRetriever
from zalo_bot.modules.rag.orchestrator import RagOrchestrator
from zalo_bot.modules.zalo.client import ZaloClient
from zalo_bot.modules.zalo.token import TokenManager


@lru_cache
def build_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


@lru_cache
def build_gateway() -> LlmGateway:
    s = get_settings()
    return LlmGateway(
        base_url=s.llm_gateway_base_url, api_key=s.llm_gateway_api_key,
        embedding_model=s.llm_embedding_model, chat_model=s.llm_chat_model,
        timeout=s.external_call_timeout_seconds,
        chat_base_url=s.llm_chat_base_url or None,
        chat_api_key=s.llm_chat_api_key or None,
    )


@lru_cache
def build_retriever() -> OpenSearchRetriever:
    s = get_settings()
    http_auth = (s.opensearch_user, s.opensearch_password) if s.opensearch_user else None
    client = AsyncOpenSearch(
        hosts=[s.opensearch_url], http_auth=http_auth,
        timeout=s.external_call_timeout_seconds,
    )
    return OpenSearchRetriever(
        client=client, index_pattern=s.opensearch_index_pattern,
        search_pipeline=s.opensearch_search_pipeline,
        text_field=s.opensearch_text_field, vector_field=s.opensearch_vector_field,
        min_score=s.opensearch_min_score,
    )


@lru_cache
def build_rag() -> RagOrchestrator:
    s = get_settings()
    return RagOrchestrator(
        gateway=build_gateway(), retriever=build_retriever(),
        top_k=s.opensearch_top_k, max_context_chars=s.rag_max_context_chars,
    )


@lru_cache
def build_zalo_client() -> ZaloClient:
    s = get_settings()
    tokens = TokenManager(
        redis=build_redis(), token_url=s.zalo_token_api_url,
        app_id=s.zalo_app_id, app_secret=s.zalo_app_secret,
        refresh_token=s.zalo_refresh_token,
    )
    return ZaloClient(
        send_url=s.zalo_send_api_url, tokens=tokens,
        timeout=s.external_call_timeout_seconds,
    )
