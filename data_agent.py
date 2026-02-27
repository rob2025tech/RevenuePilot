"""
agents/data_agent.py
Queries structured financial data and surfaces revenue risk signals.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent


class DataAgent(BaseAgent):
    """Queries structured data for revenue risk signals."""

    def __init__(self, snowflake_connector=None):
        super().__init__("data")
        self.db_connector = snowflake_connector

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def process(self, message) -> List[Dict[str, Any]]:
        action = message.content.get("action")

        if action == "fetch_risk_signals":
            return await self._fetch_risk_signals(message.content.get("accounts", []))
        if action == "get_account_details":
            return await self._get_account_details(message.content.get("account_ids", []))

        self.logger.warning("Unknown action '%s' received by DataAgent", action)
        return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _fetch_risk_signals(self, accounts: List[Dict]) -> List[Dict[str, Any]]:
        """Query for overdue invoices, churn signals, etc."""
        risk_signals: List[Dict[str, Any]] = []

        for account in accounts:
            # FIX: original code silently used account["id"] which would KeyError
            # if the key is missing. Use .get() with a fallback.
            account_id = account.get("id") or account.get("account_id", "unknown")
            signal: Dict[str, Any] = {
                "account_id": account_id,
                "account_name": account.get("name", "Unknown"),
                "overdue_invoices": await self._check_overdue_invoices(account),
                "usage_drop": await self._check_usage_patterns(account),
                "contract_end_date": account.get("contract_end"),
                "payment_delays": await self._check_payment_history(account),
                "annual_value": account.get("annual_value", 0),
            }
            risk_signals.append(signal)

        await self.log_action("fetch_risk_signals", {"count": len(risk_signals)})
        return risk_signals

    async def _get_account_details(self, account_ids: List[str]) -> List[Dict[str, Any]]:
        """Retrieve detailed account info by ID list."""
        # In production: execute a parameterised Snowflake query
        self.logger.info("Fetching details for %d accounts", len(account_ids))
        return []

    async def _check_overdue_invoices(self, account: Dict) -> Dict[str, Any]:
        """
        Check for invoices past their due date.

        Production path: SELECT … FROM invoices WHERE account_id = %s AND due_date < NOW()
        """
        # Use embedded mock data if provided (e.g. from mock_data.py), else defaults
        return account.get(
            "overdue_invoices",
            {
                "has_overdue": False,
                "amount": 0,
                "days_overdue": 0,
                "invoice_ids": [],
            },
        )

    async def _check_usage_patterns(self, account: Dict) -> Dict[str, Any]:
        """Detect significant drops in product usage."""
        return account.get(
            "usage_drop",
            {
                "usage_drop_percent": 0,
                "period": "last_30_days",
                "previous_period": "previous_30_days",
            },
        )

    async def _check_payment_history(self, account: Dict) -> Dict[str, Any]:
        """Analyse historical payment behaviour."""
        # Production: query payment_events table
        return {"late_payments_last_6m": 0, "average_days_late": 0}
