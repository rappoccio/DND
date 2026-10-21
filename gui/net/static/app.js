"use strict";
/*
 * The player's client (MULTIPLAYER_PLAN.md M4e, M5a, M4b.3).
 *
 * Four things happen here and nothing else: a join code becomes a credential
 * (`POST /join`), the credential opens `WS /live` and authenticates it with its first
 * frame (A3), every `view` that arrives is drawn, and a `prompt` this player may answer is
 * shown with its options and answered with one `submit` (M5a). The socket carries exactly
 * two frame kinds client→server, `auth` and `submit`, each sent from one place, and the
 * suite counts them (F-M5-5).
 *
 * Four rules this file exists to obey:
 *
 *   · **The credential lives in `sessionStorage`** (D-M4e-2). A reload keeps the seat; the
 *     tab closing drops it, which matches the credential's own lifetime — the signing key
 *     is minted in memory at process start (A5), so a credential cannot usefully outlive
 *     the tab by much. Never a cookie (A3), never `localStorage`.
 *
 *   · **The picture and the mask do not agree.** `fog.explored_runs` is live; `map.image`
 *     lags up to 3 s (D-M4-1). The lag is only ever *extra* fog, so a cell the party has
 *     just earned can read as dark art until the image re-keys. This file draws the live
 *     mask over the lagging picture in the server's own fog colour, which makes the two
 *     disagree invisibly rather than wrongly. It must never infer the mask FROM the picture.
 *
 *   · **`role` is a label, never a permission** (A8). Every real decision was made
 *     server-side by `authorize()`; this file branches on what it was *given* — a token
 *     with `hp.cur` was one this viewer is entitled to see numbers for — and never on who
 *     it thinks it is.
 *
 *   · **The board is nominal.** `map` carries `cell_px`, `cols` and `rows`, so the lattice
 *     here is `col * cell_px`, while the DM console and the server-side mask both use the
 *     page's real grid-line positions. What keeps the two together is the server: the
 *     image it sends is cropped to the outermost grid lines (owed item 11), so stretching
 *     it onto this lattice lands the grid's edges on the lattice's edges, and what is left
 *     is the page's spacing jitter — a few px. Before the crop the page's margins were
 *     stretched too, and on `TestDNDMap.png` the right-hand column sat 3.7 cells off its
 *     art. Drawing on the real lines needs them in Envelope 2, an M3-frozen change (M4b).
 */

const PROTOCOL_VERSION = 1;
const CRED_KEY = "dnd.credential";        // sessionStorage, per D-M4e-2
const NAME_KEY = "dnd.principal";
const MASK = "rgb(24, 24, 28)";           // net/mapimg.py MASK_RGB
const WS_UNAUTHENTICATED = 4401;          // net/server.py WS_CLOSE_UNAUTHENTICATED
const RETRY_MS = [1000, 2000, 4000, 8000, 10000];

const el = (id) => document.getElementById(id);
const canvas = el("board");
const ctx = canvas.getContext("2d");

let socket = null;
let view = null;
let prompt = null;                         // the last `prompt` frame; shown only while live
let awaiting = "";                         // the prompt id a submit is out for, or ""
let ackNote = "";                          // what the last failed ack said, in words
let promptEndsAt = 0;                      // performance.now() when the prompt is skipped; 0 = never
let filter = { id: "", text: "" };         // the filter box, for the prompt it was typed into
let attempt = 0;
let page = { url: "", img: null, objectUrl: "" };   // the map image, re-fetched on a re-key
let pageFail = { url: "", at: 0 };        // the last key that would not load, and when
const PAGE_RETRY_MS = 5000;               // …so a failing key is retried, but not per frame

// ── Session storage, which is allowed to fail ───────────────────────────────
// Private browsing and a locked-down phone both throw on access rather than returning
// null. A player who cannot store a credential should still be able to play until they
// reload, so every access is guarded and a failure degrades to "not stored".

function remember(key, value) {
  try { sessionStorage.setItem(key, value); } catch (e) { /* not stored; still playable */ }
}

function recall(key) {
  try { return sessionStorage.getItem(key); } catch (e) { return null; }
}

function forget(key) {
  try { sessionStorage.removeItem(key); } catch (e) { /* nothing to do */ }
}

// ── Joining (Envelope 1) ────────────────────────────────────────────────────

async function join(code, name) {
  const res = await fetch("/join", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // `display_name` is a matching HINT, not a rename: the server never relabels a seat
    // with it (D-M4c-4). Sending it is how a player who reconnects after a restart lands
    // back in their own chair.
    body: JSON.stringify({ v: PROTOCOL_VERSION, t: "auth", join_code: code,
                           display_name: name })
  });
  let body = {};
  try { body = await res.json(); } catch (e) { /* an HTML error page, or nothing */ }
  if (res.status !== 202 || !body.ok || !body.credential) {
    // One opaque failure for every cause, because that is all the server sent (Step 0.5's
    // closed `error` set). Guessing at which check failed would be inventing detail.
    throw new Error(res.status === 429
      ? "Too many attempts. Wait a minute and try again."
      : "That code was not accepted.");
  }
  remember(CRED_KEY, body.credential);
  remember(NAME_KEY, body.principal ? (body.principal.display_name || "") : "");
  return body;
}

// ── The socket (A3 first-frame auth, D-M4e-3) ───────────────────────────────

function connect() {
  const credential = recall(CRED_KEY);
  if (!credential) { showJoin(); return; }

  showSession();
  setStatus("connecting…", null);
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  socket = new WebSocket(`${scheme}//${location.host}/live`);

  socket.onopen = () => {
    // The one and only frame this client ever sends. The browser cannot put the credential
    // in a header (A3), so it goes here, and the server sends nothing back until it
    // verifies it.
    socket.send(JSON.stringify({ v: PROTOCOL_VERSION, t: "auth", credential }));
  };

  socket.onmessage = (event) => {
    let frame;
    try { frame = JSON.parse(event.data); } catch (e) { return; }
    if (!frame || frame.v !== PROTOCOL_VERSION) return;
    if (frame.t === "view") {
      attempt = 0;
      setStatus("live", true);
      render(frame);
    } else if (frame.t === "events") {
      onEvents(frame);
    } else if (frame.t === "prompt") {
      if (!prompt || prompt.id !== frame.id) { awaiting = ""; ackNote = ""; }
      prompt = frame;
      // `deadline_ms` is the time left when the frame was built (D-M5-7), re-sent every
      // cycle, so the countdown re-anchors on each push and never drifts far.
      promptEndsAt = frame.deadline_ms == null ? 0 : performance.now() + frame.deadline_ms;
      drawPrompt();
      if (view) drawBoard();   // a target pick rings tokens instead of painting squares
    } else if (frame.t === "submit_ack") {
      onAck(frame);
    }
  };

  socket.onclose = (event) => {
    socket = null;
    seq = null;          // the next socket starts from a view, never from an events frame
    if (event.code === WS_UNAUTHENTICATED) {
      // The credential was refused or revoked: the DM closed the seat, or the game
      // restarted and took the signing key with it (A5). Reconnecting cannot help, so
      // the credential goes and the join card comes back.
      forget(CRED_KEY);
      showJoin("Your seat was closed. Join again.");
      return;
    }
    const wait = RETRY_MS[Math.min(attempt, RETRY_MS.length - 1)];
    attempt += 1;
    setStatus(`reconnecting in ${Math.round(wait / 1000)}s…`, false);
    setTimeout(connect, wait);
  };
}

// ── Answering (Envelope 4, M5a) ─────────────────────────────────────────────

/* A prompt with more options than this gets a filter box (D-M1-12c): Wish lists 389
   spells and Divine Intervention 80. The box only hides buttons. What was typed never
   leaves this page, and the answer is still an option id (Step 0.5's no-free-text rule). */
const FILTER_AT = 40;

/* The second and last kind of frame this client sends. `answer` is exactly one of
   `{option: id}`, `{cell: [col, row]}` or `{cancel: true}` — never a string the player
   typed (Step 0.5's no-free-text rule). The server decides it on the frame tick and answers with a
   `submit_ack`; everything the answer DID reaches this client as the next `view`. */
function submit(answer) {
  if (!socket || !prompt || awaiting) return;
  awaiting = prompt.id;
  ackNote = "";
  drawPrompt();
  socket.send(JSON.stringify(Object.assign({ v: PROTOCOL_VERSION, t: "submit", id: prompt.id },
                                           answer)));
}

const ACK_WORDS = {
  not_live: "Already resolved.",
  denied: "That decision is not yours to make.",
  bad_option: "That option is not available.",
  protocol: "The table did not understand that answer.",
  // Step 0.5: the outcome is unknown, so this says so and waits for the next view rather
  // than retrying — a blind resubmit is a second valid submission (NN4).
  timeout: "The table is busy. Waiting to see whether it landed…",
};

function onAck(frame) {
  if (frame.id !== awaiting) return;
  if (frame.ok) {
    ackNote = "";                    // the next view drops `prompt_id`; nothing to say
  } else {
    ackNote = ACK_WORDS[frame.error] || "Not accepted.";
    // A timeout stays locked until a view arrives; every other refusal is final for this
    // answer, and the player may pick again if the prompt is still theirs.
    if (frame.error !== "timeout") awaiting = "";
  }
  drawPrompt();
}

/* Shown only while the view names it. `you.prompt_id` is the authority on liveness — it
   passed `authorize()` on the frame tick — and the `prompt` frame is only the body. */
function drawPrompt() {
  const box = el("prompt");
  const live = view && prompt && view.you.prompt_id === prompt.id;
  const waiting = view && view.you.prompt_id && !live;
  box.hidden = !live && !waiting;
  el("prompt-title").textContent = live ? prompt.title
    : "You are being asked for a decision…";
  const list = el("prompt-options");
  list.textContent = "";
  el("prompt-cancel").hidden = !live || prompt.cancellable === false;
  el("prompt-cancel").disabled = !!awaiting;
  el("prompt-note").textContent = ackNote;
  el("prompt-note").hidden = !ackNote;
  el("prompt-hint").hidden = !(live && prompt.expects === "cell");
  el("prompt-hint").textContent = live && prompt.kind === "target"
    ? "Tap a creature on the board." : "Tap a highlighted square.";
  drawTimer();
  const filterBox = el("prompt-filter");
  if (!live || filter.id !== prompt.id) {
    filter = { id: live ? prompt.id : "", text: "" };
    filterBox.value = "";
  }
  filterBox.hidden = !live || prompt.options.length <= FILTER_AT;
  if (!live) return;
  const needle = filter.text.trim().toLowerCase();
  for (const option of prompt.options) {
    if (needle && !option.label.toLowerCase().includes(needle)) continue;
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = option.label;
    button.disabled = !option.enabled || !!awaiting;
    button.addEventListener("click", () => submit({ option: option.id }));
    item.append(button);
    if (!option.enabled && option.disabled_reason) {
      const why = document.createElement("span");
      why.className = "hint";
      why.textContent = ` ${option.disabled_reason}`;
      item.append(why);
    }
    list.append(item);
  }
}

/* A reaction the player owns is skipped when the DM's timer runs out. The server decides
   that on its own clock; this only says how long is left. */
function drawTimer() {
  const timer = el("prompt-timer");
  const live = view && prompt && view.you.prompt_id === prompt.id;
  if (!live || !promptEndsAt) { timer.hidden = true; return; }
  const left = Math.max(0, Math.ceil((promptEndsAt - performance.now()) / 1000));
  timer.textContent = `Skipped in ${left} s if you don't answer`;
  timer.hidden = false;
}
setInterval(drawTimer, 250);

// ── Rendering ───────────────────────────────────────────────────────────────

function render(next) {
  view = next;
  seq = next.seq;      // a view sets the client's seq (B-3); an events frame continues it
  el("who").textContent = recall(NAME_KEY) || "at the table";
  // A timed-out submit is resolved by this view either way: the prompt is gone, or it is
  // still live and the player may answer it again.
  if (awaiting && awaiting !== view.you.prompt_id) { awaiting = ""; ackNote = ""; }
  else if (awaiting && ackNote) awaiting = "";
  drawPrompt();

  el("round").textContent = view.combat.active ? view.combat.round : "–";
  el("combat-state").textContent = view.combat.active
    ? (view.combat.paused ? "(paused)" : "") : "(out of combat)";

  drawInitiative();
  drawTokens();
  drawLog();
  drawBoard();
}

function agentByIndex(idx) {
  return view.agents.find((a) => a.agent === idx) || null;
}

/* How a token is coloured, and why it is not by faction: `yours` is the roster's own
   answer, and `hp.cur` is the entitlement `authorize()` already granted — party vitals are
   table information (M3). So "has numbers" reads as an ally and "has a band" reads as
   everyone else, which is exactly what this viewer was told and nothing more. */
function classOf(agent) {
  if (agent.yours) return "mine";
  return (agent.hp && agent.hp.cur !== undefined) ? "ally" : "other";
}

function hpText(agent) {
  const hp = agent.hp || {};
  if (hp.cur !== undefined) return `${hp.cur}/${hp.max}`;
  return hp.band || "";
}

function drawInitiative() {
  const list = el("initiative");
  list.textContent = "";
  /* `combat.turn_idx` indexes the UNFILTERED order, so counting rows would mark the wrong
     creature exactly when a hidden one exists. `turn_agent` (D-M5-5) is the agent index
     itself, and null when the creature on turn is one this view does not carry — so no row
     is marked, and nothing about the hidden one is inferred. */
  for (const entry of view.combat.initiative) {
    const agent = agentByIndex(entry.agent);
    const row = document.createElement("li");
    if (entry.agent === view.combat.turn_agent) row.className = "turn";
    const who = document.createElement("span");
    who.textContent = agent ? agent.name : `#${entry.agent}`;
    if (agent) who.className = classOf(agent);
    const total = document.createElement("span");
    total.className = "hint";
    total.textContent = entry.total;
    row.append(who, total);
    list.append(row);
  }
  if (!view.combat.initiative.length) {
    const row = document.createElement("li");
    row.className = "hint";
    row.textContent = "no initiative order";
    list.append(row);
  }
}

function drawTokens() {
  const list = el("tokens");
  list.textContent = "";
  for (const agent of [...view.agents].sort((a, b) => a.name.localeCompare(b.name))) {
    const row = document.createElement("li");
    const who = document.createElement("span");
    who.className = classOf(agent);
    who.textContent = agent.name;
    const right = document.createElement("span");
    right.textContent = hpText(agent);
    if (agent.conditions && agent.conditions.length) {
      const conds = document.createElement("span");
      conds.className = "conds";
      conds.textContent = ` ${agent.conditions.join(", ")}`;
      right.append(conds);
    }
    row.append(who, right);
    list.append(row);
  }
}

function drawLog() {
  const list = el("log");
  list.textContent = "";
  for (const line of view.log.slice(-60)) {
    const row = document.createElement("li");
    row.textContent = line;
    list.append(row);
  }
  list.scrollTop = list.scrollHeight;
}

// ── The board ───────────────────────────────────────────────────────────────

function drawBoard() {
  const map = view.map;
  const cell = map.cell_px || 1;
  const w = Math.max(1, map.cols * cell);
  const h = Math.max(1, map.rows * cell);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }

  ctx.fillStyle = MASK;
  ctx.fillRect(0, 0, w, h);

  // The image is named, not inlined, so it caches between re-keys (D-M4-1). It is fetched
  // again only when `map.image` changes — which for a player is when the party earns a
  // cell and the mask hash moves.
  const url = map.image || "";
  if (url && url !== page.url
      && !(url === pageFail.url && Date.now() - pageFail.at < PAGE_RETRY_MS)) {
    page.url = url;
    loadPage(url);
  } else if (!url) {
    releasePage();
  }
  if (page.img && page.img.complete && page.img.naturalWidth) {
    // Stretched to the nominal lattice rather than drawn at natural size: see the header's
    // fourth rule. The server crops the image to the grid, so this stretch maps its outer
    // lines onto the lattice's and keeps the art and the tokens in one coordinate space.
    ctx.drawImage(page.img, 0, 0, w, h);
  }

  drawFog(cell, map.cols, map.rows);
  drawGrid(cell, map.cols, map.rows);
  drawReachable(cell);
  drawAoe(cell);
  for (const agent of displayed()) drawToken(agent, cell);
  drawTargets(cell);
  const now = performance.now();
  drawFlashes(cell, now);       // the DM screen's order: tokens, flashes, then the bubble
  drawAnnouncement(cell, now);
}

/* `you.aoe` (M5e E-8): the template an area spell would cover from where the player
   tapped, sent with the "cast here?" confirm. Painted as sent, never computed (NN2). */
function drawAoe(cell) {
  const cells = view.you.aoe;
  if (!cells) return;
  ctx.fillStyle = "rgba(160, 80, 220, 0.30)";
  ctx.strokeStyle = "rgba(200, 130, 255, 0.75)";
  ctx.lineWidth = 1;
  for (const [col, row] of cells) {
    ctx.fillRect(col * cell, row * cell, cell, cell);
    ctx.strokeRect(col * cell + 0.5, row * cell + 0.5, cell - 1, cell - 1);
  }
}

/* `you.reachable` (D-M5-4): the cells the live Move prompt will accept, exactly as the
   server sent them. This file never computes one (NN2); it only paints the list. */
function drawReachable(cell) {
  const cells = view.you.reachable;
  if (!cells || pickingCreature()) return;
  ctx.fillStyle = "rgba(90, 200, 120, 0.28)";
  ctx.strokeStyle = "rgba(90, 200, 120, 0.7)";
  ctx.lineWidth = 1;
  for (const [col, row] of cells) {
    ctx.fillRect(col * cell, row * cell, cell, cell);
    ctx.strokeRect(col * cell + 0.5, row * cell + 0.5, cell - 1, cell - 1);
  }
}

/* A creature pick (M5d, `kind:"target"`) accepts every square this viewer can see, so that
   a guess at a hidden creature stays possible; painting all of them would say nothing.
   The tokens this view carries are ringed instead. Which of them the pick can actually
   take is the server's call when the tap lands — this file decides nothing (NN2). */
function pickingCreature() {
  return !!(prompt && view.you.prompt_id === prompt.id && prompt.kind === "target");
}

function drawTargets(cell) {
  if (!pickingCreature()) return;
  ctx.strokeStyle = "rgba(240, 192, 64, 0.9)";
  ctx.lineWidth = Math.max(2, cell * 0.08);
  ctx.setLineDash([cell * 0.2, cell * 0.12]);
  for (const agent of view.agents) {
    const span = (agent.size || 1) * cell;
    ctx.beginPath();
    ctx.arc(agent.col * cell + span / 2, agent.row * cell + span / 2, span * 0.48, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.setLineDash([]);
}

/* A tap on the board answers a live cell prompt with the cell under it. The canvas is
   scaled by CSS, so the tap is mapped back through the canvas's own size onto the nominal
   `col * cell_px` lattice the board is drawn on. Only a cell the server listed is sent:
   any other tap would only come back `bad_option`. */
function cellAt(event) {
  const rect = canvas.getBoundingClientRect();
  const cell = (view.map.cell_px || 1);
  const x = (event.clientX - rect.left) * canvas.width / rect.width;
  const y = (event.clientY - rect.top) * canvas.height / rect.height;
  return [Math.floor(x / cell), Math.floor(y / cell)];
}

canvas.addEventListener("click", (event) => {
  // A tap during a playback fast-forwards it and does nothing else, as a click does on the
  // DM screen: the board is showing held state, so a cell read off it is the wrong one.
  if (play) { fastForward(); if (view) drawBoard(); return; }
  if (!view || !prompt || view.you.prompt_id !== prompt.id) return;
  if (prompt.expects !== "cell" || !view.you.reachable) return;
  const [col, row] = cellAt(event);
  if (view.you.reachable.some(([c, r]) => c === col && r === row)) submit({ cell: [col, row] });
});

/* The page art is FETCHED, not assigned to an `<img src>`.
 *
 * `GET /map.png` is authenticated like every other route — a bearer, never a cookie (A3)
 * — and a browser cannot put a header on an image request any more than it can on a
 * WebSocket handshake. Assigning the URL straight to an `Image` therefore requested it
 * unauthenticated, took a 401, fired no `onload`, and left `drawBoard` with nothing to
 * draw over its MASK fill: every client saw a uniformly dark board, fog or no fog. The
 * suite could not see it — `test_mapserver.py` drives the route with the header set, and
 * nothing renders this file — and the first manual pass found it in one glance.
 *
 * `page.url` is set by the caller before the fetch starts, so a re-key arriving mid-flight
 * does not start a second load; the guards below drop a response that is no longer current
 * and revoke its blob rather than leaking it.
 */
async function loadPage(url) {
  const credential = recall(CRED_KEY);
  if (!credential) return;
  try {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${credential}` } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    if (page.url !== url) return;                        // a newer mask won the race
    const objectUrl = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      if (page.url !== url) { URL.revokeObjectURL(objectUrl); return; }
      if (page.objectUrl) URL.revokeObjectURL(page.objectUrl);   // the mask before this one
      page.img = img;
      page.objectUrl = objectUrl;
      if (view) drawBoard();
    };
    img.onerror = () => { URL.revokeObjectURL(objectUrl); pageUnavailable(url); };
    img.src = objectUrl;
  } catch (e) {
    pageUnavailable(url);
  }
}

/* A picture that will not load is not a reason to stop drawing — the live fog mask, the
 * grid and the tokens are all still correct without it, and a player can still take their
 * turn. It must not be SILENT, though: silence is how the 401 survived M4e. So the key is
 * remembered as failed, retried at a human interval rather than on every frame, and said
 * out loud once per attempt. */
function pageUnavailable(url) {
  pageFail = { url, at: Date.now() };
  if (page.url === url) page.url = "";
  console.warn("map image unavailable:", url);
}

function releasePage() {
  if (page.objectUrl) URL.revokeObjectURL(page.objectUrl);
  page = { url: "", img: null, objectUrl: "" };
}

/* The complement of `explored_runs`, filled in the server's own fog colour.
 *
 * Drawn even though `GET /map.png` already masked the art, because the two are not the
 * same mask: this one is live and that one is up to 3 s old, and the direction of the lag
 * is what makes this safe — the picture never shows a cell the runs hide, so this can only
 * ever repaint fog over fog. With no image published at all it is also the only fog there
 * is. */
function drawFog(cell, cols, rows) {
  // Fog down means the DM's own screen is drawing the whole map, and M3's rule is that a
  // client never sees MORE than the console — not that it always sees less (view.py's
  // `_cells`). So there is nothing to paint.
  if (!view.fog.active) return;

  const byRow = new Map();
  for (const run of view.fog.explored_runs) {
    const [row, from, to] = run;
    if (!byRow.has(row)) byRow.set(row, []);
    byRow.get(row).push([from, to]);
  }

  ctx.fillStyle = MASK;
  for (let row = 0; row < rows; row++) {
    const spans = (byRow.get(row) || []).sort((a, b) => a[0] - b[0]);
    let col = 0;
    for (const [from, to] of spans) {
      if (from > col) ctx.fillRect(col * cell, row * cell, (from - col) * cell, cell);
      col = Math.max(col, to + 1);
    }
    if (col < cols) ctx.fillRect(col * cell, row * cell, (cols - col) * cell, cell);
  }
}

function drawGrid(cell, cols, rows) {
  ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let col = 0; col <= cols; col++) {
    ctx.moveTo(col * cell + 0.5, 0);
    ctx.lineTo(col * cell + 0.5, rows * cell);
  }
  for (let row = 0; row <= rows; row++) {
    ctx.moveTo(0, row * cell + 0.5);
    ctx.lineTo(cols * cell, row * cell + 0.5);
  }
  ctx.stroke();
}

const TOKEN_COLOURS = { mine: "#f0c040", ally: "#5aa9e6", other: "#e06666" };

function drawToken(agent, cell) {
  const kind = classOf(agent);
  const span = (agent.size || 1) * cell;
  const x = agent.col * cell;
  const y = agent.row * cell;
  const down = (agent.hp && (agent.hp.band === "Down" || agent.hp.cur === 0));

  ctx.globalAlpha = down ? 0.45 : 1;
  ctx.beginPath();
  ctx.arc(x + span / 2, y + span / 2, span * 0.38, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(10, 10, 14, 0.72)";
  ctx.fill();
  ctx.lineWidth = Math.max(2, cell * 0.06);
  ctx.strokeStyle = TOKEN_COLOURS[kind];
  ctx.stroke();
  ctx.globalAlpha = 1;

  // A hit-point bar when this viewer has numbers, and nothing at all when they have a
  // band — a bar drawn from a band would be this file inventing a number the server
  // deliberately withheld.
  const hp = agent.hp || {};
  if (hp.cur !== undefined && hp.max) {
    const frac = Math.max(0, Math.min(1, hp.cur / hp.max));
    const barW = span * 0.72;
    const barX = x + (span - barW) / 2;
    const barY = y + span - Math.max(3, cell * 0.12);
    ctx.fillStyle = "rgba(0, 0, 0, 0.6)";
    ctx.fillRect(barX, barY, barW, Math.max(3, cell * 0.08));
    ctx.fillStyle = frac > 0.5 ? "#5ac47a" : (frac > 0 ? "#e0a33a" : "#e06666");
    ctx.fillRect(barX, barY, barW * frac, Math.max(3, cell * 0.08));
  }

  const label = agent.name + (hp.band ? ` · ${hp.band}` : "");
  ctx.font = `${Math.max(9, Math.round(cell * 0.30))}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.lineWidth = 3;
  ctx.strokeStyle = "rgba(0, 0, 0, 0.85)";
  ctx.strokeText(label, x + span / 2, y - 2);
  ctx.fillStyle = TOKEN_COLOURS[kind];
  ctx.fillText(label, x + span / 2, y - 2);
}

// ── Playback (Envelope 3, M4b.3: B-5 and B-7) ───────────────────────────────
//
// An `events` frame arrives just before the `view` of the same cycle, and that view
// already shows the turn as done. So every agent the events name is HELD at what the
// previous view said (position, HP, alive) and drawn from that, while the queue plays
// out the way `_advance_npc_playback` plays it on the DM screen: a move slides, an
// announce typewrites over the actor, and an outcome flashes and drops the bar, then
// pauses for a beat. A view that lands mid-playback is stored, but a held agent keeps
// its held state until the queue drains, so a token never jumps and then slides.
//
// The DM's pace never waits for this. Each viewer plays on their own clock, and a tap
// fast-forwards only their own board.

// gui/constants.py, copied (B-5). A change there is a change here.
const ANIM_CELLS_PER_SEC = 10.0;   // NPC_ANIM_CELLS_PER_SEC
const TYPEWRITER_CPS = 40.0;       // NPC_TYPEWRITER_CPS
const ANNOUNCE_HOLD_MS = 900;      // NPC_ANNOUNCE_HOLD_MS
const OUTCOME_BEAT_MS = 300;       // NPC_OUTCOME_BEAT_MS
const FLASH_MS = 1500;             // _spawn_flash's default `secs`
const FLASH_GOOD = "rgb(120, 220, 140)";   // FLASH_GOOD
const FLASH_BAD = "rgb(220, 110, 110)";    // FLASH_BAD
const FLASH_CRIT = "rgb(255, 215, 0)";     // FLASH_CRIT

/* The "Animate moves" toggle (B-7) is a per-device preference, not a secret, so it is the
   one thing this file keeps in `localStorage`. The credential never goes there (D-M4e-2).
   It is never sent: the server does not know or care how a viewer watches. */
const ANIM_KEY = "dnd.animate";

let seq = null;        // the last seq this client holds; null until a view arrives
let resyncing = false; // a `GET /events?since=` is out
let play = null;       // the playback in progress, or null
let flashes = [];      // floating outcome texts, which outlive the playback that spawned them
let animate = loadAnimate();
let ticking = false;   // a requestAnimationFrame is pending

function loadAnimate() {
  try { return localStorage.getItem(ANIM_KEY) !== "off"; } catch (e) { return true; }
}

function saveAnimate(on) {
  try { localStorage.setItem(ANIM_KEY, on ? "on" : "off"); } catch (e) { /* not kept */ }
}

/* The server's one promise (M4b.2, `_contiguous`): an `events` frame starts at the seq
   this socket was last sent. Anything else is a bug somewhere, so the frame is dropped
   rather than patched in, and the ring is asked for what was missed. */
function onEvents(frame) {
  if (!view || seq === null || frame.since !== seq) { resync(); return; }
  seq = frame.seq;
  if (frame.events && frame.events.length) enqueue(frame.events);
}

async function resync() {
  const credential = recall(CRED_KEY);
  if (resyncing || !credential || seq === null) return;
  resyncing = true;
  const asked = seq;
  try {
    const res = await fetch(`/events?since=${asked}`,
                            { headers: { Authorization: `Bearer ${credential}` } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const frame = await res.json();
    // The socket kept pushing while this was out. If it moved the seq, it delivered
    // something newer than this answer, which is then stale.
    if (!frame || frame.v !== PROTOCOL_VERSION || seq !== asked) return;
    if (frame.t === "view") {
      fastForward();               // the board is replaced, so nothing held is still true
      render(frame);
    } else if (frame.t === "events" && frame.since === seq) {
      seq = frame.seq;
      if (frame.events.length) enqueue(frame.events);
    }
  } catch (e) {
    console.warn("events resync failed:", e);
  } finally {
    resyncing = false;
  }
}

/* Which events hold their agent. A move and an announce, and an outcome with a timed HP
   drop: the engine's outcomes, from an automated turn, where the DM screen holds the
   whole board. A flash the GUI spawned itself carries no HP field. On the DM screen the
   state had already changed when it flashed, so it holds nothing here either. */
function holds(ev) {
  if (ev.kind === "move" || ev.kind === "announce") return true;
  return ev.kind === "outcome" && (ev.hp_after !== undefined || ev.band !== undefined);
}

function enqueue(events) {
  if (!play) play = { queue: [], ei: 0, t0: performance.now(), applied: false, held: new Map() };
  for (const ev of events) {
    if (holds(ev) && !play.held.has(ev.agent)) play.held.set(ev.agent, holdFrom(ev.agent));
    play.queue.push(ev);
  }
  tick();
}

/* The agent as the current view has it, which is the view before these events. One the
   view does not carry (it walked into sight this turn) is held as absent: it appears at
   the start of its first move, which the server cut to cells this viewer has seen. */
function holdFrom(idx) {
  const agent = view ? agentByIndex(idx) : null;
  if (!agent) return { agent: null, col: 0, row: 0, hp: {} };
  return { agent, col: agent.col, row: agent.row, hp: Object.assign({}, agent.hp) };
}

/* Its record comes from the newest view. Where it stands is the move's to say, and the
   move sets that in the same frame. */
function adopt(held, idx) {
  if (held.agent) return;
  const agent = agentByIndex(idx);
  if (!agent) return;            // not in this view either: it plays, but draws nothing
  held.agent = agent;
  held.hp = Object.assign({}, agent.hp);
}

/* `_advance_npc_playback`, line for line where it can be. Instant events chain within a
   frame; a timed one returns with its held state set for this frame's draw. */
function advance(now) {
  while (play) {
    if (play.ei >= play.queue.length) { finish(); return; }
    const ev = play.queue[play.ei];
    const elapsed = now - play.t0;
    if (ev.kind === "move") {
      const held = play.held.get(ev.agent);
      const path = ev.path;
      const steps = path.length - 1;
      adopt(held, ev.agent);
      const dur = steps / ANIM_CELLS_PER_SEC * 1000;
      // A one-cell path is a jump (B-4 cut the rest). With the toggle off every move is.
      if (steps <= 0 || !animate || elapsed >= dur) {
        land(held, path[path.length - 1]);
        next(now);
        continue;
      }
      const p = elapsed / dur * steps;
      const i = Math.min(Math.floor(p), steps - 1);
      const f = p - i;
      held.col = path[i][0] + f * (path[i + 1][0] - path[i][0]);
      held.row = path[i][1] + f * (path[i + 1][1] - path[i][1]);
      return;
    }
    if (ev.kind === "announce") {
      const dur = ev.text.length / TYPEWRITER_CPS * 1000 + ANNOUNCE_HOLD_MS;
      if (elapsed >= dur) { next(now); continue; }
      return;                    // drawAnnouncement renders the reveal from ev and t0
    }
    if (ev.kind === "outcome") {
      if (!play.applied) { play.applied = true; applyOutcome(ev, now); }
      if (elapsed >= OUTCOME_BEAT_MS) { next(now); continue; }
      return;
    }
    next(now);                   // `turn`: the view already says whose turn it is
  }
}

function next(now) {
  play.ei += 1;
  play.t0 = now;
  play.applied = false;
}

function land(held, cell) {
  if (!held) return;
  held.col = cell[0];
  held.row = cell[1];
}

/* The flash, and the bar drop it carries. `hp_after` is a number this viewer is entitled
   to; `band` is all an enemy's bar is allowed to say. Neither means "leave the bar". */
function applyOutcome(ev, now) {
  const rise = 20 * flashes.filter((f) => f.agent === ev.agent).length;
  flashes.push({ agent: ev.agent, text: ev.text, at: now === undefined ? performance.now() : now,
                 colour: ev.crit ? FLASH_CRIT : (ev.good ? FLASH_GOOD : FLASH_BAD), rise });
  const held = play && play.held.get(ev.agent);
  if (!held) return;
  if (ev.hp_after !== undefined) held.hp.cur = ev.hp_after;
  else if (ev.band !== undefined) held.hp.band = ev.band;
}

/* `_npc_anim_fast_forward`: everything left lands at once, and the held state goes. */
function fastForward() {
  if (!play) return;
  let first = true;
  for (const ev of play.queue.slice(play.ei)) {
    if (ev.kind === "move") {
      const held = play.held.get(ev.agent);
      adopt(held, ev.agent);
      land(held, ev.path[ev.path.length - 1]);
    } else if (ev.kind === "outcome" && !(first && play.applied)) {
      applyOutcome(ev);
    }
    first = false;
  }
  finish();
}

function finish() {
  play = null;                   // the live view shows, corpses and all
  tick();
}

/* The loop runs only while something moves: a playback, or a flash still fading. */
function tick() {
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(() => {
    ticking = false;
    advance(performance.now());
    if (view) drawBoard();
    if (play || flashes.length) tick();
  });
}

/* What the board draws: the view, with every held agent swapped for its held self. A
   held agent the view no longer carries is still drawn until the queue drains, as the
   DM screen keeps a corpse on the board until its killing blow has played. */
function displayed() {
  if (!play) return view.agents;
  const out = [];
  for (const agent of view.agents) {
    if (!play.held.has(agent.agent)) out.push(agent);
  }
  for (const [idx, held] of play.held) {
    if (held.agent) out.push(Object.assign({}, held.agent, { agent: idx, col: held.col,
                                                             row: held.row, hp: held.hp }));
  }
  return out;
}

function drawnAt(idx) {
  return displayed().find((a) => a.agent === idx) || null;
}

/* Rises 20 px and fades over its lifetime, staggered above any flash already over the
   same creature, as `_draw_floating_texts` does. It starts above the name label, which
   the DM screen does not draw and a player needs. */
function drawFlashes(cell, now) {
  flashes = flashes.filter((f) => now - f.at < FLASH_MS);
  if (!flashes.length) return;
  const size = Math.max(10, Math.round(cell * 0.34));
  ctx.font = `600 ${size}px system-ui, sans-serif`;
  ctx.textAlign = "center";
  ctx.lineWidth = 3;
  for (const f of flashes) {
    const agent = drawnAt(f.agent);
    if (!agent) continue;
    const span = (agent.size || 1) * cell;
    const p = Math.max(0, (now - f.at) / FLASH_MS);
    const y = agent.row * cell - Math.max(9, Math.round(cell * 0.30)) - 6 - f.rise - p * 20;
    ctx.globalAlpha = Math.max(0, 1 - p);
    ctx.strokeStyle = "rgba(0, 0, 0, 0.85)";
    ctx.strokeText(f.text, agent.col * cell + span / 2, y);
    ctx.fillStyle = f.colour;
    ctx.fillText(f.text, agent.col * cell + span / 2, y);
  }
  ctx.globalAlpha = 1;
}

/* The typewriter bubble over the actor (`_draw_npc_announcement`). The server already
   dropped a concealed actor's announce (B-4), so there is nothing to suppress here. */
function drawAnnouncement(cell, now) {
  if (!play || play.ei >= play.queue.length) return;
  const ev = play.queue[play.ei];
  if (ev.kind !== "announce") return;
  const agent = drawnAt(ev.agent);
  if (!agent) return;
  const shown = ev.text.slice(0, Math.max(1, Math.floor((now - play.t0) / 1000 * TYPEWRITER_CPS)));
  const size = Math.max(10, Math.round(cell * 0.34));
  ctx.font = `${size}px system-ui, sans-serif`;
  ctx.textAlign = "left";
  const w = ctx.measureText(shown).width + 10;
  const h = size + 6;
  const span = (agent.size || 1) * cell;
  const x = Math.max(4, Math.min(agent.col * cell + span / 2 - w / 2, canvas.width - w - 4));
  const y = Math.max(4, agent.row * cell - Math.max(9, Math.round(cell * 0.30)) - h - 8);
  ctx.fillStyle = "rgba(20, 15, 5, 0.84)";
  ctx.fillRect(x, y, w, h);
  ctx.fillStyle = "rgb(255, 240, 200)";
  ctx.textBaseline = "top";
  ctx.fillText(shown, x + 5, y + 3);
  ctx.textBaseline = "alphabetic";
}

// ── Screens ─────────────────────────────────────────────────────────────────

function showJoin(message) {
  el("session").hidden = true;
  el("join").hidden = false;
  const error = el("join-error");
  error.textContent = message || "";
  error.hidden = !message;
  el("join-go").disabled = false;
}

function showSession() {
  el("join").hidden = true;
  el("session").hidden = false;
}

function setStatus(text, live) {
  const status = el("status");
  status.textContent = text;
  if (live === null) status.removeAttribute("data-live");
  else status.dataset.live = live ? "yes" : "no";
}

// ── Boot ────────────────────────────────────────────────────────────────────

el("join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  el("join-go").disabled = true;
  el("join-error").hidden = true;
  try {
    await join(el("code").value.trim(), el("name").value.trim());
    attempt = 0;
    connect();
  } catch (err) {
    showJoin(err.message || "That code was not accepted.");
  }
});

el("prompt-cancel").addEventListener("click", () => submit({ cancel: true }));
el("animate").checked = animate;
el("animate").addEventListener("change", (event) => {
  animate = event.target.checked;   // a slide under way lands on the next frame
  saveAnimate(animate);
});
el("prompt-filter").addEventListener("input", (event) => {
  filter.text = event.target.value;
  drawPrompt();
});

// A reload keeps the seat, which is the whole of what `sessionStorage` buys (D-M4e-2).
connect();
