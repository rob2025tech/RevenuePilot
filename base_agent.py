"""
agents/base_agent.py
Abstract base class for all RevenuePilot specialized agents.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict


class BaseAgent(ABC):
    """Base class for all specialized agents."""

    def __init__(self, agent_type: str):
        self.agent_type = agent_type
        # FIX: use a per-agent logger name for easier log filtering
        self.logger = logging.getLogger(f"revenue_pilot.agent.{agent_type}")
        self.memory: Dict[str, Any] = {}

    @abstractmethod
    async def process(self, message: Any) -> Any:
        """Process an incoming AgentMessage and return a result."""

    async def log_action(self, action: str, details: Dict) -> Dict[str, Any]:
        """
        Produce a structured audit entry.

        FIX: original lacked the `datetime` import in this file and called
        datetime.now() which would raise NameError. Now uses utcnow() for
        timezone-safe timestamps.
        """
        log_entry: Dict[str, Any] = {
            "agent": self.agent_type,
            "action": action,
            "details": details,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        self.logger.debug("Action logged: %s | %s", action, details)
        return log_entry
