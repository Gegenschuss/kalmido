// 2.102.0 (#1995): types of the web client's shared globals for the type check (jsconfig.json, tsc --noEmit). Only tsc reads
// this file; the app never loads it. Keep it small: the fields many files use, everything else stays `any` (index signature),
// so a file can switch on `// @ts-check` without typing the whole client first.

/** The route of the open view (core.js parseHash / S.route). */
interface KalmidoRoute {
  mod: string;
  key?: string | number;
  [k: string]: any;
}

/** The person signed in (state "me"). */
interface KalmidoMe {
  id: number;
  username: string;
  display_name?: string;
  is_admin?: boolean;
  [k: string]: any;
}

/** GET /api/about, also state "about" (core/instance.py about_info). */
interface KalmidoAbout {
  version: string;
  /** 2.102.0 (#1999): the server operator chose a list for the browser's error reports */
  client_errors?: boolean;
  client_errors_list?: number | null;
  client_errors_lists?: {id: number, name: string}[];
  [k: string]: any;
}

interface KalmidoList {
  id: number;
  name: string;
  [k: string]: any;
}

interface KalmidoTask {
  id: number;
  list_id: number;
  title: string;
  status: number;
  [k: string]: any;
}

/** The client's state object `S` (core.js). Known fields typed, the rest any. */
interface KalmidoState {
  lists: KalmidoList[];
  sections: any[];
  tasks: Map<number, KalmidoTask>;
  settings: Record<string, any>;
  me: KalmidoMe | null;
  route: KalmidoRoute;
  about?: KalmidoAbout;
  sel: number | null;
  multi: Set<number>;
  v: number;
  [k: string]: any;
}

/** An error api() throws for an answer that is not ok (core.js rawFetch0). */
interface KalmidoApiError extends Error {
  status?: number;
  data?: any;
  shown?: boolean;
}

// The client hangs stand-ins and hooks on window (lazyload.js LD_CALL, oa_switchLoad, ...): any name may be there.
interface Window {
  [k: string]: any;
}

/** Network Information API (Chrome / Android): data saver and connection type, missing elsewhere. */
interface Navigator {
  connection?: {saveData?: boolean, effectiveType?: string};
}

// The client finds its elements with closest() / querySelector() and reads data-* attributes from what they return (always
// HTML elements here), so dataset is known on Element too.
interface Element {
  dataset: DOMStringMap;
}
