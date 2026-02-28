# agents/orchestrator.py
"""
RevenuePilot + Shadow Operator — Integrated Orchestrator
=========================================================

Shadow Operator's GuardianAgent is inserted between StrategyAgent and
ExecutionAgent. Every proposed action is risk-scored before it touches
any external system. Nothing is sent without either:
  (a) a Guardian risk_score < 0.40  →  AUTO_EXECUTE
  (b) explicit human approval       →  HUMAN_APPROVED
  (c) neither                       →  held in guardian_queue

The rest of RevenuePilot is unchanged.
"""

from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
from datetime import datetime
import asyncio
import re
import logging

logger = logging.getLogger("revenuepilot.orchestrator")


# ─────────────────────────────────────────────────────────────
# ENUMS & MESSAGES (unchanged from original)
# ─────────────────────────────────────────────────────────────

class AgentType(Enum):
    DATA = "data"
    RISK = "risk"
    STRATEGY = "strategy"
    GUARDIAN = "guardian"       # NEW — Shadow Operator
    EXECUTION = "execution"
    AUDIT = "audit"
    ORCHESTRATOR = "orchestrator"


class GuardianVerdict(Enum):
    AUTO_EXECUTE = "AUTO_EXECUTE"
    HUMAN_APPROVAL_REQUIRED = "HUMAN_APPROVAL_REQUIRED"
    HOLD_FOR_REVIEW = "HOLD_FOR_REVIEW"


class AgentMessage:
    def __init__(self, sender: AgentType, receiver: AgentType,
                 content: Dict[str, Any], task_id: str):
        self.sender = sender
        self.receiver = receiver
        self.content = content
        self.task_id = task_id
        self.timestamp = datetime.now()


# ─────────────────────────────────────────────────────────────
# SHADOW OPERATOR — GUARDIAN RISK ENGINE
# Deterministic scorer: no LLM call required, fully testable.
# ─────────────────────────────────────────────────────────────

class GuardianAgent:
    """
    Shadow Operator's safety gate.
    Scores every proposed action and decides: auto-execute, hold for
    human approval, or block entirely.

    Plugs into RevenuePilot between StrategyAgent → ExecutionAgent.
    """

    # Risk thresholds
    AUTO_EXECUTE_THRESHOLD = 0.40
    HOLD_THRESHOLD = 0.70

    # Action type base risk scores
    ACTION_BASE_RISK = {
        "email":          0.30,   # External — reputational risk
        "slack":          0.10,   # Internal — minimal risk
        "crm_update":     0.20,   # Record mutation
        "escalation":     0.05,   # Internal routing only
        "offer_incentive":0.35,   # Financial commitment
        "offer":          0.35,   # Same as incentive
        "late_fee_waiver":0.40,   # Direct revenue impact
    }

    def score_action(
        self,
        action_step: Dict,
        strategy: Dict,
        account_risk: Dict,
    ) -> Tuple[float, List[str]]:
        """
        Score a single action step from a strategy.

        Args:
            action_step:  One step dict from strategy["strategy"]["steps"]
            strategy:     Full strategy dict from StrategyAgent
            account_risk: Risk assessment dict from RiskAgent

        Returns:
            (risk_score: float, risk_factors: List[str])
        """
        score = 0.0
        factors = []

        # 1. Action type base risk
        action_type = action_step.get("action", "email")
        base = self.ACTION_BASE_RISK.get(action_type, 0.25)
        score += base
        factors.append(f"Action type '{action_type}': +{base:.2f}")

        # 2. Tone escalation penalty (urgent / escalated emails are riskier)
        tone = action_step.get("tone", "")
        if tone in ("urgent", "escalated"):
            score += 0.15
            factors.append(f"Tone '{tone}': +0.15")

        # 3. Recovery value / financial impact
        recovery = strategy.get("estimated_recovery", 0)
        if recovery > 50_000:
            score += 0.30
            factors.append(f"High recovery value ${recovery:,.0f}: +0.30")
        elif recovery > 10_000:
            score += 0.15
            factors.append(f"Moderate recovery value ${recovery:,.0f}: +0.15")

        # 4. Account churn risk level — high-risk accounts need more care
        risk_level = account_risk.get("risk_level", "LOW")
        risk_bonus = {"LOW": 0.0, "MEDIUM": 0.05, "HIGH": 0.20}.get(risk_level, 0.0)
        if risk_bonus > 0:
            score += risk_bonus
            factors.append(f"Account risk level {risk_level}: +{risk_bonus:.2f}")

        # 5. Escalation required flag (from RiskAgent)
        if account_risk.get("escalation_required", False):
            score += 0.15
            factors.append("RiskAgent flagged escalation required: +0.15")

        # 6. Recovery probability — low confidence actions are riskier
        recovery_prob = account_risk.get("recovery_probability", 0.5)
        if recovery_prob < 0.3:
            score += 0.25
            factors.append(f"Low recovery probability {recovery_prob:.0%}: +0.25")
        elif recovery_prob < 0.5:
            score += 0.10
            factors.append(f"Moderate recovery probability {recovery_prob:.0%}: +0.10")

        # Cap at 1.0
        score = round(min(score, 1.0), 2)
        return score, factors

    def get_verdict(self, risk_score: float) -> GuardianVerdict:
        if risk_score < self.AUTO_EXECUTE_THRESHOLD:
            return GuardianVerdict.AUTO_EXECUTE
        elif risk_score < self.HOLD_THRESHOLD:
            return GuardianVerdict.HUMAN_APPROVAL_REQUIRED
        else:
            return GuardianVerdict.HOLD_FOR_REVIEW

    def evaluate_strategy(
        self,
        strategy: Dict,
        account_risk: Dict,
    ) -> Dict:
        """
        Evaluate all steps in a strategy and return a Guardian decision
        for the strategy as a whole.

        The strategy-level verdict is the WORST verdict across all steps
        (most conservative wins).
        """
        steps = strategy.get("strategy", {}).get("steps", [])
        step_decisions = []
        worst_score = 0.0

        for step in steps:
            score, factors = self.score_action(step, strategy, account_risk)
            verdict = self.get_verdict(score)
            step_decisions.append({
                "step": step.get("step"),
                "action": step.get("action"),
                "risk_score": score,
                "verdict": verdict.value,
                "risk_factors": factors,
            })
            if score > worst_score:
                worst_score = score

        overall_verdict = self.get_verdict(worst_score)

        return {
            "account_id": strategy["account_id"],
            "account_name": strategy["account_name"],
            "strategy_type": strategy.get("strategy", {}).get("type"),
            "estimated_recovery": strategy.get("estimated_recovery", 0),
            "overall_risk_score": round(worst_score, 2),
            "overall_verdict": overall_verdict.value,
            "step_decisions": step_decisions,
            "strategy": strategy,           # preserved for execution
            "account_risk": account_risk,   # preserved for audit
            "evaluated_at": datetime.now().isoformat(),
        }


# ─────────────────────────────────────────────────────────────
# MAIN ORCHESTRATOR
# ─────────────────────────────────────────────────────────────

class RevenuePilotOrchestrator:
    """
    Main orchestration layer coordinating all specialized agents.

    Pipeline:
        DataAgent → RiskAgent → StrategyAgent
            → GuardianAgent (Shadow Operator safety gate)
                → AUTO_EXECUTE  → ExecutionAgent
                → HUMAN_APPROVAL_REQUIRED → approval_queue (API polling)
                → HOLD_FOR_REVIEW → guardian_hold_queue (manual review)
            → AuditAgent
    """

    def __init__(self):
        self.agents: Dict[AgentType, Any] = {}
        self.message_queue = asyncio.Queue()
        self.active_tasks: Dict[str, Any] = {}
        self.system_memory: Dict[str, Any] = {}

        # Shadow Operator queues
        self.guardian_approval_queue: List[Dict] = []   # HUMAN_APPROVAL_REQUIRED
        self.guardian_hold_queue: List[Dict] = []        # HOLD_FOR_REVIEW

        # Guardian agent (stateless scorer — no LLM needed)
        self._guardian = GuardianAgent()

    def register_agent(self, agent_type: AgentType, agent_instance):
        self.agents[agent_type] = agent_instance

    # ── Main entry point ──────────────────────────────────────

    async def process_revenue_signals(self, accounts: List[Dict]) -> Dict:
        """
        Full pipeline: detect → assess → plan → guard → execute → audit.
        Returns the final audit report.
        """

        # Step 1: DataAgent — fetch risk signals
        logger.info("Step 1/5: DataAgent — fetching risk signals")
        data_task = await self._dispatch_agent(
            AgentType.DATA,
            {"accounts": accounts, "action": "fetch_risk_signals"}
        )

        # Step 2: RiskAgent — score every account
        logger.info("Step 2/5: RiskAgent — assessing account risk")
        risk_results: List[Dict] = await self._dispatch_agent(
            AgentType.RISK,
            {"data": data_task, "action": "assess_risk"}
        )

        # Build a lookup so Guardian can access risk data per account
        risk_by_account: Dict[str, Dict] = {
            r["account_id"]: r for r in risk_results
        }

        # Step 3: StrategyAgent — create recovery plans for high-risk accounts
        logger.info("Step 3/5: StrategyAgent — generating recovery strategies")
        high_risk_accounts = [r for r in risk_results if r["risk_score"] > 0.7]
        strategies: List[Dict] = await self._dispatch_agent(
            AgentType.STRATEGY,
            {"accounts": high_risk_accounts, "action": "create_strategies"}
        )

        # Step 4: GuardianAgent (Shadow Operator) — gate every action
        logger.info("Step 4/5: GuardianAgent — risk-scoring all actions")
        auto_execute_strategies, guardian_summary = self._run_guardian(
            strategies, risk_by_account
        )

        # Step 5: ExecutionAgent — only receives Guardian-cleared strategies
        logger.info(
            "Step 5/5: ExecutionAgent — executing %d auto-approved strategies "
            "(%d pending human approval, %d held)",
            len(auto_execute_strategies),
            len(self.guardian_approval_queue),
            len(self.guardian_hold_queue),
        )
        execution_results = await self._dispatch_agent(
            AgentType.EXECUTION,
            {"strategies": auto_execute_strategies, "action": "execute_outreach"}
        )

        # Step 6: AuditAgent — full trace
        audit_log = await self._dispatch_agent(
            AgentType.AUDIT,
            {
                "data": data_task,
                "risk": risk_results,
                "strategies": strategies,
                "guardian": guardian_summary,
                "execution": execution_results,
            }
        )

        return audit_log

    # ── Guardian integration ──────────────────────────────────

    def _run_guardian(
        self,
        strategies: List[Dict],
        risk_by_account: Dict[str, Dict],
    ) -> Tuple[List[Dict], Dict]:
        """
        Run every strategy through GuardianAgent.
        Sorts strategies into three buckets and returns:
          - auto_execute_strategies (safe to send immediately)
          - summary dict (for audit trail)
        """
        auto_execute: List[Dict] = []
        approval_required: List[Dict] = []
        held: List[Dict] = []

        for strategy in strategies:
            account_id = strategy["account_id"]
            account_risk = risk_by_account.get(account_id, {})
            decision = self._guardian.evaluate_strategy(strategy, account_risk)

            verdict = decision["overall_verdict"]
            logger.info(
                "Guardian: %s → %s (risk=%.2f)",
                strategy["account_name"],
                verdict,
                decision["overall_risk_score"],
            )

            if verdict == GuardianVerdict.AUTO_EXECUTE.value:
                auto_execute.append(decision["strategy"])

            elif verdict == GuardianVerdict.HUMAN_APPROVAL_REQUIRED.value:
                self.guardian_approval_queue.append(decision)
                approval_required.append(decision)

            else:  # HOLD_FOR_REVIEW
                self.guardian_hold_queue.append(decision)
                held.append(decision)

        summary = {
            "evaluated": len(strategies),
            "auto_executed": len(auto_execute),
            "pending_human_approval": len(approval_required),
            "held_for_review": len(held),
            "approval_queue_snapshot": [
                {
                    "account_id": d["account_id"],
                    "account_name": d["account_name"],
                    "risk_score": d["overall_risk_score"],
                    "verdict": d["overall_verdict"],
                    "estimated_recovery": d["estimated_recovery"],
                }
                for d in approval_required + held
            ],
        }

        return auto_execute, summary

    async def approve_guardian_decision(
        self,
        account_id: str,
        approved: bool,
        approver_notes: str = "",
    ) -> Dict:
        """
        Human approves or rejects a Guardian-queued strategy.
        Called by the /api/approve-strategy endpoint.

        On approval: strategy is dispatched to ExecutionAgent immediately.
        On rejection: strategy is removed and logged.
        """
        # Search both queues
        target = None
        for queue in (self.guardian_approval_queue, self.guardian_hold_queue):
            for item in queue:
                if item["account_id"] == account_id:
                    target = item
                    queue.remove(item)
                    break
            if target:
                break

        if not target:
            return {"status": "not_found", "account_id": account_id}

        if approved:
            logger.info("Human approved: %s — executing now", account_id)
            execution_result = await self._dispatch_agent(
                AgentType.EXECUTION,
                {
                    "strategies": [target["strategy"]],
                    "action": "execute_outreach",
                }
            )
            return {
                "status": "executed",
                "account_id": account_id,
                "approved_by": "human",
                "approver_notes": approver_notes,
                "execution": execution_result,
                "guardian_risk_score": target["overall_risk_score"],
                "executed_at": datetime.now().isoformat(),
            }
        else:
            logger.info("Human rejected: %s", account_id)
            return {
                "status": "rejected",
                "account_id": account_id,
                "approver_notes": approver_notes,
                "guardian_risk_score": target["overall_risk_score"],
                "rejected_at": datetime.now().isoformat(),
            }

    def get_guardian_queue(self) -> Dict:
        """
        Returns the current approval queue — used by /api/pending-approvals.
        Replaces the old execution_agent.approval_queue.
        """
        return {
            "pending_approval": [
                {
                    "account_id": d["account_id"],
                    "account_name": d["account_name"],
                    "risk_score": d["overall_risk_score"],
                    "risk_level": d["account_risk"].get("risk_level"),
                    "estimated_recovery": d["estimated_recovery"],
                    "strategy_type": d["strategy_type"],
                    "step_decisions": d["step_decisions"],
                    "verdict": d["overall_verdict"],
                }
                for d in self.guardian_approval_queue
            ],
            "held_for_review": [
                {
                    "account_id": d["account_id"],
                    "account_name": d["account_name"],
                    "risk_score": d["overall_risk_score"],
                    "estimated_recovery": d["estimated_recovery"],
                    "verdict": d["overall_verdict"],
                }
                for d in self.guardian_hold_queue
            ],
        }

    # ── Internal dispatcher (unchanged from original) ─────────

    async def _dispatch_agent(self, agent_type: AgentType, payload: Dict) -> Any:
        """Dispatch task to specific agent and await response."""
        task_id = f"{agent_type.value}_{datetime.now().timestamp()}"

        message = AgentMessage(
            sender=AgentType.ORCHESTRATOR,
            receiver=agent_type,
            content=payload,
            task_id=task_id,
        )

        await self.message_queue.put(message)

        agent = self.agents.get(agent_type)
        if not agent:
            raise ValueError(f"Agent {agent_type} not registered")

        result = await agent.process(message)
        return result
