/**
 * Minimal rehype plugin: syntax-highlight fenced code with a curated set of
 * highlight.js grammars (instead of all ~37 "common" ones) to keep the bundle small.
 * Unknown languages are left as plain text.
 */
import { createLowlight } from 'lowlight';
import bash from 'highlight.js/lib/languages/bash';
import c from 'highlight.js/lib/languages/c';
import cpp from 'highlight.js/lib/languages/cpp';
import csharp from 'highlight.js/lib/languages/csharp';
import css from 'highlight.js/lib/languages/css';
import dockerfile from 'highlight.js/lib/languages/dockerfile';
import go from 'highlight.js/lib/languages/go';
import ini from 'highlight.js/lib/languages/ini';
import java from 'highlight.js/lib/languages/java';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import markdown from 'highlight.js/lib/languages/markdown';
import php from 'highlight.js/lib/languages/php';
import plaintext from 'highlight.js/lib/languages/plaintext';
import powershell from 'highlight.js/lib/languages/powershell';
import python from 'highlight.js/lib/languages/python';
import rust from 'highlight.js/lib/languages/rust';
import shell from 'highlight.js/lib/languages/shell';
import sql from 'highlight.js/lib/languages/sql';
import typescript from 'highlight.js/lib/languages/typescript';
import xml from 'highlight.js/lib/languages/xml';
import yaml from 'highlight.js/lib/languages/yaml';

const lowlight = createLowlight({
  bash, c, cpp, csharp, css, dockerfile, go, ini, java, javascript, json, markdown, php,
  plaintext, powershell, python, rust, shell, sql, typescript, xml, yaml,
});
lowlight.registerAlias({
  javascript: ['js', 'jsx'], typescript: ['ts', 'tsx'], bash: ['sh', 'zsh'], xml: ['html', 'svg'],
  cpp: ['c++', 'hpp'], csharp: ['cs'], yaml: ['yml'], ini: ['toml'], plaintext: ['text', 'txt'],
  python: ['py'], powershell: ['ps1'],
});

function text(node) {
  if (node.type === 'text') return node.value;
  return (node.children || []).map(text).join('');
}

function walk(node, parent) {
  if (node.type === 'element' && node.tagName === 'code' && parent?.tagName === 'pre') {
    const classes = node.properties?.className || [];
    const langClass = classes.find((cls) => String(cls).startsWith('language-'));
    const lang = langClass ? String(langClass).slice('language-'.length).toLowerCase() : null;
    if (lang && lowlight.registered(lang)) {
      node.children = lowlight.highlight(lang, text(node)).children;
      node.properties.className = [...classes, 'hljs'];
    }
    return;
  }
  (node.children || []).forEach((child) => walk(child, node));
}

export default function rehypeHighlightSubset() {
  return (tree) => walk(tree, null);
}
