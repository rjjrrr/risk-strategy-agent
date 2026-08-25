from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
LABELS = (ROOT / "frontend/src/i18n/businessLabels.ts").read_text(encoding="utf-8")
GUIDE = (ROOT / "frontend/src/pages/GuidePage.tsx").read_text(encoding="utf-8")


def _has(values):
    assert all(f"{value}:" in LABELS for value in values)


def test_validation_labels():
    _has(["PROMISING", "EXPLORATORY", "REVIEW", "REJECTED"])


def test_diagnosis_labels():
    _has(["DATA_QUALITY", "LEAKAGE", "LOW_SIGNAL", "OVERFITTING", "FEATURE_DRIFT", "REDUNDANCY"])


def test_action_labels():
    _has(["TEST_FEATURE", "TEST_HYPOTHESIS", "MODEL_SWITCH", "MODEL_TUNE", "ROLLBACK", "NO_ACTION"])


def test_workflow_labels():
    _has(["NOT_STARTED", "RUNNING", "SUCCESS", "FAILED", "WAITING", "SKIPPED", "STALE", "CANCELLED"])


def test_credit_labels():
    _has(["POSITIVE", "NEUTRAL", "NEGATIVE", "UNSTABLE", "SUPPORTED", "PARTIALLY_SUPPORTED", "INCONCLUSIVE"])


def test_unknown_enum_fallback():
    assert "未知状态" in LABELS and "系统返回了尚未配置的状态" in LABELS


def test_guide_route_and_anchors():
    app = (ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    layout = (ROOT / "frontend/src/components/Layout.tsx").read_text(encoding="utf-8")
    assert "page==='guide'" in app and "['guide','使用指南'" in layout
    for anchor in ["quick", "flow", "pages", "metrics", "agent", "approval", "faq"]:
        assert f'id="{anchor}"' in GUIDE and f"['{anchor}'" in GUIDE
    for page in ["import", "overview", "rules", "agent-chat", "feature-engine", "decision-loop", "workflow-run"]:
        assert f"'{page}'" in GUIDE


def test_guide_business_boundaries_and_safety():
    for text in ["Agent 不会直接修改模型或上线策略", "真实的数据计算", "高风险操作仍需要人工确认", "只作辅助参考"]:
        assert text in GUIDE


def test_ui_mapping_scan_passes():
    module_path = ROOT / "scripts/full_flow_acceptance.py"
    spec = importlib.util.spec_from_file_location("mapping_scan", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    result = module.scan_ui_mapping()
    assert result["missing_core_mappings"] == []
    assert result["unmapped_user_visible"] == 0, result["findings"]


def test_decision_chat_renders_business_summary_instead_of_raw_json():
    page=(ROOT / "frontend/src/pages/AgentChatPage.tsx").read_text(encoding="utf-8")
    assert "实验决策建议" in page and "DECISION_AGENT" in page
    assert "NO_ACTIVE_BINDING:'当前模型没有可用密钥" in page


def test_feature_page_discloses_existing_validation_source():
    page=(ROOT / "frontend/src/pages/FeatureEnginePage.tsx").read_text(encoding="utf-8")
    assert "含模型初始化产生的特征，不代表本次聊天执行" in page
