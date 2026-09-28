"""
tests/test_approval_flow.py — small, focused tests for the Guardian HITL
approval transition (the core demo story). No large framework: each test builds
a fresh orchestrator from the REAL agents and drives it with asyncio.run.

Covers:
  * analysis holds the HIGH-risk account and does NOT auto-execute it
  * approve_guardian_decision(approved=True) executes the strategy and clears
    the queue  (regression guard for the ExecutionAgent re-gate bug)
  * approve_guardian_decision(approved=False) rejects without executing
"""

from __future__ import annotations

import asyncio
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agents.orchestrator import RevenuePilotOrchestrator, AgentType  # noqa: E402
from agents.data_agent import DataAgent  # noqa: E402
from agents.risk_agent import RiskAgent  # noqa: E402
from agents.strategy_agent import StrategyAgent  # noqa: E402
from agents.execution_agent import ExecutionAgent  # noqa: E402
from agents.audit_agent import AuditAgent  # noqa: E402
from utils import mock_accounts  # noqa: E402

HIGH_RISK_ID = "acc_001"


def _build_orchestrator() -> RevenuePilotOrchestrator:
    """Wire the real agents exactly as the application does (fresh state)."""
    o = RevenuePilotOrchestrator()
    o.register_agent(AgentType.DATA, DataAgent())
    o.register_agent(AgentType.RISK, RiskAgent())
    o.register_agent(AgentType.STRATEGY, StrategyAgent())
    o.register_agent(AgentType.EXECUTION, ExecutionAgent())
    o.register_agent(AgentType.AUDIT, AuditAgent())
    return o


def _queued_ids(o: RevenuePilotOrchestrator) -> list:
    q = o.get_guardian_queue()
    return [x["account_id"] for x in q["pending_approval"]] + [
        x["account_id"] for x in q["held_for_review"]
    ]


def test_high_risk_held_and_not_auto_executed():
    async def scenario():
        o = _build_orchestrator()
        audit = await o.process_revenue_signals(mock_accounts)
        es = audit["report"]["executive_summary"]

        assert es["accounts_analyzed"] == 3
        assert es["high_risk_accounts"] == 1
        assert es["medium_risk_accounts"] == 2

        # HIGH-risk account is held for human review, not auto-executed.
        assert HIGH_RISK_ID in _queued_ids(o)
        initial_exec = o.agents[AgentType.AUDIT].audit_log[-1]["execution"]
        assert initial_exec["auto_executed"] == 0

    asyncio.run(scenario())


def test_approval_executes_and_clears_queue():
    async def scenario():
        o = _build_orchestrator()
        await o.process_revenue_signals(mock_accounts)

        res = await o.approve_guardian_decision(HIGH_RISK_ID, True, "test approver")

        assert res["status"] == "executed"
        assert res["approved_by"] == "human"
        # Regression guard: the approved strategy MUST actually execute and not
        # be silently re-queued by ExecutionAgent._requires_approval.
        assert res["execution"]["auto_executed"] == 1
        assert res["execution"]["pending_approval"] == 0
        assert res["execution"]["results"], "expected a non-empty execution log"
        # Decision removed from the Guardian queues.
        assert HIGH_RISK_ID not in _queued_ids(o)

    asyncio.run(scenario())


def test_rejection_clears_queue_without_executing():
    async def scenario():
        o = _build_orchestrator()
        await o.process_revenue_signals(mock_accounts)

        res = await o.approve_guardian_decision(HIGH_RISK_ID, False, "not now")

        assert res["status"] == "rejected"
        assert "execution" not in res  # nothing dispatched on rejection
        assert HIGH_RISK_ID not in _queued_ids(o)

    asyncio.run(scenario())


def test_not_found_for_unknown_account():
    async def scenario():
        o = _build_orchestrator()
        await o.process_revenue_signals(mock_accounts)
        res = await o.approve_guardian_decision("does_not_exist", True)
        assert res["status"] == "not_found"

    asyncio.run(scenario())
