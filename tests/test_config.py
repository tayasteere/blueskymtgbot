from bot.config import BotConfig, RateLimitConfig, load_config


def test_defaults_when_no_file(tmp_path):
    result = load_config(tmp_path / "nonexistent.toml")
    assert result == BotConfig()


def test_defaults_are_correct():
    c = BotConfig()
    assert c.poll_interval_seconds == 5.0
    assert c.max_cards_per_mention == 4
    assert c.metrics_enabled is True
    assert c.rate_limiting == RateLimitConfig()


def test_rate_limit_defaults_are_correct():
    rl = RateLimitConfig()
    assert rl.window_seconds == 60.0
    assert rl.max_mentions_per_window == 5
    assert rl.violation_window_seconds == 600.0
    assert rl.violations_before_warning == 3
    assert rl.violations_before_block == 5


def test_full_config_loaded(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[bot]\n"
        "poll_interval_seconds = 10\n"
        "max_cards_per_mention = 2\n"
        "metrics_enabled = false\n"
        "[rate_limiting]\n"
        "window_seconds = 30\n"
        "max_mentions_per_window = 3\n"
        "violation_window_seconds = 300\n"
        "violations_before_warning = 2\n"
        "violations_before_block = 4\n"
    )
    result = load_config(config_file)
    assert result.poll_interval_seconds == 10.0
    assert result.max_cards_per_mention == 2
    assert result.metrics_enabled is False
    assert result.rate_limiting.window_seconds == 30.0
    assert result.rate_limiting.max_mentions_per_window == 3
    assert result.rate_limiting.violation_window_seconds == 300.0
    assert result.rate_limiting.violations_before_warning == 2
    assert result.rate_limiting.violations_before_block == 4


def test_partial_config_uses_defaults_for_missing_keys(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[bot]\npoll_interval_seconds = 15\n")
    result = load_config(config_file)
    assert result.poll_interval_seconds == 15.0
    assert result.max_cards_per_mention == 4
    assert result.rate_limiting == RateLimitConfig()


def test_empty_config_file_uses_all_defaults(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("")
    result = load_config(config_file)
    assert result == BotConfig()
