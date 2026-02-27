"""
agents/strategy_agent.py
Designs multi-step recovery workflows for at-risk accounts.
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Dict, List

from .base_agent import BaseAgent


class StrategyAgent(BaseAgent):
    """Designs multi-step recovery workflows."""

    def __init__(self):
        super().__init__("strategy")
        # FIX: typing was implicit; now explicit for clarity
        self.strategy_templates: Dict[
            str,
            Callable[[Dict], Coroutine[Any, Any, Dict]],
        ] = {
            "overdue_invoice": self._invoice_recovery_strategy,
            "usage_drop": self._reengagement_strategy,
            "contract_renewal": self._renewal_strategy,
        }

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def process(self, message) -> List[Dict[str, Any]]:
        accounts: List[Dict] = message.content.get("accounts", [])
        strategies = await self._create_strategies(accounts)
        await self.log_action("strategies_created", {"count": len(strategies)})
        return strategies

    # ------------------------------------------------------------------
    # Strategy creation
    # ------------------------------------------------------------------

    async def _create_strategies(self, accounts: List[Dict]) -> List[Dict[str, Any]]:
        strategies: List[Dict[str, Any]] = []

        for account in accounts:
            primary_signal = self._identify_primary_signal(account)
            template = self.strategy_templates.get(primary_signal)

            if template:
                strategy = await template(account)
            else:
                strategy = await self._default_strategy(account)

            estimated_recovery = self._estimate_recovery_value(account)

            strategies.append(
                {
                    "account_id": account.get("account_id"),
                    "account_name": account.get("account_name"),
                    "risk_level": account.get("risk_level"),
                    "primary_signal": primary_signal,
                    "strategy": strategy,
                    "estimated_recovery": estimated_recovery,
                    "timeline_days": strategy.get("estimated_days", 7),
                    # FIX: expose priority at the top level so ExecutionAgent
                    # can read it without digging into nested 'strategy' dict
                    "priority": strategy.get("priority", "medium"),
                }
            )

        return strategies

    def _identify_primary_signal(self, account: Dict) -> str:
        """Determine the dominant risk driver for this account."""
        signals = account.get("signals", {})

        overdue = signals.get("overdue", {}) or account.get("overdue_invoices", {})
        usage = signals.get("usage_drop", {}) or account.get("usage_drop", {})
        contract = signals.get("contract_ending", {})

        if overdue.get("has_overdue") and overdue.get("days_overdue", 0) > 0:
            return "overdue_invoice"
        if usage.get("usage_drop_percent", 0) > 20:
            return "usage_drop"
        if contract.get("ending_soon"):
            return "contract_renewal"
        return "default"

    # ------------------------------------------------------------------
    # Individual strategy templates
    # ------------------------------------------------------------------

    async def _invoice_recovery_strategy(self, account: Dict) -> Dict[str, Any]:
        """Multi-step strategy for overdue invoice recovery."""
        signals = account.get("signals", {})
        overdue = signals.get("overdue", {}) or account.get("overdue_invoices", {})
        days_overdue = overdue.get("days_overdue", 0)

        tone = "friendly_reminder" if days_overdue < 30 else "urgent"
        escalation_delay = "+3_days" if days_overdue < 30 else "+1_day"

        steps: List[Dict[str, Any]] = [
            {
                "step": 1,
                "action": "email",
                "recipient": "finance_contact",
                "tone": tone,
                "timing": "immediate",
                "template": "overdue_invoice_reminder",
            },
        ]

        # Add late-fee waiver incentive for significantly overdue accounts
        if days_overdue > 45:
            steps.append(
                {
                    "step": 2,
                    "action": "offer_incentive",
                    "type": "late_fee_waiver",
                    "conditions": "Payment within 5 business days",
                    "timing": "after_step_1",
                }
            )

        steps.extend(
            [
                {
                    "step": len(steps) + 1,
                    "action": "email",
                    "recipient": "executive_sponsor",
                    "tone": "escalated",
                    "timing": escalation_delay,
                    "template": "payment_escalation",
                },
                {
                    "step": len(steps) + 2,
                    "action": "slack",
                    "channel": "internal-finance",
                    "message": "Consider escalating to collections if no response within 48h.",
                    "timing": "+7_days",
                },
            ]
        )

        return {
            "type": "invoice_recovery",
            "steps": steps,
            "estimated_days": 3 if days_overdue >= 30 else 7,
            "priority": "high" if days_overdue > 45 else "medium",
        }

    async def _reengagement_strategy(self, account: Dict) -> Dict[str, Any]:
        """Strategy for accounts showing significant usage decline."""
        signals = account.get("signals", {})
        usage = signals.get("usage_drop", {}) or account.get("usage_drop", {})
        drop_percent = usage.get("usage_drop_percent", 0)

        return {
            "type": "reengagement",
            "steps": [
                {
                    "step": 1,
                    "action": "email",
                    "recipient": "power_user",
                    "template": "usage_drop_alert",
                    "timing": "immediate",
                },
                {
                    "step": 2,
                    "action": "offer",
                    "type": "training_session",
                    "value": "free_workshop",
                    "timing": "+2_days",
                },
                {
                    "step": 3,
                    "action": "email",
                    "recipient": "executive_sponsor",
                    "template": "executive_check_in",
                    "timing": "+7_days",
                },
            ],
            "estimated_days": 5,
            "priority": "high" if drop_percent > 50 else "medium",
        }

    async def _renewal_strategy(self, account: Dict) -> Dict[str, Any]:
        """Strategy for accounts approaching contract expiry."""
        return {
            "type": "contract_renewal",
            "steps": [
                {
                    "step": 1,
                    "action": "email",
                    "recipient": "executive_sponsor",
                    "template": "renewal_intro",
                    "timing": "immediate",
                },
                {
                    "step": 2,
                    "action": "calendar_invite",
                    "recipient": "executive_sponsor",
                    "subject": "Contract Renewal Discussion",
                    "timing": "+3_days",
                },
            ],
            "estimated_days": 14,
            "priority": "high",
        }

    async def _default_strategy(self, account: Dict) -> Dict[str, Any]:
        """Generic outreach for accounts without a dominant risk signal."""
        return {
            "type": "general_outreach",
            "steps": [
                {
                    "step": 1,
                    "action": "email",
                    "recipient": "primary_contact",
                    "template": "account_health_check",
                    "timing": "immediate",
                }
            ],
            "estimated_days": 7,
            "priority": "low",
        }

    def _estimate_recovery_value(self, account: Dict) -> float:
        """
        Estimate potential revenue recovery for this account.

        FIX: original hardcoded annual_value = 50000; now uses real data when
        available, falling back to a conservative default.
        """
        overdue_amount = (
            account.get("overdue_invoices", {}) or
            (account.get("signals", {}) or {}).get("overdue", {}) or {}
        ).get("amount", 0)

        annual_value = account.get("annual_value", 50_000)
        # Recovery value = whichever is larger: full overdue amount or 20% of ARR
        return round(max(float(overdue_amount), annual_value * 0.20), 2)
