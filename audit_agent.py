"""
agents/audit_agent.py
Tracks measurable outcomes and maintains workflow explainability.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from .base_agent import BaseAgent


class AuditAgent(BaseAgent):
    """Tracks measurable outcomes and maintains explainability."""

    # Estimated analyst hours saved per at-risk account processed
    HOURS_SAVED_PER_ACCOUNT = 2

    def __init__(self):
        super().__init__("audit")
        self.audit_log: List[Dict[str, Any]] = []
        # FIX: metrics now accumulate across multiple runs instead of being
        # overwritten each time. Use _update_metrics carefully.
        self.metrics: Dict[str, Any] = {
            "total_risk_identified": 0,
            "strategies_created": 0,
            "strategies_executed": 0,
            "pending_approval": 0,
            "estimated_recovery": 0.0,
            "human_time_saved_hours": 0,
            "runs": 0,
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def process(self, message) -> Dict[str, Any]:
        workflow_data = message.content

        audit_id = f"audit_{uuid.uuid4().hex[:8]}"
        audit_entry = {
            "audit_id": audit_id,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "data_analysis": workflow_data.get("data", []),
            "risk_assessment": workflow_data.get("risk", []),
            "strategies": workflow_data.get("strategies", []),
            "execution": workflow_data.get("execution", {}),
        }
        self.audit_log.append(audit_entry)

        await self._update_metrics(workflow_data)
        report = await self._generate_report(workflow_data)

        await self.log_action("audit_complete", {"audit_id": audit_id})

        return {
            "audit_id": audit_id,
            "metrics": self.metrics,
            "report": report,
            "log_summary": self._summarize_log(),
        }

    # ------------------------------------------------------------------
    # Metrics & reporting
    # ------------------------------------------------------------------

    async def _update_metrics(self, data: Dict) -> None:
        """
        Update running metrics from a single workflow run.

        FIX: original overwrote totals instead of accumulating them across runs.
        """
        risk_items: List[Dict] = data.get("risk", [])
        strategies: List[Dict] = data.get("strategies", [])
        execution: Dict = data.get("execution", {})

        self.metrics["runs"] += 1
        self.metrics["total_risk_identified"] += len(risk_items)
        self.metrics["strategies_created"] += len(strategies)
        self.metrics["strategies_executed"] += execution.get("auto_executed", 0)
        self.metrics["pending_approval"] += execution.get("pending_approval", 0)
        self.metrics["estimated_recovery"] += sum(
            s.get("estimated_recovery", 0) for s in strategies
        )
        self.metrics["human_time_saved_hours"] += len(risk_items) * self.HOURS_SAVED_PER_ACCOUNT

    async def _generate_report(self, data: Dict) -> Dict[str, Any]:
        """Generate an executive-level summary of this workflow run."""
        risk_items: List[Dict] = data.get("risk", [])
        strategies: List[Dict] = data.get("strategies", [])

        high_risk = [r for r in risk_items if r.get("risk_level") == "HIGH"]
        medium_risk = [r for r in risk_items if r.get("risk_level") == "MEDIUM"]

        # FIX: original looked for priority on the nested strategy dict;
        # now we read it from the top-level key set by StrategyAgent.
        immediate_actions = [s for s in strategies if s.get("priority") == "high"]

        run_recovery = sum(s.get("estimated_recovery", 0) for s in strategies)

        return {
            "executive_summary": {
                "accounts_analyzed": len(risk_items),
                "high_risk_accounts": len(high_risk),
                "medium_risk_accounts": len(medium_risk),
                "total_at_risk_revenue": round(run_recovery, 2),
                "immediate_actions_required": len(immediate_actions),
            },
            "top_accounts": sorted(
                [
                    {
                        "account_id": r.get("account_id"),
                        "account_name": r.get("account_name"),
                        "risk_score": r.get("risk_score"),
                        "risk_level": r.get("risk_level"),
                    }
                    for r in high_risk
                ],
                key=lambda x: x.get("risk_score", 0),
                reverse=True,
            )[:5],
            "recommendations": self._build_recommendations(data),
        }

    def _build_recommendations(self, data: Dict) -> List[str]:
        """Derive actionable recommendations from workflow data."""
        recommendations: List[str] = []
        risk_items: List[Dict] = data.get("risk", [])

        # Check for severely overdue accounts
        severe_overdue = [
            r for r in risk_items
            if (r.get("signals", {}).get("overdue", {}) or {}).get("days_overdue", 0) > 60
        ]
        if severe_overdue:
            recommendations.append(
                f"Escalate {len(severe_overdue)} account(s) with invoices >60 days overdue "
                "to collections immediately."
            )

        # Check for high usage-drop accounts
        high_drop = [
            r for r in risk_items
            if (r.get("signals", {}).get("usage_drop", {}) or {}).get("usage_drop_percent", 0) > 40
        ]
        if high_drop:
            recommendations.append(
                f"Schedule proactive check-in calls for {len(high_drop)} account(s) "
                "showing >40% usage decline."
            )

        # Check for expiring contracts
        expiring = [
            r for r in risk_items
            if (r.get("signals", {}).get("contract_ending", {}) or {}).get("ending_soon")
        ]
        if expiring:
            recommendations.append(
                f"Initiate renewal conversations for {len(expiring)} account(s) "
                "with contracts expiring within 90 days."
            )

        if not recommendations:
            recommendations.append("No immediate critical actions identified. Continue monitoring.")

        return recommendations

    def _summarize_log(self) -> Dict[str, Any]:
        """Return a lightweight summary of the entire audit trail."""
        return {
            "total_entries": len(self.audit_log),
            "latest_entry": self.audit_log[-1]["audit_id"] if self.audit_log else None,
        }
