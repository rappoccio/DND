"use strict";
/*
 * The browser playback (M4b.3: B-5, B-7), driven through `app.js` itself under node.
 * Run by `test_playback.py`; each check prints one line, and the first failure exits 1.
 */

const assert = require("assert");
const { load } = require("./app_harness");

const plain = (x) => JSON.parse(JSON.stringify(x));

function agent(idx, col, row, extra = {}) {
  return Object.assign({ agent: idx, name: `A${idx}`, col, row, size: 1,
                         hp: { cur: 20, max: 20 }, conditions: [] }, extra);
}

function view(seq, agents) {
  return {
    t: "view", seq,
    map: { cell_px: 50, cols: 20, rows: 20, image: "" },
    fog: { active: false, explored_runs: [] },
    combat: { active: true, paused: false, round: 1, turn_idx: 0, turn_agent: 1,
              initiative: [] },
    you: { prompt_id: null },
    log: [],
    agents,
  };
}

const ORC = () => agent(1, 2, 2, { hp: { band: "Healthy" } });
const ANN = () => agent(0, 8, 8);

/* A session that has its first view, seq 4: Ann at (8,8), an orc at (2,2). */
function seated(opts) {
  const h = load(opts);
  h.deliver(view(4, [ANN(), ORC()]));
  return h;
}

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check("a view sets seq, and a contiguous events frame continues it", () => {
  const h = seated();
  assert.strictEqual(h.ev("seq"), 4);
  h.deliver({ t: "events", since: 4, seq: 6, events: [
    { kind: "turn", round: 1, turn_idx: 1, agent: 1 },
    { kind: "turn", round: 1, turn_idx: 2, agent: 0 }] });
  assert.strictEqual(h.ev("seq"), 6);
  assert.strictEqual(h.fetches.length, 0, "a contiguous frame asked the ring for nothing");
});

check("a move is held, then slides, then lands on the live view", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 5, events: [
    { kind: "move", agent: 1, path: [[2, 2], [3, 2], [4, 2], [5, 2]] }] });
  // The same cycle's view already shows the orc at the end of its route.
  h.deliver(view(5, [ANN(), agent(1, 5, 2, { hp: { band: "Healthy" } })]));
  assert.deepStrictEqual(plain(h.board()[1]).slice(0, 2), [2, 2],
                         "the token jumped to the view's position before sliding");
  h.frame(0);                         // the first frame of the playback
  h.frame(150);                       // 3 steps at 10 cells/s is 300 ms; half way
  const [col, row] = h.board()[1];
  assert.ok(Math.abs(col - 3.5) < 1e-9 && row === 2, `mid-slide at ${col},${row}`);
  h.frame(150);
  assert.strictEqual(h.ev("play"), null, "the queue did not drain at the end of the slide");
  assert.deepStrictEqual(plain(h.board()[1]).slice(0, 2), [5, 2]);
});

check("an unheld agent draws live during a playback", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 5, events: [
    { kind: "move", agent: 1, path: [[2, 2], [3, 2]] }] });
  h.deliver(view(5, [agent(0, 9, 9), agent(1, 3, 2, { hp: { band: "Healthy" } })]));
  assert.deepStrictEqual(plain(h.board()[0]).slice(0, 2), [9, 9]);
});

check("a frame that does not start at seq is dropped and the ring is asked", async () => {
  const h = seated();
  h.replies.push({ v: 1, t: "events", since: 4, seq: 7, events: [
    { kind: "move", agent: 1, path: [[2, 2], [2, 3]] }] });
  h.deliver({ t: "events", since: 5, seq: 7, events: [
    { kind: "move", agent: 1, path: [[2, 3], [2, 4]] }] });
  assert.strictEqual(h.ev("seq"), 4, "a gapped frame moved seq");
  assert.strictEqual(h.ev("play"), null, "a gapped frame was played");
  assert.strictEqual(h.fetches.length, 1);
  assert.strictEqual(h.fetches[0].url, "/events?since=4");
  assert.strictEqual(h.fetches[0].init.headers.Authorization, "Bearer cred");
  await h.settle();
  assert.strictEqual(h.ev("seq"), 7, "the ring's answer was not applied");
  assert.strictEqual(h.ev("play.queue.length"), 1);
  assert.deepStrictEqual(plain(h.ev("play.queue[0].path")), [[2, 2], [2, 3]]);
});

check("the ring's view replaces the board; a stale answer is ignored", async () => {
  const h = seated();
  h.replies.push(Object.assign({ v: 1 }, view(40, [agent(0, 1, 1)])));
  h.deliver({ t: "events", since: 9, seq: 10, events: [] });
  await h.settle();
  assert.strictEqual(h.ev("seq"), 40);
  assert.deepStrictEqual(plain(h.board()[0]).slice(0, 2), [1, 1]);

  const s = seated();
  s.deliver({ t: "events", since: 9, seq: 10, events: [] });   // asks since=4, no answer yet
  s.replies.length = 0;
  s.deliver(view(12, [ANN(), ORC()]));                           // the socket moves on
  assert.strictEqual(s.ev("seq"), 12);
  // An answer for since=4 arriving now is older than what the socket already sent.
  s.ev("resyncing = false");
  s.replies.push(Object.assign({ v: 1 }, view(5, [agent(0, 0, 0)])));
  s.ev("seq = 4");                    // ask from 4 …
  const p = s.ev("resync()");
  s.ev("seq = 12");                   // … while the socket moves past it
  return p.then(() => {
    assert.strictEqual(s.ev("seq"), 12, "a stale ring answer rolled seq back");
    assert.deepStrictEqual(plain(s.board()[0]).slice(0, 2), [8, 8]);
  });
});

check("an outcome drops the held bar when it plays, not before", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 7, events: [
    { kind: "announce", agent: 1, target: 0, text: "Orc attacks Ann" },
    { kind: "outcome", agent: 0, text: "Hit (7)", good: true, died: false, hp_after: 13 },
    { kind: "outcome", agent: 1, text: "Hit (9)", good: true, died: false, band: "Bloodied" }] });
  h.deliver(view(7, [agent(0, 8, 8, { hp: { cur: 13, max: 20 } }),
                     agent(1, 2, 2, { hp: { band: "Bloodied" } })]));
  h.frame(0);
  assert.strictEqual(h.board()[0][2].cur, 20, "the bar dropped before its outcome played");
  assert.strictEqual(h.board()[1][2].band, "Healthy");
  // 15 characters at 40 cps, then the 900 ms hold.
  h.frame(15 / 40 * 1000 + 900);
  assert.strictEqual(h.board()[0][2].cur, 13);
  assert.strictEqual(h.board()[1][2].band, "Healthy", "the second outcome played early");
  h.frame(300);
  assert.strictEqual(h.board()[1][2].band, "Bloodied");
  assert.ok(h.ev("play") !== null, "the second outcome's beat was skipped");
  h.frame(300);
  assert.strictEqual(h.ev("play"), null);
  assert.deepStrictEqual(plain(h.ev("flashes.map((f) => [f.agent, f.text, f.colour])")),
                         [[0, "Hit (7)", "rgb(120, 220, 140)"], [1, "Hit (9)", "rgb(120, 220, 140)"]]);
});

check("a flash's colour: gold for a critical, red for a miss", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 6, events: [
    { kind: "outcome", agent: 1, text: "Hit (20)", good: true, died: false, crit: true },
    { kind: "outcome", agent: 1, text: "Miss", good: false, died: false }] });
  h.frame(0);
  h.frame(300);
  assert.deepStrictEqual(plain(h.ev("flashes.map((f) => [f.colour, f.rise])")),
                         [["rgb(255, 215, 0)", 0], ["rgb(220, 110, 110)", 20]]);
});

check("a GUI flash (no HP field) holds nothing", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 5, events: [
    { kind: "outcome", agent: 1, text: "Hit (7)", good: true, died: false }] });
  h.deliver(view(5, [ANN(), agent(1, 2, 2, { hp: { band: "Bloodied" } })]));
  h.frame(0);
  assert.strictEqual(h.ev("play.held.size"), 0);
  assert.strictEqual(h.board()[1][2].band, "Bloodied");
});

check("a creature killed this turn stays drawn until the queue drains", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 5, events: [
    { kind: "outcome", agent: 1, text: "Hit (30)", good: true, died: true, band: "Down" }] });
  h.deliver(view(5, [ANN()]));
  h.frame(0);
  assert.ok(h.board()[1], "the corpse vanished before its killing blow played");
  assert.strictEqual(h.board()[1][2].band, "Down");
  h.frame(300);
  assert.strictEqual(h.board()[1], undefined);
});

check("a creature that walks into sight appears at the start of its cut path", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 6, events: [
    { kind: "outcome", agent: 0, text: "Miss", good: false, died: false, hp_after: 20 },
    { kind: "move", agent: 5, path: [[10, 10], [11, 10]] }] });
  h.deliver(view(6, [ANN(), ORC(), agent(5, 11, 10)]));
  h.frame(0);
  assert.strictEqual(h.board()[5], undefined, "drawn before its move began");
  h.frame(300);                       // the outcome's beat; the move starts
  h.frame(50);
  const [col, row] = h.board()[5];
  assert.ok(Math.abs(col - 10.5) < 1e-9 && row === 10, `at ${col},${row}`);
});

check("a view mid-playback keeps the held agents held", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 5, events: [
    { kind: "move", agent: 1, path: [[2, 2], [3, 2], [4, 2], [5, 2]] }] });
  h.deliver(view(5, [ANN(), agent(1, 5, 2, { hp: { band: "Healthy" } })]));
  h.frame(0);
  h.frame(100);
  h.deliver(view(5, [ANN(), agent(1, 5, 2, { hp: { band: "Bloodied" } })]));
  const held = h.board()[1];
  assert.ok(Math.abs(held[0] - 3) < 1e-9, `jumped to ${held[0]}`);
  assert.strictEqual(held[2].band, "Healthy");
});

check("a tap fast-forwards: everything lands, nothing is submitted", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 7, events: [
    { kind: "move", agent: 1, path: [[2, 2], [3, 2], [4, 2]] },
    { kind: "outcome", agent: 0, text: "Hit (4)", good: true, died: false, hp_after: 16 },
    { kind: "outcome", agent: 0, text: "Hit (3)", good: true, died: false, hp_after: 13 }] });
  h.frame(0);
  h.frame(50);
  h.ev("prompt = { id: 'p1', expects: 'cell', options: [] }");
  h.ev("view.you = { prompt_id: 'p1', reachable: [[0, 0]] }");
  h.el("board").fire("click", { clientX: 1, clientY: 1 });
  assert.strictEqual(h.ev("play"), null);
  assert.strictEqual(h.ev("flashes.length"), 2, "fast-forward skipped an outcome");
  assert.deepStrictEqual(h.socket.sent.map((f) => f.t), ["auth"], "the tap also submitted");
});

check("fast-forward does not flash an outcome that already played", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 6, events: [
    { kind: "outcome", agent: 0, text: "Hit (4)", good: true, died: false, hp_after: 16 },
    { kind: "outcome", agent: 0, text: "Hit (3)", good: true, died: false, hp_after: 13 }] });
  h.frame(0);
  h.el("board").fire("click", { clientX: 1, clientY: 1 });
  assert.deepStrictEqual(plain(h.ev("flashes.map((f) => f.text)")), ["Hit (4)", "Hit (3)"]);
});

check("the announce bubble typewrites at 40 characters a second", () => {
  const h = seated();
  h.deliver({ t: "events", since: 4, seq: 5, events: [
    { kind: "announce", agent: 1, target: null, text: "Orc casts Fireball" }] });
  h.frame(0);
  h.frame(100);
  const bubble = h.texts.filter((t) => t.fill === "rgb(255, 240, 200)").pop();
  assert.strictEqual(bubble.text, "Orc ");
});

check("Animate moves off: a move lands at once, the rest still plays", () => {
  const h = seated();
  assert.strictEqual(h.el("animate").checked, true, "the toggle is not on by default");
  h.el("animate").checked = false;
  h.el("animate").fire("change", { target: h.el("animate") });
  assert.strictEqual(h.stores.local.get("dnd.animate"), "off");
  h.deliver({ t: "events", since: 4, seq: 6, events: [
    { kind: "move", agent: 1, path: [[2, 2], [3, 2], [4, 2], [5, 2]] },
    { kind: "outcome", agent: 0, text: "Hit (4)", good: true, died: false, hp_after: 16 }] });
  h.frame(0);
  assert.deepStrictEqual(plain(h.board()[1]).slice(0, 2), [5, 2], "the move slid");
  assert.strictEqual(h.board()[0][2].cur, 16);
  assert.ok(h.ev("play") !== null, "the outcome's beat was skipped with the slide");
  h.frame(300);
  assert.strictEqual(h.ev("play"), null);
});

check("the toggle is remembered on this device", () => {
  const h = load({ local: { "dnd.animate": "off" } });
  assert.strictEqual(h.ev("animate"), false);
  assert.strictEqual(h.el("animate").checked, false);
});

check("a reconnect forgets seq until the new socket's view", () => {
  const h = seated();
  h.close();
  assert.strictEqual(h.ev("seq"), null);
  h.deliver({ t: "events", since: 4, seq: 5, events: [
    { kind: "move", agent: 1, path: [[2, 2], [3, 2]] }] });
  assert.strictEqual(h.ev("play"), null, "an events frame played with no view under it");
});

(async () => {
  for (const [name, fn] of checks) {
    try {
      await fn();
      console.log(`✅ ${name}`);
    } catch (e) {
      console.log(`❌ ${name}\n   ${e.message}`);
      process.exit(1);
    }
  }
})();
