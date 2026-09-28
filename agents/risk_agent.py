"""
agents/risk_agent.py
Evaluates recovery probability and churn risk for each account.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from .base_agent import BaseAgent


class RiskAgent(BaseAgent):
    """Evaluates probability of recovery and churn risk."""

    HIGH_THRESHOLD = 0.7
    MEDIUM_THRESHOLD = 0.4

    def __init__(self):
        super().__init__("risk")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def process(self, message) -> List[Dict[str, Any]]:
        accounts_data: List[Dict] = message.content.get("data", [])
        results = await self._assess_risks(accounts_data)
        await self.log_action("risk_assessment", {"accounts_analyzed": len(results)})
        return results

    # ------------------------------------------------------------------
    # Risk assessment
    # ------------------------------------------------------------------

    async def _assess_risks(self, accounts_data: List[Dict]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        for account in accounts_data:
            risk_score = self._calculate_risk_score(account)
            recovery_prob = self._calculate_recovery_probability(account)

            results.append(
                {
                    "account_id": account.get("account_id"),
                    "account_name": account.get("account_name"),
                    "annual_value": account.get("annual_value", 0),
                    "risk_score": risk_score,
                    "risk_level": self._get_risk_level(risk_score),
                    "recovery_probability": recovery_prob,
                    # FIX: escalation threshold lowered to 0.85 to avoid
                    # over-escalating accounts that are merely "high" risk
                    "escalation_required": risk_score > 0.85,
                    "signals": {
                        "overdue": account.get("overdue_invoices"),
                        "usage_drop": account.get("usage_drop"),
                        "contract_ending": self._check_contract_end(account),
                        "payment_delays": account.get("payment_delays"),
                    },
                }
            )

        return results

    def _calculate_risk_score(self, account: Dict) -> float:
        """
        Heuristic risk scorer (replace with an ML model in production).

        Score components (all capped to prevent any single signal dominating):
          • Overdue invoices  – up to 0.40
          • Usage drop        – up to 0.30
          • Contract ending   – up to 0.20
          • Payment history   – up to 0.10
        """
        score = 0.0

        # Overdue invoices factor
        overdue = account.get("overdue_invoices", {})
        if overdue.get("has_overdue"):
            days = overdue.get("days_overdue", 0)
            score += min(0.40, days / 100)

        # Usage drop factor
        drop_percent = account.get("usage_drop", {}).get("usage_drop_percent", 0)
        score += min(0.30, drop_percent / 100)

        # Contract-ending factor
        # FIX: original code always added 0.2 regardless of actual proximity;
        # now we calculate real days remaining.
        days_until_end = self._days_until_contract_end(account.get("contract_end_date"))
        if days_until_end is not None:
            if days_until_end <= 0:
                score += 0.20          # Already expired
            elif days_until_end <= 30:
                score += 0.15
            elif days_until_end <= 90:
                score += 0.10
            elif days_until_end <= 180:
                score += 0.05

        # Payment history factor
        delays = account.get("payment_delays", {})
        late_count = delays.get("late_payments_last_6m", 0)
        score += min(0.10, late_count * 0.025)

        return round(min(1.0, score), 4)

    def _calculate_recovery_probability(self, account: Dict) -> float:
        """Estimate the likelihood of successful recovery."""
        prob = 0.65  # Slightly optimistic prior

        days_overdue = account.get("overdue_invoices", {}).get("days_overdue", 0)
        if days_overdue > 60:
            prob -= 0.20
        elif days_overdue > 30:
            prob -= 0.10

        drop_percent = account.get("usage_drop", {}).get("usage_drop_percent", 0)
        if drop_percent > 50:
            prob -= 0.15
        elif drop_percent > 25:
            prob -= 0.07

        late_count = account.get("payment_delays", {}).get("late_payments_last_6m", 0)
        prob -= late_count * 0.02

        return round(max(0.0, min(1.0, prob)), 4)

    def _get_risk_level(self, score: float) -> str:
        if score >= self.HIGH_THRESHOLD:
            return "HIGH"
        if score >= self.MEDIUM_THRESHOLD:
            return "MEDIUM"
        return "LOW"

    def _check_contract_end(self, account: Dict) -> Dict[str, Any]:
        days = self._days_until_contract_end(account.get("contract_end_date"))
        return {
            "contract_end_date": account.get("contract_end_date"),
            "days_until_end": days,
            "ending_soon": days is not None and 0 <= days <= 90,
        }

    @staticmethod
    def _days_until_contract_end(contract_end_str: str | None) -> int | None:
        """
        FIX: original code skipped actual date arithmetic.
        Returns None if no date provided, otherwise integer days remaining
        (negative means already expired).
        """
        if not contract_end_str:
            return None
        try:
            end_date = datetime.strptime(contract_end_str, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            now = datetime.now(tz=timezone.utc)
            return (end_date - now).days
        except ValueError:
            return None
