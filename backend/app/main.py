from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import datasets,analysis,governance,rules,insights
app=FastAPI(title="Risk Strategy Agent V0.5")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
app.include_router(datasets.router); app.include_router(analysis.router); app.include_router(governance.router); app.include_router(rules.router)
app.include_router(insights.router)
@app.get("/api/health")
def health(): return {"status":"ok"}
