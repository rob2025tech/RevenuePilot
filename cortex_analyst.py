"""
cortex_analyst.py
=================

Thin, synchronous Snowflake Cortex Analyst data layer for RevenuePilot.

Responsibilities (intentionally narrow):
  1. Establish / use a Snowflake connection (snowflake.connector).
  2. Call the Cortex Analyst REST API to turn a natural-language question
     into SQL, using a staged semantic-model file.
  3. Execute that generated SQL through the same Snowflake connection.
  4. Normalize the returned rows into the EXACT data contract already
     consumed by agents/data_agent.py → agents/risk_agent.py.

Design constraints honoured here:
  * No framework, no class hierarchy, no async — a single small client.
  * ``snowflake.connector`` and ``httpx`` are imported lazily so that merely
    importing this module NEVER requires live credentials or the connector to
    be installed. This keeps the deterministic mock pipeline importable.
  * Secrets/tokens are never logged.

Reference pattern (LOCAL connector + REST only) adapted from:
  ~/Projects/Snowflake/sfguide-getting-started-with-cortex-analyst/
      cortex_analyst_streaming_demo.py
The Streamlit UI, SSE streaming, feedback, Cortex Search and verified-query
infrastructure from that demo are deliberately NOT used.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from config import Config

logger = logging.getLogger("revenue_pilot.cortex_analyst")

# Cortex Analyst REST endpoint (v2). Non-streaming: we POST once and read JSON.
CORTEX_ANALYST_PATH = "/api/v2/cortex/analyst/message"

# Default natural-language question. Maps 1:1 onto the fields declared in
# semantic_model/revenue_risk.yaml so Cortex Analyst can emit a simple SELECT.
# Override via CORTEX_ANALYST_QUESTION if the semantic model differs.
DEFAULT_QUESTION = (
    "For each account, return account_id, account_name, annual_value, "
    "contract_end_date, has_overdue, overdue_amount, days_overdue, "
    "usage_drop_percent, late_payments_last_6m, and average_days_late."
)


class CortexAnalystError(RuntimeError):
    """Raised when a live Cortex Analyst request or SQL execution fails."""


# ---------------------------------------------------------------------------
# Column aliases → normalized contract keys.
# Keeps the adapter tolerant of casing / naming drift without inventing a
# second account schema: everything collapses into the existing RiskAgent
# input contract.
# ---------------------------------------------------------------------------
_ALIASES: Dict[str, Tuple[str, ...]] = {
    "account_id": ("account_id", "account", "id", "account_key", "customer_id"),
    "account_name": ("account_name", "name", "customer_name"),
    "annual_value": ("annual_value", "arr", "annual_contract_value", "acv"),
    "contract_end_date": ("contract_end_date", "contract_end", "contract_end_dt"),
    "has_overdue": ("has_overdue", "has_overdue_invoices", "is_overdue"),
    "overdue_amount": ("overdue_amount", "amount_overdue", "overdue_balance", "amount"),
    "days_overdue": ("days_overdue", "max_days_overdue", "days_past_due"),
    "usage_drop_percent": ("usage_drop_percent", "usage_drop", "usage_decline_percent"),
    "late_payments_last_6m": ("late_payments_last_6m", "late_payments", "late_payment_count"),
    "average_days_late": ("average_days_late", "avg_days_late"),
    "invoice_ids": ("invoice_ids", "invoices"),
}


class CortexAnalystClient:
    """Minimal synchronous client for the Cortex Analyst → SQL → rows flow."""

    def __init__(
        self,
        account: str,
        user: str,
        password: str,
        database: str,
        schema: str,
        stage: str,
        semantic_model_file: str,
        warehouse: str = "",
        role: str = "",
        question: str = "",
        timeout: float = 60.0,
    ) -> None:
        self.account = account
        self.user = user
        self.password = password
        self.database = database
        self.schema = schema
        self.stage = stage
        self.semantic_model_file = semantic_model_file
        self.warehouse = warehouse
        self.role = role
        self.question = question or DEFAULT_QUESTION
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Construction / configuration gating
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: Any = Config) -> Optional["CortexAnalystClient"]:
        """
        Build a client from environment-driven config.

        Returns ``None`` when the required configuration is absent, so callers
        can transparently fall back to the deterministic mock-data path.
        Never raises for missing config.
        """
        account = getattr(config, "SNOWFLAKE_ACCOUNT", "") or ""
        user = getattr(config, "SNOWFLAKE_USER", "") or ""
        password = getattr(config, "SNOWFLAKE_PASSWORD", "") or ""
        database = getattr(config, "SNOWFLAKE_DATABASE", "") or ""
        schema = getattr(config, "SNOWFLAKE_SCHEMA", "") or ""
        stage = getattr(config, "SNOWFLAKE_STAGE", "") or ""
        model_file = getattr(config, "CORTEX_SEMANTIC_MODEL_FILE", "") or ""

        client = cls(
            account=account,
            user=user,
            password=password,
            database=database,
            schema=schema,
            stage=stage,
            semantic_model_file=model_file,
            warehouse=getattr(config, "SNOWFLAKE_WAREHOUSE", "") or "",
            role=getattr(config, "SNOWFLAKE_ROLE", "") or "",
            question=getattr(config, "CORTEX_ANALYST_QUESTION", "") or "",
        )
        return client if client.is_configured else None

    @property
    def is_configured(self) -> bool:
        """True only when every value needed for a live request is present."""
        return bool(
            self.account
            and self.user
            and self.password
            and self.database
            and self.schema
            and self.stage
            and self.semantic_model_file
        )

    @property
    def staged_semantic_model_path(self) -> str:
        """Fully-qualified staged semantic-model reference for the REST body."""
        return f"@{self.database}.{self.schema}.{self.stage}/{self.semantic_model_file}"

    # ------------------------------------------------------------------
    # Snowflake connection (lazy import so module import never fails)
    # ------------------------------------------------------------------

    def _connect(self):
        try:
            import snowflake.connector  # imported lazily on purpose
        except ImportError as exc:  # pragma: no cover - env dependent
            raise CortexAnalystError(
                "snowflake-connector-python is not installed; add it to "
                "requirements.txt to use the live Cortex Analyst path."
            ) from exc

        kwargs: Dict[str, Any] = {
            "account": self.account,
            "user": self.user,
            "password": self.password,
        }
        if self.warehouse:
            kwargs["warehouse"] = self.warehouse
        if self.database:
            kwargs["database"] = self.database
        if self.schema:
            kwargs["schema"] = self.schema
        if self.role:
            kwargs["role"] = self.role
        # NOTE: never log kwargs — they contain the password.
        return snowflake.connector.connect(**kwargs)

    # ------------------------------------------------------------------
    # Cortex Analyst REST call → generated SQL
    # ------------------------------------------------------------------

    def _generate_sql(self, conn, question: str) -> str:
        import httpx  # already a project dependency; avoids adding `requests`

        url = f"https://{conn.host}{CORTEX_ANALYST_PATH}"
        body = {
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": question}]}
            ],
            "semantic_model_file": self.staged_semantic_model_path,
        }
        headers = {
            # Token comes from the live connection; never logged.
            "Authorization": f'Snowflake Token="{conn.rest.token}"',
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        resp = httpx.post(url, json=body, headers=headers, timeout=self.timeout)
        if resp.status_code >= 400:
            # Do not echo resp.text: keep failure output free of payloads.
            raise CortexAnalystError(
                f"Cortex Analyst request failed with HTTP {resp.status_code}"
            )

        sql = self._extract_sql(resp.json())
        if not sql:
            raise CortexAnalystError(
                "Cortex Analyst response contained no SQL statement"
            )
        return sql

    @staticmethod
    def _extract_sql(payload: Dict[str, Any]) -> str:
        """Pull the first `sql` content block out of a non-streaming response."""
        message = payload.get("message") or {}
        content = message.get("content")
        if content is None:
            content = payload.get("content")
        if not isinstance(content, list):
            return ""
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "sql":
                statement = block.get("statement") or block.get("sql") or ""
                if statement:
                    return statement.strip()
        return ""

    # ------------------------------------------------------------------
    # SQL execution
    # ------------------------------------------------------------------

    def _run_sql(self, conn, sql: str) -> List[Dict[str, Any]]:
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Public flow: question → SQL → rows → normalized risk signals
    # ------------------------------------------------------------------

    def fetch_rows(self, question: Optional[str] = None) -> Tuple[List[Dict[str, Any]], str]:
        """Run the full live flow once; returns (raw_rows, generated_sql)."""
        q = question or self.question
        conn = self._connect()
        try:
            sql = self._generate_sql(conn, q)
            logger.info(
                "Cortex Analyst generated SQL for semantic model %s",
                self.staged_semantic_model_path,
            )
            logger.debug("Generated SQL: %s", sql)
            rows = self._run_sql(conn, sql)
            return rows, sql
        finally:
            try:
                conn.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass

    def fetch_risk_signals(
        self, accounts: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Return rows normalized into the DataAgent/RiskAgent contract.

        If `accounts` carries explicit ids and the warehouse rows include them,
        the result is filtered to those ids; otherwise all rows are returned
        (we never silently drop live data down to nothing).
        """
        rows, _sql = self.fetch_rows()
        signals = [normalize_row(row) for row in rows]

        requested_ids = _requested_account_ids(accounts)
        if requested_ids:
            matched = [s for s in signals if s["account_id"] in requested_ids]
            if matched:
                return matched

        return signals


# ---------------------------------------------------------------------------
# Normalization helpers — adapt Cortex rows into the existing contract.
# ---------------------------------------------------------------------------

def _lower_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k).lower(): v for k, v in row.items()}


def _pick(lower_row: Dict[str, Any], key: str) -> Any:
    for alias in _ALIASES.get(key, (key,)):
        if alias in lower_row and lower_row[alias] is not None:
            return lower_row[alias]
    return None


def _to_number(value: Any, default: float = 0.0) -> float:
    """Cast Snowflake numerics (incl. Decimal) to float for downstream math."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    return int(round(_to_number(value, float(default))))


def _to_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return _to_number(value) != 0
    text = str(value).strip().lower()
    if text in ("true", "t", "yes", "y", "1"):
        return True
    if text in ("false", "f", "no", "n", "0"):
        return False
    return None


def _to_date_str(value: Any) -> Optional[str]:
    """RiskAgent parses contract_end_date with strptime('%Y-%m-%d'), so it
    must be a string. Snowflake returns date/datetime objects — convert them."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def normalize_row(row: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    """
    Convert one Cortex Analyst row into the risk-signal dict produced by
    DataAgent._fetch_risk_signals and consumed by RiskAgent.
    """
    lr = _lower_row(row)

    account_id = _pick(lr, "account_id")
    account_id = str(account_id) if account_id is not None else f"account_{index}"

    overdue_amount = _to_number(_pick(lr, "overdue_amount"))
    days_overdue = _to_int(_pick(lr, "days_overdue"))

    has_overdue = _to_bool(_pick(lr, "has_overdue"))
    if has_overdue is None:
        # Infer when the model does not expose an explicit flag.
        has_overdue = overdue_amount > 0 or days_overdue > 0

    invoice_ids = _pick(lr, "invoice_ids") or []
    if isinstance(invoice_ids, str):
        invoice_ids = [invoice_ids] if invoice_ids else []

    return {
        "account_id": account_id,
        "account_name": _pick(lr, "account_name") or "Unknown",
        "annual_value": _to_number(_pick(lr, "annual_value")),
        "contract_end_date": _to_date_str(_pick(lr, "contract_end_date")),
        "overdue_invoices": {
            "has_overdue": has_overdue,
            "amount": overdue_amount,
            "days_overdue": days_overdue,
            "invoice_ids": invoice_ids,
        },
        "usage_drop": {
            "usage_drop_percent": _to_number(_pick(lr, "usage_drop_percent")),
            "period": "last_30_days",
            "previous_period": "previous_30_days",
        },
        "payment_delays": {
            "late_payments_last_6m": _to_int(_pick(lr, "late_payments_last_6m")),
            "average_days_late": _to_int(_pick(lr, "average_days_late")),
        },
    }


def _requested_account_ids(accounts: Optional[List[Dict[str, Any]]]) -> set:
    ids = set()
    for acct in accounts or []:
        if not isinstance(acct, dict):
            continue
        value = acct.get("id") or acct.get("account_id")
        if value is not None:
            ids.add(str(value))
    return ids
