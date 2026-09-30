import React, { useCallback, useEffect, useState } from 'react';
import {
  RefreshCw, Activity, CheckCircle2, XCircle, CalendarDays, Server, Cpu, ScanText, AlertTriangle, Gauge,
  Database, HardDrive, ThumbsUp, ThumbsDown, FlaskConical, Loader2,
} from 'lucide-react';
import { useI18n } from '../../utils/i18n';
import { getUsage, getSystemStatus, runDeepCheck } from '../../api/dashboardApi';
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

function formatMs(ms) {
  if (ms == null) return '—';
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** Requests per day for the last 14 days (failed part in red), with average response time on hover. */
function TrendChart({ days }) {
  const { t, lang } = useI18n();
  const max = Math.max(1, ...days.map((d) => d.total));
  const W = 900; const H = 110; const pad = 18; const gap = 8;
  const bw = (W - gap * (days.length - 1)) / days.length;
  const locale = lang === 'hi' ? 'hi-IN' : undefined;
  const label = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString(locale, { day: 'numeric', month: 'short' });
  const total = days.reduce((n, d) => n + d.total, 0);
  return (
    <figure className="trend">
      <svg viewBox={`0 0 ${W} ${H + pad}`} role="img"
        aria-label={t('Requests per day, last 14 days: {n} in total', { n: total })}>
        {days.map((d, i) => {
          const x = i * (bw + gap);
          const h = (d.total / max) * H;
          const hf = (d.failed / max) * H;
          return (
            <g key={d.date}>
              <title>{`${label(d.date)}: ${t('{n} requests', { n: d.total })}${d.failed ? `, ${t('{n} failed', { n: d.failed })}` : ''}${d.avg_ms != null ? ` · ${t('avg')} ${formatMs(d.avg_ms)}` : ''}`}</title>
              <rect className="trend-bg" x={x} y={0} width={bw} height={H} rx={3} />
              {h > 0 && <rect className="trend-bar" x={x} y={H - h} width={bw} height={h} rx={3} />}
              {hf > 0 && <rect className="trend-fail" x={x} y={H - hf} width={bw} height={hf} rx={3} />}
              {(i % 2 === 1 || days.length <= 7) && (
                <text className="trend-label" x={x + bw / 2} y={H + 13} textAnchor="middle">{label(d.date)}</text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption>
        <span className="trend-key is-ok" /> {t('Requests')} <span className="trend-key is-fail" /> {t('Failed')}
        {' · '}{t('peak {n} per day', { n: max })}
      </figcaption>
    </figure>
  );
}

function ModelTable({ rows }) {
  const { t } = useI18n();
  return (
    <div className="md-table-wrap">
      <table className="dash-table">
        <thead>
          <tr>
            <th scope="col">{t('Model')}</th>
            <th scope="col">{t('Requests')}</th>
            <th scope="col">{t('Failed')}</th>
            <th scope="col">{t('Average response time')}</th>
            <th scope="col">{t('Regenerated')}</th>
            <th scope="col">{t('User ratings')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => {
            const rated = (m.feedback?.up || 0) + (m.feedback?.down || 0);
            return (
              <tr key={m.model}>
                <th scope="row">{modelLabel(m.model)}</th>
                <td>{m.queries.toLocaleString()}</td>
                <td className={m.failed ? 'is-bad' : ''}>{m.failed.toLocaleString()}</td>
                <td>{formatMs(m.avg_ms)}</td>
                <td>{(m.regenerated || 0).toLocaleString()}</td>
                <td>
                  <span className="rating" title={rated ? t('{pct}% rated helpful', { pct: Math.round((m.feedback.up / rated) * 100) }) : t('No ratings yet')}>
                    <ThumbsUp size={12} aria-label={t('Helpful')} /> {m.feedback?.up || 0}
                    <ThumbsDown size={12} aria-label={t('Not helpful')} /> {m.feedback?.down || 0}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
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
          {usage.trend?.length > 0 && (
            <div className="dash-card">
              <h3>{t('Last 14 days')}</h3>
              <TrendChart days={usage.trend} />
            </div>
          )}
          <div className="dash-card">
            <h3>{t('Per model')}</h3>
            <ModelTable rows={usage.model_details || []} />
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
          {Object.keys(usage.pre_model_failures || {}).length > 0 && (
            <p className="dash-footnote is-warn">
              <AlertTriangle size={13} />{' '}
              {Object.entries(usage.pre_model_failures).map(([stage, n]) => (
                stage === 'ocr' ? t('{n} request(s) failed in local OCR before any model ran.', { n })
                  : t('{n} document(s) failed during text extraction.', { n })
              )).join(' ')}
            </p>
          )}
          <p className="dash-footnote">
            {t('User ratings are opinions from the 👍/👎 buttons, not a measured accuracy.')}
            {usage.backfilled > 0 && ` ${t('{n} older requests were reconstructed from stored answers (no timing).', { n: usage.backfilled })}`}
          </p>
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
    { key: 'database', icon: Database, name: t('Database') },
    { key: 'disk', icon: HardDrive, name: t('Disk space') },
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
                  ].filter(Boolean).join(' · ')
                    : key === 'database' && s.engine ? [
                      s.engine === 'sqlite' ? 'SQLite' : s.engine,
                      s.size_bytes != null ? `${(s.size_bytes / 1024 ** 2).toFixed(1)} MB` : null,
                      s.latency_ms != null ? `${s.latency_ms} ms` : null,
                    ].filter(Boolean).join(' · ')
                      : key === 'disk' && s.total_bytes ? t('{free} GB free of {total} GB', {
                        free: (s.free_bytes / 1024 ** 3).toFixed(1), total: (s.total_bytes / 1024 ** 3).toFixed(0),
                      }) : null;
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
      <DeepChecks models={status?.models} />
      {status?.checked_at && !checking && (
        <p className="dash-footnote">{t('Checked {time}', { time: new Date(status.checked_at).toLocaleTimeString(lang === 'hi' ? 'hi-IN' : undefined) })}</p>
      )}
    </section>
  );
}

/** Opt-in functional tests: each runs only when its button is pressed. */
function DeepChecks({ models }) {
  const { t } = useI18n();
  const [results, setResults] = useState({});
  const [running, setRunning] = useState(null);
  const targets = [{ id: 'ocr', label: t('OCR Engine') },
    ...(models || []).map((m) => ({ id: m.id, label: modelLabel(m.id) }))];

  const run = async (id) => {
    setRunning(id);
    const r = await runDeepCheck(id);
    setResults((prev) => ({ ...prev, [id]: r }));
    setRunning(null);
  };

  return (
    <div className="dash-card deep-checks">
      <h3><FlaskConical size={15} /> {t('Deep checks')}</h3>
      <p className="dash-footnote">
        {t('Runs a real test: OCR reads a generated line of text, or a model answers a one-word prompt. Loads the model into GPU memory (can take 10–60 s) and is not counted as usage.')}
      </p>
      <ul className="health-list">
        {targets.map(({ id, label }) => {
          const r = results[id];
          return (
            <li key={id}>
              <div className="health-row">
                <span className="health-name">{label}</span>
                <span className="deep-check-actions">
                  {r && (
                    <StatusPill state={r.success ? 'ready' : 'unavailable'} label={r.success ? 'Passed' : 'Failed'} />
                  )}
                  <button type="button" className="dash-btn" disabled={running !== null} onClick={() => run(id)}>
                    {running === id ? <Loader2 size={14} className="spin" /> : null}
                    {running === id ? t('Running…') : t('Run test')}
                  </button>
                </span>
              </div>
              {r && (
                <div className={r.success ? 'health-detail' : 'health-reason'}>
                  {r.detail}{r.duration_ms != null ? ` · ${formatMs(r.duration_ms)}` : ''}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
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
