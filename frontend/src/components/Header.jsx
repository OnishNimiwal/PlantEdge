import React from 'react';
import { PanelLeft, ShieldCheck } from 'lucide-react';

/** Slim top bar: sidebar toggle (small screens), current title, on-premise indicator. */
export default function Header({ title, onMenu }) {
  return (
    <header className="topbar">
      <button type="button" className="icon-btn topbar-menu" onClick={onMenu} aria-label="Open sidebar">
        <PanelLeft size={18} />
      </button>
      <h2 className="topbar-title" title={title}>{title}</h2>
      <span className="topbar-badge" title="Inference runs on local models; no external AI APIs">
        <ShieldCheck size={13} /> On-premise
      </span>
    </header>
  );
}
