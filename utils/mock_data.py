"""
utils/mock_data.py
Realistic mock accounts for hackathon demo and local development.

FIX: contract_end dates updated to realistic future dates (relative to 2026).
     Added annual_value to all accounts for proper recovery estimation.
     Added payment_delays field consumed by DataAgent / RiskAgent.
"""

mock_accounts = [
    {
        "id": "acc_001",
        "name": "TechCorp Solutions",
        "contract_end": "2026-04-15",
        "annual_value": 150_000,
        "overdue_invoices": {
            "has_overdue": True,
            "amount": 45_000,
            "days_overdue": 52,
            "invoice_ids": ["INV-2026-001", "INV-2026-002"],
        },
        "usage_drop": {
            "usage_drop_percent": 65,
            "period": "last_30_days",
            "previous_period": "previous_30_days",
        },
        "payment_delays": {
            "late_payments_last_6m": 3,
            "average_days_late": 18,
        },
    },
    {
        "id": "acc_002",
        "name": "InnovateLabs",
        "contract_end": "2026-08-30",
        "annual_value": 75_000,
        "overdue_invoices": {
            "has_overdue": False,
            "amount": 0,
            "days_overdue": 0,
            "invoice_ids": [],
        },
        "usage_drop": {
            "usage_drop_percent": 20,
            "period": "last_30_days",
            "previous_period": "previous_30_days",
        },
        "payment_delays": {
            "late_payments_last_6m": 0,
            "average_days_late": 0,
        },
    },
    {
        "id": "acc_003",
        "name": "Global Dynamics",
        "contract_end": "2026-03-20",   # Expires soon
        "annual_value": 250_000,
        "overdue_invoices": {
            "has_overdue": True,
            "amount": 12_500,
            "days_overdue": 18,
            "invoice_ids": ["INV-2026-010"],
        },
        "usage_drop": {
            "usage_drop_percent": 10,
            "period": "last_30_days",
            "previous_period": "previous_30_days",
        },
        "payment_delays": {
            "late_payments_last_6m": 1,
            "average_days_late": 5,
        },
    },
]
