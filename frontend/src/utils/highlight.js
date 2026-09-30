/**
 * Minimal rehype plugin: syntax-highlight fenced code with a curated set of
 * highlight.js grammars (instead of all ~37 "common" ones) to keep the bundle small.
 * Other languages (EXTRA_LANGUAGES) are fetched on first use: ensureLanguages()
 * loads them and the Markdown renderer re-renders once they are registered.
 * Languages highlight.js does not know are left as plain text.
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

export const lowlight = createLowlight({
  bash, c, cpp, csharp, css, dockerfile, go, ini, java, javascript, json, markdown, php,
  plaintext, powershell, python, rust, shell, sql, typescript, xml, yaml,
});
lowlight.registerAlias({
  javascript: ['js', 'jsx'], typescript: ['ts', 'tsx'], bash: ['sh', 'zsh'], xml: ['html', 'svg'],
  cpp: ['c++', 'hpp'], csharp: ['cs'], yaml: ['yml'], ini: ['toml'], plaintext: ['text', 'txt'],
  python: ['py'], powershell: ['ps1'],
});

// Loaded on demand (one small chunk each) so the base bundle stays small.
const EXTRA_LANGUAGES = {
  kotlin: () => import('highlight.js/lib/languages/kotlin'),
  swift: () => import('highlight.js/lib/languages/swift'),
  r: () => import('highlight.js/lib/languages/r'),
  matlab: () => import('highlight.js/lib/languages/matlab'),
  scala: () => import('highlight.js/lib/languages/scala'),
  ruby: () => import('highlight.js/lib/languages/ruby'),
  perl: () => import('highlight.js/lib/languages/perl'),
  lua: () => import('highlight.js/lib/languages/lua'),
  haskell: () => import('highlight.js/lib/languages/haskell'),
  dart: () => import('highlight.js/lib/languages/dart'),
  groovy: () => import('highlight.js/lib/languages/groovy'),
  gradle: () => import('highlight.js/lib/languages/gradle'),
  makefile: () => import('highlight.js/lib/languages/makefile'),
  cmake: () => import('highlight.js/lib/languages/cmake'),
  nginx: () => import('highlight.js/lib/languages/nginx'),
  diff: () => import('highlight.js/lib/languages/diff'),
  latex: () => import('highlight.js/lib/languages/latex'),
  julia: () => import('highlight.js/lib/languages/julia'),
  fortran: () => import('highlight.js/lib/languages/fortran'),
  vbnet: () => import('highlight.js/lib/languages/vbnet'),
  objectivec: () => import('highlight.js/lib/languages/objectivec'),
  protobuf: () => import('highlight.js/lib/languages/protobuf'),
  graphql: () => import('highlight.js/lib/languages/graphql'),
  scss: () => import('highlight.js/lib/languages/scss'),
  less: () => import('highlight.js/lib/languages/less'),
  properties: () => import('highlight.js/lib/languages/properties'),
  x86asm: () => import('highlight.js/lib/languages/x86asm'),
  verilog: () => import('highlight.js/lib/languages/verilog'),
  vhdl: () => import('highlight.js/lib/languages/vhdl'),
  delphi: () => import('highlight.js/lib/languages/delphi'),
  elixir: () => import('highlight.js/lib/languages/elixir'),
  erlang: () => import('highlight.js/lib/languages/erlang'),
  ocaml: () => import('highlight.js/lib/languages/ocaml'),
  fsharp: () => import('highlight.js/lib/languages/fsharp'),
  clojure: () => import('highlight.js/lib/languages/clojure'),
  awk: () => import('highlight.js/lib/languages/awk'),
  tcl: () => import('highlight.js/lib/languages/tcl'),
};
const EXTRA_ALIASES = {
  kt: 'kotlin', rb: 'ruby', pl: 'perl', hs: 'haskell', make: 'makefile', mk: 'makefile', patch: 'diff',
  tex: 'latex', jl: 'julia', f90: 'fortran', vb: 'vbnet', objc: 'objectivec', proto: 'protobuf',
  gql: 'graphql', asm: 'x86asm', v: 'verilog', sv: 'verilog', pascal: 'delphi', ex: 'elixir',
  erl: 'erlang', ml: 'ocaml', fs: 'fsharp', clj: 'clojure',
};
const pending = new Map();

/** Fenced-code languages in `markdown` that are not registered yet but can be loaded. */
export function missingLanguages(markdown) {
  const out = new Set();
  for (const m of (markdown || '').matchAll(/^\s*(?:```|~~~)\s*([\w+#.-]+)/gm)) {
    const name = m[1].toLowerCase();
    const id = EXTRA_ALIASES[name] || name;
    if (!lowlight.registered(name) && EXTRA_LANGUAGES[id]) out.add(id);
  }
  return [...out];
}

/** Load and register the given extra languages; resolves when all are available. */
export function ensureLanguages(ids) {
  return Promise.all(ids.map((id) => {
    if (!pending.has(id)) {
      pending.set(id, EXTRA_LANGUAGES[id]().then((mod) => {
        lowlight.register(id, mod.default);
        const aliases = Object.keys(EXTRA_ALIASES).filter((a) => EXTRA_ALIASES[a] === id);
        if (aliases.length) lowlight.registerAlias(id, aliases);
      }).catch(() => { /* stays plain text */ }));
    }
    return pending.get(id);
  }));
}

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
