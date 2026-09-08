from backend.app.agent.route_helpers import select_train_samples


def _trains() -> list[dict[str, str]]:
    return [
        {"train_no": "G101", "start_time": "06:30"},
        {"train_no": "G102", "start_time": "07:10"},
        {"train_no": "G103", "start_time": "09:20"},
        {"train_no": "G201", "start_time": "12:05"},
        {"train_no": "G202", "start_time": "13:40"},
        {"train_no": "G203", "start_time": "17:30"},
        {"train_no": "G301", "start_time": "18:05"},
        {"train_no": "G302", "start_time": "20:15"},
        {"train_no": "G303", "start_time": "22:00"},
        {"train_no": "G304", "start_time": "23:10"},
    ]


def test_default_selection_is_time_diverse_and_bounded() -> None:
    selected = select_train_samples(_trains(), 9, "郑州到北京的车次")

    assert len(selected) == 9
    assert [item["train_no"] for item in selected[:3]] == ["G101", "G201", "G301"]
    assert sum(item["start_time"] < "12:00" for item in selected) == 3
    assert sum("12:00" <= item["start_time"] < "18:00" for item in selected) == 3
    assert sum(item["start_time"] >= "18:00" for item in selected) == 3


def test_explicit_period_is_a_hard_filter_even_under_limit() -> None:
    selected = select_train_samples(_trains(), 9, "明天下午出发")

    assert [item["train_no"] for item in selected] == ["G201", "G202", "G203"]


def test_explicit_clock_selects_matching_period() -> None:
    selected = select_train_samples(_trains(), 9, "20点左右出发")

    assert [item["train_no"] for item in selected] == ["G301", "G302", "G303", "G304"]
