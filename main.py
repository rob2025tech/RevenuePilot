# main.py
"""
RevenuePilot + Shadow Operator — FastAPI Backend
================================================

Changes from original:
- /api/pending-approvals  now reads from orchestrator.get_guardian_queue()
  instead of execution_agent.approval_queue
- /api/approve-strategy   now calls orchestrator.approve_guardian_decision()
  which runs the full Guardian → Execution flow
- /api/guardian-queue     NEW — exposes both approval + hold queues with
  full risk scores and step-level decisions for the frontend
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

from agents.orchestrator import RevenuePilotOrchestrator, AgentType
from agents.data_agent import DataAgent
from agents.risk_agent import RiskAgent
from agents.strategy_agent import StrategyAgent
from agents.execution_agent import ExecutionAgent
from agents.audit_agent import AuditAgent

app = FastAPI(
    title="RevenuePilot API",
    description="Revenue intelligence with Shadow Operator safety gates",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Initialize orchestrator ───────────────────────────────────

orchestrator = RevenuePilotOrchestrator()
orchestrator.register_agent(AgentType.DATA, DataAgent())
orchestrator.register_agent(AgentType.RISK, RiskAgent())
orchestrator.register_agent(AgentType.STRATEGY, StrategyAgent())
orchestrator.register_agent(AgentType.EXECUTION, ExecutionAgent())
orchestrator.register_agent(AgentType.AUDIT, AuditAgent())
# Note: GuardianAgent is built into the orchestrator directly —
# no separate registration needed.


# ── Pydantic models ───────────────────────────────────────────

class Account(BaseModel):
    id: str
    name: str
    contract_end: Optional[str] = None
    annual_value: Optional[float] = None


class AnalysisRequest(BaseModel):
    accounts: List[Account]


class ApprovalRequest(BaseModel):
    account_id: str          # changed from strategy_id for clarity
    approved: bool
    notes: Optional[str] = ""


# ── Endpoints ─────────────────────────────────────────────────

@app.post("/api/analyze")
async def analyze_revenue_risk(request: AnalysisRequest):
    """
    Main pipeline endpoint.
    Runs: Data → Risk → Strategy → Guardian → Execution → Audit
    Auto-safe actions execute immediately. Others land in Guardian queues.
    """
    try:
        accounts_data = [a.dict() for a in request.accounts]
        result = await orchestrator.process_revenue_signals(accounts_data)
        return {
            "status": "success",
            "data": result,
            "message": f"Analyzed {len(accounts_data)} accounts",
            "guardian_summary": result.get("guardian"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/pending-approvals")
async def get_pending_approvals():
    """
    Returns Guardian-queued strategies awaiting human review.
    Includes both HUMAN_APPROVAL_REQUIRED and HOLD_FOR_REVIEW buckets,
    with full risk scores and step-level decisions.
    """
    return orchestrator.get_guardian_queue()


@app.post("/api/approve-strategy")
async def approve_strategy(request: ApprovalRequest):
    """
    Human approves or rejects a Guardian-queued strategy.
    On approval: immediately dispatched to ExecutionAgent via Composio.
    On rejection: removed from queue and logged.
    """
    try:
        result = await orchestrator.approve_guardian_decision(
            account_id=request.account_id,
            approved=request.approved,
            approver_notes=request.notes or "",
        )
        if result["status"] == "not_found":
            raise HTTPException(
                status_code=404,
                detail=f"No pending Guardian decision for account {request.account_id}"
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/guardian-queue")
async def get_guardian_queue():
    """
    NEW endpoint — full Guardian queue view for the Shadow Operator UI.
    Returns risk scores, factors, and step-level decisions.
    Designed to feed the parallel reality simulation panel.
    """
    return orchestrator.get_guardian_queue()


@app.get("/api/metrics")
async def get_metrics():
    """Current metrics from AuditAgent."""
    audit_agent = orchestrator.agents.get(AgentType.AUDIT)
    if not audit_agent:
        raise HTTPException(status_code=503, detail="AuditAgent not registered")
    return audit_agent.metrics


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "RevenuePilot + Shadow Operator",
        "guardian_queue_depth": len(orchestrator.guardian_approval_queue),
        "guardian_hold_depth": len(orchestrator.guardian_hold_queue),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
