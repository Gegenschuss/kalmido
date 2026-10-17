/* Kalmido web client: the lock per list -- data layer (2.64.1, #1817). Classic script sharing the global scope (load order:
   index.html). List keys (fetch, unwrap, wrap for members), encrypting / decrypting the texts of a locked list, the hooks
   where tasks enter and leave the client state (state, delta, answers, cache, outbox), switching on / off (migration).
   Built on e2e.js (2.42.0): the person's keys E2E.priv / E2E.ckey; server side kalmido/collab/liste2e.py. */
'use strict';
