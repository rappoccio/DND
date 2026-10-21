"use strict";
/*
 * The token look (M4b.5: B-8), driven through `app.js` itself under node.
 * Run by `test_sprites.py`; each check prints one line, and the first failure exits 1.
 *
 * The board is 50 px a cell, so a token at (2, 2) covers x, y in [100, 150).
 */

const assert = require("assert");
const { load } = require("./app_harness");

function agent(idx, col, row, extra = {}) {
  return Object.assign({ agent: idx, name: `a${idx}`, col, row, size: 1, faction: 2,
                         sprite: "", hp: { cur: 20, max: 20 }, conditions: [] }, extra);
}

function view(seq, agents) {
  return {
    t: "view", seq,
    map: { cell_px: 50, cols: 20, rows: 20, image: "" },
    fog: { active: false, explored_runs: [] },
    combat: { active: true, paused: false, round: 1, turn_idx: 0, turn_agent: 0,
              initiative: [] },
    you: { prompt_id: null },
    log: [],
    agents,
  };
}

/* A session showing exactly `agents`, with the canvas record cleared after the draw. */
function board(agents, opts) {
  const h = load(opts);
  h.deliver(view(4, agents));
  return h;
}

/* Redraw, and return only what this draw did. */
function redraw(h) {
  h.calls.length = 0;
  h.ev("drawBoard()");
  return h.calls;
}

const at = (calls, fn, x, y) => calls.filter((c) => c.fn === fn && c.args[0] === x
                                                    && c.args[1] === y);
const square = (calls) => at(calls, "fillRect", 101, 101).filter((c) => c.args[2] === 48);
const glyphs = (calls) => calls.filter((c) => c.fn === "fillText" && c.args[1] === 125
                                              && c.args[2] === 125);
const hatched = (calls) => calls.some((c) => c.fn === "stroke"
                                             && c.stroke === "rgba(180, 0, 0, 0.784)");

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check("the token is a square in its team's colour, bordered 50 lighter", () => {
  const h = board([agent(0, 2, 2, { faction: 1 })]);
  const calls = redraw(h);
  assert.strictEqual(square(calls).length, 1, "no 48 px square at (101, 101)");
  assert.strictEqual(square(calls)[0].fill, "rgb(210, 70, 70)");
  const border = at(calls, "strokeRect", 102, 102);
  assert.strictEqual(border.length, 1);
  assert.strictEqual(border[0].stroke, "rgb(255, 120, 120)");
  assert.ok(!calls.some((c) => c.fn === "arc"), "the old ringed circle is still drawn");
});

check("a team the client does not know is faction_color's fallback", () => {
  const h = board([agent(0, 2, 2, { faction: 7 })]);
  assert.strictEqual(square(redraw(h))[0].fill, "rgb(200, 200, 60)");
});

check("no art: the name's first letter, centred, and nothing fetched", () => {
  const h = board([agent(0, 2, 2, { name: "goblin", sprite: "" })]);
  const g = glyphs(redraw(h));
  assert.strictEqual(g.length, 1);
  assert.strictEqual(g[0].args[0], "G");
  assert.strictEqual(g[0].fill, "rgb(25, 25, 30)");
  assert.strictEqual(h.sprites.length, 0);
});

check("a one-letter placeholder sprite is never fetched; the letter is drawn", () => {
  const h = board([agent(0, 2, 2, { name: "orc", sprite: "O.png" })]);
  const calls = redraw(h);
  assert.strictEqual(h.sprites.length, 0, "a placeholder tile was fetched");
  assert.strictEqual(glyphs(calls)[0].args[0], "O");
});

check("real art is fetched once, with the credential, and drawn over the square", async () => {
  const h = board([agent(0, 2, 2, { name: "goblin", sprite: "cult-mage.png" })]);
  assert.strictEqual(h.sprites.length, 1);
  assert.strictEqual(h.sprites[0].url, "/sprite?name=cult-mage.png");
  assert.strictEqual(h.sprites[0].init.headers.Authorization, "Bearer cred");
  // Until the art loads, the token draws its letter.
  assert.strictEqual(glyphs(redraw(h)).length, 1);
  await h.settle();
  await h.settle();
  assert.strictEqual(h.images.length, 1, "no Image was made from the answer");
  h.images[0].onload();
  const calls = redraw(h);
  const drawn = at(calls, "drawImage", h.images[0], 100);
  assert.strictEqual(drawn.length, 1, "the sprite was not drawn at the token's corner");
  assert.deepStrictEqual(drawn[0].args.slice(1), [100, 100, 50, 50]);
  assert.strictEqual(glyphs(calls).length, 0, "the letter was drawn over the art");
  assert.ok(calls.indexOf(drawn[0]) > calls.indexOf(square(calls)[0]),
            "the art was drawn under the square");
  redraw(h);
  assert.strictEqual(h.sprites.length, 1, "the art was fetched again");
});

check("a sprite the server refuses draws the letter and is not re-asked at once", async () => {
  const h = board([agent(0, 2, 2, { name: "goblin", sprite: "cult-mage.png" })],
                  { spriteStatus: [["cult-mage.png", 404]] });
  await h.settle();
  await h.settle();
  assert.strictEqual(glyphs(redraw(h)).length, 1);
  assert.strictEqual(h.sprites.length, 1, "a refused sprite was re-asked every frame");
  assert.strictEqual(h.images.length, 0);
});

check("an unconscious token is grey, square, border and art, with no hatch", async () => {
  const h = board([agent(0, 2, 2, { sprite: "cult-mage.png",
                                    hp: { cur: 0, max: 20 }, conditions: ["unconscious"] })]);
  await h.settle();
  await h.settle();
  h.calls.length = 0;
  h.images[0].onload();              // its redraw builds the grey copy, once
  assert.ok(h.calls.some((c) => c.fn === "fillRect" && c.op === "multiply"
                                && c.fill === "rgb(105, 105, 115)"),
            "the art was not multiplied by the grey");
  const calls = redraw(h);
  assert.ok(!calls.some((c) => c.op === "multiply"), "the grey copy was rebuilt per frame");
  assert.strictEqual(square(calls)[0].fill, "rgb(105, 105, 115)");
  assert.strictEqual(at(calls, "strokeRect", 102, 102)[0].stroke, "rgb(105, 105, 115)");
  const art = calls.filter((c) => c.fn === "drawImage" && c.args[1] === 100);
  assert.strictEqual(art.length, 1);
  assert.notStrictEqual(art[0].args[0], h.images[0], "the art was drawn untinted");
  assert.ok(!hatched(calls), "an unconscious body was hatched");
});

check("a corpse keeps its team colour and is hatched", () => {
  const h = board([agent(0, 2, 2, { faction: 1, hp: { cur: 0, max: 20 },
                                    conditions: ["dead"] })]);
  const calls = redraw(h);
  assert.strictEqual(square(calls)[0].fill, "rgb(210, 70, 70)");
  assert.ok(hatched(calls), "a corpse was not hatched");
});

check("an enemy's band says down: dead is hatched, otherwise grey", () => {
  const h = board([agent(0, 2, 2, { faction: 1, hp: { band: "Down" }, conditions: ["dead"] }),
                   agent(1, 6, 6, { faction: 1, hp: { band: "Down" }, conditions: [] })]);
  const calls = redraw(h);
  assert.ok(hatched(calls));
  assert.strictEqual(at(calls, "fillRect", 301, 301)[0].fill, "rgb(105, 105, 115)");
  assert.strictEqual(square(calls)[0].fill, "rgb(210, 70, 70)");
});

check("a healthy token is neither grey nor hatched", () => {
  const calls = redraw(board([agent(0, 2, 2)]));
  assert.strictEqual(square(calls)[0].fill, "rgb(80, 120, 220)");
  assert.ok(!hatched(calls));
});

check("a held body turns into a corpse when its killing blow plays, not before", () => {
  const h = board([agent(0, 2, 2)]);
  h.deliver({ t: "events", since: 4, seq: 6, events: [
    { kind: "announce", agent: 0, target: 0, text: "x" },
    { kind: "outcome", agent: 0, text: "Hit (20)", good: true, died: true, hp_after: 0 }] });
  h.deliver(view(6, [agent(0, 2, 2, { hp: { cur: 0, max: 20 }, conditions: ["dead"] })]));
  h.frame(0);
  let calls = redraw(h);
  assert.ok(!hatched(calls), "the corpse showed before its killing blow");
  assert.strictEqual(square(calls)[0].fill, "rgb(80, 120, 220)");
  h.frame(1000);                     // past the announce's reveal and hold
  calls = redraw(h);
  assert.ok(hatched(calls), "the killing blow played and the body was not hatched");
});

check("the HP bar is _draw_hp_bar's: colour by fraction, none from a band", () => {
  const h = board([agent(0, 2, 2, { hp: { cur: 5, max: 20 } }),
                   agent(1, 6, 6, { hp: { band: "Bloodied" } })]);
  const calls = redraw(h);
  // inset 2, bar height max(3, 50 // 12) = 4, so the bar's top is 150 - 4 - 2.
  const track = at(calls, "fillRect", 102, 144);
  assert.strictEqual(track.length, 2, "no track and fill at the bar's corner");
  assert.strictEqual(track[0].fill, "rgb(40, 40, 40)");
  assert.strictEqual(track[1].fill, "rgb(220, 60, 60)");
  assert.strictEqual(track[1].args[2], Math.round(46 * 0.25));
  assert.strictEqual(at(calls, "fillRect", 302, 344).length, 0, "a bar drawn from a band");
});

check("the name label and band stay", () => {
  const h = board([agent(1, 6, 6, { name: "Skarn", hp: { band: "Bloodied" } })]);
  redraw(h);
  assert.ok(h.texts.some((t) => t.text === "Skarn · Bloodied"));
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
