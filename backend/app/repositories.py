import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import text

from backend.app.database import session_scope

_CATEGORY_TERMS = {
    "destination_info": ("景点", "景区", "名胜", "古迹", "城市介绍", "城市概况", "城市简介", "文化", "历史", "古城", "人文"),
    "accommodation": ("酒店", "酒店推荐", "住宿", "民宿", "宾馆"),
    "food": ("美食", "餐厅", "餐馆", "小吃"),
    "travel_updates": ("交通动态", "文旅新闻", "新闻", "资讯", "动态"),
    "notices_events": ("开放", "开园", "闭园", "公告", "节假日", "节日", "活动"),
    "transportation": ("交通", "路线", "公交", "地铁"),
    "trip_plans": ("攻略", "游记", "行程", "一日游", "三日游", "亲子游", "自驾游"),
    "practical_tips": ("避坑", "预算", "FAQ", "常见问题", "摄影", "打卡"),
}
_CATEGORY_PARENTS = {
    "destination_info": "destination", "trip_plans": "travel_guide",
    "food": "food_lodging_transport", "accommodation": "food_lodging_transport", "transportation": "food_lodging_transport",
    "practical_tips": "travel_experience", "notices_events": "travel_news", "travel_updates": "travel_news",
}
_CATEGORY_TTL_HOURS = {"notices_events": 168, "travel_updates": 336}
_LEAF_CATEGORIES = set(_CATEGORY_PARENTS)
_CATEGORY_ALIASES = {
    "attraction": "destination_info", "city_intro": "destination_info", "culture_history": "destination_info",
    "one_day": "trip_plans", "three_day": "trip_plans", "family_trip": "trip_plans", "self_drive": "trip_plans",
    "travel_guide": "trip_plans", "hotel": "accommodation", "lodging_experience": "accommodation",
    "avoid_pitfalls": "practical_tips", "budget": "practical_tips", "faq": "practical_tips", "photography": "practical_tips",
    "opening": "notices_events", "festival": "notices_events", "traffic_update": "travel_updates", "news": "travel_updates",
    "general": "destination_info", "未分类": "destination_info",
}
_ROOT_DEFAULTS = {
    "destination": "destination_info", "travel_guide": "trip_plans",
    "food_lodging_transport": "food", "travel_experience": "practical_tips",
    "travel_news": "travel_updates",
}


def _canonical_category(value: Any) -> str:
    """Translate legacy leaf names to the compact taxonomy."""

    code = str(value or "").strip()
    return _CATEGORY_ALIASES.get(code, code)


def _category_pair(value: Any) -> tuple[str, str]:
    """Return ``(parent, leaf)`` for either a parent or leaf code."""

    code = _canonical_category(value)
    if code in _CATEGORY_PARENTS:
        return _CATEGORY_PARENTS[code], code
    return code, ""
_METADATA_FIELDS = ("category", "sub_category", "city", "province", "season", "travel_type", "source", "update_time")
_AD_TERMS = ("广告", "推广", "优惠券", "扫码加微信", "联系客服", "购买链接", "限时抢购")
_REALTIME_TERMS = ("余票", "车次", "票价实时", "12306", "高铁时刻表", "公交实时到站")
_A_SOURCE_DOMAINS = ("gov.cn", "mct.gov.cn", "12306.cn", "amap.com")
_B_SOURCE_DOMAINS = (
    "ctrip.com", "trip.com", "mafengwo.cn", "fliggy.com", "qunar.com",
    "17u.cn", "ly.com", "qyer.com", "tuniu.com", "lvmama.com", "dianping.com",
)


def _normalise_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    metadata = dict(value or {})
    for field in _METADATA_FIELDS:
        metadata.setdefault(field, "")
    return metadata


def _source_grade(url: str | None, title: str) -> str | None:
    host = (urlparse(url or "").hostname or "").lower().removeprefix("www.")
    if any(host == domain or host.endswith("." + domain) for domain in _A_SOURCE_DOMAINS):
        return "A"
    if any(host == domain or host.endswith("." + domain) for domain in _B_SOURCE_DOMAINS):
        return "B"
    if "景区官网" in title or "官方网站" in title or "官方公告" in title:
        return "A"
    return None


def _content_quality(content: str) -> float:
    text = re.sub(r"\s+", "", content)
    if len(text) < 240 or any(term in text for term in _AD_TERMS):
        return 0.0
    unique_ratio = len(set(text)) / max(1, len(text))
    # Penalize boilerplate/repeated crawled fragments while allowing ordinary
    # Chinese travel prose (which naturally has repeated common characters).
    return round(min(1.0, 0.55 + min(0.4, len(text) / 5000) + max(0.0, unique_ratio - 0.15)), 3)
_KNOWN_CITIES = (
    "北京", "上海", "广州", "深圳", "杭州", "苏州", "郑州", "成都", "西安", "重庆",
    "南京", "武汉", "长沙", "厦门", "福州", "青岛", "大连", "天津", "济南", "合肥",
    "昆明", "桂林", "三亚", "海口", "哈尔滨", "沈阳", "洛阳", "开封", "无锡", "宁波",
)


def _normalise_inferred_city(value: str) -> str:
    """Return a display-friendly city name from a title/preview match.

    Most uploaded documents use a bare city name (``杭州``), while web
    results often use administrative suffixes (``杭州市``).  Keeping the
    suffix out of metadata makes city filters consistent with the values
    produced by the agents and the administrator's upload form.
    """

    return value[:-1] if value.endswith(("市", "区", "县")) else value


def _infer_document_tags(name: str, preview: str) -> tuple[str, str, str]:
    text = f"{name} {preview}"
    category = next(
        (key for key, terms in _CATEGORY_TERMS.items() if any(term in text for term in terms)),
        "attraction",
    )

    # Prefer the explicit list for common cities, then fall back to Chinese
    # administrative names so arbitrary places such as ``嘉兴市`` or
    # ``西溪湿地所在的杭州市`` can still be classified without a hard-coded
    # whitelist.  The regex intentionally only considers names ending in an
    # administrative suffix; this avoids treating ordinary Chinese words as
    # cities.
    city_matches = [(text.find(item), item) for item in _KNOWN_CITIES if item in text]
    # The first city in a document title is generally its subject.  Sorting
    # by position (and preferring the longer name on a tie) avoids depending
    # on the order of the fallback city list when an article mentions several
    # destinations.
    city = min(city_matches, key=lambda pair: (pair[0], -len(pair[1])))[1] if city_matches else ""
    if not city:
        # Try a city-level suffix first so ``杭州市西湖区`` is classified as
        # 杭州 rather than the (less useful) district string ``杭州市西湖``.
        match = re.search(
            r"([\u4e00-\u9fff]{2,6}市)|([\u4e00-\u9fff]{2,8}(?:区|县))",
            text,
        )
        if match:
            city = _normalise_inferred_city(next(group for group in match.groups() if group))
    parent = _CATEGORY_PARENTS.get(category, "destination")
    return parent, category if category in _LEAF_CATEGORIES else "", city


async def save_web_candidates(items: list[Any], embeddings: list[list[float]]) -> int:
    """Persist only top-ranked public evidence as active knowledge documents.

    Web evidence is already fetched, filtered, embedded and semantically
    reranked before reaching this sink.  The top one or two chunks therefore
    enter the active PGVector index immediately; administrators can still edit
    or delete them from the knowledge-management screen.
    """
    if len(items) != len(embeddings):
        return 0
    saved = 0
    async with session_scope() as session:
        for item, embedding in zip(items, embeddings, strict=True):
            content = str(getattr(item, "content", "") or "").strip()
            if not content:
                continue
            url = str(getattr(item, "url", "") or "").strip() or None
            title = str(getattr(item, "title", "") or "外部网页").strip()
            # Search results remain available to the current answer, but only
            # authoritative travel sources are eligible for persistence.
            source_grade = _source_grade(url, title)
            if source_grade is None or _content_quality(content) < 0.65:
                continue
            if any(term in f"{title} {content[:1200]}" for term in _REALTIME_TERMS):
                continue
            file_hash = hashlib.sha256(f"{url or ''}\n{content}".encode()).hexdigest()
            exists = await session.scalar(
                text("SELECT 1 FROM knowledge_document WHERE file_hash = :file_hash"),
                {"file_hash": file_hash},
            )
            if exists:
                continue
            document_id = uuid4()
            metadata = _normalise_metadata({
                "candidate": True,
                "candidate_id": str(document_id),
                "source_type": "external_web",
                **(getattr(item, "metadata", {}) or {}),
            })
            # Keep externally discovered evidence searchable by the same
            # category/city filters as administrator uploads once it is
            # reviewed and published.  Explicit metadata supplied by the
            # search provider still takes precedence over our lightweight
            # title/content inference.
            inferred_category, inferred_sub_category, inferred_city = _infer_document_tags(title, content[:500])
            raw_sub_category = _canonical_category(metadata.get("sub_category"))
            raw_category = _canonical_category(metadata.get("category"))
            if raw_sub_category in _CATEGORY_PARENTS:
                metadata["category"] = _CATEGORY_PARENTS[raw_sub_category]
                metadata["sub_category"] = raw_sub_category
            elif raw_category in _CATEGORY_PARENTS:
                metadata["category"] = _CATEGORY_PARENTS[raw_category]
                metadata["sub_category"] = raw_category
            elif raw_category in _ROOT_DEFAULTS:
                metadata["category"] = raw_category
                metadata["sub_category"] = _ROOT_DEFAULTS[raw_category]
            else:
                metadata["category"] = inferred_category
                metadata["sub_category"] = inferred_sub_category
            existing_city = str(metadata.get("city") or "").strip()
            if inferred_city and existing_city in {"", "未指定城市", "未指定"}:
                metadata["city"] = inferred_city
            metadata["source"] = metadata.get("source") or url or "external_web"
            metadata["source_grade"] = source_grade
            metadata["quality_score"] = _content_quality(content)
            metadata["update_time"] = metadata.get("update_time") or datetime.now(UTC).isoformat()
            # Live traffic/route data belongs to Amap/12306 MCP and must not
            # become durable knowledge, even when a web search returns it.
            if str(metadata.get("sub_category") or "") == "travel_updates" and any(
                term in f"{title} {content[:1200]}" for term in ("交通动态", "余票", "车次", "12306")
            ):
                continue
            ttl_hours = _CATEGORY_TTL_HOURS.get(str(metadata.get("sub_category") or ""))
            expires_at = datetime.now(UTC) + timedelta(hours=ttl_hours) if ttl_hours else None
            vector = "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
            duplicate_semantic = await session.scalar(
                text("""SELECT 1 FROM knowledge_chunk c
                         JOIN knowledge_document d ON d.id = c.document_id
                         WHERE d.status = 'READY' AND d.enabled = true
                           AND c.embedding IS NOT NULL
                           AND c.embedding <=> CAST(:embedding AS vector) <= 0.08
                         LIMIT 1"""),
                {"embedding": vector},
            )
            if duplicate_semantic:
                continue
            await session.execute(
                text(
                    """INSERT INTO knowledge_document
                       (id, file_name, file_hash, media_type, source_url, status, enabled, expires_at)
                       VALUES (:id, :file_name, :file_hash, 'text/html', :source_url, 'READY', true, :expires_at)"""
                ),
                {"id": document_id, "file_name": title[:500], "file_hash": file_hash, "source_url": url, "expires_at": expires_at},
            )
            await session.execute(
                text(
                    """INSERT INTO knowledge_chunk
                       (id, document_id, chunk_index, content, content_hash, metadata, embedding, token_count)
                       VALUES (:id, :document_id, 0, :content, :content_hash,
                               CAST(:metadata AS jsonb), CAST(:embedding AS vector), :token_count)"""
                ),
                {
                    "id": uuid4(),
                    "document_id": document_id,
                    "content": content,
                    "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "metadata": json.dumps(metadata, ensure_ascii=False, default=str),
                    "embedding": vector,
                    "token_count": len(content),
                },
            )
            saved += 1
    return saved


async def delete_document(document_id: str) -> bool:
    """Delete a knowledge document and its chunks (FK cascade)."""

    async with session_scope() as session:
        result = await session.execute(
            text("DELETE FROM knowledge_document WHERE id = CAST(:id AS uuid)"),
            {"id": document_id},
        )
    return bool(result.rowcount)


async def create_chat_session(
    user_id: str, scene_code: str = "TRAVEL_PLAN", max_sessions: int = 5
) -> dict[str, Any]:
    session_id = uuid4()
    async with session_scope() as session:
        await session.execute(
            text(
                "INSERT INTO chat_session (id, user_id, scene_code) "
                "VALUES (:id, CAST(:user_id AS uuid), :scene_code)"
            ),
            {"id": session_id, "user_id": user_id, "scene_code": scene_code},
        )
        await session.execute(
            text(
                """DELETE FROM chat_session
                   WHERE user_id = CAST(:user_id AS uuid) AND scene_code = :scene_code
                     AND id NOT IN (
                       SELECT id FROM chat_session
                       WHERE user_id = CAST(:user_id AS uuid) AND scene_code = :scene_code
                       ORDER BY updated_at DESC, id DESC LIMIT :max_sessions
                     )"""
            ),
            {"user_id": user_id, "scene_code": scene_code, "max_sessions": max(1, max_sessions)},
        )
    return {"session_id": str(session_id), "scene_code": scene_code}


async def save_chat_exchange(
    session_id: str,
    request_id: str,
    user_id: str,
    user_message: str,
    assistant_message: str,
    metadata: dict[str, Any],
) -> None:
    async with session_scope() as session:
        exists = await session.scalar(
            text(
                """
                SELECT 1 FROM chat_session
                WHERE id = CAST(:id AS uuid) AND user_id = CAST(:user_id AS uuid)
                """
            ),
            {"id": session_id, "user_id": user_id},
        )
        if not exists:
            raise ValueError("会话不存在或无权访问")
        await session.execute(
            text(
                """
                INSERT INTO chat_message (id, session_id, request_id, role, content, metadata)
                VALUES
                  (:user_id, CAST(:session_id AS uuid), CAST(:request_id AS uuid),
                   'user', :user_content, CAST(:user_metadata AS jsonb)),
                  (:assistant_id, CAST(:session_id AS uuid), CAST(:request_id AS uuid),
                   'assistant', :assistant_content, CAST(:assistant_metadata AS jsonb))
                """
            ),
            {
                "user_id": uuid4(),
                "assistant_id": uuid4(),
                "session_id": session_id,
                "request_id": request_id,
                "user_content": user_message,
                "assistant_content": assistant_message,
                "user_metadata": json.dumps({}, ensure_ascii=False),
                "assistant_metadata": json.dumps(metadata, ensure_ascii=False, default=str),
            },
        )
        await session.execute(
            text("UPDATE chat_session SET updated_at = now() WHERE id = CAST(:id AS uuid)"),
            {"id": session_id},
        )


async def get_chat_session(session_id: str, user_id: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        session_row = (
            (
                await session.execute(
                    text(
                        "SELECT id, scene_code, title, created_at, updated_at "
                        "FROM chat_session "
                        "WHERE id = CAST(:id AS uuid) AND user_id = CAST(:user_id AS uuid)"
                    ),
                    {"id": session_id, "user_id": user_id},
                )
            )
            .mappings()
            .first()
        )
        if not session_row:
            return None
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT role, content, metadata, created_at
                    FROM chat_message
                    WHERE session_id = CAST(:id AS uuid)
                    ORDER BY created_at, id
                    """
                    ),
                    {"id": session_id},
                )
            )
            .mappings()
            .all()
        )
    return {
        "session_id": str(session_row["id"]),
        "scene_code": session_row["scene_code"],
        "title": session_row["title"],
        "created_at": session_row["created_at"],
        "updated_at": session_row["updated_at"],
        "messages": [dict(row) for row in rows],
    }


async def list_chat_sessions(
    user_id: str, scene_code: str = "TRAVEL_PLAN"
) -> list[dict[str, Any]]:
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT s.id, s.title, s.created_at, s.updated_at,
                               count(m.id)::integer AS message_count,
                               COALESCE(
                                 (array_agg(m.content ORDER BY m.created_at, m.id)
                                   FILTER (WHERE m.role = 'user'))[1],
                                 ''
                               ) AS preview
                        FROM chat_session s
                        LEFT JOIN chat_message m ON m.session_id = s.id
                        WHERE s.user_id = CAST(:user_id AS uuid)
                          AND s.scene_code = :scene_code
                        GROUP BY s.id
                        ORDER BY s.updated_at DESC
                        LIMIT 5
                        """
                    ),
                    {"user_id": user_id, "scene_code": scene_code},
                )
            )
            .mappings()
            .all()
        )
    return [
        {
            "session_id": str(row["id"]),
            "scene_code": scene_code,
            "title": row["title"] or row["preview"] or "新会话",
            "preview": row["preview"] or "",
            "message_count": row["message_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


async def list_all_chat_sessions(
    user_id: str, max_sessions_per_scene: int = 5
) -> list[dict[str, Any]]:
    """List recent sessions across all specialist scenes for one user.

    The per-scene window mirrors ``list_chat_sessions`` and the retention rule
    used when creating sessions.  Keeping the limit in SQL avoids loading a
    user's entire history just to render the profile page.
    """

    limit = max(1, int(max_sessions_per_scene))
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                        WITH session_stats AS (
                            SELECT s.id, s.scene_code, s.title,
                                   s.created_at, s.updated_at,
                                   count(m.id)::integer AS message_count,
                                   COALESCE(
                                     (array_agg(m.content ORDER BY m.created_at, m.id)
                                       FILTER (WHERE m.role = 'user'))[1],
                                     ''
                                   ) AS preview
                            FROM chat_session s
                            LEFT JOIN chat_message m ON m.session_id = s.id
                            WHERE s.user_id = CAST(:user_id AS uuid)
                            GROUP BY s.id
                        )
                        SELECT id, scene_code, title, created_at, updated_at,
                               message_count, preview
                        FROM (
                            SELECT session_stats.*,
                                   row_number() OVER (
                                     PARTITION BY scene_code
                                     ORDER BY updated_at DESC, id DESC
                                   ) AS scene_rank
                            FROM session_stats
                        ) ranked
                        WHERE scene_rank <= :max_sessions
                        ORDER BY updated_at DESC, id DESC
                        """
                    ),
                    {"user_id": user_id, "max_sessions": limit},
                )
            )
            .mappings()
            .all()
        )
    return [
        {
            "session_id": str(row["id"]),
            "scene_code": row["scene_code"],
            "title": row["title"] or row["preview"] or "新会话",
            "preview": row["preview"] or "",
            "message_count": row["message_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


async def delete_chat_session(session_id: str, user_id: str) -> bool:
    async with session_scope() as session:
        result = await session.execute(
            text("DELETE FROM chat_session WHERE id = CAST(:id AS uuid) AND user_id = CAST(:user_id AS uuid)"),
            {"id": session_id, "user_id": user_id},
        )
    return bool(result.rowcount)


async def find_document_by_hash(file_hash: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    SELECT id, file_name, file_hash, status, enabled, created_at
                    FROM knowledge_document WHERE file_hash = :file_hash
                    """
                    ),
                    {"file_hash": file_hash},
                )
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


async def create_document(
    file_name: str,
    file_hash: str,
    media_type: str | None,
    local_path: Path,
    source_url: str | None = None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    document_id = uuid4()
    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                    INSERT INTO knowledge_document
                      (id, file_name, file_hash, media_type, object_key, source_url, status, expires_at)
                    VALUES
                      (:id, :file_name, :file_hash, :media_type, :object_key, :source_url, 'PARSING', :expires_at)
                    RETURNING id, file_name, file_hash, media_type, source_url, status,
                              enabled, created_at
                    """
                    ),
                    {
                        "id": document_id,
                        "file_name": file_name,
                        "file_hash": file_hash,
                        "media_type": media_type,
                        "object_key": str(local_path),
                        "source_url": source_url,
                        "expires_at": expires_at,
                    },
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def complete_document_ingestion(
    document_id: str,
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> None:
    if len(chunks) != len(embeddings):
        raise ValueError("分片数量与向量数量不一致")
    async with session_scope() as session:
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            vector = "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
            await session.execute(
                text(
                    """
                    INSERT INTO knowledge_chunk
                      (id, document_id, chunk_index, content, content_hash, metadata,
                       embedding, token_count)
                    VALUES
                      (:id, CAST(:document_id AS uuid), :chunk_index, :content, :content_hash,
                       CAST(:metadata AS jsonb), CAST(:embedding AS vector), :token_count)
                    """
                ),
                {
                    "id": uuid4(),
                    "document_id": document_id,
                    "chunk_index": index,
                    "content": chunk["content"],
                    "content_hash": chunk["content_hash"],
                    "metadata": json.dumps(_normalise_metadata(chunk.get("metadata", {})), ensure_ascii=False),
                    "embedding": vector,
                    "token_count": len(chunk["content"]),
                },
            )
        await session.execute(
            text("UPDATE knowledge_document SET status = 'REVIEWING' WHERE id = CAST(:id AS uuid)"),
            {"id": document_id},
        )


async def fail_document_ingestion(document_id: str, error: str) -> None:
    async with session_scope() as session:
        await session.execute(
            text(
                """
                UPDATE knowledge_document
                SET status = 'FAILED', error_message = :error
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": document_id, "error": error[:1000]},
        )


async def list_documents() -> list[dict[str, Any]]:
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text(
                        """
                    SELECT d.id, d.file_name, d.file_hash, d.media_type, d.source_url,
                           d.status, d.enabled, d.error_message, d.created_at, d.expires_at,
                           count(c.id)::integer AS chunk_count,
                           left(min(c.content), 500) AS preview,
                           min(c.metadata->>'category') AS category,
                           min(c.metadata->>'sub_category') AS sub_category,
                           min(c.metadata->>'city') AS city,
                           min(c.metadata->>'province') AS province,
                           min(c.metadata->>'season') AS season,
                           min(c.metadata->>'travel_type') AS travel_type,
                           min(c.metadata->>'source') AS source,
                           min(c.metadata->>'update_time') AS update_time
                    FROM knowledge_document d
                    LEFT JOIN knowledge_chunk c ON c.document_id = d.id
                    GROUP BY d.id
                    ORDER BY d.created_at DESC
                    """
                    )
                )
            )
            .mappings()
            .all()
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            inferred_category, inferred_sub_category, inferred_city = _infer_document_tags(
                str(item.get("file_name") or ""),
                str(item.get("preview") or ""),
            )
            updates: dict[str, str] = {}

            # Older documents predate category/city metadata.  Fill those
            # fields from the filename and first chunk so they immediately
            # appear in the correct administrator category and can be used by
            # the RAG pre-filter after publication.
            category = _canonical_category(item.get("category"))
            sub_category = _canonical_category(item.get("sub_category"))
            if sub_category in _CATEGORY_PARENTS:
                item["category"] = _CATEGORY_PARENTS[sub_category]
                item["sub_category"] = sub_category
                updates.update({"category": item["category"], "sub_category": sub_category})
            elif category in _CATEGORY_PARENTS:
                item["category"] = _CATEGORY_PARENTS[category]
                item["sub_category"] = category
                updates.update({"category": item["category"], "sub_category": category})
            else:
                # Parent codes (destination, travel_guide, …) and empty or
                # legacy values receive an inferred compact leaf.
                item["category"] = inferred_category
                item["sub_category"] = inferred_sub_category
                updates.update({"category": inferred_category, "sub_category": inferred_sub_category})
            city = str(item.get("city") or "").strip()
            if not city or city in {"未指定城市", "未指定"}:
                item["city"] = inferred_city
                if inferred_city:
                    updates["city"] = inferred_city

            if updates:
                await session.execute(
                    text(
                        """
                        UPDATE knowledge_chunk
                        SET metadata = metadata || CAST(:tags AS jsonb)
                        WHERE document_id = CAST(:document_id AS uuid)
                        """
                    ),
                    {
                        "document_id": item["id"],
                        "tags": json.dumps(updates, ensure_ascii=False),
                    },
                )
            result.append(item)
    return result


async def get_document(document_id: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        row = (
            await session.execute(
                text(
                    """SELECT d.id, d.file_name, d.source_url, d.status, d.enabled,
                              d.created_at, d.expires_at, c.content, c.metadata
                       FROM knowledge_document d
                       LEFT JOIN knowledge_chunk c ON c.document_id = d.id AND c.chunk_index = 0
                       WHERE d.id = CAST(:id AS uuid)"""
                ),
                {"id": document_id},
            )
        ).mappings().first()
    return dict(row) if row else None


async def update_document_content(document_id: str, content: str, embedding: list[float]) -> dict[str, Any] | None:
    vector = "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    async with session_scope() as session:
        exists = await session.scalar(
            text("SELECT 1 FROM knowledge_document WHERE id = CAST(:id AS uuid)"),
            {"id": document_id},
        )
        if not exists:
            return None
        metadata_row = (await session.execute(
            text("SELECT metadata FROM knowledge_chunk WHERE document_id = CAST(:id AS uuid) ORDER BY chunk_index LIMIT 1"),
            {"id": document_id},
        )).mappings().first()
        metadata = _normalise_metadata((metadata_row or {}).get("metadata") or {})
        metadata["update_time"] = datetime.now(UTC).isoformat()
        await session.execute(
            text("DELETE FROM knowledge_chunk WHERE document_id = CAST(:id AS uuid)"),
            {"id": document_id},
        )
        await session.execute(
            text("""INSERT INTO knowledge_chunk
                   (id, document_id, chunk_index, content, content_hash, metadata, embedding, token_count)
                   VALUES (:chunk_id, CAST(:id AS uuid), 0, :content, :content_hash,
                           CAST(:metadata AS jsonb), CAST(:embedding AS vector), :token_count)"""),
            {"chunk_id": uuid4(), "id": document_id, "content": content,
             "content_hash": content_hash, "metadata": json.dumps(metadata, ensure_ascii=False, default=str),
             "embedding": vector, "token_count": len(content)},
        )
        row = (await session.execute(
            text("SELECT id, file_name, source_url, status, enabled FROM knowledge_document WHERE id = CAST(:id AS uuid)"),
            {"id": document_id},
        )).mappings().first()
    return dict(row) if row else None


async def publish_document(document_id: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        row = (
            (
                await session.execute(
                    text(
                        """
                        UPDATE knowledge_document
                        SET status = 'READY', enabled = true
                        WHERE id = CAST(:id AS uuid) AND status = 'REVIEWING'
                    RETURNING id, file_name, status, enabled, created_at
                    """
                    ),
                    {"id": document_id},
                )
        )
        .mappings()
        .first()
        )
    return dict(row) if row else None


async def delete_evaluation_documents() -> int:
    """Remove only records created by the repeatable local RAG evaluator."""
    async with session_scope() as session:
        result = await session.execute(
            text("DELETE FROM knowledge_document WHERE source_url LIKE 'evaluation://ollama/%'")
        )
    return result.rowcount or 0
