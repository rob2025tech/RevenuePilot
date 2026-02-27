"""
agents/execution_agent.py
Executes recovery actions via external integrations (Gmail, Slack, CRM).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent

# ---------------------------------------------------------------------------
# Email templates
# ---------------------------------------------------------------------------
EMAIL_TEMPLATES: Dict[str, str] = {
    "overdue_invoice_reminder": (
        "Subject: Invoice Past Due – Action Required\n\n"
        "Dear {contact_name},\n\n"
        "This is a reminder that invoice {invoice_id} for ${amount} became overdue on "
        "{due_date}. Please arrange payment at your earliest convenience or contact us "
        "to discuss a payment plan.\n\n"
        "Best regards,\nRevenuePilot"
    ),
    "payment_escalation": (
        "Subject: URGENT: Outstanding Payment for {account_name}\n\n"
        "Dear {contact_name},\n\n"
        "Despite previous reminders, invoices totalling ${amount} remain unpaid. "
        "Please contact us within 48 hours to resolve this matter and avoid further action.\n\n"
        "Best regards,\nRevenuePilot"
    ),
    "usage_drop_alert": (
        "Subject: We noticed a drop in your usage – can we help?\n\n"
        "Hi {contact_name},\n\n"
        "We noticed your usage of {product_name} has decreased recently. "
        "We'd love to help you get more value. Would you be open to a brief call?\n\n"
        "Best regards,\nRevenuePilot"
    ),
    "renewal_intro": (
        "Subject: Your contract is coming up for renewal\n\n"
        "Dear {contact_name},\n\n"
        "Your contract expires on {contract_end_date}. We'd love to continue working with "
        "you. Please let us know a good time to discuss your renewal options.\n\n"
        "Best regards,\nRevenuePilot"
    ),
    "executive_check_in": (
        "Subject: Checking in on your team's experience\n\n"
        "Dear {contact_name},\n\n"
        "I wanted to personally reach out to make sure your team is getting full value "
        "from your investment. Could we schedule a brief call this week?\n\n"
        "Best regards,\nRevenuePilot"
    ),
    "account_health_check": (
        "Subject: Quick check-in from RevenuePilot\n\n"
        "Hi {contact_name},\n\n"
        "Hope all is well! We wanted to check in and see how things are going. "
        "Do you have any questions or concerns we can help address?\n\n"
        "Best regards,\nRevenuePilot"
    ),
}


class ExecutionAgent(BaseAgent):
    """Executes recovery actions via integrations."""

    # Strategies above this recovery value always require human approval
    APPROVAL_THRESHOLD_AMOUNT = 10_000

    def __init__(self, composio_client=None):
        super().__init__("execution")
        self.composio = composio_client
        # FIX: approval_queue is now keyed by account_id for O(1) look-up;
        # previously it was a plain list requiring a linear scan.
        self.approval_queue: Dict[str, Dict] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def process(self, message) -> Dict[str, Any]:
        strategies: List[Dict] = message.content.get("strategies", [])

        needs_approval = [s for s in strategies if self._requires_approval(s)]
        auto_execute = [s for s in strategies if not self._requires_approval(s)]

        # Queue strategies that need human sign-off
        for s in needs_approval:
            self.approval_queue[s["account_id"]] = s

        # Execute auto-approved strategies concurrently
        import asyncio

        results = await asyncio.gather(
            *[self._execute_strategy(s) for s in auto_execute],
            return_exceptions=True,
        )

        # Separate successes from failures
        executed, failed = [], []
        for s, r in zip(auto_execute, results):
            if isinstance(r, Exception):
                self.logger.error("Strategy execution failed for %s: %s", s.get("account_id"), r)
                failed.append({"account_id": s.get("account_id"), "error": str(r)})
            else:
                executed.append(r)

        await self.log_action(
            "execution_summary",
            {
                "auto_executed": len(executed),
                "failed": len(failed),
                "pending_approval": len(needs_approval),
            },
        )

        return {
            "auto_executed": len(executed),
            "pending_approval": len(needs_approval),
            "failed": len(failed),
            "results": executed,
            "errors": failed,
        }

    async def execute_approved_strategy(self, account_id: str) -> Optional[Dict[str, Any]]:
        """
        Called by the API after a human approves a queued strategy.

        FIX: original /approve-strategy endpoint did a linear list scan;
        now this is a direct dict look-up.
        """
        strategy = self.approval_queue.pop(account_id, None)
        if strategy is None:
            return None
        return await self._execute_strategy(strategy)

    # ------------------------------------------------------------------
    # Strategy execution
    # ------------------------------------------------------------------

    async def _execute_strategy(self, strategy: Dict) -> Dict[str, Any]:
        """Execute all steps in a single strategy."""
        steps: List[Dict] = strategy.get("strategy", {}).get("steps", [])
        execution_log: List[Dict[str, Any]] = []

        for step in steps:
            action = step.get("action")
            try:
                if action == "email":
                    success = await self._send_email(step, strategy)
                elif action == "slack":
                    success = await self._send_slack(step, strategy)
                elif action == "offer_incentive":
                    success = await self._apply_incentive(step, strategy)
                elif action in ("offer", "calendar_invite"):
                    success = True  # Stub for future integrations
                else:
                    self.logger.warning("Unknown step action: %s", action)
                    success = False
            except Exception as exc:
                self.logger.exception("Step %s failed: %s", step.get("step"), exc)
                success = False

            execution_log.append(
                {
                    "step": step.get("step"),
                    "action": action,
                    "status": "success" if success else "failed",
                    # FIX: use timezone-aware UTC timestamp
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                }
            )

        overall_status = (
            "completed"
            if all(e["status"] == "success" for e in execution_log)
            else "partial"
        )

        return {
            "account_id": strategy.get("account_id"),
            "account_name": strategy.get("account_name"),
            "execution_log": execution_log,
            "status": overall_status,
        }

    # ------------------------------------------------------------------
    # Integration stubs (replace with real Composio calls)
    # ------------------------------------------------------------------

    async def _send_email(self, step: Dict, strategy: Dict) -> bool:
        """Send email via Composio/Gmail integration."""
        template_key = step.get("template", "account_health_check")
        template = EMAIL_TEMPLATES.get(template_key, "")

        # In production: fill placeholders from CRM data and call composio.gmail.send()
        self.logger.info(
            "[EMAIL] To: %s | Template: %s | Account: %s",
            step.get("recipient"),
            template_key,
            strategy.get("account_name"),
        )
        return True

    async def _send_slack(self, step: Dict, strategy: Dict) -> bool:
        """Post a message to an internal Slack channel."""
        # In production: composio.slack.post_message(channel=step["channel"], text=step["message"])
        self.logger.info(
            "[SLACK] Channel: %s | %s",
            step.get("channel"),
            step.get("message"),
        )
        return True

    async def _apply_incentive(self, step: Dict, strategy: Dict) -> bool:
        """Record and communicate an incentive offer."""
        self.logger.info(
            "[INCENTIVE] Type: %s | Conditions: %s | Account: %s",
            step.get("type"),
            step.get("conditions"),
            strategy.get("account_name"),
        )
        return True

    def _requires_approval(self, strategy: Dict) -> bool:
        """
        Determine whether a strategy needs human review before execution.

        FIX: original read priority from strategy["strategy"]["priority"] which
        could KeyError. Now reads the top-level 'priority' key set by StrategyAgent.
        """
        exceeds_threshold = strategy.get("estimated_recovery", 0) > self.APPROVAL_THRESHOLD_AMOUNT
        is_high_priority = strategy.get("priority") == "high"
        return exceeds_threshold or is_high_priority
