from bot.config import RateLimitConfig
from bot.rate_limiter import RateLimiter

_CFG = RateLimitConfig(
    window_seconds=60.0,
    max_mentions_per_window=3,
    violation_window_seconds=600.0,
    violations_before_warning=2,
    violations_before_block=3,
)


def _make_limiter(blocked_dids=None, start_time=0.0):
    clock = [start_time]
    return RateLimiter(
        _CFG,
        blocked_dids=blocked_dids,
        clock_fn=lambda: clock[0],
    ), clock


# ── allowed / blocked states ──────────────────────────────────────────────────


def test_first_mention_allowed():
    limiter, _ = _make_limiter()
    decision = limiter.record_mention("did:plc:user1")
    assert decision.allowed is True


def test_mentions_within_limit_all_allowed():
    limiter, _ = _make_limiter()
    for _ in range(_CFG.max_mentions_per_window):
        assert limiter.record_mention("did:plc:user1").allowed is True


def test_mention_over_limit_not_allowed():
    limiter, _ = _make_limiter()
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention("did:plc:user1")
    decision = limiter.record_mention("did:plc:user1")
    assert decision.allowed is False


def test_window_resets_after_expiry():
    limiter, clock = _make_limiter()
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention("did:plc:user1")
    clock[0] = _CFG.window_seconds + 1
    assert limiter.record_mention("did:plc:user1").allowed is True


def test_different_users_tracked_independently():
    limiter, _ = _make_limiter()
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention("did:plc:user1")
    assert limiter.record_mention("did:plc:user2").allowed is True


def test_pre_blocked_user_not_allowed():
    limiter, _ = _make_limiter(blocked_dids={"did:plc:badactor"})
    decision = limiter.record_mention("did:plc:badactor")
    assert decision.allowed is False
    assert decision.should_block is False


def test_is_blocked_returns_true_for_blocked_did():
    limiter, _ = _make_limiter(blocked_dids={"did:plc:badactor"})
    assert limiter.is_blocked("did:plc:badactor") is True


def test_is_blocked_returns_false_for_unknown_did():
    limiter, _ = _make_limiter()
    assert limiter.is_blocked("did:plc:user1") is False


# ── violation tracking ────────────────────────────────────────────────────────


def test_first_violation_silently_dropped():
    limiter, _ = _make_limiter()
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention("did:plc:user1")
    decision = limiter.record_mention("did:plc:user1")
    assert decision.allowed is False
    assert decision.should_warn is False
    assert decision.should_block is False


def test_warning_issued_at_threshold():
    limiter, _ = _make_limiter()
    did = "did:plc:user1"
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention(did)
    for _ in range(_CFG.violations_before_warning - 1):
        limiter.record_mention(did)
    decision = limiter.record_mention(did)
    assert decision.should_warn is True


def test_warning_issued_only_once():
    limiter, _ = _make_limiter()
    did = "did:plc:user1"
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention(did)
    warn_count = 0
    for _ in range(_CFG.violations_before_block - 1):
        d = limiter.record_mention(did)
        if d.should_warn:
            warn_count += 1
    assert warn_count == 1


def test_block_issued_at_threshold():
    limiter, _ = _make_limiter()
    did = "did:plc:user1"
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention(did)
    for _ in range(_CFG.violations_before_block - 1):
        limiter.record_mention(did)
    decision = limiter.record_mention(did)
    assert decision.should_block is True


def test_block_adds_did_to_blocked_set():
    limiter, _ = _make_limiter()
    did = "did:plc:user1"
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention(did)
    for _ in range(_CFG.violations_before_block):
        limiter.record_mention(did)
    assert limiter.is_blocked(did)


def test_blocked_user_stays_blocked():
    limiter, _ = _make_limiter()
    did = "did:plc:user1"
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention(did)
    for _ in range(_CFG.violations_before_block):
        limiter.record_mention(did)
    decision = limiter.record_mention(did)
    assert decision.allowed is False
    assert decision.should_block is False


# ── populate_blocked ──────────────────────────────────────────────────────────


def test_populate_blocked_adds_dids():
    limiter, _ = _make_limiter()
    limiter.populate_blocked({"did:plc:a", "did:plc:b"})
    assert limiter.is_blocked("did:plc:a")
    assert limiter.is_blocked("did:plc:b")


def test_populate_blocked_merges_with_existing():
    limiter, _ = _make_limiter(blocked_dids={"did:plc:existing"})
    limiter.populate_blocked({"did:plc:new"})
    assert limiter.is_blocked("did:plc:existing")
    assert limiter.is_blocked("did:plc:new")


def test_populate_blocked_empty_set_is_noop():
    limiter, _ = _make_limiter(blocked_dids={"did:plc:existing"})
    limiter.populate_blocked(set())
    assert limiter.is_blocked("did:plc:existing")


def test_populated_user_is_subsequently_blocked():
    limiter, _ = _make_limiter()
    assert limiter.record_mention("did:plc:user1").allowed is True
    limiter.populate_blocked({"did:plc:user1"})
    assert limiter.record_mention("did:plc:user1").allowed is False


# ── violation tracking ────────────────────────────────────────────────────────


def test_violations_expire_after_window():
    limiter, clock = _make_limiter()
    did = "did:plc:user1"
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention(did)
    for _ in range(_CFG.violations_before_warning - 1):
        limiter.record_mention(did)
    clock[0] = _CFG.violation_window_seconds + 1
    for _ in range(_CFG.max_mentions_per_window):
        limiter.record_mention(did)
    decision = limiter.record_mention(did)
    assert decision.should_warn is False
    assert decision.should_block is False
