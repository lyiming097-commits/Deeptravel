"""Travel intent classification and lightweight entity extraction.

The agents need a small canonical vocabulary to select tools, but the decision
itself should not be made by a growing list of string checks.  High-confidence
obvious requests use the deterministic scorer immediately; ambiguous requests
use the configured LLM with the same scorer as a safe fallback.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from backend.app.config import Settings
from backend.app.llm.deepseek import DeepSeekClient

TravelIntent = Literal[
    "itinerary",
    "attraction",
    "transportation",
    "accommodation",
    "food",
    "shopping",
    "budget",
    "weather",
    "general",
]

SEARCH_INTENT_MAP: dict[TravelIntent, str] = {
    "itinerary": "general",
    "attraction": "attraction",
    "transportation": "general",
    "accommodation": "hotel",
    "food": "restaurant",
    "shopping": "shopping",
    "budget": "general",
    "weather": "general",
    "general": "general",
}

_ALIASES: dict[str, TravelIntent] = {
    "itinerary": "itinerary",
    "travel_plan": "itinerary",
    "travel planning": "itinerary",
    "行程": "itinerary",
    "行程规划": "itinerary",
    "attraction": "attraction",
    "poi": "attraction",
    "scenic": "attraction",
    "景点": "attraction",
    "景点推荐": "attraction",
    "transportation": "transportation",
    "transport": "transportation",
    "route": "transportation",
    "traffic": "transportation",
    "交通": "transportation",
    "路线": "transportation",
    "出行": "transportation",
    "accommodation": "accommodation",
    "hotel": "accommodation",
    "住宿": "accommodation",
    "酒店": "accommodation",
    "food": "food",
    "restaurant": "food",
    "dining": "food",
    "美食": "food",
    "餐饮": "food",
    "shopping": "shopping",
    "购物": "shopping",
    "budget": "budget",
    "cost": "budget",
    "费用": "budget",
    "预算": "budget",
    "weather": "weather",
    "天气": "weather",
    "general": "general",
    "other": "general",
    "其他": "general",
}

# Rules are deliberately broad semantic hints, not a city/category whitelist.
# The model remains the primary classifier; these terms only provide a safe
# answer when a provider is unavailable or the message is unambiguous.
_RULE_TERMS: dict[TravelIntent, tuple[tuple[str, float], ...]] = {
    "itinerary": (
        ("行程", 4.0),
        ("怎么玩", 3.5),
        ("安排", 2.8),
        ("规划", 2.8),
        ("几日游", 3.2),
        ("游玩", 2.0),
        ("想去", 2.4),
        ("旅行计划", 4.0),
        ("旅游计划", 4.0),
    ),
    "attraction": (
        ("景点", 4.0),
        ("景区", 3.8),
        ("好玩的", 3.5),
        ("名胜", 3.0),
        ("博物馆", 3.0),
        ("公园", 2.5),
        ("古镇", 2.5),
        ("景观", 2.5),
        ("打卡", 2.0),
        ("观光", 2.5),
    ),
    "transportation": (
        ("交通", 4.0),
        ("路线", 3.8),
        ("怎么走", 3.8),
        ("出行", 3.5),
        ("高铁", 3.5),
        ("动车", 3.5),
        ("火车", 3.2),
        ("地铁", 3.0),
        ("公交", 3.0),
        ("驾车", 3.0),
        ("开车", 3.0),
        ("步行", 2.8),
        ("机场", 2.5),
        ("车站", 2.5),
    ),
    "accommodation": (
        ("酒店", 4.5),
        ("住宿", 4.5),
        ("民宿", 4.2),
        ("宾馆", 4.0),
        ("客栈", 3.8),
        ("住哪里", 4.0),
        ("住哪", 4.0),
        ("入住", 3.0),
    ),
    "food": (
        ("美食", 4.5),
        ("餐厅", 4.3),
        ("餐馆", 4.0),
        ("吃什么", 4.0),
        ("小吃", 3.8),
        ("火锅", 3.5),
        ("烧烤", 3.5),
        ("咖啡", 3.0),
        ("甜品", 3.0),
        ("餐饮", 3.8),
    ),
    "shopping": (
        ("购物", 4.5),
        ("商场", 4.0),
        ("商业街", 4.0),
        ("步行街", 3.8),
        ("买什么", 3.0),
        ("免税店", 3.5),
    ),
    "budget": (
        ("预算", 4.5),
        ("费用", 4.0),
        ("花费", 4.0),
        ("多少钱", 3.8),
        ("价格", 3.0),
        ("人均", 3.0),
        ("成本", 3.5),
    ),
    "weather": (
        ("天气", 4.5),
        ("气温", 3.8),
        ("下雨", 3.2),
        ("温度", 3.0),
        ("穿什么", 2.8),
    ),
    "general": (),
}


@dataclass(frozen=True)
class IntentDecision:
    intent: TravelIntent
    confidence: float
    source: Literal["llm", "rules"]
    entities: dict[str, str] = field(default_factory=dict)

    @property
    def search_intent(self) -> str:
        """Map the richer planning intent to the web/POI filter vocabulary."""

        return SEARCH_INTENT_MAP[self.intent]


def normalize_intent(value: Any) -> TravelIntent | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return _ALIASES.get(normalized)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _grounded_entity(value: Any, conversation: str) -> str:
    """Keep an LLM entity only when it is visibly present in the dialogue.

    Models often normalise “宁波” to “宁波市” or “西湖” to “西湖景区”.
    Exact-string validation used to discard those otherwise correct entities,
    which then made the agent think no destination/landmark was supplied.
    """

    candidate = _text(value)
    if not candidate:
        return ""
    compact = re.sub(r"\s+", "", conversation)
    variants: list[str] = []
    for suffix in ("风景名胜区", "风景区", "景区", "市", "省", "区", "县"):
        if candidate.endswith(suffix) and len(candidate) > len(suffix) + 1:
            variants.append(candidate[: -len(suffix)])
    variants.append(candidate)
    return next((variant for variant in variants if variant and variant in compact), "")


def extract_area_entity(message: str) -> str:
    """Extract an area/landmark mentioned before a local-search suffix.

    This is an NER fallback, not a fixed place list.  It recognizes arbitrary
    Chinese or Latin place names such as 西溪湿地、灵隐寺、外滩 and leaves the
    canonicalization of the entity to the map POI resolver.
    """

    text = _text(message)
    if not text:
        return ""
    atom = r"[\u4e00-\u9fffA-Za-z0-9·'’\-]{2,40}?"
    suffix = r"(?:附近|周边|旁边|一带|区域)"
    patterns = (
        rf"(?:住在|入住|位于|靠近|在)\s*(?P<area>{atom})\s*{suffix}",
        rf"(?P<area>{atom})\s*{suffix}\s*(?:的\s*)?(?:酒店|住宿|民宿|宾馆|餐厅|美食|景点|交通)?",
        rf"(?:住在|入住|位于|靠近)\s*(?P<area>{atom})\s*(?:的\s*)?(?:酒店|住宿|民宿|宾馆)",
    )
    generic_terms = {
        "哪里",
        "那里",
        "附近",
        "周边",
        "一个地方",
        "目的地",
        "旅游",
    }
    for pattern in patterns:
        matches = list(re.finditer(pattern, text))
        if not matches:
            continue
        candidate = matches[-1].group("area").strip(" ，,。；;、的")
        if candidate and candidate not in generic_terms:
            return candidate
    return ""


def rule_classify(message: str) -> IntentDecision:
    """Deterministic fallback with latest-intent tie breaking."""

    text = _text(message).lower()
    if not text:
        return IntentDecision("general", 0.0, "rules")
    scores: dict[TravelIntent, float] = {}
    latest: dict[TravelIntent, int] = {}
    for intent, terms in _RULE_TERMS.items():
        for term, weight in terms:
            position = text.rfind(term.lower())
            if position >= 0:
                scores[intent] = scores.get(intent, 0.0) + weight
                latest[intent] = max(latest.get(intent, -1), position)
    if re.search(r"(?:[0-9零一二两三四五六七八九十百]+)\s*[天日]", text):
        scores["itinerary"] = scores.get("itinerary", 0.0) + 3.2
        latest["itinerary"] = max(latest.get("itinerary", -1), text.rfind("天"), text.rfind("日"))
    if not scores:
        intent: TravelIntent = "general"
        confidence = 0.2
    else:
        # A later explicit request wins over an earlier category in the same
        # sentence ("酒店附近有哪些景点" is an attraction query).  Scores
        # only break ties between terms ending at the same location.
        intent = max(scores, key=lambda item: (latest.get(item, -1), scores[item]))
        strongest = scores[intent]
        confidence = min(0.98, 0.5 + strongest / 12)
    entities = {}
    area = extract_area_entity(message)
    if area:
        entities["area"] = area
    return IntentDecision(intent, round(confidence, 3), "rules", entities)


class TravelIntentClassifier:
    """LLM-first classifier shared by every specialist Agent."""

    def __init__(self, settings: Settings, llm: DeepSeekClient) -> None:
        self.settings = settings
        self.llm = llm

    async def classify(self, message: str, context: str = "") -> IntentDecision:
        context = context.strip()
        message = message.strip()
        conversation = context
        if message and not context.endswith(message):
            conversation = "\n".join(part for part in (context, message) if part)
        conversation = conversation.strip()
        fallback = rule_classify(conversation)
        fallback_payload = {
            "intent": fallback.intent,
            "confidence": fallback.confidence,
            "entities": fallback.entities,
        }
        if self.settings.llm_mocked or not self.llm.configured:
            return fallback
        # Explicit requests such as "帮我规划杭州三日游" already carry a strong
        # intent signal. A remote model round-trip cannot improve tool routing
        # enough to justify spending up to half of the Agent's total budget.
        # Ambiguous and multi-intent questions remain model-classified.
        if fallback.intent == "itinerary" and fallback.confidence >= 0.9:
            return fallback
        try:
            parsed = await self.llm.chat_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是旅行助手的意图识别器。根据用户当前问题和必要的对话上下文，"
                            "选择最主要的旅行意图，并抽取原文中明确出现的地点实体。"
                            "只返回 JSON 对象，不要解释。intent 只能是 itinerary、attraction、"
                            "transportation、accommodation、food、shopping、budget、weather、general。"
                            "entities 可包含 destination、area、origin、target、transport_mode、"
                            "route_scope。transport_mode 只能是 high_speed_rail、bullet_train、"
                            "rail、air、transit、driving、walking 或 unknown；route_scope 只能是"
                            "cross_city、city_internal 或 unknown。没有明确出现的地点实体返回"
                            "空字符串，不得猜测地点；交通方式和路线范围可根据语义判断。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "message": message,
                                "context": context,
                                "rule_fallback": fallback_payload,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ]
            )
        except RuntimeError:
            return fallback
        intent = normalize_intent(parsed.get("intent")) or fallback.intent
        try:
            confidence = float(parsed.get("confidence", 0.8))
        except (TypeError, ValueError):
            confidence = 0.8
        confidence = max(0.0, min(1.0, confidence))
        raw_entities = parsed.get("entities")
        entities = dict(fallback.entities)
        if isinstance(raw_entities, dict):
            # Never let an LLM invent a place that was not in the user input.
            for key in (
                "destination",
                "area",
                "origin",
                "target",
                "transport_mode",
                "route_scope",
            ):
                value = _text(raw_entities.get(key))
                grounded = (
                    _grounded_entity(value, conversation)
                    if key not in {"transport_mode", "route_scope"}
                    else value
                )
                if grounded:
                    entities[key] = grounded
        return IntentDecision(intent, round(confidence, 3), "llm", entities)


__all__ = [
    "SEARCH_INTENT_MAP",
    "IntentDecision",
    "TravelIntent",
    "TravelIntentClassifier",
    "extract_area_entity",
    "normalize_intent",
    "rule_classify",
]
