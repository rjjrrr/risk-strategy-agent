class WorkflowError(RuntimeError):
    def __init__(self, code: str, message: str, *, route: str = "end"):
        super().__init__(message); self.code = code; self.route = route


class LLMWorkflowError(WorkflowError):
    def __init__(self, message: str): super().__init__("LLM_FAILED", message, route="review")


class FeatureWorkflowError(WorkflowError):
    def __init__(self, message: str): super().__init__("FEATURE_EXECUTION_FAILED", message, route="end")


class ModelWorkflowError(WorkflowError):
    def __init__(self, message: str): super().__init__("MODEL_TRAIN_FAILED", message, route="rollback")
