#!/usr/bin/env python3
"""
scripts/demo.py — deterministic 60–90 second RevenuePilot demonstration.

Runs the REAL RevenuePilotOrchestrator and agents (the exact singleton the
FastAPI app uses — no orchestration logic is duplicated here) over the
existing mock accounts, then walks the full demo story:

    analyze → detect risk → strategy → Guardian HOLD → human approval
            → execution dispatch → audit transition

No Snowflake required: the Cortex Analyst layer is optional and falls back to
deterministic mock data when unconfigured (the default in this repo).

Usage:
    python scripts/demo.py
"""

from __future__ import annotations

import asyncio
import os
import sys

# Allow `python scripts/demo.py` from anywhere; repo root must be importable.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Reuse the actual application wiring (same orchestrator instance as the API).
from main import orchestrator, AgentType  # noqa: E402
from utils import mock_accounts  # noqa: E402

HIGH_RISK_ID = "acc_001"
RULE = "─" * 62


def _section(title: str) -> None:
    print()
    print(title)
    print(RULE)


async def run_demo() -> int:
    # ── 1. Analyze ────────────────────────────────────────────────────────
    _section("REVENUEPILOT DEMO")
    print(f"Accounts analyzed: {len(mock_accounts)}")
    for a in mock_accounts:
        print(
            f"  • {a['id']:<8} {a['name']:<22} "
            f"ARR ${a.get('annual_value', 0):>9,.0f}   contract end {a.get('contract_end')}"
        )

    # Runs Data → Risk → Strategy → Guardian → Execution → Audit.
    audit = await orchestrator.process_revenue_signals(mock_accounts)
    summary = audit["report"]["executive_summary"]

    # The AuditAgent records the full risk assessment; read it back (real data).
    audit_agent = orchestrator.agents[AgentType.AUDIT]
    entry = audit_agent.audit_log[-1]
    risk_results = entry["risk_assessment"]

    # ── 2. Risk ───────────────────────────────────────────────────────────
    _section("RISK")
    for r in risk_results:
        print(
            f"  {r['account_name']:<22} {r['risk_level']:<7} "
            f"score={r['risk_score']:.2f}  recovery_prob={r['recovery_probability']:.0%}"
        )
    print(
        f"\n  HIGH: {summary['high_risk_accounts']}   "
        f"MEDIUM: {summary['medium_risk_accounts']}   "
        f"at-risk revenue: ${summary['total_at_risk_revenue']:,.0f}"
    )

    # ── 3. Strategy ───────────────────────────────────────────────────────
    _section("STRATEGY")
    strategies = entry["strategies"]
    if not strategies:
        print("  (no high-risk strategies generated)")
    for s in strategies:
        steps = s["strategy"]["steps"]
        print(
            f"  {s['account_name']:<22} {s['strategy']['type']:<18} "
            f"priority={s['priority']:<6} est_recovery=${s['estimated_recovery']:,.0f}"
        )
        print(f"      steps: {' → '.join(str(st.get('action')) for st in steps)}")

    # ── 4. Guardian gate (HITL) ───────────────────────────────────────────
    _section("GUARDIAN")
    initial_exec = entry["execution"]
    print(
        f"  Auto-executed before approval: {initial_exec['auto_executed']}  "
        f"(no unsafe execution)"
    )
    held = orchestrator.guardian_hold_queue + orchestrator.guardian_approval_queue
    for d in held:
        print(
            f"  {d['account_name']:<22} → {d['overall_verdict']}  "
            f"(risk {d['overall_risk_score']:.2f})"
        )
        worst = max(d["step_decisions"], key=lambda x: x["risk_score"], default=None)
        if worst:
            print(f"      highest-risk step: {worst['action']} (score {worst['risk_score']:.2f})")
            for factor in worst["risk_factors"]:
                print(f"        - {factor}")
    print("\n  Guardian queue snapshot:")
    q = orchestrator.get_guardian_queue()
    print(f"      pending_approval : {[x['account_id'] for x in q['pending_approval']]}")
    print(f"      held_for_review  : {[x['account_id'] for x in q['held_for_review']]}")

    # ── 5. Human approval ─────────────────────────────────────────────────
    _section("HUMAN APPROVAL")
    approval = await orchestrator.approve_guardian_decision(
        account_id=HIGH_RISK_ID, approved=True, approver_notes="VP Sales (demo)"
    )
    print(f"  {HIGH_RISK_ID} → {approval['status'].upper()} by {approval.get('approved_by')}")
    print(f"      notes: {approval.get('approver_notes')}")
    print(f"      guardian risk at approval: {approval.get('guardian_risk_score')}")
    q_after = orchestrator.get_guardian_queue()
    still_queued = [x["account_id"] for x in q_after["pending_approval"]] + [
        x["account_id"] for x in q_after["held_for_review"]
    ]
    print(f"      removed from Guardian queue: {HIGH_RISK_ID not in still_queued}")

    # ── 6. Execution dispatch ─────────────────────────────────────────────
    _section("EXECUTION")
    ex = approval.get("execution", {})
    print(
        f"  dispatched: auto_executed={ex.get('auto_executed')}  "
        f"pending={ex.get('pending_approval')}  failed={ex.get('failed')}"
    )
    for res in ex.get("results", []):
        print(f"  {res['account_name']} → {res['status']}")
        for step in res["execution_log"]:
            print(f"      step {step['step']}: {step['action']:<16} {step['status']}")

    # ── 7. Audit ──────────────────────────────────────────────────────────
    _section("AUDIT")
    print(f"  audit_id: {audit['audit_id']}")
    print(f"  executive summary: {summary}")
    print("  recommendations:")
    for rec in audit["report"]["recommendations"]:
        print(f"      - {rec}")
    print("  approval → execution transition:")
    print(
        f"      {HIGH_RISK_ID} approved by human at {approval.get('executed_at')} "
        f"→ {ex.get('auto_executed')} strategy dispatched "
        f"(status={approval['status']})"
    )
    print(f"  cumulative metrics: {audit['metrics']}")

    _section("DEMO COMPLETE")
    ok = (
        summary["accounts_analyzed"] == 3
        and summary["high_risk_accounts"] == 1
        and summary["medium_risk_accounts"] == 2
        and initial_exec["auto_executed"] == 0
        and approval["status"] == "executed"
        and ex.get("auto_executed") == 1
    )
    print("  All demo invariants held:" , ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_demo()))
