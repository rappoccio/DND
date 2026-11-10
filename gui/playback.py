"""GUI Playback mode: watch a recorded fight (NPC_LEARNING_PLAN.md Step 2).

**Load Playback…** (Table menu) opens a ``sim_trace.jsonl`` trace (``sim_trace.py``) on a
read-only board. Each turn's recorded visual events go through the same
``App._npc_anim_start`` the live NPC turns use, seeded from that turn's recorded
snapshot. Step back re-seeds from the earlier turn's snapshot. Nothing re-executes the
engine (D7).

**The DM's scene is set aside, not reloaded.** Entering stashes every App attribute the
trace board replaces (``bm``, ``combat``, the map surfaces, the index-keyed metadata, the
view flags) by reference, and builds the trace's board in fresh objects. Leaving puts the
stashed objects back. Nothing is read from or written to the save, the store or the
autosave ring, and since the DM's ``bm`` is never touched it comes back exactly as it was.

While Playback is up, ``App.run`` skips everything that would act on the board or reach
the players: the NPC drive, net submits, the net pump and push, and the fog reveal (which
can deploy on-deck enemies). ``App._handle_events`` hands every event here first, so no
click reaches the setup panel or the map's editing handlers.

The trace format has no terrain yet, so the board is the map image and its grid, and the
trace's ``manual_grid`` if it recorded one. Doors, painted walls and lights are not drawn.
"""

from __future__ import annotations

import json
import os

import pygame
import rpg_battle_map as rpg

import sim_trace
from constants import (COL_BTN, COL_BTN_HOVER, COL_LABEL, COL_PANEL_BG, COL_PANEL_BORDER,
                       COL_TEXT, PANEL_W)
from net.roster import tokens_from_battle_map
from widgets import Button

SPEEDS = (0.5, 1.0, 2.0, 4.0, 8.0)
TURN_GAP_MS = 600            # pause between turns while playing, at 1×
COL_ACTOR = (255, 210, 50)   # the acting token's ring, the initiative tracker's gold

# App attributes the trace board replaces. Containers that the loaders clear in place are
# replaced by fresh ones on entry (see Playback._enter), so the stashed object survives.
_STASH = (
    "bm", "combat", "_map_path", "base_map_scale", "view_zoom", "map_scale",
    "_map_converted", "_map_native_size", "map_surf", "map_rect", "overlay",
    "pan_x", "pan_y", "selected_idx", "drag_idx", "pending_configs", "_spell_metadata",
    "_agent_meta", "_xp_awarded_agents", "_manual_grid", "_attack_cells_melee",
    "_attack_cells_rnorm", "_attack_cells_rlong", "_floating_texts", "_fog_dirty",
    "show_fog", "dm_view", "show_lighting_overlay", "animate_moves", "_npc_anim_speed",
)


# ── Pure helpers (no App, no display) ────────────────────────────────────────

def playable_turns(trace: sim_trace.Trace) -> list[sim_trace.TraceTurn]:
    """The turns Playback steps through: every record with an actor and a snapshot. The
    prelude (``actor == -1``, log lines before the first turn) has neither."""
    return [t for t in trace.turns if t.actor >= 0 and t.snapshot is not None]


def roster(trace: sim_trace.Trace) -> list[dict] | None:
    """The whole raw agent list: the header's agents, then every ``spawned`` record in
    order. The visual events and snapshots are keyed by this basis. None when the header
    has no agents (the recorder could not build them)."""
    doc = trace.header.get("agents")
    if not isinstance(doc, dict) or not isinstance(doc.get("agents"), list):
        return None
    out = list(doc["agents"])
    for t in trace.turns:
        out.extend(t.spawned)
    return out


def fold_events(snapshot: dict, events) -> dict:
    """The display state after a turn: ``snapshot`` with each Move landed on its route's
    end and each Outcome's ``hp_after`` / ``died`` applied. Used after the last turn, which
    has no following snapshot to show."""
    out = {i: dict(s) for i, s in snapshot.items()}
    for ev in events:
        s = out.get(ev.agent_idx)
        if s is None:
            continue
        if ev.kind == 0 and len(ev.path) > 0:                      # Move
            s["pos"] = (float(ev.path[-1].col), float(ev.path[-1].row))
        elif ev.kind == 2:                                         # Outcome
            if ev.hp_after >= 0:
                s["hp"] = ev.hp_after
            if ev.died:
                s["was_alive"] = False
    return out


def outcome_text(trace: sim_trace.Trace) -> str:
    f = trace.footer
    if f is None:
        return "cut short (no footer)"
    winner = f.get("winner")
    rnd = f.get("rounds")
    if trace.header.get("arena"):
        # gui/arena.py: the winner is a side, and rounds counts the rounds played.
        who = {"pc": "PCs won", "npc": "NPCs won"}.get(winner, "no winner")
        last = str(int(rnd)) if isinstance(rnd, int) else "?"
    else:
        # The GUI recorder: a faction, and round_num, zero-based as on turns.
        who = f"faction {winner} won" if winner is not None else "no winner"
        last = str(int(rnd) + 1) if isinstance(rnd, int) else "?"
    return f"{f.get('reason', '?')} · {who} · ended in round {last}"


# The fallback rung as the HUD shows it (NPC_LEARNING_PLAN.md Step 4). Heuristic turns show none.
RUNG_TEXT = {"TreeTop": "rung 1 tree", "TreeRanked": "rung 2 tree", "Archetype": "rung 3 archetype",
             "Level4": "rung 4 Level 4", "Simple": "rung 5 Simple"}


def decision_text(decision: dict | None) -> str:
    """`` · Blaster: PreferAOE (rung 3 archetype)`` for a turn's decision; "" for none."""
    if not decision:
        return ""
    rung = RUNG_TEXT.get(decision.get("rung", ""))
    return (f" · {decision.get('archetype', '?')}: {decision.get('strategy', '?')}"
            f"{f' ({rung})' if rung else ''}")


# ── The mode ─────────────────────────────────────────────────────────────────

def open_browser(app) -> None:
    """Load Playback…: pick a trace. Refused mid-combat, before the browser opens."""
    why = blocked(app)
    if why:
        app._flash_status(f"Playback: {why}")
        return
    start = os.path.dirname(os.path.abspath(app.SIM_TRACE_FILE))
    app.file_browser.open(start, lambda p: enter(app, p), save_mode=False,
                          extensions={".jsonl"}, title="Load Playback")


def blocked(app) -> str | None:
    if getattr(app, "playback", None) is not None:
        return "already playing back"
    if app.combat_active:
        return "end combat first"
    if app._npc_anim is not None:
        return "an animation is still playing"
    return None


def enter(app, path: str) -> "Playback | None":
    """Open ``path`` in Playback. Returns the mode, or None (and flashes why) when the
    trace cannot be shown. A refusal leaves the DM's scene exactly as it was."""
    why = blocked(app)
    trace = None
    if why is None:
        try:
            trace = sim_trace.load_trace(path)
        except (OSError, ValueError, KeyError, TypeError) as e:
            why = f"cannot read {os.path.basename(path)} ({e})"
    if why is None:
        why = _check(trace)
    if why is not None:
        app._flash_status(f"Playback: {why}")
        return None
    pb = Playback(app, trace, path)
    why = pb._enter()
    if why is not None:
        app._flash_status(f"Playback: {why}")
        return None
    app.playback = pb
    return pb


def _check(trace: sim_trace.Trace) -> str | None:
    if roster(trace) is None:
        return "the trace has no agents"
    if not playable_turns(trace):
        return "the trace has no turns"
    m = trace.header.get("map") or ""
    if not m or not os.path.exists(m):
        return f"map image not found ({m or 'none recorded'})"
    return None


class Playback:
    def __init__(self, app, trace: sim_trace.Trace, path: str):
        self.app = app
        self.trace = trace
        self.path = path
        self.turns = playable_turns(trace)
        self.ti = 0                  # the next turn to play; the board shows the state before it
        self.playing = False
        self.speed_i = SPEEDS.index(1.0)
        self._gap_until = 0          # ms: the next turn may start (between-turn pause)
        self._stash: dict = {}
        self._screen_size = None
        self._scrub_rect = pygame.Rect(0, 0, 0, 0)
        self._speed_rects: list[pygame.Rect] = []
        self._buttons: dict[str, Button] = {}

    # ── Entering and leaving ─────────────────────────────────────────────
    def _enter(self) -> str | None:
        app = self.app
        self._stash = {k: getattr(app, k) for k in _STASH}
        self._screen_size = app.screen.get_size()
        # The loaders clear these in place; give them fresh ones so the stash keeps the DM's.
        app.pending_configs = []
        app._spell_metadata = {}
        app._agent_meta = {}
        app._xp_awarded_agents = set()
        app._floating_texts = []
        try:
            self._build_board()
        except Exception as e:           # noqa: BLE001 — any failure puts the scene back
            self._restore()
            return f"could not build the board ({e})"
        n = len(app.bm.placed_agents)
        if n != len(roster(self.trace)):
            self._restore()
            return f"placed {n} of {len(roster(self.trace))} agents"
        app.show_fog = False             # the trace is watched with the whole board shown
        app.dm_view = False
        app.show_lighting_overlay = False
        app.animate_moves = True
        app._npc_anim_speed = SPEEDS[self.speed_i]
        self._seed(self.ti)
        return None

    def _build_board(self):
        """The trace's map, grid and agents, in fresh objects. ``_load_map_png`` replaces
        ``bm`` and the surfaces; ``_load_agents`` reads a temp file of the full roster."""
        app = self.app
        h = self.trace.header
        app._load_map_png(h["map"])
        mg = h.get("manual_grid")
        if mg:
            app.bm.set_uniform_grid(int(mg["cell_px"]), int(mg["anchor"][0]),
                                    int(mg["anchor"][1]))
            app._build_overlay()
        app._manual_grid = mg or None
        # A bare engine: RecordingCombat would log these loads into the checked replay.
        app.combat = rpg.CombatEngine(int(h.get("seed", 0)) % (2 ** 32))
        agents = [dict(a) for a in roster(self.trace)]
        for a in agents:
            # apply_agent_configs drops a record whose cell is blocked, which would shift
            # every later index. Any free cell will do: _seed sets each position.
            if app.bm.is_blocked(rpg.Cell(int(a["col"]), int(a["row"])), int(a["size"])):
                a["col"], a["row"] = app._placeable_cell(int(a["size"]))
        doc = dict(h["agents"], agents=agents)
        doc.pop("active_conditions", None)    # keyed to the header's basis, and not drawn
        tmp = self.path + ".playback.tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(doc, f)
            app._load_agents(tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        # _load_agents re-keyed the roster's ownership cache to this board; seats keep the
        # DM's scene's.
        app.roster.sync_tokens(tokens_from_battle_map(self._stash["bm"]))

    def exit(self):
        """Put the DM's scene back."""
        app = self.app
        if app._npc_anim is not None:
            app._npc_anim = None         # no on_done: it belongs to this board
        self._restore()
        app.playback = None
        app._flash_status("Playback closed")

    def _restore(self):
        app = self.app
        for k, v in self._stash.items():
            setattr(app, k, v)
        if self._screen_size and app.screen.get_size() != self._screen_size:
            app.screen = pygame.display.set_mode(self._screen_size, pygame.RESIZABLE)
            app._reposition_panel()
        app.roster.sync_tokens(tokens_from_battle_map(app.bm))
        app.sprites.clear()              # the cache is keyed by path; drop the trace's

    # ── The board ────────────────────────────────────────────────────────
    def _state_before(self, ti: int) -> dict:
        """Display state before turn ``ti``: its snapshot, or after the last turn, the
        last snapshot with that turn's events folded in."""
        if ti < len(self.turns):
            return self.turns[ti].snapshot
        last = self.turns[-1]
        return fold_events(last.snapshot, last.events)

    def _seed(self, ti: int):
        """Set the board's live state to the display state before turn ``ti``: what the
        board shows between turns, and what a turn's animation ends on."""
        app = self.app
        bm, combat = app.bm, app.combat
        snap = self._state_before(ti)
        for i, pt in enumerate(bm.placed_agents):
            s = snap.get(i)
            if s is None:                # not spawned yet, or dismissed
                if not pt.removed_from_play:
                    bm.set_agent_removed_from_play(i, True)
                continue
            if pt.removed_from_play:
                bm.set_agent_removed_from_play(i, False)
            col, row = int(round(s["pos"][0])), int(round(s["pos"][1]))
            if (pt.origin.col, pt.origin.row) != (col, row):
                bm.set_agent_position(i, rpg.Cell(col, row))
            st = combat.get_agent_stats(bm, i)
            if st.hp_cur != s["hp"]:
                st.hp_cur = s["hp"]
                combat.set_agent_stats(bm, i, st)
            co = combat.get_agent_conditions(bm, i)
            if co.dead != (not s["was_alive"]):
                co.dead = not s["was_alive"]
                combat.set_agent_conditions(bm, i, co)

    # ── Controls ─────────────────────────────────────────────────────────
    @property
    def speed(self) -> float:
        return SPEEDS[self.speed_i]

    def set_speed(self, i: int):
        self.speed_i = max(0, min(len(SPEEDS) - 1, i))
        self.app._npc_anim_speed = self.speed

    def _cancel_anim(self):
        self.app._npc_anim = None

    def _play_turn(self):
        """Animate turn ``ti`` from its snapshot; when it drains, the board moves on."""
        if self.ti >= len(self.turns):
            return
        t = self.turns[self.ti]
        self._seed(self.ti)
        self.app._npc_anim_start(t.events, t.snapshot, on_done=self._turn_done)

    def _turn_done(self):
        self.ti += 1
        self._seed(self.ti)
        self._gap_until = pygame.time.get_ticks() + int(TURN_GAP_MS / self.speed)
        if self.ti >= len(self.turns):
            self.playing = False

    def toggle_play(self):
        if self.ti >= len(self.turns):
            self.goto(0)             # play again from the top
        self.playing = not self.playing
        self._gap_until = 0

    def step(self):
        """One turn forward: finish the turn in progress, else play the next one."""
        self.playing = False
        if self.app._npc_anim is not None:
            self.app._npc_anim_fast_forward()
        elif self.ti < len(self.turns):
            self._play_turn()

    def step_back(self):
        """One turn back: to the start of the turn in progress, else of the one before."""
        self.playing = False
        if self.app._npc_anim is not None:
            self.goto(self.ti)
        else:
            self.goto(self.ti - 1)

    def goto(self, ti: int):
        self._cancel_anim()
        self.ti = max(0, min(len(self.turns), ti))
        self._seed(self.ti)
        self._gap_until = 0

    def tick(self):
        """Per frame: while playing, start the next turn once the last one and the gap
        between turns are done."""
        if (self.playing and self.app._npc_anim is None
                and pygame.time.get_ticks() >= self._gap_until):
            if self.ti < len(self.turns):
                self._play_turn()
            else:
                self.playing = False

    # ── Input ────────────────────────────────────────────────────────────
    def handle_event(self, event) -> bool:
        """Every event comes here first while Playback is up. Returns False only for the
        ones the App may still have (a window resize); everything else is consumed."""
        if event.type == pygame.VIDEORESIZE:
            return False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE:
                self.toggle_play()
            elif event.key == pygame.K_RIGHT:
                self.step()
            elif event.key == pygame.K_LEFT:
                self.step_back()
            elif event.key == pygame.K_ESCAPE:
                self.exit()
            elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                self.set_speed(self.speed_i + 1)
            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.set_speed(self.speed_i - 1)
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._click(event.pos)
        elif (event.type == pygame.MOUSEMOTION and event.buttons[0]
              and self._scrub_rect.collidepoint(event.pos)):
            self._scrub(event.pos[0])
        return True

    def _click(self, pos):
        b = self._buttons
        if b.get("exit") and b["exit"].rect.collidepoint(pos):
            self.exit()
        elif b.get("play") and b["play"].rect.collidepoint(pos):
            self.toggle_play()
        elif b.get("step") and b["step"].rect.collidepoint(pos):
            self.step()
        elif b.get("back") and b["back"].rect.collidepoint(pos):
            self.step_back()
        elif self._scrub_rect.collidepoint(pos):
            self._scrub(pos[0])
        else:
            for i, r in enumerate(self._speed_rects):
                if r.collidepoint(pos):
                    self.set_speed(i)
                    break

    def _scrub(self, x: int):
        r = self._scrub_rect
        if r.w <= 0:
            return
        f = (x - r.x) / r.w
        ti = int(round(f * len(self.turns)))
        if ti != self.ti or self.app._npc_anim is not None:
            self.goto(ti)

    # ── Drawing ──────────────────────────────────────────────────────────
    def current_turn(self) -> sim_trace.TraceTurn | None:
        """The turn on screen: the one animating, else the next to play, else the last."""
        if not self.turns:
            return None
        return self.turns[min(self.ti, len(self.turns) - 1)]

    def hud_text(self) -> str:
        """The map's top line: round, actor, driver, the actor's archetype and strategy
        (with the fallback rung on a Level 5/6 policy turn), and the policy per side. The
        chosen macro-action replaces the strategy once Step 5 records it."""
        h = self.trace.header
        t = self.current_turn()
        if t is None:
            return ""
        done = " · END" if self.ti >= len(self.turns) and self.app._npc_anim is None else ""
        return (f"PLAYBACK · Round {t.round + 1} · {t.actor_name or t.actor} ({t.driver})"
                f"{decision_text(t.decision)}"
                f" · NPC policy {h.get('npc_policy', '?')} · PCs {h.get('pc_mode', '?')}"
                f"{done}")

    def party_lines(self) -> list[tuple[str, str]]:
        """The party box under the HUD line: a title, then one ``(text, state)`` per PC, where
        state is ``actor`` (its turn), ``down`` (0 HP on the board) or ``up``. Empty when the
        trace has no PCs."""
        party = sim_trace.trace_party(self.trace.header)
        if not party:
            return []
        sc = self.trace.header.get("scenario") or {}
        title = "Party"
        if sc:
            title += (f" · L{sc.get('party_level', '?')} · {sc.get('difficulty', '?')}"
                      f" vs {', '.join(sc.get('mobs', []))}")
        t = self.current_turn()
        agents = self.app.bm.placed_agents
        by_name = {pt.name: i for i, pt in enumerate(agents)}
        lines = [(title, "title")]
        for p in party:
            i = by_name.get(p["name"], -1)
            state = "up"
            if t is not None and i == t.actor:
                state = "actor"
            elif i >= 0 and (agents[i].stats.hp_cur <= 0 or agents[i].conditions.dead):
                state = "down"
            lines.append((f"{p['name']} — {p['class']}", state))
        return lines

    def draw_map_layer(self):
        """The acting token's ring and the HUD line, over the board."""
        app = self.app
        t = self.current_turn()
        if t is not None and 0 <= t.actor < len(app.bm.placed_agents):
            pt = app.bm.placed_agents[t.actor]
            if not pt.removed_from_play:
                pos = app._npc_anim_display_pos(t.actor) or (pt.origin.col, pt.origin.row)
                sx, sy = app._cell_to_screen_f(pos[0], pos[1])
                size = int(app.bm.cell_pixel_size * app.map_scale) * pt.size
                pygame.draw.rect(app.screen, COL_ACTOR,
                                 pygame.Rect(sx - 2, sy - 2, size + 4, size + 4), 3)
        label = app.font_md.render(self.hud_text(), True, COL_TEXT)
        bg = pygame.Surface((label.get_width() + 16, label.get_height() + 8), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        app.screen.blit(bg, (8, 8))
        app.screen.blit(label, (16, 12))
        # The party box, under the HUD line.
        colors = {"title": COL_LABEL, "up": COL_TEXT, "actor": COL_ACTOR, "down": (110, 110, 120)}
        rows = [app.font_sm.render(txt + ("  (down)" if st == "down" else ""), True, colors[st])
                for txt, st in self.party_lines()]
        if rows:
            top = 8 + bg.get_height() + 6
            box = pygame.Surface((max(r.get_width() for r in rows) + 16,
                                  sum(r.get_height() + 2 for r in rows) + 8), pygame.SRCALPHA)
            box.fill((0, 0, 0, 160))
            app.screen.blit(box, (8, top))
            y = top + 4
            for r in rows:
                app.screen.blit(r, (16, y))
                y += r.get_height() + 2

    def draw_panel(self):
        app = self.app
        scr = app.screen
        sw, sh = scr.get_size()
        px = sw - PANEL_W
        pad = app._PANEL_PAD
        x, w = px + pad, PANEL_W - 2 * pad
        pygame.draw.rect(scr, COL_PANEL_BG, pygame.Rect(px, 0, PANEL_W, sh))
        pygame.draw.line(scr, COL_PANEL_BORDER, (px, 0), (px, sh))

        y = 12
        scr.blit(app.font_lg.render("Playback", True, COL_TEXT), (x, y))
        y += 30
        for line in (os.path.basename(self.path), outcome_text(self.trace)):
            scr.blit(app.font_sm.render(line, True, COL_LABEL), (x, y))
            y += 18
        y += 8

        bw = (w - 8) // 3
        bh = app._BTN_H
        self._buttons = {
            "back": Button(pygame.Rect(x, y, bw, bh), "◀ Back", font=app.font_md),
            "play": Button(pygame.Rect(x + bw + 4, y, bw, bh),
                           "Pause" if self.playing else "Play", font=app.font_md),
            "step": Button(pygame.Rect(x + 2 * (bw + 4), y, bw, bh), "Step ▶",
                           font=app.font_md),
        }
        for b in self._buttons.values():
            b.draw(scr)
        y += bh + 14

        # Speed: a stepped slider, one stop per speed.
        scr.blit(app.font_sm.render(f"Speed {self._speed_label(self.speed)}", True,
                                    COL_LABEL), (x, y))
        y += 18
        sw_ = w // len(SPEEDS)
        self._speed_rects = []
        mouse = pygame.mouse.get_pos()
        for i, sp in enumerate(SPEEDS):
            r = pygame.Rect(x + i * sw_, y, sw_ - 4, 24)
            self._speed_rects.append(r)
            on = i == self.speed_i
            col = COL_BTN_HOVER if (on or r.collidepoint(mouse)) else COL_BTN
            pygame.draw.rect(scr, col, r, border_radius=4)
            if on:
                pygame.draw.rect(scr, COL_ACTOR, r, 2, border_radius=4)
            lab = app.font_sm.render(self._speed_label(sp), True, COL_TEXT)
            scr.blit(lab, lab.get_rect(center=r.center))
        y += 36

        # Scrubber: one tick per round start; the knob is the turn on screen.
        n = len(self.turns)
        t = self.current_turn()
        where = (f"Turn {self.ti + 1} / {n} · Round {t.round + 1}" if self.ti < n
                 else f"End · {n} turns")
        scr.blit(app.font_sm.render(where, True, COL_LABEL), (x, y))
        y += 20
        self._scrub_rect = pygame.Rect(x, y, w, 18)
        pygame.draw.rect(scr, (35, 35, 45), self._scrub_rect, border_radius=4)
        prev = None
        for i, tt in enumerate(self.turns):
            if tt.round != prev:
                tx = x + int(i / n * w)
                pygame.draw.line(scr, COL_PANEL_BORDER, (tx, y + 2), (tx, y + 15))
                prev = tt.round
        kx = x + int(min(self.ti, n) / n * w)
        pygame.draw.rect(scr, COL_ACTOR, pygame.Rect(kx - 3, y - 2, 6, 22), border_radius=2)
        y += 30

        # The turn's combat-log lines.
        scr.blit(app.font_sm.render("Log", True, COL_LABEL), (x, y))
        y += 18
        exit_y = sh - bh - 12
        if t is not None:
            for line in t.log:
                for chunk in _wrap(app.font_sm, line, w):
                    if y + 16 > exit_y - 8:
                        break
                    scr.blit(app.font_sm.render(chunk, True, COL_TEXT), (x, y))
                    y += 16

        self._buttons["exit"] = Button(pygame.Rect(x, exit_y, w, bh), "Exit Playback",
                                       font=app.font_md)
        self._buttons["exit"].draw(scr)

    @staticmethod
    def _speed_label(sp: float) -> str:
        return "½×" if sp == 0.5 else f"{int(sp)}×"


def _wrap(font, text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        trial = f"{cur} {wd}" if cur else wd
        if font.size(trial)[0] <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines
