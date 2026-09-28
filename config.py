"""
config.py
Environment-based configuration for RevenuePilot.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # Snowflake
    SNOWFLAKE_ACCOUNT: str = os.getenv("SNOWFLAKE_ACCOUNT", "")
    SNOWFLAKE_USER: str = os.getenv("SNOWFLAKE_USER", "")
    SNOWFLAKE_PASSWORD: str = os.getenv("SNOWFLAKE_PASSWORD", "")
    SNOWFLAKE_WAREHOUSE: str = os.getenv("SNOWFLAKE_WAREHOUSE", "")
    SNOWFLAKE_DATABASE: str = os.getenv("SNOWFLAKE_DATABASE", "")
    SNOWFLAKE_SCHEMA: str = os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")
    SNOWFLAKE_ROLE: str = os.getenv("SNOWFLAKE_ROLE", "")

    # Cortex Analyst (staged semantic model). When STAGE + FILE are set (and
    # the connection values above are present), DataAgent attempts the live
    # Cortex Analyst path; otherwise it uses the deterministic mock data.
    SNOWFLAKE_STAGE: str = os.getenv("SNOWFLAKE_STAGE", "")
    CORTEX_SEMANTIC_MODEL_FILE: str = os.getenv("CORTEX_SEMANTIC_MODEL_FILE", "")
    CORTEX_ANALYST_QUESTION: str = os.getenv("CORTEX_ANALYST_QUESTION", "")

    # Composio
    COMPOSIO_API_KEY: str = os.getenv("COMPOSIO_API_KEY", "")

    # Application
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # Risk thresholds (overridable via env)
    APPROVAL_THRESHOLD_AMOUNT: float = float(os.getenv("APPROVAL_THRESHOLD_AMOUNT", "10000"))
    HIGH_RISK_SCORE_THRESHOLD: float = float(os.getenv("HIGH_RISK_SCORE_THRESHOLD", "0.7"))
