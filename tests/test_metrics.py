import json
from unittest.mock import patch

import pytest

from bot.metrics import record_metric, set_enabled


def test_record_metric_writes_valid_json(capsys):
    record_metric("TestMetric")
    data = json.loads(capsys.readouterr().out.strip())
    assert data["TestMetric"] == 1
    assert data["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "ScryfallBot"


def test_record_metric_custom_value(capsys):
    record_metric("CardsInMention", value=3)
    data = json.loads(capsys.readouterr().out.strip())
    assert data["CardsInMention"] == 3


def test_record_metric_default_value_is_one(capsys):
    record_metric("TestMetric")
    data = json.loads(capsys.readouterr().out.strip())
    assert data["TestMetric"] == 1


def test_record_metric_name_in_metrics_list(capsys):
    record_metric("MentionProcessed")
    data = json.loads(capsys.readouterr().out.strip())
    metrics = data["_aws"]["CloudWatchMetrics"][0]["Metrics"]
    assert any(m["Name"] == "MentionProcessed" for m in metrics)


def test_record_metric_with_dimensions(capsys):
    record_metric("CardLookup", {"Mode": "prices"})
    data = json.loads(capsys.readouterr().out.strip())
    assert data["Mode"] == "prices"
    dimensions = data["_aws"]["CloudWatchMetrics"][0]["Dimensions"]
    assert ["Mode"] in dimensions


def test_record_metric_no_dimensions_empty_dimension_keys(capsys):
    record_metric("TestMetric")
    data = json.loads(capsys.readouterr().out.strip())
    assert data["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [[]]


def test_record_metric_swallows_exception(capsys):
    with patch("bot.metrics.json.dumps", side_effect=RuntimeError("fail")):
        record_metric("TestMetric")  # must not raise
    assert "Failed to record metric" in capsys.readouterr().err


# ── set_enabled ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def restore_enabled():
    yield
    set_enabled(True)


def test_disabled_metrics_produce_no_output(capsys):
    set_enabled(False)
    record_metric("TestMetric")
    assert capsys.readouterr().out == ""


def test_re_enabled_metrics_produce_output(capsys):
    set_enabled(False)
    set_enabled(True)
    record_metric("TestMetric")
    assert capsys.readouterr().out != ""
