"""
agents/orchestrator.py
Core orchestration layer for RevenuePilot multi-agent system.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


class AgentType(Enum):
    # FIX: Added ORCHESTRATOR which was missing, causing AttributeError in _dispatch_agent
    ORCHESTRATOR = "orchestrator"
    DATA = "data"
    RISK = "risk"
    STRATEGY = "strategy"
    EXECUTION = "execution"
    AUDIT = "audit"


@dataclass
class AgentMessage:
    sender: AgentType
    receiver: AgentType
    content: Dict[str, Any]
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)


class RevenuePilotOrchestrator:
    """Main orchestration layer coordinating all specialized agents."""

    def __init__(self):
        self.agents: Dict[AgentType, Any] = {}
        # FIX: message_queue is only meaningful inside a running event loop.
        # Defer creation to first use via property to avoid issues when
        # instantiated at module import time (before an event loop exists).
        self._message_queue: Optional[asyncio.Queue] = None
        self.active_tasks: Dict[str, Any] = {}
        self.system_memory: Dict[str, Any] = {}

    @property
    def message_queue(self) -> asyncio.Queue:
        if self._message_queue is None:
            self._message_queue = asyncio.Queue()
        return self._message_queue

    def register_agent(self, agent_type: AgentType, agent_instance) -> None:
        self.agents[agent_type] = agent_instance
        logger.info("Registered agent: %s", agent_type.value)

    async def process_revenue_signals(self, accounts: List[Dict]) -> Dict[str, Any]:
        """
        Main entry point – processes accounts for revenue risks.

        Pipeline:
          DataAgent → RiskAgent → StrategyAgent → ExecutionAgent → AuditAgent
        """
        if not accounts:
            return {"error": "No accounts provided", "metrics": {}}

        # Step 1: DataAgent – fetch structured risk signals
        data_results: List[Dict] = await self._dispatch_agent(
            AgentType.DATA,
            {"accounts": accounts, "action": "fetch_risk_signals"},
        )

        # Step 2: RiskAgent – evaluate each account
        risk_results: List[Dict] = await self._dispatch_agent(
            AgentType.RISK,
            {"data": data_results, "action": "assess_risk"},
        )

        # Step 3: StrategyAgent – only act on high-risk accounts
        high_risk = [r for r in risk_results if r.get("risk_score", 0) > 0.7]
        strategies: List[Dict] = []
        if high_risk:
            strategies = await self._dispatch_agent(
                AgentType.STRATEGY,
                {"accounts": high_risk, "action": "create_strategies"},
            )

        # Step 4: ExecutionAgent – execute approved strategies
        execution_results: Dict = await self._dispatch_agent(
            AgentType.EXECUTION,
            {"strategies": strategies, "action": "execute_outreach"},
        )

        # Step 5: AuditAgent – track everything
        audit_log: Dict = await self._dispatch_agent(
            AgentType.AUDIT,
            {
                "data": data_results,
                "risk": risk_results,
                "strategies": strategies,
                "execution": execution_results,
            },
        )

        # Store in system memory for later retrieval
        run_id = str(uuid.uuid4())
        self.system_memory[run_id] = {
            "timestamp": datetime.utcnow().isoformat(),
            "accounts_analyzed": len(accounts),
            "audit": audit_log,
        }

        return audit_log

    async def _dispatch_agent(self, agent_type: AgentType, payload: Dict) -> Any:
        """Dispatch task to a specific agent and await its response."""
        agent = self.agents.get(agent_type)
        if agent is None:
            raise ValueError(
                f"Agent '{agent_type.value}' is not registered. "
                f"Registered agents: {[a.value for a in self.agents]}"
            )

        task_id = str(uuid.uuid4())
        message = AgentMessage(
            sender=AgentType.ORCHESTRATOR,
            receiver=agent_type,
            content=payload,
            task_id=task_id,
        )

        # Put on queue for observability / future async routing
        await self.message_queue.put(message)
        self.active_tasks[task_id] = {"status": "processing", "agent": agent_type.value}

        try:
            result = await agent.process(message)
            self.active_tasks[task_id]["status"] = "completed"
            return result
        except Exception as exc:
            self.active_tasks[task_id]["status"] = "failed"
            logger.exception("Agent %s failed on task %s: %s", agent_type.value, task_id, exc)
            raise
