class FeatureEngineError(Exception):
    code = "FEATURE_ENGINE_ERROR"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message); self.details = details or {}


class FeatureSpecInvalid(FeatureEngineError): code = "FEATURE_SPEC_INVALID"
class SourceFieldMissing(FeatureEngineError): code = "SOURCE_FIELD_MISSING"
class SourceDataMissing(FeatureEngineError): code = "SOURCE_DATA_MISSING"
class OperatorUnsupported(FeatureEngineError): code = "OPERATOR_UNSUPPORTED"
class LeakageBlocked(FeatureEngineError): code = "LEAKAGE_BLOCKED"
class DatetimeRawBlocked(FeatureEngineError): code = "DATETIME_RAW_BLOCKED"
class ExecutionFailed(FeatureEngineError): code = "EXECUTION_FAILED"
class RebuildMismatch(FeatureEngineError): code = "REBUILD_MISMATCH"
