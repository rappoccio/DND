"use strict";
/*
 * The player's client (MULTIPLAYER_PLAN.md M4e).
 *
 * Three things happen here and nothing else: a join code becomes a credential
 * (`POST /join`), the credential opens `WS /live` and authenticates it with its first
 * frame (A3), and every `view` that arrives is drawn. There is no game input in this file
 * — D-M4e-3 keeps M4e read-only, and the socket carries exactly one frame in the
 * client→server direction, the auth frame below.
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
 *     page's real grid-line positions. Evenly-spaced grids agree exactly; an offset or
 *     jittery one puts a token up to one line-spacing off its art. Envelope 2 carries no
 *     line positions and adding them is an M3-frozen protocol change, so this is written
 *     down rather than bundled.
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
let attempt = 0;
let page = { url: "", img: null };         // the map image, re-fetched only when it re-keys

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
    if (!frame || frame.t !== "view" || frame.v !== PROTOCOL_VERSION) return;
    attempt = 0;
    setStatus("live", true);
    render(frame);
  };

  socket.onclose = (event) => {
    socket = null;
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

// ── Rendering ───────────────────────────────────────────────────────────────

function render(next) {
  view = next;
  el("who").textContent = recall(NAME_KEY) || "at the table";
  el("prompt-banner").hidden = !view.you.prompt_id;

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
  /* `combat.turn_idx` indexes the UNFILTERED order (view.py's `_combat`), and this list is
     cut to the tokens the view explains — so the active row cannot be resolved here, and
     counting rows would mark the wrong creature exactly when a hidden one exists. The
     marker needs a cursor Envelope 2 does not carry; it is owed, not guessed. */
  for (const entry of view.combat.initiative) {
    const agent = agentByIndex(entry.agent);
    const row = document.createElement("li");
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
  if (url && url !== page.url) {
    page.url = url;
    const img = new Image();
    img.onload = () => { if (view) drawBoard(); };
    img.src = url;
    page.img = img;
  } else if (!url) {
    page.url = "";
    page.img = null;
  }
  if (page.img && page.img.complete && page.img.naturalWidth) {
    // Stretched to the nominal lattice rather than drawn at natural size: see the header's
    // fourth rule. This keeps the art and the token grid in the same coordinate space.
    ctx.drawImage(page.img, 0, 0, w, h);
  }

  drawFog(cell, map.cols, map.rows);
  drawGrid(cell, map.cols, map.rows);
  for (const agent of view.agents) drawToken(agent, cell);
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

// A reload keeps the seat, which is the whole of what `sessionStorage` buys (D-M4e-2).
connect();
