from __future__ import annotations


class FeatureCapabilityRegistry:
    VERSION = "feature-capability-v2"
    ARITHMETIC = {
        "ADD","SUB","MUL","SAFE_DIV","MOD","POWER","ABS","SIGN","SQRT","EXP","LOG1P",
        "MIN","MAX","CLIP","ROUND","FLOOR","CEIL",
    }
    MISSING = {"IS_MISSING","MISSING_FLAG","COALESCE"}
    AGGREGATION = {"COUNT","SUM","MEAN","MEDIAN","MIN_AGG","MAX_AGG","STD","NUNIQUE"}
    TEMPORAL = {
        "COUNT_OVER_WINDOW","SUM_OVER_WINDOW","MEAN_OVER_WINDOW","MIN_OVER_WINDOW","MAX_OVER_WINDOW",
        "STD_OVER_WINDOW","NUNIQUE_OVER_WINDOW","CONDITIONAL_COUNT","CONDITIONAL_NUNIQUE",
        "TIME_DIFF","DAYS_BETWEEN","HOURS_BETWEEN","HOUR","DAY_OF_WEEK","DAY_OF_MONTH","MONTH","IS_WEEKEND",
    }
    ENTITY = {
        "ENTITY_COUNT","ENTITY_NUNIQUE","ENTITY_SUM","ENTITY_MEAN","ENTITY_MIN","ENTITY_MAX","ENTITY_STD",
        "ENTITY_WINDOW_COUNT","ENTITY_WINDOW_NUNIQUE",
    }
    CONDITIONAL = {"IF","EQ","NE","GT","GE","LT","LE","IN","BOOLEAN_AND","BOOLEAN_OR","NOT"}
    DERIVED = {"RULE_GROUP_HIT","RULE_GROUP_HIT_COUNT"}
    WINDOWS = {"1h","6h","24h","7d","30d","90d"}
    DATA_SOURCES = {"CURRENT_WIDE_TABLE","APPLICATION_EVENT_TABLE","DEVICE_RELATION_TABLE","IP_RELATION_TABLE","RULE_GROUP_ARTIFACT"}

    @property
    def operators(self) -> set[str]:
        return self.ARITHMETIC | self.MISSING | self.AGGREGATION | self.TEMPORAL | self.ENTITY | self.CONDITIONAL | self.DERIVED

    def supports(self, operator: str) -> bool: return operator.upper() in self.operators
    def supports_window(self, window: str | None) -> bool: return window is None or window.lower() in self.WINDOWS

    def summary(self) -> dict:
        return {
            "version":self.VERSION,"operators":sorted(self.operators),"arithmetic":sorted(self.ARITHMETIC),
            "missing":sorted(self.MISSING),"aggregations":sorted(self.AGGREGATION),"temporal":sorted(self.TEMPORAL),
            "entities":sorted(self.ENTITY),"conditional":sorted(self.CONDITIONAL),"derived_features":sorted(self.DERIVED),
            "windows":sorted(self.WINDOWS),"data_sources":sorted(self.DATA_SOURCES),
            "formula_examples":[
                {"name":"短长周期加速度","formula":"SAFE_DIV(SUB(cnt_7d,cnt_90d),ADD(ABS(cnt_90d),1))"},
                {"name":"非线性金额强度","formula":"POWER(LOG1P(ABS(amount)),2)"},
                {"name":"组合风险条件","formula":"IF(BOOLEAN_OR(GT(risk_score,80),IS_MISSING(device_id)),1,0)"},
                {"name":"30天行为波动","formula":"STD_OVER_WINDOW(user_id,amount,create_time,\"30d\")"},
                {"name":"实体平均强度","formula":"SAFE_DIV(ENTITY_SUM(device_id,amount),ENTITY_COUNT(device_id))"},
                {"name":"周末申请标记","formula":"IS_WEEKEND(create_time)"},
            ],
            "unsupported_examples":["GRAPH_CENTRALITY","EMBEDDING_SIMILARITY"],
        }
