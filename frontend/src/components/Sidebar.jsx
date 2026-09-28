import React, { useMemo, useState } from 'react';
import {
  SquarePen, MessageSquare, FileText, Search, Pencil, Trash2, Check, X, ShieldCheck, PanelLeftClose,
} from 'lucide-react';

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
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(conv.title || 'Untitled');

  const save = () => {
    const t = title.trim();
    setEditing(false);
    if (t && t !== conv.title) onRename(conv.id, t);
    else setTitle(conv.title || 'Untitled');
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
            if (e.key === 'Escape') { setEditing(false); setTitle(conv.title || 'Untitled'); }
          }}
          aria-label="Conversation title"
        />
        <button type="button" className="conv-icon" onClick={save} aria-label="Save title"><Check size={14} /></button>
        <button
          type="button"
          className="conv-icon"
          onClick={() => { setEditing(false); setTitle(conv.title || 'Untitled'); }}
          aria-label="Cancel rename"
        >
          <X size={14} />
        </button>
      </div>
    );
  }

  return (
    <div className={`conv-item ${active ? 'is-active' : ''}`}>
      <button type="button" className="conv-title" onClick={() => onSelect(conv.id)} title={conv.title}>
        {conv.title || 'Untitled'}
      </button>
      <div className="conv-actions">
        <button type="button" className="conv-icon" onClick={() => setEditing(true)} title="Rename" aria-label="Rename conversation">
          <Pencil size={13} />
        </button>
        <button type="button" className="conv-icon" onClick={() => onDelete(conv)} title="Delete" aria-label="Delete conversation">
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  );
}

export default function Sidebar({
  view, onViewChange, conversations, activeId, onSelect, onNewChat, onRename, onDelete, open, onClose,
}) {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? conversations.filter((c) => (c.title || '').toLowerCase().includes(q)) : conversations;
  }, [conversations, query]);
  const groups = groupByDate(filtered);

  return (
    <>
      <div className={`sidebar-scrim ${open ? 'is-open' : ''}`} onClick={onClose} aria-hidden="true" />
      <aside className={`sidebar ${open ? 'is-open' : ''}`} aria-label="Navigation">
        <div className="sidebar-brand">
          <div className="brand-mark" aria-hidden="true">M</div>
          <div className="brand-text">
            <span className="brand-name">MRPL Local AI</span>
            <span className="brand-sub">Sovereign AI Workbench</span>
          </div>
          <button type="button" className="icon-btn sidebar-close" onClick={onClose} aria-label="Close sidebar">
            <PanelLeftClose size={18} />
          </button>
        </div>

        <button type="button" className="new-chat-btn" onClick={onNewChat}>
          <SquarePen size={16} />
          <span>New chat</span>
        </button>

        <nav className="sidebar-nav">
          <button
            type="button"
            className={`nav-item ${view === 'chat' ? 'is-active' : ''}`}
            onClick={() => onViewChange('chat')}
          >
            <MessageSquare size={16} /> Chat
          </button>
          <button
            type="button"
            className={`nav-item ${view === 'documents' ? 'is-active' : ''}`}
            onClick={() => onViewChange('documents')}
          >
            <FileText size={16} /> Document Assistant
          </button>
        </nav>

        <div className="sidebar-search">
          <Search size={14} aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search chats"
            aria-label="Search conversations"
          />
        </div>

        <div className="conv-list">
          {groups.length === 0 ? (
            <div className="conv-empty">{query ? 'No matching chats.' : 'No conversations yet.'}</div>
          ) : (
            groups.map(([label, items]) => (
              <div className="conv-group" key={label}>
                <div className="conv-group-label">{label}</div>
                {items.map((c) => (
                  <ConversationItem
                    key={c.id}
                    conv={c}
                    active={view === 'chat' && c.id === activeId}
                    onSelect={onSelect}
                    onRename={onRename}
                    onDelete={onDelete}
                  />
                ))}
              </div>
            ))
          )}
        </div>

        <div className="sidebar-footer" title="All inference runs on local models inside the company network">
          <ShieldCheck size={14} />
          <span>On-premise · local models only</span>
        </div>
      </aside>
    </>
  );
}
