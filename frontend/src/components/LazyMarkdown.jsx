import React, { Component, Suspense, lazy } from 'react';

// The Markdown renderer (parser + syntax grammars) is the largest part of the bundle;
// load it on first use so the welcome screen appears quickly.
const Markdown = lazy(() => import('./Markdown'));

function PlainText({ text }) {
  return <div className="markdown markdown-fallback">{text}</div>;
}

/**
 * If the renderer chunk cannot be loaded (e.g. an old tab after a redeploy), show the
 * answer as plain text instead of unmounting the whole app.
 */
class RenderBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error) {
    console.warn('Markdown renderer unavailable, showing plain text:', error?.message);
  }

  render() {
    return this.state.failed ? <PlainText text={this.props.text} /> : this.props.children;
  }
}

export default function LazyMarkdown({ text }) {
  return (
    <RenderBoundary text={text}>
      <Suspense fallback={<PlainText text={text} />}>
        <Markdown text={text} />
      </Suspense>
    </RenderBoundary>
  );
}
