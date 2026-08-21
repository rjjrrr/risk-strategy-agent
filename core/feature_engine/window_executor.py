from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from .ast import FieldNode, OperatorNode, WindowNode
from .capability import FeatureCapabilityRegistry
from .exceptions import ExecutionFailed


class WindowExecutor:
    OPS = {
        "COUNT_OVER_WINDOW", "SUM_OVER_WINDOW", "MEAN_OVER_WINDOW", "NUNIQUE_OVER_WINDOW",
        "ENTITY_WINDOW_COUNT", "ENTITY_WINDOW_NUNIQUE", "CONDITIONAL_COUNT", "CONDITIONAL_NUNIQUE",
    }

    def __init__(self, capabilities=None, *, include_same_timestamp: bool = False):
        self.capabilities = capabilities or FeatureCapabilityRegistry()
        # V1 fixes the historical-window right boundary as strictly open.
        self.include_same_timestamp = include_same_timestamp

    @staticmethod
    def _field(node):
        if not isinstance(node, FieldNode):
            raise ExecutionFailed("Window field arguments must be field names")
        return node.name

    @staticmethod
    def _window(node):
        if not isinstance(node, WindowNode):
            raise ExecutionFailed("Window argument must be a quoted supported duration")
        return node.value

    @staticmethod
    def _bounded_nunique(raw_values, lower, upper):
        """Distinct counts for monotonically processed query bounds in O(events + queries)."""
        order = np.argsort(upper, kind="stable")
        counts = defaultdict(int)
        result = np.zeros(len(upper), dtype=float)
        left = right = 0
        for query_position in order:
            query_left = int(lower[query_position])
            query_right = int(upper[query_position])
            while right < query_right:
                value = raw_values[right]
                if not pd.isna(value):
                    counts[value] += 1
                right += 1
            while left < query_left:
                value = raw_values[left]
                if not pd.isna(value):
                    counts[value] -= 1
                    if counts[value] == 0:
                        del counts[value]
                left += 1
            result[query_position] = len(counts)
        return result

    def execute(self, node: OperatorNode, df: pd.DataFrame, evaluate=None, *, application_time_field: str | None = None):
        if node.op not in self.OPS:
            return None
        entity = self._field(node.args[0])
        count_op = node.op in {"COUNT_OVER_WINDOW", "ENTITY_WINDOW_COUNT", "CONDITIONAL_COUNT"}
        conditional = node.op in {"CONDITIONAL_COUNT", "CONDITIONAL_NUNIQUE"}
        if node.op == "CONDITIONAL_COUNT":
            time_field = self._field(node.args[1]); value_field = None; condition_node = node.args[2]; window = self._window(node.args[3])
        elif node.op == "CONDITIONAL_NUNIQUE":
            value_field = self._field(node.args[1]); time_field = self._field(node.args[2]); condition_node = node.args[3]; window = self._window(node.args[4])
        elif count_op:
            time_field = self._field(node.args[1]); value_field = None; condition_node = None; window = self._window(node.args[2])
        else:
            value_field = self._field(node.args[1]); time_field = self._field(node.args[2]); condition_node = None; window = self._window(node.args[3])
        if not self.capabilities.supports_window(window):
            raise ExecutionFailed(f"Unsupported window: {window}")

        anchor_field = application_time_field or time_field
        needed = {entity, time_field, anchor_field} | ({value_field} if value_field else set())
        missing = needed - set(df.columns)
        if missing:
            raise ExecutionFailed(f"Window source fields missing: {sorted(missing)}")

        work = pd.DataFrame({
            "_entity": df[entity],
            "_event_time": pd.to_datetime(df[time_field], errors="coerce"),
            "_anchor_time": pd.to_datetime(df[anchor_field], errors="coerce"),
            "_position": np.arange(len(df)),
        }, index=df.index)
        if value_field:
            work["_value"] = df[value_field]
        if conditional:
            if evaluate is None:
                raise ExecutionFailed("Conditional window requires a controlled condition evaluator")
            work["_condition"] = pd.Series(evaluate(condition_node), index=df.index).fillna(False).astype(bool)

        result = pd.Series(np.nan, index=df.index, dtype=float)
        query_valid = work["_entity"].notna() & work["_anchor_time"].notna()
        if not query_valid.any():
            return result
        window_delta = pd.Timedelta(window).to_timedelta64()
        upper_side = "right" if self.include_same_timestamp else "left"
        event_valid = work["_entity"].notna() & work["_event_time"].notna()
        event_groups = {
            key: group.sort_values(["_event_time", "_position"], kind="stable")
            for key, group in work.loc[event_valid].groupby("_entity", sort=False)
        }

        for entity_value, queries in work.loc[query_valid].groupby("_entity", sort=False):
            events = event_groups.get(entity_value)
            if events is None or events.empty:
                result.loc[queries.index] = 0.0
                continue
            event_times = events["_event_time"].to_numpy(dtype="datetime64[ns]")
            anchors = queries["_anchor_time"].to_numpy(dtype="datetime64[ns]")
            lower = np.searchsorted(event_times, anchors - window_delta, side="left")
            upper = np.searchsorted(event_times, anchors, side=upper_side)

            if count_op:
                source = events["_condition"].astype(float).to_numpy() if conditional else np.ones(len(events), dtype=float)
                prefix = np.concatenate(([0.0], np.cumsum(source)))
                values = prefix[upper] - prefix[lower]
            elif node.op in {"SUM_OVER_WINDOW", "MEAN_OVER_WINDOW"}:
                numeric = pd.to_numeric(events["_value"], errors="coerce").to_numpy(dtype=float)
                valid_numeric = np.isfinite(numeric)
                sums = np.concatenate(([0.0], np.cumsum(np.where(valid_numeric, numeric, 0.0))))
                counts = np.concatenate(([0], np.cumsum(valid_numeric.astype(int))))
                window_sums = sums[upper] - sums[lower]
                window_counts = counts[upper] - counts[lower]
                values = window_sums if node.op == "SUM_OVER_WINDOW" else np.divide(
                    window_sums, window_counts, out=np.zeros_like(window_sums), where=window_counts > 0
                )
            else:
                raw = events["_value"].where(events["_condition"]) if conditional else events["_value"]
                values = self._bounded_nunique(raw.to_numpy(dtype=object), lower, upper)
            result.loc[queries.index] = values.astype(float)
        return result
