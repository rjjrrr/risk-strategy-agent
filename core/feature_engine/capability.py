from __future__ import annotations


class FeatureCapabilityRegistry:
    VERSION = "feature-capability-v1"
    ARITHMETIC = {"ADD","SUB","MUL","SAFE_DIV","ABS","MIN","MAX","CLIP","LOG1P"}
    MISSING = {"IS_MISSING","MISSING_FLAG"}
    AGGREGATION = {"COUNT","SUM","MEAN","MIN_AGG","MAX_AGG","STD","NUNIQUE"}
    TEMPORAL = {
        "COUNT_OVER_WINDOW","SUM_OVER_WINDOW","MEAN_OVER_WINDOW","NUNIQUE_OVER_WINDOW",
        "CONDITIONAL_COUNT","CONDITIONAL_NUNIQUE","TIME_DIFF",
    }
    ENTITY = {"ENTITY_COUNT","ENTITY_NUNIQUE","ENTITY_WINDOW_COUNT","ENTITY_WINDOW_NUNIQUE"}
    CONDITIONAL = {"IF","EQ","NE","GT","GE","LT","LE","IN","BOOLEAN_AND"}
    DERIVED = {"RULE_GROUP_HIT","RULE_GROUP_HIT_COUNT"}
    WINDOWS = {"1h","6h","24h","7d","30d","90d"}
    DATA_SOURCES = {"CURRENT_WIDE_TABLE","APPLICATION_EVENT_TABLE","DEVICE_RELATION_TABLE","IP_RELATION_TABLE","RULE_GROUP_ARTIFACT"}

    @property
    def operators(self) -> set[str]:
        return self.ARITHMETIC | self.MISSING | self.AGGREGATION | self.TEMPORAL | self.ENTITY | self.CONDITIONAL | self.DERIVED

    def supports(self, operator: str) -> bool: return operator.upper() in self.operators
    def supports_window(self, window: str | None) -> bool: return window is None or window.lower() in self.WINDOWS

    def summary(self) -> dict:
        return {"version":self.VERSION,"operators":sorted(self.operators),"arithmetic":sorted(self.ARITHMETIC),"missing":sorted(self.MISSING),"aggregations":sorted(self.AGGREGATION),"temporal":sorted(self.TEMPORAL),"entities":sorted(self.ENTITY),"conditional":sorted(self.CONDITIONAL),"derived_features":sorted(self.DERIVED),"windows":sorted(self.WINDOWS),"data_sources":sorted(self.DATA_SOURCES),"unsupported_examples":["GRAPH_CENTRALITY","EMBEDDING_SIMILARITY"]}
