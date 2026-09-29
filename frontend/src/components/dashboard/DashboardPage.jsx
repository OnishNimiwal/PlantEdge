import React, { useCallback, useEffect, useState } from 'react';
import {
  RefreshCw, Activity, CheckCircle2, XCircle, CalendarDays, Server, Cpu, ScanText, AlertTriangle,
} from 'lucide-react';
import { getUsage, getSystemStatus } from '../../api/dashboardApi';
import { modelLabel } from '../../utils/modelLabels';

const CATEGORY_LABELS = { general: 'General', coding: 'Coding', vision: 'Vision' };

function formatBytes(bytes) {
  if (!bytes) return null;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function timeAgo(iso) {
  if (!iso) return 'Not used yet';
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
}

function StatCard({ icon: Icon, label, value, tone }) {
  return (
    <div className={`stat-card ${tone || ''}`}>
      <div className="stat-card-label"><Icon size={15} /> {label}</div>
      <div className="stat-card-value">{value.toLocaleString()}</div>
    </div>
  );
}

function BarList({ rows, total }) {
  return (
    <ul className="bar-list">
      {rows.map((r) => {
        const pct = total ? Math.round((r.value / total) * 100) : 0;
        return (
          <li key={r.key}>
            <div className="bar-list-head">
              <span className="bar-list-label">{r.label}</span>
              <span className="bar-list-value">{r.value.toLocaleString()} <span>· {pct}%</span></span>
            </div>
            <div className="bar-track" role="img" aria-label={`${r.label}: ${r.value} (${pct}%)`}>
              <span className={`bar-fill ${r.tone || ''}`} style={{ width: `${pct}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** state: ready | unavailable | checking */
function StatusPill({ state, label }) {
  return (
    <span className={`status-pill is-${state}`}>
      <span className="status-dot" aria-hidden="true" />
      {state === 'checking' ? 'Checking…' : label}
    </span>
  );
}

function UsageSection() {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setUsage(await getUsage());
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const empty = usage && !usage.error && usage.total_queries === 0;
  const modelRows = (usage?.model_details || []).map((m, i) => ({
    key: m.model, label: modelLabel(m.model), value: m.queries, tone: `tone-${i % 3}`,
  }));
  const routingRows = Object.entries(usage?.routing || {}).map(([k, v], i) => ({
    key: k, label: CATEGORY_LABELS[k] || k, value: v, tone: `tone-${i % 3}`,
  }));

  return (
    <section className="dash-section" aria-labelledby="usage-heading">
      <div className="dash-section-head">
        <div>
          <h2 id="usage-heading">Usage Dashboard</h2>
          <p>How the local models are being used. Counts are requests, not a measure of answer quality.</p>
        </div>
        <button type="button" className="dash-btn" onClick={load} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
        </button>
      </div>

      {usage?.error ? (
        <div className="dash-error"><AlertTriangle size={15} /> {usage.error}</div>
      ) : !usage ? (
        <div className="dash-placeholder">Loading usage…</div>
      ) : empty ? (
        <div className="dash-empty">No model usage recorded yet.</div>
      ) : (
        <>
          <div className="stat-grid">
            <StatCard icon={Activity} label="Total queries" value={usage.total_queries} />
            <StatCard icon={CheckCircle2} label="Successful" value={usage.successful_queries} tone="is-good" />
            <StatCard icon={XCircle} label="Failed" value={usage.failed_queries} tone={usage.failed_queries ? 'is-bad' : ''} />
            <StatCard icon={CalendarDays} label="Today" value={usage.today} />
          </div>
          <div className="dash-columns">
            <div className="dash-card">
              <h3>Model usage</h3>
              <BarList rows={modelRows} total={usage.total_queries} />
            </div>
            <div className="dash-card">
              <h3>Routing distribution</h3>
              <BarList rows={routingRows} total={usage.total_queries} />
            </div>
          </div>
          <p className="dash-footnote">
            Recorded since {new Date(usage.first_recorded).toLocaleString()} · includes chat, document Q&A and
            summaries · failed = the model call did not complete.
          </p>
        </>
      )}
    </section>
  );
}

function StatusSection() {
  const [status, setStatus] = useState(null);
  const [checking, setChecking] = useState(true);

  const check = useCallback(async () => {
    setChecking(true);
    setStatus(await getSystemStatus());
    setChecking(false);
  }, []);

  useEffect(() => { check(); }, [check]);

  const unreachable = status?.error;
  const services = [
    { key: 'backend', icon: Server, name: 'Django Backend' },
    { key: 'ollama', icon: Cpu, name: 'Ollama' },
    { key: 'ocr', icon: ScanText, name: 'OCR Engine' },
  ];

  const serviceState = (key) => {
    if (checking) return { state: 'checking' };
    if (unreachable) return key === 'backend'
      ? { state: 'unavailable', label: 'Offline', reason: status.error }
      : { state: 'unavailable', label: 'Unknown', reason: 'Cannot be checked while the backend is unreachable.' };
    return status.services[key];
  };

  return (
    <section className="dash-section" aria-labelledby="status-heading">
      <div className="dash-section-head">
        <div>
          <h2 id="status-heading">System Status</h2>
          <p>Lightweight checks only: no model is loaded and no inference is run.</p>
        </div>
        <button type="button" className="dash-btn" onClick={check} disabled={checking}>
          <RefreshCw size={14} className={checking ? 'spin' : ''} /> Check Status
        </button>
      </div>

      <div className="dash-columns">
        <div className="dash-card">
          <h3>Services</h3>
          <ul className="health-list">
            {services.map(({ key, icon: Icon, name }) => {
              const s = serviceState(key);
              const detail = key === 'ollama' && s.version ? `Version ${s.version}`
                : key === 'ocr' && s.detail ? s.detail : null;
              return (
                <li key={key}>
                  <div className="health-row">
                    <span className="health-name"><Icon size={15} /> {name}</span>
                    <StatusPill state={s.state} label={s.label} />
                  </div>
                  {s.state === 'unavailable' && s.reason && <div className="health-reason">{s.reason}</div>}
                  {s.state === 'ready' && detail && <div className="health-detail">{detail}</div>}
                </li>
              );
            })}
          </ul>
        </div>

        <div className="dash-card">
          <h3>Model Health</h3>
          <ul className="health-list">
            {(status?.models || [{ id: 'qwen3' }, { id: 'qwen-coder' }, { id: 'qwen-vl' }]).map((m) => {
              const state = checking ? 'checking' : unreachable ? 'unavailable' : m.state;
              return (
                <li key={m.id}>
                  <div className="health-row">
                    <span className="health-name">{modelLabel(m.id)}</span>
                    <StatusPill state={state} label={unreachable ? 'Unknown' : m.label} />
                  </div>
                  {!checking && !unreachable && (
                    <>
                      <div className="health-detail">
                        {m.capability_label}
                        {m.state === 'ready' && m.size_bytes ? ` · ${formatBytes(m.size_bytes)} on disk` : ''}
                        {m.loaded ? ` · loaded in GPU memory (${formatBytes(m.vram_bytes)})` : ''}
                      </div>
                      <div className="health-detail">Last successful use: {timeAgo(m.last_success)}</div>
                      {m.state === 'unavailable' && m.reason && <div className="health-reason">{m.reason}</div>}
                    </>
                  )}
                </li>
              );
            })}
          </ul>
          <p className="dash-footnote">
            "Ready" means the model is installed in the local Ollama service. It does not measure answer quality.
            Models load into the 8 GB GPU one at a time when first used.
          </p>
        </div>
      </div>
      {status?.checked_at && !checking && (
        <p className="dash-footnote">Checked {new Date(status.checked_at).toLocaleTimeString()}</p>
      )}
    </section>
  );
}

export default function DashboardPage() {
  return (
    <div className="dashboard">
      <div className="dashboard-inner">
        <UsageSection />
        <StatusSection />
      </div>
    </div>
  );
}
