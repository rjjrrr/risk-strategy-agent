import numpy as np
import pandas as pd

from core.model_agent.target_proxy import audit_target_proxies, remove_target_proxies


def test_near_perfect_target_proxy_is_removed_across_time_split():
    size = 400
    target = np.tile([0, 1], size // 2)
    frame = pd.DataFrame({
        "target7": target,
        "pay_type": target.copy(),
        "legitimate_signal": np.random.default_rng(42).normal(size=size),
    })
    dev, oot = frame.index[:280], frame.index[280:]
    kept, audit = remove_target_proxies(frame, "target7", dev, oot, ["pay_type", "legitimate_signal"])
    assert kept == ["legitimate_signal"]
    assert audit["status"] == "BLOCKED_TARGET_PROXIES"
    assert audit["excluded_fields"] == ["pay_type"]
    assert audit["findings"][0]["dev_auc"] == audit["findings"][0]["oot_auc"] == 1.0


def test_random_feature_passes_target_proxy_audit():
    rng = np.random.default_rng(7)
    frame = pd.DataFrame({"target7": rng.integers(0, 2, 500), "feature": rng.normal(size=500)})
    result = audit_target_proxies(frame, "target7", frame.index[:350], frame.index[350:], ["feature"])
    assert result["status"] == "PASS" and result["excluded_fields"] == []


def test_proxy_after_display_feature_limit_is_still_detected():
    size = 400
    rng = np.random.default_rng(11)
    target = np.tile([0, 1], size // 2)
    values = {f"safe_{index}": rng.normal(size=size) for index in range(35)}
    values["late_proxy"] = target
    frame = pd.DataFrame({"target7": target, **values})
    fields = [f"safe_{index}" for index in range(35)] + ["late_proxy"]
    kept, audit = remove_target_proxies(frame, "target7", frame.index[:280], frame.index[280:], fields)
    assert "late_proxy" not in kept
    assert audit["excluded_fields"] == ["late_proxy"]
