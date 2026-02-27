// frontend/src/components/Dashboard.jsx
import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const fmt = (n) =>
  typeof n === 'number' ? n.toLocaleString('en-US', { maximumFractionDigits: 0 }) : n;

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [pendingApprovals, setPendingApprovals] = useState([]);
  const [loading, setLoading] = useState(false);
  // FIX: track errors so users see actionable feedback instead of silent failures
  const [error, setError] = useState(null);

  const fetchMetrics = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_BASE}/metrics`);
      setMetrics(data);
    } catch (err) {
      console.error('Error fetching metrics:', err);
    }
  }, []);

  const fetchPendingApprovals = useCallback(async () => {
    try {
      const { data } = await axios.get(`${API_BASE}/pending-approvals`);
      setPendingApprovals(data.pending ?? []);
    } catch (err) {
      console.error('Error fetching approvals:', err);
    }
  }, []);

  // Poll for updates every 15 s so new approvals surface automatically
  useEffect(() => {
    fetchMetrics();
    fetchPendingApprovals();
    const id = setInterval(() => {
      fetchMetrics();
      fetchPendingApprovals();
    }, 15_000);
    return () => clearInterval(id);
  }, [fetchMetrics, fetchPendingApprovals]);

  const analyzeAccounts = async () => {
    setLoading(true);
    setError(null);
    try {
      // FIX: contract_end dates updated to 2026+ to match realistic mock data
      const sampleAccounts = [
        { id: 'acc1', name: 'Acme Corp',        contract_end: '2026-06-30', annual_value: 120_000 },
        { id: 'acc2', name: 'TechStart Inc',    contract_end: '2026-04-15', annual_value:  75_000 },
        { id: 'acc3', name: 'Global Solutions', contract_end: '2026-03-20', annual_value: 250_000 },
      ];

      const { data } = await axios.post(`${API_BASE}/analyze`, { accounts: sampleAccounts });

      // FIX: guard against undefined nested path before accessing .total_risk_identified
      const risksFound = data?.data?.metrics?.total_risk_identified ?? 'some';
      alert(`Analysis complete! Found ${risksFound} risk signal(s).`);
      fetchMetrics();
      fetchPendingApprovals();
    } catch (err) {
      setError('Analysis failed. Please check the backend is running and try again.');
      console.error('Error analyzing:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleApproval = async (accountId, approved) => {
    try {
      await axios.post(`${API_BASE}/approve-strategy`, {
        // FIX: field renamed account_id to match the updated API model
        account_id: accountId,
        approved,
        notes: approved ? 'Approved by operator' : 'Rejected – manual review required',
      });
      fetchPendingApprovals();
      fetchMetrics();
    } catch (err) {
      console.error('Error processing approval:', err);
      alert('Failed to process approval. Please try again.');
    }
  };

  return (
    <div className="dashboard" style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <h1>RevenuePilot Dashboard</h1>

      {error && (
        <div style={{ background: '#fee', color: '#c00', padding: 12, borderRadius: 6, marginBottom: 16 }}>
          {error}
        </div>
      )}

      <div className="metrics-grid" style={{ display: 'flex', gap: 16, marginBottom: 24 }}>
        {metrics ? (
          <>
            <MetricCard
              title="Est. Recovery"
              value={`$${fmt(metrics.estimated_recovery)}`}
              subtitle="Cumulative across all runs"
            />
            <MetricCard
              title="Risk Signals"
              value={fmt(metrics.total_risk_identified)}
              subtitle="Accounts flagged"
            />
            <MetricCard
              title="Time Saved"
              value={`${fmt(metrics.human_time_saved_hours)}h`}
              subtitle="Analyst hours saved"
            />
            <MetricCard
              title="Strategies Run"
              value={fmt(metrics.strategies_executed)}
              subtitle="Auto-executed"
            />
          </>
        ) : (
          <p style={{ color: '#888' }}>Loading metrics…</p>
        )}
      </div>

      <button
        onClick={analyzeAccounts}
        disabled={loading}
        style={{
          padding: '10px 24px',
          background: loading ? '#aaa' : '#1d4ed8',
          color: '#fff',
          border: 'none',
          borderRadius: 6,
          cursor: loading ? 'not-allowed' : 'pointer',
          marginBottom: 32,
        }}
      >
        {loading ? 'Analysing…' : 'Run Revenue Analysis'}
      </button>

      {pendingApprovals.length > 0 && (
        <section>
          <h2>Pending Approvals ({pendingApprovals.length})</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {pendingApprovals.map((strategy) => (
              <ApprovalCard
                key={strategy.account_id}
                strategy={strategy}
                onApprove={() => handleApproval(strategy.account_id, true)}
                onReject={() => handleApproval(strategy.account_id, false)}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function MetricCard({ title, value, subtitle }) {
  return (
    <div
      style={{
        flex: 1,
        background: '#f8fafc',
        border: '1px solid #e2e8f0',
        borderRadius: 8,
        padding: '16px 20px',
      }}
    >
      <div style={{ fontSize: 13, color: '#64748b', marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: '#0f172a' }}>{value}</div>
      <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>{subtitle}</div>
    </div>
  );
}

function ApprovalCard({ strategy, onApprove, onReject }) {
  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e2e8f0',
        borderRadius: 8,
        padding: 16,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}
    >
      <div>
        <strong>{strategy.account_name}</strong>
        <div style={{ fontSize: 13, color: '#64748b', marginTop: 4 }}>
          Risk: <span style={{ fontWeight: 600 }}>{strategy.risk_level}</span>
          &nbsp;·&nbsp;Est. Recovery:{' '}
          <span style={{ fontWeight: 600 }}>${fmt(strategy.estimated_recovery)}</span>
          &nbsp;·&nbsp;Timeline: {strategy.timeline_days}d
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={onApprove}
          style={{
            padding: '8px 16px',
            background: '#16a34a',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
          }}
        >
          Approve
        </button>
        <button
          onClick={onReject}
          style={{
            padding: '8px 16px',
            background: '#dc2626',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
          }}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

export default Dashboard;
