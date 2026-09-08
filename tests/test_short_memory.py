from backend.app.agent.base import (
    SpecialistAgent,
    infer_destination,
    normalize_destination,
    short_term_memory,
)
from backend.app.config import Settings
from backend.app.llm.deepseek import DeepSeekClient
from backend.app.tools import EvidenceItem


def test_short_term_memory_is_inserted_between_system_and_current_request() -> None:
    settings = Settings(_env_file=None, mock_llm=True)
    llm = DeepSeekClient("", "https://api.deepseek.com", "deepseek-chat")
    agent = SpecialistAgent(settings, llm)
    memory = [
        {"role": "user", "content": "我想去郑州"},
        {"role": "assistant", "content": "打算玩几天呢？"},
        {"role": "tool", "content": "不应进入对话记忆"},
    ]

    with short_term_memory(memory):
        messages = agent._messages("解析当前需求", {"message": "两天"})

    assert [item["role"] for item in messages] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert messages[1]["content"] == "我想去郑州"
    assert messages[-1]["content"] == '{"message": "两天"}'


def test_destination_inference_prefers_the_latest_city_in_memory() -> None:
    assert infer_destination("之前想去成都\n现在想看杭州西湖附近酒店", "") == "杭州"


def test_normalize_destination_separates_city_and_landmark() -> None:
    assert normalize_destination("洛阳龙门石窟", "洛阳龙门石窟的图片") == "洛阳"
    assert normalize_destination("杭州西湖", "杭州西湖两日游") == "杭州"


def test_web_evidence_for_model_contains_body_but_not_url() -> None:
    payload = SpecialistAgent.evidence_for_model(
        [
            EvidenceItem(
                content="抓取并清洗后的网页正文",
                title="成都旅游资料",
                url="https://example.com/chengdu",
                source_type="external_web",
                similarity=0.91,
            )
        ]
    )

    assert payload[0]["content"] == "抓取并清洗后的网页正文"
    assert "url" not in payload[0]


def test_clean_answer_removes_markdown_and_bare_urls() -> None:
    answer = SpecialistAgent.clean_answer(
        "参考[旅游攻略](https://example.com/guide)，详情见 https://example.com/more。"
    )

    assert answer == "参考旅游攻略，详情见 。"


def test_clean_answer_keeps_a_scan_friendly_layout() -> None:
    answer = SpecialistAgent.clean_answer(
        "### 行程建议\n\n**第 1 天**\n- **西湖**漫步\n- 灵隐寺参观\n\n1、晚餐安排"
    )

    assert answer == "行程建议\n\n第 1 天\n\n• 西湖漫步\n• 灵隐寺参观\n\n1. 晚餐安排"


def test_clean_answer_separates_plain_day_headings() -> None:
    answer = SpecialistAgent.clean_answer("第 1 天：西湖与灵隐寺\n上午参观，下午漫步。\n第 2 天：河坊街")

    assert answer == "第 1 天：西湖与灵隐寺\n\n上午参观，下午漫步。\n\n第 2 天：河坊街"
