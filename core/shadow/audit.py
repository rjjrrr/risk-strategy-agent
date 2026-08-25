from pathlib import Path
from core.model_agent.registry import JsonRegistry
class ShadowPredictionRegistry(JsonRegistry):
    def __init__(self,root:str|Path):super().__init__(Path(root)/"shadow_predictions.json","shadow_id")
class PredictionErrorRegistry(JsonRegistry):
    def __init__(self,root:str|Path):super().__init__(Path(root)/"prediction_errors.json","error_id")
class ShadowModelStateRegistry(JsonRegistry):
    def __init__(self,root:str|Path):super().__init__(Path(root)/"shadow_model_states.json","state_id")
