/* Kalmido — self-hosted task manager. Vanilla JS, no build step.
   State lives on the server (SQLite); the client keeps a copy, renders views
   from it and polls /api/version to pick up changes from other devices. */
'use strict';
const APP_NAME = 'Kalmido';

// ------------------------------------------------------------------ icons
// 2.8.0 (#434) icon set "Punkt": a 20 x 20 grid, open arcs and lines (1.6, round caps), and one filled dot per icon where it
// carries meaning (class d: the accent, or the text colour in dense places, see app.css). Few strokes, no boxes in boxes.
const icDot = (x, y, r = 2) => `<circle class="d" cx="${x}" cy="${y}" r="${r}"/>`;
const icFill = (x, y, r = 1.2) => `<circle class="f" cx="${x}" cy="${y}" r="${r}"/>`;
const icPath = d => `<path d="${d}"/>`;
const P = {
  check: icPath('M4 10.5L8 14.5L16 5.5'),
  zap: icPath('M11 3L5.5 11H10.5L9 17') + icDot(15.5, 6),
  plus: icPath('M10 4V16M4 10H16'),
  x: icPath('M5 5L15 15M15 5L5 15'),
  pr: icPath('M6 3.5V16.5M14 14V9.5A3.5 3.5 0 0 0 10.5 6H8M10 4L8 6L10 8') + icDot(14, 16),
  commit: icPath('M2.5 10H6.5M13.5 10H17.5M13.5 10A3.5 3.5 0 1 1 6.5 10A3.5 3.5 0 0 1 13.5 10') + icDot(10, 10, 1.4),
  git: icPath('M6 3.5V16.5M6 13A6.5 6.5 0 0 0 12.5 6.5') + icDot(14.5, 5),
  bot: icPath('M4 16V11A6 6 0 0 1 16 11V16H4') + icDot(10, 11),
  inbox: icPath('M3 10V16H17V10M3 10H7A3 3 0 0 0 13 10H17') + icDot(10, 5),
  // 2.16.0 (#645): Today = a sun with rays (the open arc read as "reload"), Tomorrow = a half sun on the horizon with rays
  // (no arrow, it must not read as "upload")
  sun: icPath('M13.5 10A3.5 3.5 0 1 1 6.5 10A3.5 3.5 0 0 1 13.5 10M10 2.5V4.3M10 15.7V17.5M2.5 10H4.3M15.7 10H17.5M4.7 4.7L5.9 5.9M14.1 14.1L15.3 15.3M4.7 15.3L5.9 14.1M14.1 5.9L15.3 4.7') + icDot(10, 10, 1.5),
  smile: icPath('M17 10A7 7 0 1 1 10 3A7 7 0 0 1 17 10M7 12.2Q10 15 13 12.2') + icFill(7.6, 8.3, 1) + icFill(12.4, 8.3, 1),  // 2.16.0 (#643)
  sunrise: icPath('M2.5 15.5H17.5M6 15.5A4 4 0 0 1 14 15.5M10 6.5V8.7M4.4 9.9L5.8 11.3M15.6 9.9L14.2 11.3') + icDot(10, 14, 1.4),
  up: icPath('M10 16V4.5M5.5 9L10 4.5L14.5 9'),
  down: icPath('M10 4V15.5M5.5 11L10 15.5L14.5 11'),
  week: icPath('M3 5H17M3 10H17M3 15H11') + icDot(15.5, 15),
  cal: icPath('M17 9V15A2 2 0 0 1 15 17H5A2 2 0 0 1 3 15V6A2 2 0 0 1 5 4H12M3 8.5H10.5M7 2.5V5.5') + icDot(15.5, 4.5),
  all: icPath('M3 4H17M3 8H17M3 12H17M3 16H10') + icDot(14.5, 16),
  done: icPath('M17 10A7 7 0 1 1 10 3M7 10L9.5 12.5L13.5 7.5') + icDot(15.5, 4.5),
  trash: icPath('M3.5 5.5H16.5M8 5.5V3.5H12V5.5M5 5.5L6 17H14L15 5.5') + icDot(10, 11.5, 1.6),
  list: icPath('M7 5H17M7 10H17M7 15H17') + icDot(3.5, 5) + icFill(3.5, 10) + icFill(3.5, 15),
  tag: icPath('M10 3H3V10L10 17L17 10L11.5 4.5') + icDot(7, 7, 1.7),
  grid: icPath('M3 3H8.5V8.5H3ZM11.5 11.5H17V17H11.5ZM11.5 8.5V3H17') + icDot(5.75, 14.25),
  habit: icPath('M4 16C4 9 9 4 16 4C16 11 11 16 4 16M4 16L9.5 10.5') + icDot(12.5, 7.5, 1.7),
  timer: icPath('M16 11A6 6 0 1 1 10 5M10 8V11M8 2.5H12') + icDot(15, 6, 1.8),
  search: icPath('M14 9A5 5 0 1 1 4 9A5 5 0 0 1 14 9M13 13L17 17') + icDot(9, 9),
  gear: icPath('M3 6H17M3 14H17') + icDot(7, 6) + icFill(13, 14, 2),
  menu: icPath('M3 5H17M3 10H17M3 15H12'),
  back: icPath('M12.5 4.5L7 10L12.5 15.5'),
  chev: icPath('M5 7.5L10 12.5L15 7.5'),
  left: icPath('M12.5 4.5L7 10L12.5 15.5'),
  right: icPath('M7.5 4.5L13 10L7.5 15.5'),
  flag: icPath('M4.5 17.5V3.5M4.5 4H15L12.5 8L15 12H4.5') + icDot(15.5, 16.5, 1.6),
  bell: icPath('M5 14V9A5 5 0 0 1 15 9V14M3 14H17') + icDot(10, 17.5),
  belloff: icPath('M5 14V9A5 5 0 0 1 12.5 4.7M15 9V14M3 14H17M3 3L17 17') + icDot(10, 17.5),
  bellring: icPath('M5 14V9A5 5 0 0 1 15 9V14M3 14H17M2 7A7.5 7.5 0 0 1 4 3M18 7A7.5 7.5 0 0 0 16 3') + icDot(10, 17.5),
  hourglass: icPath('M5 3H15M5 17H15M6 3C6 8 14 7 14 11.5M14 3C14 6 12 7.5 10 9M6 17C6 14 8 12.5 10 11.5') + icDot(10, 14.8, 1.7),
  repeat: icPath('M16 10A6 6 0 0 1 5 13.5M4 10A6 6 0 0 1 15 6.5M15 3V6.5H11.5') + icDot(4.5, 15.5, 1.7),
  clock: icPath('M17 10A7 7 0 1 1 10 3M10 7V10L13 12') + icDot(15.5, 4.5),
  dots: icFill(4.5, 10, 1.4) + icFill(10, 10, 1.4) + icFill(15.5, 10, 1.4),
  sub: icPath('M4 3V12A2 2 0 0 0 6 14H11M8 6H16') + icDot(15, 14),
  kanban: icPath('M4 3V17M10 3V12M16 3V9') + icDot(16, 14),
  play: icPath('M6 4L16 10L6 16Z'),
  pause: icPath('M7 4V16M13 4V16'),
  stop: icPath('M5 5H15V15H5Z'),
  edit: icPath('M4 16V12.5L12.5 4L16 7.5L7.5 16H4M10.5 6L14 9.5') + icDot(16, 16, 1.6),
  undo: icPath('M7 4.5L3.5 8L7 11.5M4 8H12A4.5 4.5 0 0 1 12 17H9'),
  redo: icPath('M13 4.5L16.5 8L13 11.5M16 8H8A4.5 4.5 0 0 0 8 17H11'),
  folder: icPath('M17 9V15A2 2 0 0 1 15 17H5A2 2 0 0 1 3 15V5A2 2 0 0 1 5 3H8L10 5.5H13') + icDot(16, 5.5),
  cart: icPath('M2.5 3.5H5L7 13H15L17 6.5H8') + icFill(8, 16.5, 1.3) + icDot(14.5, 16.5, 1.6),
  sort: icPath('M4.5 4V16M2 13.5L4.5 16L7 13.5M9.5 5H17M9.5 10H15M9.5 15H12.5'),
  eye: icPath('M2 10C4 6 7 4.5 10 4.5S16 6 18 10C16 14 13 15.5 10 15.5S4 14 2 10') + icDot(10, 10, 2.2),
  ban: icPath('M17 10A7 7 0 1 1 3 10A7 7 0 0 1 17 10M5 5L15 15'),
  upload: icPath('M3 13V16H17V13M10 3.5V12M6 7.5L10 3.5L14 7.5'),
  download: icPath('M3 13V16H17V13M10 3.5V12M6 8L10 12L14 8'),
  arrow: icPath('M4 10H16M11 5L16 10L11 15'),
  pin: icPath('M10 13.5V18M5.5 13.5H14.5M7 3H13M8 3V8L5.5 13.5M12 3V8L14.5 13.5'),
  mappin: icPath('M16 8.5C16 13 10 18 10 18S4 13 4 8.5A6 6 0 0 1 16 8.5') + icDot(10, 8.5),
  select: icPath('M16 10.5V15A2 2 0 0 1 14 17H5A2 2 0 0 1 3 15V5A2 2 0 0 1 5 3H11M7 9.5L10 12.5L17 4'),
  timeline: icPath('M3 5H9M3 10H13M3 15H7') + icDot(16.5, 10),
  filter: icPath('M3 4H17L11.5 10.5V16L8.5 17.5V10.5L5.5 7'),
  indent: icPath('M3 6.5L6 9.5L3 12.5M9 5H17M9 10H17M9 15H17'),
  outdent: icPath('M6 6.5L3 9.5L6 12.5M9 5H17M9 10H17M9 15H17'),
  alert: icPath('M10 3L17.5 16.5H2.5ZM10 8V11.5') + icFill(10, 14, 1.1),
  skip: icPath('M5 4L13 10L5 16ZM15.5 4V16'),
  stopwatch: icPath('M16 11.5A6 6 0 1 1 10 5.5M10 9V11.5M8 2.5H12') + icDot(15.2, 7, 1.8),
  archive: icPath('M3 4H17V7.5H3ZM4.5 7.5V15A2 2 0 0 0 6.5 17H13.5A2 2 0 0 0 15.5 15V7.5') + icDot(10, 12, 1.8),
  // 2.14.0 (#484): quick add: "add and open the details" (a window with its details panel) and "add with a file"
  qopen: icPath('M3 5A2 2 0 0 1 5 3H15A2 2 0 0 1 17 5V15A2 2 0 0 1 15 17H5A2 2 0 0 1 3 15ZM12 3V17') + icDot(7.5, 10, 1.6),
  qclip: icPath('M14.5 9L9.5 14A3.2 3.2 0 0 1 5 9.5L10.5 4A2.1 2.1 0 0 1 13.5 7L8.3 12.2A1.1 1.1 0 0 1 6.7 10.6L11.5 5.8') + icDot(16, 15.5, 1.6),
  clip: icPath('M15.5 9.5L10 15A3.5 3.5 0 0 1 5 10L11 4A2.3 2.3 0 0 1 14.3 7.3L8.5 13A1.2 1.2 0 0 1 6.8 11.3L12 6'),
  file: icPath('M11.5 3H6A2 2 0 0 0 4 5V15A2 2 0 0 0 6 17H14A2 2 0 0 0 16 15V8M7.5 11H12.5M7.5 14H10.5') + icDot(15, 4.5, 1.8),
  pdf: icPath('M11.5 3H6A2 2 0 0 0 4 5V15A2 2 0 0 0 6 17H14A2 2 0 0 0 16 15V8M7.5 15V10.5H9.5A1.5 1.5 0 0 1 9.5 13.5H7.5M12.5 10.5V15') + icDot(15, 4.5, 1.8),
  users: icPath('M2.5 17A5 5 0 0 1 12.5 17M10.5 8A3 3 0 1 1 4.5 8A3 3 0 0 1 10.5 8M14.5 12A4 4 0 0 1 17.5 16') + icDot(14.5, 7.5, 2.2),
  user: icPath('M4 17A6 6 0 0 1 16 17M13 8A3 3 0 1 1 7 8A3 3 0 0 1 13 8') + icDot(16, 4),
  logout: icPath('M8 3H5A2 2 0 0 0 3 5V15A2 2 0 0 0 5 17H8M12 6L16 10L12 14M16 10H7'),
  key: icPath('M9.5 14A3.5 3.5 0 1 1 6 10.5M8.5 11.5L16.5 3.5M13.5 6.5L15.5 8.5') + icDot(6, 14, 1.5),
  link: icPath('M8.5 11.5L11.5 8.5M9 5.5L10.5 4A3.2 3.2 0 0 1 16 8.5L14.5 10M11 14.5L9.5 16A3.2 3.2 0 0 1 4 11.5L5.5 10'),
  at: icPath('M13 10A3 3 0 1 1 7 10A3 3 0 0 1 13 10M13 7V11.5A2.5 2.5 0 0 0 18 11.5V10A8 8 0 1 0 14 17'),
  palette: icPath('M10 17A7 7 0 1 1 17 10C17 12 15.5 13 14 13H12.5A1.5 1.5 0 0 0 11.5 15.5') + icDot(13, 6.5, 1.6) + icFill(7, 7) + icFill(6.5, 11),
  sliders: icPath('M3 5H17M3 10H17M3 15H17') + icDot(13, 5) + icFill(7, 10, 2) + icFill(11, 15, 2),
  hash: icPath('M8 3L6 17M14 3L12 17M4 7.5H16M3.5 12.5H15.5'),  // 2.13.0: task numbers
  info: icPath('M17 10A7 7 0 1 1 3 10A7 7 0 0 1 17 10M10 9V14') + icDot(10, 6.3, 1.2),  // 2.13.0: the (i) of the helper texts
  help: icPath('M17 10A7 7 0 1 1 3 10A7 7 0 0 1 17 10M7.8 8A2.2 2.2 0 1 1 11 9.9C10.4 10.3 10 10.8 10 11.5') + icDot(10, 14.2, 1.3),
  comment: icPath('M17 10A7 7 0 0 1 6.5 16L3 17L4 13.5A7 7 0 1 1 17 10') + icDot(10, 10, 1.6),
  send: icPath('M17 3L10.5 17L8.5 11.5L3 9.5ZM8.5 11.5L17 3'),
  chart: icPath('M3 3V17H17M7 14V10M11 14V6') + icDot(15, 12, 1.8),
  phone: icPath('M6 4A2 2 0 0 1 8 2H12A2 2 0 0 1 14 4V16A2 2 0 0 1 12 18H8A2 2 0 0 1 6 16Z') + icDot(10, 15, 1.2),
  copy: icPath('M8 8H16V16H8ZM12 5V4H4V12H5'),
  lock: icPath('M4.5 9H15.5V17H4.5ZM7 9V6.5A3 3 0 0 1 13 6.5V9') + icDot(10, 13, 1.6),
  pulse: icPath('M2 10H5.5L8 4L12 16L14.5 10H15') + icDot(17.5, 10, 1.6),
  columns: icPath('M3 3H17V17H3ZM8 3V17M12.5 3V17'),
  deps: icPath('M5 7.5V9A3 3 0 0 0 8 12H15.5M12.5 9L15.5 12L12.5 15') + icDot(5, 4.5),
  collapse: icPath('M6 17L10 13L14 17M6 3L10 7L14 3'),
  grip: icFill(7.5, 5) + icFill(12.5, 5) + icFill(7.5, 10) + icFill(12.5, 10) + icFill(7.5, 15) + icFill(12.5, 15),
  expand: icPath('M6 13L10 17L14 13M6 7L10 3L14 7'),
  cloudoff: icPath('M3 3L17 17M6 7.5A4.5 4.5 0 0 0 6 16H14M17 14.3A3.5 3.5 0 0 0 14 8.5A5 5 0 0 0 8.5 5.2'),
  sync: icPath('M16 10A6 6 0 0 1 5 13.5M4 10A6 6 0 0 1 15 6.5M15 3V6.5H11.5M5 17V13.5H8.5'),
  panel: icPath('M3 3H17V17H3ZM8 3V17'),
  // 2.4.0: ticket types (#340), project types (#243)
  bug: icPath('M6 9A4 4 0 0 1 14 9V12A4 4 0 0 1 6 12ZM10 9V16M3 11H6M14 11H17M4 6.5L6 7.5M16 6.5L14 7.5M4 16L6 14.5M16 16L14 14.5') + icDot(10, 4.2, 1.8),
  bulb: icPath('M7.5 13.5C7.5 12 5 10.5 5 7.5A5 5 0 0 1 15 7.5C15 10.5 12.5 12 12.5 13.5ZM8 16.5H12') + icDot(10, 7.5, 1.8),
  tsq: icPath('M16 10.5V15A2 2 0 0 1 14 17H5A2 2 0 0 1 3 15V5A2 2 0 0 1 5 3H11M7 10L10 13') + icDot(15, 5),
  brief: icPath('M3 7H17V16H3ZM7 7V4H13V7') + icDot(10, 11.5, 1.6),
  code: icPath('M13 6L17 10L13 14M7 6L3 10L7 14'),
  home: icPath('M3 9L10 3L17 9M5 7.5V17H15V7.5') + icDot(10, 13, 1.8),
  // 2.19.0 (#653): the module Family
  family: icPath('M2.5 17V15.5A3.5 3.5 0 0 1 9.5 15.5V17M11 17V16.5A2.75 2.75 0 0 1 16.5 16.5V17M6 4.5A2.5 2.5 0 1 1 6 9.5A2.5 2.5 0 0 1 6 4.5') + icDot(13.75, 10.5, 1.9),
  cake: icPath('M4 17V11H16V17M2.5 17H17.5M4 13.5C6 15 8 12 10 13.5C12 15 14 12 16 13.5M10 11V8') + icDot(10, 5, 1.6),
  star: icPath('M10 3L12.1 7.6L17 8.2L13.4 11.6L14.3 16.5L10 14.1L5.7 16.5L6.6 11.6L3 8.2L7.9 7.6Z'),
  gift: icPath('M3 8H17V11H3ZM4.5 11V17H15.5V11M10 8V17M10 8C8.5 4.5 5.5 4.5 6 7M10 8C11.5 4.5 14.5 4.5 14 7'),
  meal: icPath('M4 9.5H16V12A4 4 0 0 1 12 16H8A4 4 0 0 1 4 12ZM2.5 9.5H17.5M7.5 6.5V5M12.5 6.5V5') + icDot(10, 4.5, 1.6),
  bag: icPath('M3 7H17V16.5H3ZM7.5 7V4.5H12.5V7M7 7V16.5M13 7V16.5'),
  // 2.22.0 (#663): Home & life
  heart: icPath('M10 16.5C5 13 2.5 10.5 2.5 7.5A3.5 3.5 0 0 1 10 5.5A3.5 3.5 0 0 1 17.5 7.5C17.5 10.5 15 13 10 16.5Z') + icDot(13.5, 7.5, 1.4),
  plane: icPath('M2.5 11.5L17.5 5.5L14 16L10.5 12.5L7.5 15.5V11.5ZM10.5 12.5L17.5 5.5') + icDot(4.5, 5, 1.4),
  book: icPath('M10 5.5C8 4 5.5 3.5 3 4V15.5C5.5 15 8 15.5 10 17C12 15.5 14.5 15 17 15.5V4C14.5 3.5 12 4 10 5.5ZM10 5.5V17') + icDot(13.5, 8, 1.4),
  tool: icPath('M12.5 3A4 4 0 0 0 9 8.5L3 14.5A1.8 1.8 0 0 0 5.5 17L11.5 11A4 4 0 0 0 17 7.5L14.5 10L11.5 9.5L10.5 6.5L13 4Z') + icDot(4.6, 15.4, 1.1),
  journal: icPath('M5 3H14A2 2 0 0 1 16 5V17H6A2 2 0 0 1 4 15V4A1 1 0 0 1 5 3ZM4 15A2 2 0 0 1 6 13H16M8 7H12') + icDot(10, 10, 1.3),
  turns: icPath('M4.5 10A5.5 5.5 0 0 1 14.5 6.5M15.5 10A5.5 5.5 0 0 1 5.5 13.5M12.5 4L14.5 6.5L12 8.5M7.5 16L5.5 13.5L8 11.5') + icDot(10, 10, 1.6),
};
const ic = (n, c = '') => `<svg class="i ${c}" viewBox="0 0 20 20" aria-hidden="true">${P[n] || ''}</svg>`;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
// colors from the server only ever reach a style attribute as a plain hex value
const cssColor = v => typeof v === 'string' && /^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(v) ? v : '';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const isMobile = () => matchMedia('(max-width:899px)').matches;
// ---- 2.7.0 (K13, #405): one layout for an unfolded foldable in both orientations. The phone / desktop switch is at
// 900 px; a near-square touch screen (an unfolded Fold is ~880-910 px each way) sat right on it and flipped between the
// tab bar and rail + sidebar when turned. Such a screen gets a layout width of at least 900 px in both orientations (the
// page is scaled down by a few percent instead), so it keeps the tablet layout. Phones and tablets with a clear portrait
// or landscape shape keep the plain device width.
// 2.13.0 (#453, iPhone): iOS Safari zooms into any field with a font below 16 px when it gets the focus (the page then
// looks cut off at the right and the input sits apart from the keyboard); maximum-scale=1 stops only that zoom, pinch
// zoom keeps working on iOS. iOS also ignores interactive-widget: bottom sheets follow the visual viewport (--vvb, vvSync)
const VIEWPORT = 'width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content' + (/iPad|iPhone|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1) ? ', maximum-scale=1' : '');
// 2.7.2 (hotfix): the orientation comes from the PHYSICAL screen (screen.orientation / screen.width), never from the media
// query (orientation: landscape): on Android that follows the viewport, so the on-screen keyboard (it shrinks the height)
// flipped it, the meta changed, the page re-laid out, the input lost its focus and the keyboard closed at once. And the meta
// never changes while something editable has the focus (it waits until the focus leaves).
const editFocused = () => { const e = document.activeElement; return !!e && (e.isContentEditable || (/^(INPUT|TEXTAREA|SELECT)$/.test(e.tagName) && !['button', 'checkbox', 'radio', 'submit', 'range', 'color', 'file'].includes(e.type))); };
function screenLandscape() {
  const t = screen.orientation?.type;
  if (typeof t === 'string' && t) return t.startsWith('landscape');
  return screen.width > screen.height;
}
let vpPending = false;
function stableViewport() {
  const m = document.querySelector('meta[name="viewport"]'); if (!m) return;
  let want = VIEWPORT;
  try {
    const a = screen.width, b = screen.height, lo = Math.min(a, b), hi = Math.max(a, b);
    const coarse = matchMedia('(pointer:coarse)').matches, square = coarse && lo >= 760 && hi >= 900 && hi / lo < 1.3;
    const land = screenLandscape(), w = land ? hi : lo;
    if (square && w < 900) want = 'width=900, viewport-fit=cover, interactive-widget=resizes-content';
    // 2.24.0 (#908): an unfolded foldable held sideways (landscape, 860-899 px wide, e.g. a Fold at ~880 px) gets the desktop
    // layout (sidebar + list + task panel): the page is laid out 900 px wide and scaled down by at most 4.5 %. Portrait
    // (unfolded ~690 px) stays the tablet layout, phones in landscape (< 860 px) stay as they are.
    else if (coarse && land && w >= 860 && w < 900) want = 'width=900, viewport-fit=cover, interactive-widget=resizes-content';
  } catch { /* no screen info: keep the default */ }
  if (m.getAttribute('content') === want) { vpPending = false; return; }
  if (editFocused()) { vpPending = true; return; }  // typing (the keyboard is up): later, when the focus leaves
  vpPending = false;
  m.setAttribute('content', want);
}
stableViewport();
try { if (screen.orientation?.addEventListener) screen.orientation.addEventListener('change', stableViewport); else window.addEventListener('orientationchange', stableViewport); } catch { /* old browsers */ }
document.addEventListener('focusout', () => { if (vpPending) setTimeout(() => { if (!editFocused()) stableViewport(); }, 0); }, true);
const LS = {
  get(k, d) { try { const v = localStorage.getItem('tasks.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('tasks.' + k, JSON.stringify(v)); } catch { /* private mode */ } },
  del(k) { try { localStorage.removeItem('tasks.' + k); } catch { /* private mode */ } },
};
// multi-user: everything under tasks.* belongs to the logged-in user (cache, outbox, tab bar, ...) except
// these device preferences. Wiped on logout and when another user logs in in the same browser.
// 1.5.3: helper lines are tooltips now; where there is no hover (touch) a hint shows once, until it is dismissed (×) or
// used. Settings > Appearance > "Show tips again" brings them back on this device.
// 2.13.0 (#453 P16): the logo inside the app follows the accent colour (the installed app icon keeps its own colours)
// 2.18.0 (#394): the app icon "on one leg" (tools/make_icons.py draws the same paths): light lines on the dark plate,
// the sun on the water line in the accent (svg.logo color in app.css), so the mark follows the chosen accent colour;
// the half sun is a path (no clipPath id, the logo can be on the page more than once)
const logoSvg = (sz = 20) => `<svg class="logo" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="${sz}" height="${sz}" aria-hidden="true" focusable="false"><rect width="100" height="100" rx="22" fill="#161a21"/><path d="M65 74A11 11 0 0 1 87 74Z" fill="currentColor"/><path d="M18 74H86" stroke="#e9e6f2" stroke-width="3" stroke-linecap="round" opacity=".55"/><g fill="none" stroke="#e9e6f2" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"><path d="M24 50C34 42 52 43 62 51C55 58 40 60 30 55"/><path d="M54 48C51 39 49 32 51 25C53 20 58 19 61 22"/><path d="M61 22L77 26"/><path d="M44 58V84"/><path d="M44 68L37 64L41 60" stroke-width="4"/></g></svg>`;
const hintSeen = k => (LS.get('hintsSeen', []) || []).includes(k);
function hintDone(k) { if (!hintSeen(k)) LS.set('hintsSeen', [...(LS.get('hintsSeen', []) || []), k]); }
const hintOnce = (k, text, cls = '') => isTouch() && !hintSeen(k) ? `<div class="muted mhint once ${cls}" data-hint="${k}"><span>${esc(text)}</span><button type="button" class="iconbtn hx" data-act="hint-x" data-k="${k}" aria-label="${esc(tr('Dismiss'))}" title="${esc(tr('Dismiss'))}">${ic('x', 's')}</button></div>` : '';
// 2.13.0 (#453): helper texts. A helper line (.shint) that only explains is no longer printed inline: it moves behind
// a small (i) button next to its heading / label (hover or keyboard focus shows it as a tooltip, a tap toggles it; the text
// stays in the DOM as the button's aria-describedby). Inline stay only lines that prevent data loss or security mistakes,
// that are needed to finish the step, or that show a state: class "keep", the kinds below, lines with links / buttons /
// code / fields, empty status lines that get filled later. One MutationObserver handles every dialog, sheet and view.
const II_KEEP = '.keep,.cnote,.warn,.wpstate,.updline,.aanone,.aimodoff,.trkeep,.rpsec,[role],[aria-live]';
let iiN = 0;
function infoize(root) {
  for (const h of (root.querySelectorAll ? root.querySelectorAll('.shint:not([data-ii])') : [])) {
    h.dataset.ii = '0';
    // 2.13.2 (#478): .iiok = code in the text is fine behind (i) (the tooltip shows it as text)
    if (h.matches(II_KEEP) || h.querySelector('a, button, input, select, textarea') || (!h.matches('.iiok') && h.querySelector('code')) || !h.textContent.trim()) continue;
    let a = null;
    for (let p = h.previousElementSibling, n = 0; p && n < 3 && !a; p = p.previousElementSibling, n++) {
      if (p.matches('h2, h3, h4, label, legend, .shead')) a = p;
      else if (p.matches('.row, .srow, .lrow')) a = p.querySelector(':scope > label, :scope > b, :scope > span:first-child:not([aria-hidden="true"])');  // 2.22.0 (#679): never a decorative letter
      else if (p.querySelector?.(':scope > label, :scope > h4')) a = p.querySelector(':scope > label, :scope > h4');
      if (p.matches('.shint')) break;
    }
    if (!a && h.parentElement?.matches('details')) a = h.parentElement.querySelector(':scope > summary');
    h.dataset.ii = '1'; h.id = h.id || 'ii' + (++iiN); h.classList.add('iisrc');
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'ib' + (a ? '' : ' ibl'); b.dataset.ii = h.id; b.setAttribute('aria-describedby', h.id); b.setAttribute('aria-expanded', 'false');
    b.setAttribute('aria-label', tr('More information')); b.innerHTML = ic('info', 's') + (a ? '' : `<span>${esc(tr('More information'))}</span>`);
    if (a) a.appendChild(b); else h.before(b);
  }
}
new MutationObserver(ms => { for (const m of ms) for (const n of m.addedNodes) if (n.nodeType === 1) { if (n.classList.contains('shint')) infoize(n.parentElement || n); else if (n.getElementsByClassName('shint').length) infoize(n); } })
  .observe(document.documentElement, {childList: true, subtree: true});
function iiShow(b, pinned) {
  const src = document.getElementById(b.dataset.ii); if (!src) return;
  let t = $('#iitip');
  if (!t) { t = document.createElement('div'); t.id = 'iitip'; t.setAttribute('role', 'tooltip'); document.body.appendChild(t); }
  t.textContent = src.textContent.trim(); t.classList.remove('hidden'); t.dataset.for = b.dataset.ii; t.classList.toggle('pin', !!pinned);
  t.classList.toggle('pl', src.classList.contains('pl'));  // 2.15.0: one line per entry (the permissions)
  $$('.ib[aria-expanded="true"]').forEach(x => x !== b && x.setAttribute('aria-expanded', 'false')); b.setAttribute('aria-expanded', String(!!pinned));
  const r = b.getBoundingClientRect(), w = Math.min(t.offsetWidth, innerWidth - 16), h = t.offsetHeight;
  t.style.left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 8)) + 'px';
  t.style.top = (r.bottom + 6 + h > innerHeight - 8 && r.top - 6 - h > 8 ? r.top - 6 - h : r.bottom + 6) + 'px';
}
function iiHide(force) { const t = $('#iitip'); if (!t || (t.classList.contains('pin') && !force)) return; t.classList.add('hidden'); t.classList.remove('pin'); $$('.ib[aria-expanded="true"]').forEach(x => x.setAttribute('aria-expanded', 'false')); }
document.addEventListener('click', e => {
  const b = e.target.closest?.('.ib[data-ii]');
  if (b) { e.preventDefault(); e.stopPropagation(); const t = $('#iitip'); if (t && !t.classList.contains('hidden') && t.classList.contains('pin') && t.dataset.for === b.dataset.ii) iiHide(true); else iiShow(b, true); return; }
  if (!e.target.closest?.('#iitip')) iiHide(true);
}, true);
document.addEventListener('mouseover', e => { const b = e.target.closest?.('.ib[data-ii]'); if (b && !isTouch()) iiShow(b); });
document.addEventListener('mouseout', e => { if (e.target.closest?.('.ib[data-ii]')) iiHide(); });
document.addEventListener('focusin', e => { if (e.target.matches?.('.ib[data-ii]')) iiShow(e.target); });
document.addEventListener('focusout', e => { if (e.target.matches?.('.ib[data-ii]')) iiHide(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && $('#iitip:not(.hidden)')) { iiHide(true); e.stopPropagation(); } }, true);
document.addEventListener('scroll', () => iiHide(true), true);
const hintK = t => `<div class="shint keep">${t}</div>`;  // 2.13.0: a helper line that stays inline (security, data loss, a state)
const kt = (label, keys) => isTouch() ? label : `${label} (${kbText(keys)})`;  // a label with its keyboard shortcut
const LS_KEEP = new Set(['tasks.theme', 'tasks.i18n', 'tasks.density', 'tasks.densitySide', 'tasks.densityRows', 'tasks.densSideV', 'tasks.densRowsV', 'tasks.fsize', 'tasks.font', 'tasks.accent', 'tasks.accentMig280', 'tasks.pw.det', 'tasks.pw.chat', 'tasks.sideGroups', 'tasks.agband', 'tasks.sideFold']);
function clearLocal() {
  try {
    const ks = [];
    for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k && k.startsWith('tasks.') && !LS_KEEP.has(k)) ks.push(k); }
    ks.forEach(k => localStorage.removeItem(k));
  } catch { /* private mode */ }
}
// design per device: auto (follows the OS) | dark | light
function applyTheme() {
  const pref = LS.get('theme', 'auto');
  document.documentElement.dataset.theme = pref;
  const light = pref === 'light' || (pref === 'auto' && matchMedia('(prefers-color-scheme: light)').matches);
  const m = document.querySelector('meta[name="theme-color"]'); if (m) m.content = light ? '#f8f8f9' : '#16171a';
}
applyTheme();
try { matchMedia('(prefers-color-scheme: light)').addEventListener('change', applyTheme); } catch { /* old browser */ }
// density per device: compact (default on desktop) | comfortable (default on phones and touch screens)
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || '');
const isTouch = () => { try { return isMobile() || matchMedia('(hover: none)').matches; } catch { return false; } };
// 2.16.0 (#642): "Custom" = the sidebar (lists, folders, filters) and the task rows each compact or comfortable; Compact /
// Comfortable set both (before, the sidebar ignored the density)
const DENS_OK = v => v === 'compact' || v === 'comfortable';
const densityMode = () => { const v = LS.get('density', null); return v === 'custom' || DENS_OK(v) ? v : (isTouch() ? 'comfortable' : 'compact'); };
const densityPref = () => { const m = densityMode(); if (m !== 'custom') return m; const v = LS.get('densityRows', null); return DENS_OK(v) ? v : (isTouch() ? 'comfortable' : 'compact'); };
const sideDensityPref = () => { const m = densityMode(); if (m !== 'custom') return m; const v = LS.get('densitySide', null); return DENS_OK(v) ? v : (isTouch() ? 'comfortable' : 'compact'); };
// 2.18.0 (#642): "Custom" = two sliders, the row spacing of the sidebar and of the task rows, 0-100 % each
// (LS densSideV / densRowsV per device). They only change the spacing: on touch screens rows never go below 44 px,
// with a mouse they may get as tight as 24 px (WCAG 2.5.8). Without a stored value a slider starts at the step the
// device showed before (compact / comfortable of 2.16.0).
// 2.18.0 (review R8): starting "Custom" must not make the layout jump, so the sliders map piecewise-linearly through
// anchors: at the start value of Compact / Comfortable (per device: mouse and touch differ) they give exactly the CSS
// values of that preset (app.css :root / data-density / data-sdensity); between the anchors linear, 0 = tight, 100 = airy.
// On touch the sidebar rows are 44 px in both presets (only the gaps differ), so there Compact starts at 0, Comfortable at 20.
const DENS_A = {side: {mouse: {at: [0, 20, 60, 100], h: [1.5, 1.75, 2.25, 2.75]}, touch: {at: [0, 20, 100], h: [2.75, 2.75, 3.25]}},
  rows: {at: [0, 33, 67, 100], py: [.125, .375, .625, .875], mouse: [1.5, 2.5, 2.75, 3.25], touch: [2.75, 2.75, 2.75, 3.5]}};
const DENS_V = k => k === 'side' ? (isTouch() ? {compact: 0, comfortable: 20} : {compact: 20, comfortable: 60}) : {compact: 33, comfortable: 67};
const densV = k => { const n = +LS.get(k === 'side' ? 'densSideV' : 'densRowsV', NaN); if (n >= 0 && n <= 100) return Math.round(n);
  return DENS_V(k)[k === 'side' ? sideDensityPref() : densityPref()] ?? 50; };
function densLerp(at, ys, v) {
  for (let i = 1; i < at.length; i++) if (v <= at[i]) return ys[i - 1] + (ys[i] - ys[i - 1]) * (v - at[i - 1]) / (at[i] - at[i - 1]);
  return ys[ys.length - 1];
}
function densVars(side, rows) {  // the CSS variables of the custom density (rem)
  const t = isTouch(), A = DENS_A, f = x => +x.toFixed(4) + 'rem', sa = A.side[t ? 'touch' : 'mouse'];
  return {'--srow-h': f(densLerp(sa.at, sa.h, side)), '--row-py': f(densLerp(A.rows.at, A.rows.py, rows)), '--row-h': f(densLerp(A.rows.at, A.rows[t ? 'touch' : 'mouse'], rows)),
    '--row-fs': rows < 50 ? '.875rem' : '.9375rem', '--meta-fs': rows < 50 ? '.75rem' : '.78125rem'};
}
function applyDensity() {
  const el = document.documentElement, r = el.dataset, custom = densityMode() === 'custom', vars = densVars(densV('side'), densV('rows'));
  r.density = custom ? 'custom' : densityPref(); r.sdensity = custom ? 'custom' : sideDensityPref();
  // 2.18.0 (review R8): the sidebar's gaps (group margins, search field, footer) of Compact up to halfway to Comfortable
  const sv = DENS_V('side');
  if (custom && densV('side') < (sv.compact + sv.comfortable) / 2) r.sbase = 'compact'; else delete r.sbase;
  for (const [k, v] of Object.entries(vars)) { if (custom) el.style.setProperty(k, v); else el.style.removeProperty(k); }
}
applyDensity();
// Appearance per device (settings > Appearance, command palette): font size (rem scale, see app.css), font, accent.
// Values are checked against these tables; anything else in localStorage falls back to the default (first entry).
// The accent drives everything that is mint by default (buttons, links, focus, selection, tab bar, timer pill,
// charts, confetti, the heron's sun and the in-app logo's sun); the installed app icon keeps its own colours.
const LOOK = {
  fsize: [['m', N_('Normal'), 1], ['s', N_('Small'), .9], ['l', N_('Large'), 1.12], ['xl', N_('Extra large'), 1.25]],
  font: [['geist', 'Geist'], ['system', N_('System font')], ['atkinson', 'Atkinson Hyperlegible']],
  // [key, name, dark, light] (ink colours and the CSS variables live in app.css :root[data-accent=...])
  // 2.11.0 (#449): violet is the default (first entry); raspberry (the 2.8.0 default) and mint (before) stay selectable.
  // The default is never stored (lookSet null), so every device that never picked a colour gets violet; picked ones stay.
  accent: [['violet', N_('Violet'), '#a78bfa', '#6d4bd8'], ['raspberry', N_('Raspberry'), '#f472b6', '#be185d'], ['mint', N_('Mint'), '#2dd4bf', '#0a766b'], ['sky', N_('Sky'), '#38bdf8', '#0b6aa2'],
    ['rose', N_('Rose'), '#f472b6', '#b8306f'], ['orange', N_('Orange'), '#fb923c', '#ad4c07'], ['lime', N_('Lime'), '#a3e635', '#4a7110']],
};
try { if (localStorage.getItem('tasks.accent') === '"amber"') localStorage.setItem('tasks.accent', '"orange"'); } catch { /* private mode */ }  // 1.1.3: Amber became Orange
// 2.8.0 (#434): a device that had the old default (mint) gets the new default once; a colour picked later stays
try { if (!localStorage.getItem('tasks.accentMig280')) { if (localStorage.getItem('tasks.accent') === '"mint"') localStorage.removeItem('tasks.accent'); localStorage.setItem('tasks.accentMig280', '1'); } } catch { /* private mode */ }
const lookPref = k => { const v = LS.get(k, null); return (LOOK[k].find(x => x[0] === v) || LOOK[k][0])[0]; };
const lookRow = k => LOOK[k].find(x => x[0] === lookPref(k));
// 2.13.0 (#429): the font size is a percentage (75-150 since 2.13.2) in steps of 5 (per device, LS fsize); the old steps s / m / l / xl
// (90 / 100 / 112 / 125) are read as their percentages. Named steps keep data-fsize (the CSS rules), any other value sets
// --ui inline. Below 100 % touch screens keep 44 px hit areas (app.css: .ui-small), only the text and spacing shrink.
const FS_OLD = {s: 90, m: 100, l: 112, xl: 125};
// 2.13.2 (#478 N5, decision #429): 75-150 %. At 50 % the text was 7.5 px (unreadable) and the 44 px touch rows bent the
// proportions; a stored value below 75 (2.13.0 / 2.13.1) counts as 75
const FS_MIN = 75, FS_MAX = 150;
const fsPct = () => { const v = LS.get('fsize', null); if (typeof v === 'string' && v in FS_OLD) return FS_OLD[v]; const n = +v; return n >= 50 && n <= FS_MAX ? Math.max(FS_MIN, Math.round(n)) : 100; };
const uiZ = () => fsPct() / 100;  // UI scale factor for sizes drawn in JS (week grid, charts, tour card)
function applyLook() {
  const r = document.documentElement.dataset, pct = fsPct(), named = Object.keys(FS_OLD).find(k => FS_OLD[k] === pct);
  r.fsize = named || 'custom'; document.documentElement.style.setProperty('--ui', named ? '' : String(pct / 100));
  if (named) document.documentElement.style.removeProperty('--ui');
  document.documentElement.classList.toggle('ui-small', pct < 100);
  r.font = lookPref('font'); r.accent = lookPref('accent');
}
applyLook();
// one setter for all device appearance settings (settings pane, palette); v = null -> default
// 2.13.0 (#429): one step (±5 %) or back to 100 % (0); also Ctrl / ⌘ + / − / 0 on desktops (the app's size, not the
// browser zoom)
function fsStep(d) { const v = d ? Math.max(FS_MIN, Math.min(FS_MAX, fsPct() + d)) : 100; lookSet('fsize', v === 100 ? null : v); const sl = $('#s-fsize'); if (sl) { sl.value = v; fsLabel(v); } toast(tr('Font size: {0}', v + ' %')); }
function fsLabel(v) { const o = $('#s-fsv'); if (o) o.textContent = v + ' %'; const sl = $('#s-fsize'); if (sl) sl.setAttribute('aria-valuetext', v + ' %'); const r = $('[data-m="fs-reset"]'); if (r) r.disabled = +v === 100; }
document.addEventListener('keydown', e => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || isTouch()) return;
  const d = {'+': 5, '=': 5, '-': -5, '_': -5, '0': 0}[e.key]; if (d === undefined) return;
  e.preventDefault(); fsStep(d);
});
function lookSet(k, v) {
  const prev = [sideDensityPref(), densityPref()];  // 2.16.0 (#642): "Custom" starts from what is shown now
  const prev0 = densityMode();
  if (v == null) LS.del(k); else LS.set(k, v);
  if (k === 'density' && v === 'custom' && prev0 !== 'custom') { LS.set('densitySide', prev[0]); LS.set('densityRows', prev[1]); LS.del('densSideV'); LS.del('densRowsV'); }  // 2.18.0 (review R8): the sliders start at what is shown now, not at an old custom value
  if ((k === 'densitySide' || k === 'densityRows') && v != null && LS.get('density', null) !== 'custom') { LS.set(k === 'densitySide' ? 'densityRows' : 'densitySide', k === 'densitySide' ? prev[1] : prev[0]); LS.set('density', 'custom'); }
  if (k === 'theme') applyTheme(); else if (/^density/.test(k)) applyDensity(); else applyLook();
  if (k === 'fsize' && typeof render === 'function' && S.settings) render();  // week grid, timeline and charts are drawn in px
}
