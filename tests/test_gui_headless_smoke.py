#!/usr/bin/env python3
"""Rendered-geometry invariants for the combat panel (MULTIPLAYER_PLAN.md M2).

This is the third leg of the M2 test stool, and it exists because the other two both
missed something a human looking at the screen caught in about four seconds:

  · `test_combat_panel.py` proves the panel's STRUCTURE did not change. It records
    every widget's rect and asks whether it matches a golden. It cannot notice that a
    rect is *wrong*, only that it is *different* — and a rect that has been wrong since
    before M2a is, to a golden, simply the truth.
  · `test_action_menu.py` proves the AVAILABILITY rules. No screen in the room at all.
  · this file asks the questions you can only ask once pixels exist: does the label fit
    inside the button, do two buttons overlap, is a run of options stacked or laid out
    side by side, did the panel actually paint where it claimed to.

**It needs no display server and no browser.** `SDL_VIDEODRIVER=dummy` still renders
into a real `pygame.Surface`, so `app.screen` holds true pixels after a frame and
`font.size()` measures the same glyphs the panel blits. The manual pass this file
replaces was run against Xvfb + XTEST inside the GUI container, which was useful for
watching but is not needed to assert. What the suite could not previously do was never
headless rendering — it was *looking*.

Every check sweeps a spread of creature states (see `_STATES`), because a layout bug is
usually a bug about one class's band being longer than someone assumed.

Found by the pass this file is the residue of: **F12**, in `_KNOWN_TOO_WIDE` below.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import rpg_battle_map as rpg

from constants import COL_PANEL_BG, PANEL_W
from widgets import Button
from test_combat_panel import (App, MAP_PATH, SEED, _build_scene, _goto, _idx,
                               _reclass, _set_conditions, _set_res,
                               _snapshot_baseline, _preserve_cwd_logs,
                               _restore_cwd_logs)


def _place_duplicate(app, caster_idx, col=1, row=1):
    """One Invoke Duplicity illusion, so the Trickery cluster draws all three buttons.

    Spawned once and reused: `_sweep` runs each state's setup afresh, and a duplicate
    per sweep would pile tokens onto the map.
    """
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.summon_spell == "Invoke Duplicity" and pt.summoner_idx == caster_idx:
            app.bm.set_agent_removed_from_play(i, False)
            return i
    cfg = rpg.AgentConfig()
    cfg.name      = "Duplicate"
    cfg.size      = 1
    cfg.start_col = col
    cfg.start_row = row
    idx = app.bm.spawn_agent(cfg)
    app.bm.set_agent_summoner_idx(idx, caster_idx)
    app.bm.set_agent_summon_spell(idx, "Invoke Duplicity")
    return idx


# ─────────────────────────────────────────────────────────────────────────────
#  One frame, and what was in it
# ─────────────────────────────────────────────────────────────────────────────

class Drawn:
    """One widget as it was actually drawn: rect and font sampled AT DRAW TIME.

    The font matters and cannot be read afterwards: `panel.draw_action_row` swaps
    `btn.font` for the narrow rows and puts `font_md` back before it returns, so
    measuring a label against `btn.font` after the frame measures the wrong glyphs.
    """

    __slots__ = ("name", "text", "rect", "font", "color")

    def __init__(self, name, btn):
        self.name = name
        self.text = btn.text
        self.rect = btn.rect.copy()
        self.font = btn.font
        self.color = btn.color

    @property
    def text_w(self):
        return self.font.size(self.text)[0]

    def __repr__(self):
        return f"<{self.name} {self.text!r} {tuple(self.rect)}>"


def _frame(app):
    """Draw one combat panel and return every `btn_cbt_*` that really rendered.

    `Button.draw` is hooked rather than the rects being read afterwards, for the same
    reason `test_combat_panel.py` hooks it: "has a rect" and "was drawn" are different
    questions. They were different because the stale-rect guard parked undrawn buttons
    off-screen and F4 found a hole even in the parking; since M2e retired the guard they
    are different because an undrawn button simply keeps whatever rect it last had.
    """
    names = {}
    for attr, val in vars(app).items():
        if not attr.startswith("btn_cbt_"):
            continue
        if isinstance(val, Button):      # every one of them is an attribute since M2e
            names[id(val)] = attr

    out = []
    real_draw = Button.draw

    def draw(btn, surf):
        if id(btn) in names:
            out.append(Drawn(names[id(btn)], btn))
        return real_draw(btn, surf)

    Button.draw = draw
    try:
        app._draw_combat_panel()
    finally:
        Button.draw = real_draw
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  The states swept
# ─────────────────────────────────────────────────────────────────────────────
#
# Chosen for BAND LENGTH and label width rather than for rules coverage — that is
# `test_combat_panel.py`'s job. A Paladin 20 and a Clockwork Sorcerer 18 are here
# because they draw the longest §7 columns in the game, and the Sorcerer's labels
# ("Clockwork Cavalcade (7 SP)") are the widest.

def _states(app):
    """(label, setup) pairs. Each setup leaves a creature on turn, ready to draw."""

    def fighter():
        _goto(app, "Aria")

    def fighter_bonus_spent():
        _goto(app, "Aria")
        app.bonus_used = True

    def fighter_action_spent():
        _goto(app, "Aria")
        app.action_used = True

    def prone():
        idx = _goto(app, "Aria")
        _set_conditions(app, idx, prone=True)

    def incapacitated():
        idx = _goto(app, "Aria")
        _set_conditions(app, idx, incapacitated=True)

    def monk():
        _reclass(app, "Cyra", rpg.CharacterClass.Monk, 17,
                 monk_subclass=rpg.MonkSubclass.WarriorOfTheOpenHand)

    def sorcerer():
        _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 18,
                 sorcerer_subclass=rpg.SorcererSubclass.Clockwork)

    def draconic():
        _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 14,
                 sorcerer_subclass=rpg.SorcererSubclass.Draconic,
                 draconic_affinity_type=0)

    def paladin():
        _reclass(app, "Cyra", rpg.CharacterClass.Paladin, 20,
                 paladin_oath=rpg.PaladinOath.OathOfVengeance)

    def ranger():
        _reclass(app, "Cyra", rpg.CharacterClass.Ranger, 14,
                 ranger_subclass=rpg.RangerSubclass.BeastMaster)

    def cleric():
        _goto(app, "Brannor")

    # ── M2d's clusters. Chosen for band length and label width, as above: the
    #    Glamour Bard's four are the longest labels in §7, and the grappler is the
    #    only state that draws bucket 7c's Drop and Bite at all.
    def trickery_cleric():
        idx = _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 6,
                       cleric_subclass=rpg.ClericSubclass.TrickeryDomain)
        _place_duplicate(app, idx)

    def glamour_bard():
        idx = _reclass(app, "Cyra", rpg.CharacterClass.Bard, 14,
                       bard_subclass=rpg.BardCollege.Glamour)
        _set_res(app, idx, "Beguiling Magic", 0)

    def soulknife():
        _reclass(app, "Cyra", rpg.CharacterClass.Rogue, 13,
                 rogue_subclass=rpg.RogueSubclass.Soulknife)

    def shadow_monk():
        _reclass(app, "Cyra", rpg.CharacterClass.Monk, 17,
                 monk_subclass=rpg.MonkSubclass.WarriorOfShadow)

    def archfey():
        _reclass(app, "Cyra", rpg.CharacterClass.Warlock, 6,
                 warlock_subclass=rpg.WarlockSubclass.Archfey)

    def elemental_monk():
        _reclass(app, "Cyra", rpg.CharacterClass.Monk, 6,
                 monk_subclass=rpg.MonkSubclass.WarriorOfFourElements)

    def grappler():
        aria = _goto(app, "Aria")
        _set_conditions(app, _idx(app, "Skarn"), grappled=True, grappler_idx=aria)

    def featureless():
        _goto(app, "Skarn")

    def nobody():
        _goto(app, "Aria")
        app.initiative_order = []

    return [
        ("fighter", fighter),
        ("fighter, bonus spent", fighter_bonus_spent),
        ("fighter, action spent", fighter_action_spent),
        ("prone", prone),
        ("incapacitated", incapacitated),
        ("monk 17", monk),
        ("clockwork sorcerer 18", sorcerer),
        ("draconic sorcerer 14", draconic),
        ("paladin 20", paladin),
        ("ranger 14", ranger),
        ("cleric", cleric),
        ("trickery cleric 6", trickery_cleric),
        ("glamour bard 14", glamour_bard),
        ("soulknife rogue 13", soulknife),
        ("shadow monk 17", shadow_monk),
        ("archfey warlock 6", archfey),
        ("elemental monk 6", elemental_monk),
        ("grappling a neighbour", grappler),
        ("featureless", featureless),
        ("nobody on turn", nobody),
    ]


def _app():
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    _snapshot_baseline(app)
    return app


def _sweep(app):
    """Yield (state label, [Drawn, …]) for every state, restoring conditions after."""
    for label, setup in _states(app):
        setup()
        try:
            yield label, _frame(app)
        finally:
            # `nobody on turn` is deliberately last-ish and destroys the order; the
            # condition-setting states have to put the creature back.
            if app.initiative_order:
                idx = app._current_agent_idx()
                if 0 <= idx < len(app.bm.placed_agents):
                    _set_conditions(app, idx, prone=False, incapacitated=False)
                # the grappler state holds SKARN, not the creature on turn
                _set_conditions(app, _idx(app, "Skarn"),
                                grappled=False, grappler_idx=-1)


# ─────────────────────────────────────────────────────────────────────────────
#  F12 — does the label fit inside the button?
# ─────────────────────────────────────────────────────────────────────────────
#
# `Button.draw` blits the rendered text CENTRED on the rect and never clips it, so a
# label wider than its button silently bleeds across the gap into its neighbours. The
# structural golden cannot see this: it records `1052,300,60,30` and that rect is
# exactly what the layout intends. Only the glyphs are wrong.
#
# It held three names — `btn_cbt_disengage`, `btn_cbt_standup`, `btn_cbt_prone`, all of
# them in §4's five-up posture row, where a 60px column had to hold a 76px "Disengage".
# F12 closed that by letting `panel.draw_action_row` size a row to its labels when an equal
# split would clip (`panel.row_widths`), so the set is now EMPTY and stays that way: a new
# overflow fails the sweep below, and a name that starts fitting again fails the stale
# check, which is the only reason to keep the empty set rather than delete it.

_KNOWN_TOO_WIDE: set[str] = set()


def test_every_drawn_label_fits_its_button():
    app = _app()
    too_wide, seen_known = {}, set()
    for label, drawn in _sweep(app):
        for d in drawn:
            if d.text_w <= d.rect.w:
                continue
            if d.name in _KNOWN_TOO_WIDE:
                seen_known.add(d.name)
                continue
            too_wide.setdefault(d.name, (label, d.text, d.text_w, d.rect.w))

    assert not too_wide, (
        "label wider than its button (it will bleed over its neighbours):\n  "
        + "\n  ".join(f"{n}: {t!r} needs {w}px, button is {rw}px  [{st}]"
                      for n, (st, t, w, rw) in sorted(too_wide.items())))

    stale = _KNOWN_TOO_WIDE - seen_known
    assert not stale, (
        f"_KNOWN_TOO_WIDE is stale — {sorted(stale)} now fit. F12 is (partly) fixed; "
        f"delete them from the set so the fix cannot regress.")
    print(f"✅ test_every_drawn_label_fits_its_button passed "
          f"({len(_KNOWN_TOO_WIDE)} known F12 overflows still pinned)")


# ─────────────────────────────────────────────────────────────────────────────
#  Layout invariants
# ─────────────────────────────────────────────────────────────────────────────

def test_no_two_drawn_buttons_overlap():
    """Two widgets sharing pixels means one is unclickable wherever they meet.

    The golden records each rect on its own line and so is blind to the relationship
    between them; a button that was drawn holds the rect this frame gave it.
    """
    app = _app()
    bad = []
    for label, drawn in _sweep(app):
        for i, a in enumerate(drawn):
            for b in drawn[i + 1:]:
                if a.rect.colliderect(b.rect):
                    bad.append(f"[{label}] {a.name} {tuple(a.rect)} "
                               f"overlaps {b.name} {tuple(b.rect)}")
    assert not bad, "overlapping widgets:\n  " + "\n  ".join(bad)
    print("✅ test_no_two_drawn_buttons_overlap passed")


def test_every_drawn_button_lands_inside_the_panel():
    """A drawn button outside the panel's column is off-screen or over the map —
    either way the player cannot use it, and no availability test would notice."""
    app = _app()
    sw, sh = app.screen.get_size()
    px = app._panel_x()
    bad = []
    for label, drawn in _sweep(app):
        for d in drawn:
            if d.rect.x < px or d.rect.right > px + PANEL_W or d.rect.x < 0:
                bad.append(f"[{label}] {d.name} {tuple(d.rect)} outside panel "
                           f"x={px}..{px + PANEL_W}")
    assert not bad, "widgets drawn outside the panel:\n  " + "\n  ".join(bad)
    print("✅ test_every_drawn_button_lands_inside_the_panel passed")


def test_a_converted_run_is_stacked_not_columnised():
    """The mistake M2c actually made, as an invariant.

    §7 is a column of one-button rows. Reusing `panel.draw_action_row` for a whole run laid
    a Monk's five features out as a five-up instead, and every availability test still
    passed — the buttons existed, were enabled, and dispatched correctly. Only the
    shape was wrong. So: within one `_BON_RUN_*`, the members drawn in a frame must
    share an x and a width and differ in y.
    """
    import main
    runs = [v for k, v in vars(main).items() if k.startswith("_BON_RUN_")]
    assert runs, "no _BON_RUN_* tuples found — has §7's layout been restructured?"

    app = _app()
    checked = 0
    bad = []
    for label, drawn in _sweep(app):
        by_name = {d.name: d for d in drawn}
        for run in runs:
            members = [by_name[f"btn_cbt_{i}"] for i in run
                       if f"btn_cbt_{i}" in by_name]
            if len(members) < 2:
                continue
            checked += 1
            xs = {m.rect.x for m in members}
            ws = {m.rect.w for m in members}
            ys = {m.rect.y for m in members}
            if len(xs) != 1 or len(ws) != 1:
                bad.append(f"[{label}] run laid out side by side, not stacked: "
                           f"{[(m.name, tuple(m.rect)) for m in members]}")
            elif len(ys) != len(members):
                bad.append(f"[{label}] run shares a y (drawn on top of itself): "
                           f"{[(m.name, tuple(m.rect)) for m in members]}")
    assert not bad, "\n  ".join([""] + bad)
    assert checked >= 4, f"only {checked} runs had 2+ members drawn — sweep too thin"
    print(f"✅ test_a_converted_run_is_stacked_not_columnised passed "
          f"({checked} multi-member runs checked)")


def test_a_converted_row_is_side_by_side_not_stacked():
    """The mirror of the check above, and the other way to get a conversion wrong.

    §7 is a column of one-button rows with two exceptions — the Jump/Shove row and
    Cunning Action — and §4 is nothing but rows. Drawing one of those as a STACK is
    the same class of silent error as M2c's five-up: every availability test still
    passes, the buttons all exist, and the panel is three rows taller than it should
    be with a column of full-width buttons where a three-up belongs. So: within one
    `_*_ROW_*` tuple, the members drawn in a frame must share a y, and must tile that
    y — each one starting where the one before it ended, with no overlap.

    Equal widths used to stand in for "tiled", and that stopped being true with F12:
    a row that would clip its labels sizes its columns to them (`panel.row_widths`), so
    the posture row is 45/56/85/41/73 rather than five 60s. Overlap is what the check
    was really after — two buttons drawn on top of each other, or one stacked under
    another — and it is now tested directly rather than through a proxy.
    """
    import main
    rows = [v for k, v in vars(main).items()
            if k.startswith("_BON_ROW_") or k.startswith("_ACT_ROW_")]
    assert rows, "no _*_ROW_* tuples found — has the layout been restructured?"

    app = _app()
    checked = 0
    bad = []
    for label, drawn in _sweep(app):
        by_name = {d.name: d for d in drawn}
        for row in rows:
            members = [by_name[f"btn_cbt_{i}"] for i in row
                       if f"btn_cbt_{i}" in by_name]
            if len(members) < 2:
                continue
            checked += 1
            ys = {m.rect.y for m in members}
            xs = {m.rect.x for m in members}
            ordered = sorted(members, key=lambda m: m.rect.x)
            overlap = any(b.rect.x < a.rect.x + a.rect.w
                          for a, b in zip(ordered, ordered[1:]))
            if len(ys) != 1 or overlap:
                bad.append(f"[{label}] row stacked, not laid out side by side: "
                           f"{[(m.name, tuple(m.rect)) for m in members]}")
            elif len(xs) != len(members):
                bad.append(f"[{label}] row shares an x (drawn on top of itself): "
                           f"{[(m.name, tuple(m.rect)) for m in members]}")
    assert not bad, "\n  ".join([""] + bad)
    assert checked >= 4, f"only {checked} rows had 2+ members drawn — sweep too thin"
    print(f"✅ test_a_converted_row_is_side_by_side_not_stacked passed "
          f"({checked} multi-member rows checked)")


# ─────────────────────────────────────────────────────────────────────────────
#  Pixels — the premise everything above rests on
# ─────────────────────────────────────────────────────────────────────────────

def test_the_panel_paints_where_it_says_it_does():
    """`Button.draw` being called is not the same as pixels landing on the screen.

    Every check in this file reads a rect recorded at draw time; if the surface were
    never actually painted (a clip rect left set, a blit to the wrong surface, a panel
    drawn entirely off-screen) they would all still pass on stale bookkeeping. So this
    one reads the framebuffer back and requires each drawn button to have covered its
    own rect in its own colour.
    """
    app = _app()
    _goto(app, "Aria")
    drawn = _frame(app)
    assert drawn, "nothing drew at all"

    screen = app.screen
    thin = []
    for d in drawn:
        hits = 0
        total = 0
        for x in range(d.rect.x + 2, d.rect.right - 2, 3):
            for y in range(d.rect.y + 2, d.rect.bottom - 2, 3):
                total += 1
                if screen.get_at((x, y))[:3] == tuple(d.color[:3]):
                    hits += 1
        if total and hits / total < 0.25:
            thin.append(f"{d.name} {tuple(d.rect)}: only {hits}/{total} sampled "
                        f"pixels are its colour {tuple(d.color[:3])}")
    assert not thin, ("drawn buttons whose pixels are not on the screen:\n  "
                      + "\n  ".join(thin))

    # And the panel background is really behind them, i.e. we are reading the panel
    # and not an accidentally-blank surface.
    px = app._panel_x()
    bg = screen.get_at((px + PANEL_W - 3, screen.get_height() - 3))[:3]
    assert bg == COL_PANEL_BG, f"panel background is {bg}, expected {COL_PANEL_BG}"
    print(f"✅ test_the_panel_paints_where_it_says_it_does passed "
          f"({len(drawn)} widgets sampled)")


if __name__ == "__main__":
    # `_start_combat` truncates replay_log.txt / combat_log.txt in the cwd (gui/, per
    # the runner); the same courtesy the other two M2 suites extend.
    _saved = _preserve_cwd_logs()
    try:
        test_every_drawn_label_fits_its_button()
        test_no_two_drawn_buttons_overlap()
        test_every_drawn_button_lands_inside_the_panel()
        test_a_converted_run_is_stacked_not_columnised()
        test_a_converted_row_is_side_by_side_not_stacked()
        test_the_panel_paints_where_it_says_it_does()
    finally:
        _restore_cwd_logs(_saved)
        pygame.quit()
    print("\n✅ All headless GUI smoke tests passed!")
