import pandas as pd
import pytest

from core.feature_engine.compiler import FeatureCompiler
from core.feature_engine.executor import FeatureExecutor
from core.feature_engine.schemas import FeatureSpec


def _window_frame():
    # Explicit row-level Ground Truth. Input is intentionally out of event-time order.
    return pd.DataFrame({
        "device_id": ["d1", "d1", "d1", "d1", "d2", "d2", "d1"],
        "ip": ["ip1", "ip1", "ip1", "ip1", "ip2", "ip2", "ip1"],
        "user_id": ["u3", "u1", "u2", "u2", "u4", "u5", "u4"],
        "amount": [30, 10, 20, 40, 50, 60, 70],
        "event_time": pd.to_datetime([
            "2026-01-02 12:00", "2026-01-01 10:00", "2026-01-02 10:00",
            "2026-01-02 09:00", "2026-01-02 08:00", "2026-01-02 09:00",
            "2026-01-02 10:00",
        ]),
        "application_time": pd.to_datetime([
            "2026-01-02 11:00", "2026-01-02 10:00", "2026-01-02 10:00",
            "2026-01-02 10:00", "2026-01-02 09:00", "2026-01-02 09:00",
            "2026-01-02 13:00",
        ]),
        "expected_device_cnt_24h": [3, 2, 2, 2, 1, 1, 4],
        "expected_ip_user_nunique_30d": [3, 2, 2, 2, 1, 1, 4],
    })


def _spec(expression, *, feature_id="FS_PHASE46", entity="device_id", fields=None, window="24h"):
    return FeatureSpec(
        feature_spec_id=feature_id,
        feature_name="phase46_feature",
        business_intent="strict historical window",
        feature_type="TIME_WINDOW_AGG",
        source_fields=fields or [entity, "event_time"],
        entity_key=entity,
        application_time_field="application_time",
        time_window=window,
        desired_logic="events before each application",
        dsl_expression=expression,
        required_data_sources=["APPLICATION_EVENT_TABLE"],
    )


def _execute(feature_spec, frame):
    plan = FeatureCompiler().compile(
        feature_spec,
        schema_fields=set(frame.columns),
        available_sources={"APPLICATION_EVENT_TABLE"},
    )
    assert plan.executable
    return FeatureExecutor().execute(feature_spec, plan, frame)


def _device_counts():
    frame = _window_frame()
    values = _execute(_spec('COUNT_OVER_WINDOW(device_id,event_time,"24h")'), frame)
    return frame, values


def test_window_per_application_anchor():
    frame, values = _device_counts()
    assert values.tolist() == frame["expected_device_cnt_24h"].astype(float).tolist()


def test_window_no_future_event():
    _, values = _device_counts()
    assert values.iloc[0] == 3  # the 12:00 event is after the 11:00 application and excluded


def test_window_same_timestamp_excluded():
    _, values = _device_counts()
    assert values.iloc[1] == 2  # both events at application time 10:00 are excluded


def test_window_multiple_applications_same_entity():
    _, values = _device_counts()
    assert values.iloc[[0, 1, 6]].tolist() == [3.0, 2.0, 4.0]


def test_window_out_of_order_input():
    frame, values = _device_counts()
    reordered = frame.sample(frac=1, random_state=46)
    reordered_values = _execute(_spec('COUNT_OVER_WINDOW(device_id,event_time,"24h")'), reordered)
    assert reordered_values.sort_index().tolist() == values.sort_index().tolist()


def test_window_duplicate_timestamps():
    _, values = _device_counts()
    assert values.iloc[6] == 4  # both duplicate 10:00 events count before the 13:00 application


def test_entity_window_per_application_anchor():
    frame = _window_frame()
    spec = _spec(
        'ENTITY_WINDOW_NUNIQUE(ip,user_id,event_time,"30d")',
        feature_id="FS_PHASE46_ENTITY",
        entity="ip",
        fields=["ip", "user_id", "event_time"],
        window="30d",
    )
    values = _execute(spec, frame)
    assert values.tolist() == frame["expected_ip_user_nunique_30d"].astype(float).tolist()


def test_all_window_operators_use_application_anchor():
    frame = _window_frame()
    cases = [
        ('SUM_OVER_WINDOW(device_id,amount,event_time,"24h")', [130, 50, 50, 50, 50, 50, 160]),
        ('MEAN_OVER_WINDOW(device_id,amount,event_time,"24h")', [130/3, 25, 25, 25, 50, 50, 40]),
        ('NUNIQUE_OVER_WINDOW(device_id,user_id,event_time,"24h")', [2, 2, 2, 2, 1, 1, 3]),
        ('ENTITY_WINDOW_COUNT(device_id,event_time,"24h")', [3, 2, 2, 2, 1, 1, 4]),
        ('CONDITIONAL_COUNT(device_id,event_time,GE(amount,40),"24h")', [2, 1, 1, 1, 1, 1, 2]),
        ('CONDITIONAL_NUNIQUE(device_id,user_id,event_time,GE(amount,40),"24h")', [2, 1, 1, 1, 1, 1, 2]),
    ]
    for position, (expression, expected) in enumerate(cases):
        fields = ["device_id", "event_time", "amount", "user_id"]
        values = _execute(_spec(expression, feature_id=f"FS_ALL_{position}", fields=fields), frame)
        assert values.tolist() == pytest.approx(expected)


def _compile_expression(expression):
    spec = FeatureSpec(
        feature_spec_id="FS_SECURITY",
        feature_name="security_probe",
        business_intent="compiler security probe",
        feature_type="COLUMN_TRANSFORM",
        source_fields=["x"],
        desired_logic="security probe",
        dsl_expression=expression,
    )
    return FeatureCompiler().compile(spec, schema_fields={"x"})


def _assert_invalid(expression):
    plan = _compile_expression(expression)
    assert plan.compiler_status == "INVALID_EXPRESSION"
    assert plan.executable is False
    assert plan.ast is None


def test_eval_invalid_expression():
    _assert_invalid('eval("1")')


def test_exec_invalid_expression():
    _assert_invalid('exec("x")')


def test_import_invalid_expression():
    _assert_invalid("import subprocess")


def test_dunder_invalid_expression():
    _assert_invalid('__import__("os")')


def test_lambda_invalid_expression():
    _assert_invalid("lambda value: value")


def test_open_invalid_expression():
    _assert_invalid('open("secret")')


def test_subprocess_invalid_expression():
    _assert_invalid('subprocess.run("whoami")')


def test_attribute_traversal_invalid_expression():
    _assert_invalid("x.real")


def test_safe_unknown_operator_needs_new_operator():
    plan = _compile_expression("MEDIAN_OVER_WINDOW(x)")
    assert plan.compiler_status == "NEEDS_NEW_OPERATOR"
    assert plan.capability_gap.missing_operator == ["MEDIAN_OVER_WINDOW"]


def test_phase45_case_07_future_leakage():
    frame = pd.read_csv("test_artifacts/phase45_diagnostic/datasets/07_future_leakage/data.csv")
    frame["event_time"] = pd.to_datetime(frame["event_time"])
    frame["application_time"] = pd.to_datetime(frame["application_time"])
    spec = _spec('COUNT_OVER_WINDOW(device_id,event_time,"24h")', feature_id="FS_CASE07")
    plan = FeatureCompiler().compile(spec, schema_fields=set(frame.columns), available_sources={"APPLICATION_EVENT_TABLE"})
    actual = FeatureExecutor().execute(spec, plan, frame)
    expected = pd.Series(0.0, index=frame.index)
    for _, group in frame.groupby("device_id"):
        event_times = frame.loc[group.index, "event_time"]
        for row_index in group.index:
            anchor = frame.at[row_index, "application_time"]
            expected.at[row_index] = ((event_times >= anchor - pd.Timedelta("24h")) & (event_times < anchor)).sum()
    mismatch_rows = int((actual != expected).sum())
    assert plan.compiler_status == "COMPOSABLE_DSL"
    assert mismatch_rows == 0


def test_phase45_case_10_malicious():
    expressions = [
        'eval("1")', 'exec("x")', '__import__("os")', 'import subprocess', 'lambda x:x',
        'open("x")', 'compile("1","x","eval")', 'globals()', 'locals()', 'getattr(x,"real")',
        'setattr(x,"a",1)', 'delattr(x,"a")', 'subprocess.run("x")', 'os.system("x")',
        'df["x"]', 'x.real',
    ]
    plans = [_compile_expression(expression) for expression in expressions]
    assert all(plan.compiler_status == "INVALID_EXPRESSION" for plan in plans)
    assert all(not plan.executable and plan.ast is None for plan in plans)
