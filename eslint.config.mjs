// 2.126.0 (#1993): ESLint for the web client, a check only (CI: npx --yes eslint@<pinned>, nothing in the app or its image).
// The classic scripts static/i18n.js + static/js/*.js share ONE global scope in the browser: their top-level names come from
// tools/eslint_globals.json (written by tools/eslint_globals.py in CI / lint, not kept in git), the browser's own names stand in
// BROWSER below (add one when the client starts to use a new browser API). static/sw.js is a service worker with its own scope.
// Rules: no-undef, no-unused-vars (locals only: top-level names are globals other files and the HTML use), eqeqeq (null may
// use == to match null and undefined).
import { readFileSync } from 'node:fs';

const APP = JSON.parse(readFileSync(new URL('./tools/eslint_globals.json', import.meta.url), 'utf8')).globals;
const BROWSER = [
  'window', 'self', 'document', 'navigator', 'location', 'history', 'screen', 'visualViewport', 'console', 'performance',
  'crypto', 'caches', 'indexedDB', 'localStorage', 'sessionStorage', 'fetch', 'atob', 'btoa', 'getComputedStyle',
  'getSelection', 'matchMedia', 'innerHeight', 'innerWidth', 'outerHeight', 'outerWidth', 'addEventListener',
  'removeEventListener', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'requestAnimationFrame',
  'cancelAnimationFrame', 'queueMicrotask', 'structuredClone', 'Blob', 'CSS', 'ClipboardItem', 'CustomEvent',
  'DecompressionStream', 'CompressionStream', 'Element', 'ErrorEvent', 'Event', 'File', 'FileReader', 'FormData', 'Headers',
  'Audio', 'Image', 'IntersectionObserver', 'MediaRecorder', 'MutationObserver', 'NodeFilter', 'Notification', 'Option', 'ResizeObserver', 'Request', 'Response',
  'TextDecoder', 'TextEncoder', 'URL', 'URLSearchParams', 'XMLHttpRequest', 'AbortController', 'HTMLElement', 'Node',
  'IDBRequest', 'IDBKeyRange', 'BroadcastChannel',
];
const WORKER = ['self', 'caches', 'clients', 'registration', 'fetch', 'console', 'URL', 'URLSearchParams', 'Response',
  'Request', 'Headers', 'setTimeout', 'clearTimeout', 'atob', 'indexedDB', 'BroadcastChannel'];
const ro = names => Object.fromEntries(names.map(n => [n, 'readonly']));
const RULES = {
  'no-undef': 'error',
  'no-unused-vars': ['error', {vars: 'local', args: 'none', caughtErrors: 'none', ignoreRestSiblings: true, destructuredArrayIgnorePattern: '^_'}],
  eqeqeq: ['error', 'always', {null: 'ignore'}],
};
// 2.263.0 (#2978): toISOString() is the UTC day - on a local date it is the day before between 0 and 2 o'clock in Berlin
// (and the first of a month 00:00 becomes the last of the month before); local days come from ds() / today() of core.js
const CLIENT_RULES = {...RULES, 'no-restricted-syntax': ['error', {
  selector: "CallExpression[callee.property.name=/^(slice|substring|substr)$/][callee.object.type='CallExpression'][callee.object.callee.property.name='toISOString'][arguments.0.value=0]:matches([arguments.1.value=7], [arguments.1.value=10])",
  message: 'toISOString() is the UTC day: use ds(date) / today() of core.js for a local day or month (#2978)',
}]};

export default [
  {
    files: ['static/i18n.js', 'static/js/*.js'],
    languageOptions: {ecmaVersion: 'latest', sourceType: 'script', globals: {...ro(BROWSER), ...Object.fromEntries(APP.map(n => [n, 'writable']))}},
    rules: CLIENT_RULES,
  },
  {
    files: ['static/sw.js'],
    languageOptions: {ecmaVersion: 'latest', sourceType: 'script', globals: ro(WORKER)},
    rules: RULES,
  },
];
