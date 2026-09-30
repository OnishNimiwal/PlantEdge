import React, { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlightSubset, { ensureLanguages, missingLanguages } from '../utils/highlight';
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
        <CopyButton getText={() => raw} className="code-copy" />
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

const FENCE = /^([ \t]*)(```|~~~)[ \t]*([\w-]*)[ \t]*\n([\s\S]*?)\n\1\2[ \t]*$/gm;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_SEP = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;

/**
 * Models sometimes put a Markdown table inside a code fence (```markdown ... ```), which
 * would show it as raw pipes. Unwrap fences without a real programming language whose
 * content is a table, so it renders as a table.
 */
export function unwrapFencedTables(text) {
  return (text || '').replace(FENCE, (block, indent, fence, lang, body) => {
    if (lang && !['markdown', 'md', 'text', 'txt', 'plaintext', 'table'].includes(lang.toLowerCase())) return block;
    const lines = body.split('\n').filter((l) => l.trim());
    const isTable = lines.length >= 2 && TABLE_SEP.test(lines[1]) && lines.every((l) => TABLE_ROW.test(l) || TABLE_SEP.test(l));
    return isTable ? `\n${body.replace(new RegExp(`^${indent}`, 'gm'), '')}\n` : block;
  });
}

/**
 * Renders model output as Markdown (GFM tables, lists, code with highlighting).
 * Raw HTML in the text is NOT rendered (react-markdown default) - safer for model output.
 */
export default function Markdown({ text }) {
  const source = useMemo(() => unwrapFencedTables(text), [text]);
  const [, setLoaded] = useState(0);
  const missing = missingLanguages(source).join(',');
  // Fetch grammars for languages outside the built-in set, then re-render highlighted.
  useEffect(() => {
    if (!missing) return undefined;
    let alive = true;
    ensureLanguages(missing.split(',')).then(() => alive && setLoaded((n) => n + 1));
    return () => { alive = false; };
  }, [missing]);

  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlightSubset]}
        components={components}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
