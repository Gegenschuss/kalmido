// Kalmido: the CodeMirror 6 parts the knowledge page editor (static/js/wkcm.js) uses, bundled as ONE global "CM6"
// (tools/build_codemirror.sh). Markdown comes from @lezer/markdown with GitHub's extensions (tables, task lists,
// strikethrough); @codemirror/lang-markdown is left out on purpose: it brings HTML, CSS and JavaScript parsers along.
import {parser, GFM} from '@lezer/markdown';
import {Language, defineLanguageFacet, languageDataProp, LanguageSupport} from '@codemirror/language';
export {EditorState, StateField, StateEffect, RangeSetBuilder, EditorSelection, Compartment, Prec, Transaction, Annotation} from '@codemirror/state';
export {EditorView, Decoration, WidgetType, ViewPlugin, keymap, drawSelection, placeholder} from '@codemirror/view';
export {history, historyKeymap, defaultKeymap, undo, redo, indentMore, indentLess, insertNewlineAndIndent} from '@codemirror/commands';
export {syntaxTree, syntaxHighlighting, HighlightStyle, ensureSyntaxTree} from '@codemirror/language';
export {searchKeymap, search} from '@codemirror/search';
export {tags} from '@lezer/highlight';
const facet = defineLanguageFacet({commentTokens: {block: {open: '<!--', close: '-->'}}});
const lang = new Language(facet, parser.configure([GFM, {props: [languageDataProp.add({Document: facet})]}]), [], 'markdown');
export const markdown = () => new LanguageSupport(lang);
export const markdownLanguage = lang;
