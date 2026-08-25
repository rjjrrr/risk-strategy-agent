from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import datasets,analysis,governance,rules,insights,model_agent,agent_chat,context,feature_engine,feature_validation,decision_agent,experiment_memory,shadow,workflow
from .json_safe import SafeJSONResponse
app=FastAPI(title="Risk Strategy Agent V1.0",default_response_class=SafeJSONResponse)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(datasets.router); app.include_router(analysis.router); app.include_router(governance.router); app.include_router(rules.router)
app.include_router(insights.router)
app.include_router(model_agent.router)
app.include_router(agent_chat.llm_router);app.include_router(agent_chat.chat_router)
app.include_router(context.router)
app.include_router(feature_engine.engine_router);app.include_router(feature_engine.spec_router);app.include_router(feature_engine.feature_router)
app.include_router(feature_validation.validation_router);app.include_router(feature_validation.counterfactual_router);app.include_router(feature_validation.credit_router)
app.include_router(decision_agent.router)
app.include_router(experiment_memory.router)
app.include_router(shadow.router)
app.include_router(workflow.router)
@app.get("/api/health")
def health(): return {"status":"ok"}
