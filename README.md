# RevenuePilot

**Autonomous Multi-Agent Revenue Intelligence System**

RevenuePilot detects, prioritizes, and acts on at-risk revenue signals within enterprise data environments — replacing manual spreadsheet triage with a coordinated AI agent pipeline.

---

## Architecture

```
Accounts (CRM / Snowflake)
        │
        ▼
┌─────────────────────────────────────────────────────┐
│               RevenuePilotOrchestrator              │
│                                                     │
│  DataAgent → RiskAgent → StrategyAgent              │
│                              │                      │
│                     ExecutionAgent ←── Human HITL   │
│                              │                      │
│                         AuditAgent                  │
└─────────────────────────────────────────────────────┘
        │
        ▼
  FastAPI  ←→  React Dashboard
```

| Agent | Responsibility |
|---|---|
| **DataAgent** | Queries Snowflake for overdue invoices, usage drops, payment delays |
| **RiskAgent** | Scores each account 0–1 across four weighted signals |
| **StrategyAgent** | Selects and customises a multi-step recovery playbook |
| **ExecutionAgent** | Sends emails/Slack via Composio; queues high-value actions for human approval |
| **AuditAgent** | Tracks metrics, generates executive summaries, maintains explainability |

---

## Quickstart

### Prerequisites
- Python 3.11+
- Node.js 18+

### 1 – Backend

```bash
# Clone & enter project
git clone https://github.com/your-org/revenue-pilot.git
cd revenue-pilot

# Create virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your Snowflake / Composio credentials

# Start API server
uvicorn main:app --reload --port 8000
```

API docs available at **http://localhost:8000/docs**

### 2 – Frontend

```bash
cd frontend
npm install
npm start
```

Dashboard available at **http://localhost:3000**

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Service health check |
| `POST` | `/api/analyze` | Run full agent pipeline on a list of accounts |
| `GET` | `/api/pending-approvals` | Strategies awaiting human sign-off |
| `POST` | `/api/approve-strategy` | Approve or reject a pending strategy |
| `GET` | `/api/metrics` | Cumulative audit metrics |

### POST `/api/analyze` – example request

```json
{
  "accounts": [
    {
      "id": "acc_001",
      "name": "TechCorp Solutions",
      "contract_end": "2026-04-15",
      "annual_value": 150000
    }
  ]
}
```

### POST `/api/approve-strategy` – example request

```json
{
  "account_id": "acc_001",
  "approved": true,
  "notes": "Approved by VP Sales"
}
```

---

## Risk Scoring Model

The `RiskAgent` scores accounts on four weighted signals:

| Signal | Max contribution |
|---|---|
| Overdue invoices (days overdue / 100) | 0.40 |
| Usage drop (drop % / 100) | 0.30 |
| Contract proximity (30 / 90 / 180 day bands) | 0.20 |
| Payment history (late payments × 0.025) | 0.10 |

Scores ≥ 0.70 → **HIGH** · 0.40–0.69 → **MEDIUM** · < 0.40 → **LOW**

Strategies with estimated recovery > $10,000 or priority = `high` are routed to the human-in-the-loop approval queue before execution.

---

## Environment Variables

See [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Purpose |
|---|---|
| `SNOWFLAKE_ACCOUNT` | Snowflake account identifier |
| `COMPOSIO_API_KEY` | Composio key for Gmail / Slack / CRM |
| `APPROVAL_THRESHOLD_AMOUNT` | $ threshold for human approval (default 10000) |
| `HIGH_RISK_SCORE_THRESHOLD` | Risk score threshold for HIGH classification (default 0.7) |

---

## Tech Stack

**Backend:** Python · FastAPI · asyncio · Pydantic v2  
**Data:** Snowflake (integration-ready) · Pandas  
**Integrations:** Composio (Gmail · Slack · CRM)  
**Frontend:** React 18 · Axios  
**Hackathon sponsors:** CrewAI · Composio · Skyfire · Snowflake · Llama Lounge

---

## Project Structure

```
revenue_pilot/
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py      # Central coordination layer
│   ├── base_agent.py        # Abstract base with logging
│   ├── data_agent.py        # Snowflake queries & signal detection
│   ├── risk_agent.py        # 4-factor risk scoring
│   ├── strategy_agent.py    # Recovery playbook selection
│   ├── execution_agent.py   # Composio integrations & HITL queue
│   └── audit_agent.py       # Metrics, reporting, explainability
├── frontend/
│   ├── package.json
│   └── src/components/
│       └── Dashboard.jsx    # React operator dashboard
├── utils/
│   ├── __init__.py
│   └── mock_data.py         # Demo accounts for development
├── main.py                  # FastAPI application
├── config.py                # Environment config
├── requirements.txt
├── .env.example
└── README.md
```

---

multi-agent AI systems combining backend reliability with intuitive UX for enterprise decision-making
