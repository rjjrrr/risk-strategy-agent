import os

import pandas as pd


RULE_COLS = [
    "rule_id", "segment", "field", "rule", "rule_type", "threshold_or_category",
    "hit_count", "bad_count", "coverage", "bad_rate", "base_bad_rate", "lift",
    "bootstrap_mean_lift", "bootstrap_lift_std", "bootstrap_positive_ratio",
    "dev_hit", "dev_coverage", "dev_bad_rate", "dev_lift",
    "oot_hit", "oot_coverage", "oot_bad_rate", "oot_lift", "direction_stable",
    "oot_status", "oot_warning", "grade", "warning", "review_reason",
    "missing_rule", "rare_category", "small_segment", "rule_group_id",
    "duplicate_group", "is_representative", "similarity_max", "reason",
]


def write_outputs(governance, rules, df, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    governance.to_csv(
        os.path.join(output_dir, "variable_governance.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    rr = pd.DataFrame(rules)
    rr = rr[[c for c in RULE_COLS if c in rr.columns]] if len(rr) else pd.DataFrame(columns=RULE_COLS)
    order = {"A": 0, "B": 1, "REVIEW": 2, "C": 3}
    if len(rr):
        rr = (
            rr.assign(_g=rr.grade.map(order).fillna(9))
            .sort_values(
                ["segment", "_g", "lift", "bootstrap_positive_ratio", "coverage"],
                ascending=[True, True, False, False, False],
            )
            .drop(columns="_g")
        )
    rr.to_csv(
        os.path.join(output_dir, "candidate_rules.csv"),
        index=False,
        encoding="utf-8-sig",
    )

    lines = ["# 风控策略挖掘报告", "", "## 数据概览", "", f"样本总量：{len(df):,}"]
    for segment in ("NEW", "OLD"):
        part = df[df.__segment__ == segment]
        base_rate = part.__target__.mean() if len(part) else float("nan")
        lines.extend(
            [
                f"{segment} 样本：{len(part):,}",
                f"{segment} 平均坏率：{base_rate:.4%}" if len(part) else f"{segment}：无数据",
                "",
                f"## {segment} TOP 候选规则",
                "",
            ]
        )
        view = rr[(rr.segment == segment) & rr.is_representative.fillna(True)].head(10) if len(rr) else rr
        for index, (_, row) in enumerate(view.iterrows(), 1):
            lines.extend(
                [
                    f"### Rule {index}",
                    f"规则 ID：{getattr(row, 'rule_id', '')}",
                    f"变量：{row.field}",
                    f"规则：{row.rule}",
                    f"命中样本：{row.hit_count:,}",
                    f"覆盖率：{row.coverage:.2%}",
                    f"坏率：{row.bad_rate:.2%}",
                    f"整体坏率：{row.base_bad_rate:.2%}",
                    f"Lift：{row.lift:.2f}",
                    f"Sampling Stability：{row.bootstrap_positive_ratio:.2%}",
                    f"OOT：{getattr(row, 'oot_status', 'NOT_AVAILABLE')}",
                    f"评级：{row.grade}",
                    f"Rule Group：{getattr(row, 'rule_group_id', '')}",
                    f"解释：{row.reason}",
                    "",
                ]
            )
    lines.extend(
        [
            "## 未推荐规则的典型原因",
            "",
            "- 样本量不足",
            "- 高唯一率",
            "- Lift 不足",
            "- 孤立风险尖峰",
            "- Bootstrap 不稳定",
            "- 疑似贷后信息泄露",
        ]
    )
    with open(os.path.join(output_dir, "rule_report.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return rr
