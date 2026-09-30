import React, { useCallback, useEffect, useState } from 'react';
import {
  RefreshCw, Activity, CheckCircle2, XCircle, CalendarDays, Server, Cpu, ScanText, AlertTriangle, Gauge,
} from 'lucide-react';
import { useI18n } from '../../utils/i18n';
import { getUsage, getSystemStatus } from '../../api/dashboardApi';
import { modelLabel } from '../../utils/modelLabels';

const CATEGORY_LABELS = { general: 'General', coding: 'Coding', vision: 'Vision' };

function formatBytes(bytes) {
  if (!bytes) return null;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

function timeAgo(iso, t, lang) {
  if (!iso) return t('Not used yet');
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return t('Just now');
  if (seconds < 3600) return t('{n} min ago', { n: Math.floor(seconds / 60) });
  if (seconds < 86400) return t('{n} h ago', { n: Math.floor(seconds / 3600) });
  return new Date(iso).toLocaleDateString(lang === 'hi' ? 'hi-IN' : [], { day: 'numeric', month: 'short', year: 'numeric' });
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
  const { t } = useI18n();
  return (
    <span className={`status-pill is-${state}`}>
      <span className="status-dot" aria-hidden="true" />
      {state === 'checking' ? t('Checking…') : t(label)}
    </span>
  );
}

function UsageSection() {
  const { t, lang } = useI18n();
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
    key: k, label: CATEGORY_LABELS[k] ? t(CATEGORY_LABELS[k]) : k, value: v, tone: `tone-${i % 3}`,
  }));

  return (
    <section className="dash-section" aria-labelledby="usage-heading">
      <div className="dash-section-head">
        <div>
          <h2 id="usage-heading">{t('Usage Dashboard')}</h2>
          <p>{t('How the local models are being used. Counts are requests, not a measure of answer quality.')}</p>
        </div>
        <button type="button" className="dash-btn" onClick={load} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> {t('Refresh')}
        </button>
      </div>

      {usage?.error ? (
        <div className="dash-error"><AlertTriangle size={15} /> {usage.error}</div>
      ) : !usage ? (
        <div className="dash-placeholder">{t('Loading usage…')}</div>
      ) : empty ? (
        <div className="dash-empty">{t('No model usage recorded yet.')}</div>
      ) : (
        <>
          <div className="stat-grid">
            <StatCard icon={Activity} label={t('Total queries')} value={usage.total_queries} />
            <StatCard icon={CheckCircle2} label={t('Successful')} value={usage.successful_queries} tone="is-good" />
            <StatCard icon={XCircle} label={t('Failed')} value={usage.failed_queries} tone={usage.failed_queries ? 'is-bad' : ''} />
            <StatCard icon={CalendarDays} label={t('Today')} value={usage.today} />
          </div>
          <div className="dash-columns">
            <div className="dash-card">
              <h3>{t('Model usage')}</h3>
              <BarList rows={modelRows} total={usage.total_queries} />
            </div>
            <div className="dash-card">
              <h3>{t('Routing distribution')}</h3>
              <BarList rows={routingRows} total={usage.total_queries} />
            </div>
          </div>
          <p className="dash-footnote">
            {t('Recorded since {date} · includes chat, document Q&A and summaries · failed = the model call did not complete.',
              { date: new Date(usage.first_recorded).toLocaleString(lang === 'hi' ? 'hi-IN' : undefined) })}
          </p>
        </>
      )}
    </section>
  );
}

function StatusSection() {
  const { t, lang } = useI18n();
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
    { key: 'backend', icon: Server, name: t('Django Backend') },
    { key: 'ollama', icon: Cpu, name: 'Ollama' },
    { key: 'ocr', icon: ScanText, name: t('OCR Engine') },
    { key: 'gpu', icon: Gauge, name: t('GPU & power') },
  ];

  const serviceState = (key) => {
    if (checking) return { state: 'checking' };
    if (unreachable) return key === 'backend'
      ? { state: 'unavailable', label: 'Offline', reason: status.error }
      : { state: 'unavailable', label: 'Unknown', reason: t('Cannot be checked while the backend is unreachable.') };
    return status.services[key];
  };

  return (
    <section className="dash-section" aria-labelledby="status-heading">
      <div className="dash-section-head">
        <div>
          <h2 id="status-heading">{t('System Status')}</h2>
          <p>{t('Lightweight checks only: no model is loaded and no inference is run.')}</p>
        </div>
        <button type="button" className="dash-btn" onClick={check} disabled={checking}>
          <RefreshCw size={14} className={checking ? 'spin' : ''} /> {t('Check Status')}
        </button>
      </div>

      <div className="dash-columns">
        <div className="dash-card">
          <h3>{t('Services')}</h3>
          <ul className="health-list">
            {services.map(({ key, icon: Icon, name }) => {
              const s = serviceState(key);
              const detail = key === 'ollama' && s.version ? t('Version {v}', { v: s.version })
                : key === 'ocr' && s.detail ? s.detail
                  : key === 'gpu' && s.name ? [
                    s.name,
                    s.memory_total_mb ? t('{used} / {total} GB used', { used: (s.memory_used_mb / 1024).toFixed(1), total: (s.memory_total_mb / 1024).toFixed(1) }) : null,
                    s.temperature_c != null ? `${Math.round(s.temperature_c)} °C` : null,
                    s.power_source === 'ac' ? t('on mains power') : s.power_source === 'battery' ? t('on battery') : null,
                  ].filter(Boolean).join(' · ') : null;
              return (
                <li key={key}>
                  <div className="health-row">
                    <span className="health-name"><Icon size={15} /> {name}</span>
                    <StatusPill state={s.state} label={s.label} />
                  </div>
                  {s.state === 'unavailable' && s.reason && <div className="health-reason">{s.reason}</div>}
                  {(s.state === 'ready' || s.state === 'degraded') && detail && <div className="health-detail">{detail}</div>}
                  {s.warnings?.map((w) => <div key={w} className="health-warning">{w}</div>)}
                </li>
              );
            })}
          </ul>
        </div>

        <div className="dash-card">
          <h3>{t('Model Health')}</h3>
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
                        {t(m.capability_label)}
                        {m.state === 'ready' && m.size_bytes ? ` · ${t('{size} on disk', { size: formatBytes(m.size_bytes) })}` : ''}
                        {m.loaded ? ` · ${t('loaded in GPU memory ({size})', { size: formatBytes(m.vram_bytes) })}` : ''}
                      </div>
                      <div className="health-detail">{t('Last successful use:')} {timeAgo(m.last_success, t, lang)}</div>
                      {m.state === 'unavailable' && m.reason && <div className="health-reason">{m.reason}</div>}
                    </>
                  )}
                </li>
              );
            })}
          </ul>
          <p className="dash-footnote">
            {t('"Ready" means the model is installed in the local Ollama service. It does not measure answer quality. Models load into the 8 GB GPU one at a time when first used.')}
          </p>
        </div>
      </div>
      {status?.checked_at && !checking && (
        <p className="dash-footnote">{t('Checked {time}', { time: new Date(status.checked_at).toLocaleTimeString(lang === 'hi' ? 'hi-IN' : undefined) })}</p>
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
