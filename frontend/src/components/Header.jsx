import React from 'react';
import { PanelLeft, SquarePen, ShieldCheck } from 'lucide-react';

/**
 * Slim top bar. The sidebar toggle sits top-left whenever the sidebar is not
 * visible (collapsed on desktop, or hidden off-canvas on small screens); a
 * New chat shortcut sits next to it while the sidebar is collapsed.
 */
export default function Header({ title, onToggleSidebar, sidebarCollapsed, onNewChat }) {
  return (
    <header className={`topbar ${sidebarCollapsed ? 'is-sidebar-collapsed' : ''}`}>
      <div className="topbar-left">
        <button
          type="button"
          className="icon-btn topbar-menu"
          onClick={onToggleSidebar}
          aria-label="Open sidebar"
          aria-expanded="false"
          title="Open sidebar (Ctrl+Shift+S)"
        >
          <PanelLeft size={18} />
        </button>
        {sidebarCollapsed && (
          <button type="button" className="icon-btn topbar-new-chat" onClick={onNewChat} aria-label="New chat" title="New chat">
            <SquarePen size={17} />
          </button>
        )}
      </div>
      <h1 className="topbar-title" title={title}>{title}</h1>
      <span className="topbar-badge" title="Inference runs on local models; no external AI APIs">
        <ShieldCheck size={13} /> On-premise
      </span>
    </header>
  );
}
