import React, { useEffect, useState } from 'react';
import {
  SquarePen, MessageSquare, FileText, Search, Pencil, Trash2, Check, X, ShieldCheck, PanelLeftClose,
  Sun, Moon, Monitor, LayoutDashboard,
} from 'lucide-react';
import { useI18n, LANGUAGES } from '../utils/i18n';

const THEME_NEXT = { system: 'light', light: 'dark', dark: 'system' };
const THEME_LABEL = { system: 'System theme', light: 'Light theme', dark: 'Dark theme' };
const THEME_ICON = { system: Monitor, light: Sun, dark: Moon };

function groupByDate(conversations) {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86400000;
  const groups = { Today: [], Yesterday: [], 'Previous 7 days': [], Older: [] };
  conversations.forEach((c) => {
    const t = new Date(c.updated_at).getTime();
    if (t >= startOfToday) groups.Today.push(c);
    else if (t >= startOfToday - day) groups.Yesterday.push(c);
    else if (t >= startOfToday - 7 * day) groups['Previous 7 days'].push(c);
    else groups.Older.push(c);
  });
  return Object.entries(groups).filter(([, items]) => items.length);
}

function ConversationItem({ conv, active, onSelect, onRename, onDelete }) {
  const { t: tr } = useI18n();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(conv.title || tr('Untitled'));

  const save = () => {
    const t = title.trim();
    setEditing(false);
    if (t && t !== conv.title) onRename(conv.id, t);
    else setTitle(conv.title || tr('Untitled'));
  };

  if (editing) {
    return (
      <div className="conv-item is-editing">
        <input
          autoFocus
          value={title}
          maxLength={200}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') save();
            if (e.key === 'Escape') { setEditing(false); setTitle(conv.title || tr('Untitled')); }
          }}
          aria-label={tr('Conversation title')}
        />
        <button type="button" className="conv-icon" onClick={save} aria-label={tr('Save title')}><Check size={14} /></button>
        <button
          type="button"
          className="conv-icon"
          onClick={() => { setEditing(false); setTitle(conv.title || tr('Untitled')); }}
          aria-label={tr('Cancel rename')}
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  return (
    <div className={`conv-item ${active ? 'is-active' : ''}`}>
      <button
        type="button"
        className="conv-title"
        onClick={() => onSelect(conv)}
        title={conv.document_name ? `${conv.title} — ${conv.document_name}` : conv.title}
        aria-current={active ? 'page' : undefined}
      >
        {conv.document_id && <FileText size={13} className="conv-doc-icon" aria-label={tr('Document Q&A')} />}
        <span className="conv-title-text">{conv.title || tr('Untitled')}</span>
        {conv.document_name && <span className="conv-doc-name">{conv.document_name}</span>}
      </button>
      <div className="conv-actions">
        <button type="button" className="conv-icon" onClick={() => setEditing(true)} title={tr('Rename')} aria-label={tr('Rename conversation')}>
          <Pencil size={13} />
        </button>
        <button type="button" className="conv-icon" onClick={() => onDelete(conv)} title={tr('Delete')} aria-label={tr('Delete conversation')}>
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  );
}

export default function Sidebar({
  view, onViewChange, conversations, activeId, onSelect, onNewChat, onRename, onDelete, open, onClose,
  onSearch, theme, onThemeChange, collapsed, hasMore, onLoadMore, lang, onLangChange,
}) {
  const { t } = useI18n();
  const [loadingMore, setLoadingMore] = useState(false);
  const [query, setQuery] = useState('');
  // Server-side search over titles and message text (debounced).
  useEffect(() => {
    const t = setTimeout(() => onSearch(query), 250);
    return () => clearTimeout(t);
  }, [query, onSearch]);
  const groups = groupByDate(conversations);
  const ThemeIcon = THEME_ICON[theme] || Monitor;

  return (
    <>
      <div className={`sidebar-scrim ${open ? 'is-open' : ''}`} onClick={onClose} aria-hidden="true" />
      <aside
        className={`sidebar ${open ? 'is-open' : ''} ${collapsed ? 'is-collapsed' : ''}`}
        aria-label={t('Navigation')}
        aria-hidden={(collapsed && !open) || undefined}
      >
        <div className="sidebar-brand">
          <div className="brand-mark" aria-hidden="true">M</div>
          <div className="brand-text">
            <span className="brand-name">{t('MRPL Local AI')}</span>
            <span className="brand-sub">{t('Sovereign AI Workbench')}</span>
          </div>
          <button
            type="button"
            className="icon-btn sidebar-close"
            onClick={onClose}
            aria-label={t('Close sidebar')}
            aria-expanded="true"
            title={`${t('Close sidebar')} (Ctrl+Shift+S)`}
          >
            <PanelLeftClose size={18} />
          </button>
        </div>

        <button type="button" className="new-chat-btn" onClick={onNewChat}>
          <SquarePen size={16} />
          <span>{t('New chat')}</span>
        </button>

        <nav className="sidebar-nav">
          <button
            type="button"
            className={`nav-item ${view === 'chat' ? 'is-active' : ''}`}
            onClick={() => onViewChange('chat')}
          >
            <MessageSquare size={16} /> {t('Chat')}
          </button>
          <button
            type="button"
            className={`nav-item ${view === 'documents' ? 'is-active' : ''}`}
            onClick={() => onViewChange('documents')}
          >
            <FileText size={16} /> {t('Document Assistant')}
          </button>
          <button
            type="button"
            className={`nav-item ${view === 'dashboard' ? 'is-active' : ''}`}
            onClick={() => onViewChange('dashboard')}
          >
            <LayoutDashboard size={16} /> {t('System Status')}
          </button>
        </nav>

        <div className="sidebar-search">
          <Search size={14} aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('Search chats and messages')}
            aria-label={t('Search conversations')}
          />
        </div>

        <div className="conv-list">
          {groups.length === 0 ? (
            <div className="conv-empty">{query ? t('No matching chats.') : t('No conversations yet.')}</div>
          ) : (
            groups.map(([label, items]) => (
              <div className="conv-group" key={label}>
                <div className="conv-group-label">{t(label)}</div>
                {items.map((c) => (
                  <ConversationItem
                    key={c.id}
                    conv={c}
                    active={c.id === activeId}
                    onSelect={onSelect}
                    onRename={onRename}
                    onDelete={onDelete}
                  />
                ))}
              </div>
            ))
          )}
          {hasMore && onLoadMore && (
            <button
              type="button"
              className="conv-more"
              disabled={loadingMore}
              onClick={async () => {
                setLoadingMore(true);
                try { await onLoadMore(); } finally { setLoadingMore(false); }
              }}
            >
              {loadingMore ? t('Loading…') : t('Show more')}
            </button>
          )}
        </div>

        <div className="sidebar-footer">
          <span className="sidebar-footer-status" title={t('All inference runs on local models inside the company network')}>
            <ShieldCheck size={14} />
            <span>{t('On-premise · local models only')}</span>
          </span>
          {onLangChange && (
            <div className="lang-toggle" role="group" aria-label={t('Language')}>
              {LANGUAGES.map((l) => (
                <button
                  type="button"
                  key={l.id}
                  lang={l.id}
                  className={lang === l.id ? 'is-active' : ''}
                  aria-pressed={lang === l.id}
                  title={l.label}
                  onClick={() => onLangChange(l.id)}
                >
                  {l.short}
                </button>
              ))}
            </div>
          )}
          <button
            type="button"
            className="icon-btn theme-toggle"
            onClick={() => onThemeChange(THEME_NEXT[theme] || 'system')}
            title={`${t(THEME_LABEL[theme])} (${t('click to change')})`}
            aria-label={`${t(THEME_LABEL[theme])}. ${t('Change theme')}`}
          >
            <ThemeIcon size={15} />
          </button>
        </div>
      </aside>
    </>
  );
}
