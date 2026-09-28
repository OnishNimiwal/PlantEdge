import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import CopyButton from './CopyButton';

const LANGUAGE_NAMES = {
  py: 'Python', python: 'Python', js: 'JavaScript', javascript: 'JavaScript', jsx: 'JSX',
  ts: 'TypeScript', typescript: 'TypeScript', tsx: 'TSX', java: 'Java', c: 'C', cpp: 'C++',
  'c++': 'C++', cs: 'C#', csharp: 'C#', go: 'Go', rust: 'Rust', sql: 'SQL', bash: 'Bash',
  sh: 'Shell', shell: 'Shell', powershell: 'PowerShell', json: 'JSON', yaml: 'YAML', yml: 'YAML',
  html: 'HTML', xml: 'XML', css: 'CSS', markdown: 'Markdown', md: 'Markdown', php: 'PHP',
  kotlin: 'Kotlin', swift: 'Swift', r: 'R', matlab: 'MATLAB', dockerfile: 'Dockerfile',
  ini: 'INI', toml: 'TOML', text: 'Text', plaintext: 'Text',
};

/** Plain text of a HAST node (the original code, without highlight markup). */
function hastText(node) {
  if (!node) return '';
  if (node.type === 'text') return node.value;
  return (node.children || []).map(hastText).join('');
}

function CodeBlock({ node, children }) {
  const codeNode = node?.children?.find((c) => c.tagName === 'code');
  const classes = codeNode?.properties?.className || [];
  const langClass = classes.find((c) => String(c).startsWith('language-'));
  const lang = langClass ? String(langClass).slice('language-'.length).toLowerCase() : '';
  const label = LANGUAGE_NAMES[lang] || (lang ? lang : 'Code');
  const raw = hastText(codeNode).replace(/\n$/, '');

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-block-lang">{label}</span>
        <CopyButton getText={() => raw} label="Copy" className="code-copy" />
      </div>
      <pre>{children}</pre>
    </div>
  );
}

const components = {
  pre: CodeBlock,
  a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
  table: ({ node, ...props }) => (
    <div className="md-table-wrap">
      <table {...props} />
    </div>
  ),
};

/**
 * Renders model output as Markdown (GFM tables, lists, code with highlighting).
 * Raw HTML in the text is NOT rendered (react-markdown default) - safer for model output.
 */
export default function Markdown({ text }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: false, plainText: ['text', 'txt', 'plaintext'] }]]}
        components={components}
      >
        {text || ''}
      </ReactMarkdown>
    </div>
  );
}
