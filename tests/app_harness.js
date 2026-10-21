"use strict";
/*
 * Runs the player's client (`gui/net/static/app.js`) under node, with just enough of a
 * browser stubbed in to drive it frame by frame (M4b.3).
 *
 * Nothing here is a DOM. Every element is a bag of properties that records what the client
 * set on it; the canvas context records its `fillText` calls and ignores the rest; the
 * clock and the animation frames move only when a check moves them. The client is loaded
 * into a `vm` context, so its top-level bindings (`view`, `seq`, `play`, `displayed()` …)
 * can be read with `h.ev("…")`, and frames reach it through the one socket it opens.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const APP_JS = process.env.APP_JS || path.join(__dirname, "..", "gui", "net", "static", "app.js");

function load(opts = {}) {
  const clock = { now: 1000 };
  const rafs = [];
  const fetches = [];
  const replies = [];
  const texts = [];
  const calls = [];        // every canvas call, with the styles in force (M4b.5)
  const images = [];       // every Image the client made; a check fires its onload
  const sprites = [];      // GET /sprite?name=… requests, kept out of `fetches` and `replies`
  const spriteStatus = new Map(opts.spriteStatus || []);   // basename → HTTP status
  const elements = new Map();
  const stores = {
    session: new Map([["dnd.credential", "cred"], ["dnd.principal", "Ann"]]),
    local: new Map(Object.entries(opts.local || {})),
  };

  const ctx2d = new Proxy({ fillStyle: "", globalAlpha: 1 }, {
    get(target, prop) {
      if (prop === "fillText") {
        return (text, x, y) => {
          texts.push({ text, x, y, fill: target.fillStyle, alpha: target.globalAlpha });
          calls.push({ fn: "fillText", args: [text, x, y], fill: target.fillStyle });
        };
      }
      if (prop === "measureText") return (text) => ({ width: text.length * 6 });
      if (prop in target) return target[prop];
      return (...args) => calls.push({ fn: prop, args, fill: target.fillStyle,
                                       stroke: target.strokeStyle,
                                       op: target.globalCompositeOperation });
    },
    set(target, prop, value) { target[prop] = value; return true; },
  });

  function element(id) {
    const node = {
      id, textContent: "", hidden: false, disabled: false, value: "", checked: false,
      className: "", dataset: {}, style: {}, children: [], listeners: {},
      width: 16, height: 16, scrollTop: 0, scrollHeight: 0,
      append(...kids) { this.children.push(...kids); },
      addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
      removeAttribute() {},
      getContext() { return ctx2d; },
      getBoundingClientRect() { return { left: 0, top: 0, width: this.width, height: this.height }; },
      fire(type, event) { for (const fn of this.listeners[type] || []) fn(event); },
    };
    return node;
  }

  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element(id));
      return elements.get(id);
    },
    createElement(tag) { return element(tag); },
  };

  function storage(map) {
    return {
      getItem: (k) => (map.has(k) ? map.get(k) : null),
      setItem: (k, v) => map.set(k, String(v)),
      removeItem: (k) => map.delete(k),
    };
  }

  const sockets = [];
  class WebSocket {
    constructor(url) { this.url = url; this.sent = []; sockets.push(this); }
    send(data) { this.sent.push(JSON.parse(data)); }
  }

  function fetch(url, init = {}) {
    if (url.startsWith("/sprite?name=")) {
      sprites.push({ url, init });
      const status = spriteStatus.get(decodeURIComponent(url.slice(13))) || 200;
      return Promise.resolve({ ok: status === 200, status, blob: async () => ({ url }) });
    }
    fetches.push({ url, init });
    const reply = replies.shift();
    if (reply === undefined) return new Promise(() => {});   // never answers
    return Promise.resolve({ ok: true, status: 200, json: async () => reply,
                             blob: async () => ({}) });
  }

  const sandbox = {
    document, WebSocket, fetch, console,
    sessionStorage: storage(stores.session),
    localStorage: storage(stores.local),
    location: { protocol: "http:", host: "table:6081" },
    performance: { now: () => clock.now },
    requestAnimationFrame: (fn) => { rafs.push(fn); return rafs.length; },
    setInterval: () => 0,
    setTimeout: () => 0,
    URL: { createObjectURL: () => "blob:x", revokeObjectURL: () => {} },
    Image: class { constructor() { images.push(this); } },
  };
  const context = vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(APP_JS, "utf8"), context, { filename: "app.js" });

  const h = {
    clock, fetches, replies, texts, stores, sockets, calls, images, sprites, spriteStatus,
    el: (id) => document.getElementById(id),
    ev: (expr) => vm.runInContext(expr, context),
    get socket() { return sockets[sockets.length - 1]; },
    open() { h.socket.onopen(); },
    deliver(frame) { h.socket.onmessage({ data: JSON.stringify(Object.assign({ v: 1 }, frame)) }); },
    close(code = 1006) { h.socket.onclose({ code }); },
    /* Advance the clock by `ms`, then run the animation frames that were pending. */
    frame(ms = 0) {
      clock.now += ms;
      const due = rafs.splice(0);
      for (const fn of due) fn(clock.now);
    },
    /* Let pending promise callbacks (a fetch's answer) run. */
    settle: () => new Promise((resolve) => setImmediate(resolve)),
    /* Where the board draws each agent right now: {idx: [col, row, hp]}. */
    board() {
      const out = {};
      for (const a of vm.runInContext("displayed()", context)) out[a.agent] = [a.col, a.row, a.hp];
      return out;
    },
  };
  h.open();
  return h;
}

module.exports = { load };
