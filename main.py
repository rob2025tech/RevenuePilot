"""
main.py
FastAPI backend for RevenuePilot.
"""

from __future__ import annotations

from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agents.audit_agent import AuditAgent
from agents.data_agent import DataAgent
from agents.execution_agent import ExecutionAgent
from agents.orchestrator import AgentType, RevenuePilotOrchestrator
from agents.risk_agent import RiskAgent
from agents.strategy_agent import StrategyAgent

app = FastAPI(title="RevenuePilot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Agent initialisation
# ---------------------------------------------------------------------------
orchestrator = RevenuePilotOrchestrator()
orchestrator.register_agent(AgentType.DATA, DataAgent())
orchestrator.register_agent(AgentType.RISK, RiskAgent())
orchestrator.register_agent(AgentType.STRATEGY, StrategyAgent())
orchestrator.register_agent(AgentType.EXECUTION, ExecutionAgent())
orchestrator.register_agent(AgentType.AUDIT, AuditAgent())

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class Account(BaseModel):
    id: str
    name: str
    contract_end: Optional[str] = None
    annual_value: Optional[float] = None


class AnalysisRequest(BaseModel):
    accounts: List[Account] = Field(..., min_items=1)


class ApprovalRequest(BaseModel):
    account_id: str  # FIX: renamed from strategy_id – matches approval_queue key
    approved: bool
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "RevenuePilot",
        "registered_agents": [a.value for a in orchestrator.agents],
    }


@app.post("/api/analyze")
async def analyze_revenue_risk(request: AnalysisRequest):
    """Main endpoint – runs all accounts through the full agent pipeline."""
    try:
        # FIX: use model_dump() (Pydantic v2) with fallback to dict() for v1
        accounts_data = [
            a.model_dump() if hasattr(a, "model_dump") else a.dict()
            for a in request.accounts
        ]
        result = await orchestrator.process_revenue_signals(accounts_data)
        return {
            "status": "success",
            "data": result,
            "message": f"Analysed {len(accounts_data)} account(s)",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/pending-approvals")
async def get_pending_approvals():
    """Return strategies waiting for human approval."""
    execution_agent: ExecutionAgent = orchestrator.agents.get(AgentType.EXECUTION)
    # FIX: approval_queue is now a dict; return its values as a list
    return {"pending": list(execution_agent.approval_queue.values())}


@app.post("/api/approve-strategy")
async def approve_strategy(request: ApprovalRequest):
    """Approve or reject a pending strategy."""
    execution_agent: ExecutionAgent = orchestrator.agents.get(AgentType.EXECUTION)

    if request.approved:
        # FIX: uses the new O(1) method instead of a list scan
        result = await execution_agent.execute_approved_strategy(request.account_id)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"No pending strategy found for account '{request.account_id}'",
            )
        return {"status": "executed", "result": result}

    # Rejection path: remove from queue without executing
    removed = execution_agent.approval_queue.pop(request.account_id, None)
    if removed is None:
        raise HTTPException(
            status_code=404,
            detail=f"No pending strategy found for account '{request.account_id}'",
        )
    return {"status": "rejected", "notes": request.notes}


@app.get("/api/metrics")
async def get_metrics():
    """Return cumulative metrics from the Audit agent."""
    audit_agent: AuditAgent = orchestrator.agents.get(AgentType.AUDIT)
    return audit_agent.metrics


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)
