"use strict";
/*
 * The client's half of a reconnect and a restart (MULTIPLAYER_PLAN.md M6.5, D-M6-7),
 * driven through `app.js` itself under node. Run by `test_reclaim.py`; each check prints
 * one line, and the first failure exits 1.
 *
 *   · a dropped socket keeps the credential and retries with it;
 *   · a refused credential (4401, what a restart looks like) drops it, keeps the seat and
 *     brings back a pre-filled join card;
 *   · the join sends `principal_id` only while the name still says the remembered one;
 *   · nothing secret ever reaches `localStorage`.
 */

const assert = require("assert");
const { load } = require("./app_harness");

const SEAT = "dnd.seat";
const NO_CREDENTIAL = { session: {} };

const accepted = (id, name) => ({
  $status: 202,
  $body: { v: 1, t: "auth", ok: true, credential: `cred-${id}`,
           principal: { id, display_name: name, role: "player" }, seated: true, server_seq: 0 },
});

/* Type into the join card and press Join, then let the fetch answer. */
async function joinAs(h, code, name, reply) {
  h.replies.push(reply);
  h.el("code").value = code;
  h.el("name").value = name;
  h.el("join-form").fire("submit", { preventDefault() {} });
  for (let i = 0; i < 4; i++) await h.settle();
  const req = h.fetches.find((f) => f.url === "/join");
  assert.ok(req, "the join card did not POST /join");
  return JSON.parse(req.init.body);
}

const local = (h) => [...h.stores.local.entries()];

const checks = [];
const check = (name, fn) => checks.push([name, fn]);

check("a first join sends no principal_id, then remembers the seat it got", async () => {
  const h = load(NO_CREDENTIAL);
  assert.strictEqual(h.el("join").hidden, false, "no credential, and no join card");
  assert.strictEqual(h.sockets.length, 0);
  const body = await joinAs(h, "ABC123", "Kira", accepted("p_kira", "Kira"));
  assert.strictEqual(body.principal_id, undefined, `sent ${body.principal_id}`);
  assert.deepStrictEqual(JSON.parse(h.stores.local.get(SEAT)), { id: "p_kira", name: "Kira" });
  assert.strictEqual(h.stores.session.get("dnd.credential"), "cred-p_kira");
  assert.strictEqual(h.sockets.length, 1, "the join did not open the socket");
});

check("nothing secret reaches localStorage: not the credential, not the code", async () => {
  const h = load(NO_CREDENTIAL);
  await joinAs(h, "ABC123", "Kira", accepted("p_kira", "Kira"));
  for (const [k, v] of local(h)) {
    assert.ok(!v.includes("cred-"), `${k} holds the credential: ${v}`);
    assert.ok(!v.includes("ABC123"), `${k} holds the join code: ${v}`);
  }
});

check("a restart: the remembered name is pre-filled, and the join claims by principal_id", async () => {
  const h = load({ session: {}, local: { [SEAT]: JSON.stringify({ id: "p_kira", name: "Kira" }) } });
  assert.strictEqual(h.el("name").value, "Kira", "the join card is not pre-filled");
  assert.strictEqual(h.el("code").value, "", "the join code was remembered");
  const body = await joinAs(h, "ABC123", h.el("name").value, accepted("p_kira", "Kira"));
  assert.strictEqual(body.principal_id, "p_kira");
  assert.strictEqual(body.display_name, "Kira");
});

check("the name matches case-insensitively and around spaces, as the server's does", async () => {
  const h = load({ session: {}, local: { [SEAT]: JSON.stringify({ id: "p_kira", name: "Kira" }) } });
  const body = await joinAs(h, "ABC123", "kira", accepted("p_kira", "Kira"));
  assert.strictEqual(body.principal_id, "p_kira");
});

check("a different name on the same device is a different player: no principal_id", async () => {
  const h = load({ session: {}, local: { [SEAT]: JSON.stringify({ id: "p_kira", name: "Kira" }) } });
  const body = await joinAs(h, "ABC123", "Wen", accepted("p_wen", "Wen"));
  assert.strictEqual(body.principal_id, undefined, "Wen claimed Kira's seat");
  assert.deepStrictEqual(JSON.parse(h.stores.local.get(SEAT)), { id: "p_wen", name: "Wen" },
                         "the device does not now remember Wen's seat");
});

check("an unnamed seat is remembered with no name, and re-claimed from an empty field", async () => {
  const h = load(NO_CREDENTIAL);
  await joinAs(h, "ABC123", "", accepted("p_anon", "p_anon"));
  assert.deepStrictEqual(JSON.parse(h.stores.local.get(SEAT)), { id: "p_anon", name: "" });
  const h2 = load({ session: {}, local: { [SEAT]: h.stores.local.get(SEAT) } });
  assert.strictEqual(h2.el("name").value, "", "the seat's id was pre-filled as a name");
  const body = await joinAs(h2, "ABC123", "", accepted("p_anon", "p_anon"));
  assert.strictEqual(body.principal_id, "p_anon");
});

check("a garbled remembered seat is ignored, not a crash", async () => {
  for (const junk of ["{", "null", "[]", JSON.stringify({ id: 7, name: "Kira" })]) {
    const h = load({ session: {}, local: { [SEAT]: junk } });
    assert.strictEqual(h.el("name").value, "", `pre-filled from ${junk}`);
    const body = await joinAs(h, "ABC123", "Kira", accepted("p_kira", "Kira"));
    assert.strictEqual(body.principal_id, undefined, `sent an id from ${junk}`);
  }
});

check("a refused join leaves the remembered seat alone", async () => {
  const h = load({ session: {}, local: { [SEAT]: JSON.stringify({ id: "p_kira", name: "Kira" }) } });
  await joinAs(h, "WRONG1", "Kira", { $status: 403, $body: { ok: false } });
  assert.deepStrictEqual(JSON.parse(h.stores.local.get(SEAT)), { id: "p_kira", name: "Kira" });
  assert.strictEqual(h.el("join").hidden, false);
  assert.strictEqual(h.sockets.length, 0);
});

check("a dropped socket keeps the credential and retries with it", () => {
  const h = load();
  assert.strictEqual(h.socket.sent[0].credential, "cred");
  h.close(1006);
  assert.strictEqual(h.stores.session.get("dnd.credential"), "cred", "the drop cost the seat");
  assert.strictEqual(h.el("join").hidden, true, "a drop brought the join card back");
  assert.strictEqual(h.timeouts.length, 1, "no retry was scheduled");
  h.timeouts.shift().fn();
  assert.strictEqual(h.sockets.length, 2, "the retry opened no socket");
  h.open();
  assert.deepStrictEqual(h.socket.sent, [{ v: 1, t: "auth", credential: "cred" }]);
});

check("a restart (4401): the credential goes, the seat stays, the card comes back pre-filled", () => {
  const h = load({ local: { [SEAT]: JSON.stringify({ id: "p_kira", name: "Kira" }) } });
  h.close(4401);
  assert.strictEqual(h.stores.session.get("dnd.credential"), undefined, "a dead credential kept");
  assert.strictEqual(h.timeouts.length, 0, "a refused credential was retried");
  assert.strictEqual(h.el("join").hidden, false);
  assert.strictEqual(h.el("name").value, "Kira");
  assert.ok(h.el("join-error").textContent.includes("restarted"), h.el("join-error").textContent);
  assert.deepStrictEqual(JSON.parse(h.stores.local.get(SEAT)), { id: "p_kira", name: "Kira" });
});

check("a pre-fill never overwrites what the player already typed", () => {
  const h = load({ local: { [SEAT]: JSON.stringify({ id: "p_kira", name: "Kira" }) } });
  h.el("name").value = "Wen";
  h.close(4401);
  assert.strictEqual(h.el("name").value, "Wen");
});

(async () => {
  for (const [name, fn] of checks) {
    try {
      await fn();
      console.log(`ok   ${name}`);
    } catch (err) {
      console.log(`FAIL ${name}\n     ${err.message}`);
      process.exit(1);
    }
  }
})();
