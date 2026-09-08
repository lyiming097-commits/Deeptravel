import pytest

from backend.app.rag.ingestion import split_text


def test_split_text_prefers_sentence_boundaries() -> None:
    text = "第一段介绍成都。" * 30 + "\n\n" + "第二段介绍交通。" * 30
    chunks = split_text(text, chunk_size=160, overlap=20)

    assert len(chunks) > 1
    assert all(chunk["content"] for chunk in chunks)
    assert all(len(chunk["content"]) <= 160 for chunk in chunks)
    assert all(len(chunk["content_hash"]) == 64 for chunk in chunks)


def test_split_text_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError):
        split_text("内容", chunk_size=100, overlap=100)
