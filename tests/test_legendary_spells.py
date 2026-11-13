#!/usr/bin/env python3
"""Legendary actions that cast spells, and per-action costs (headless App).

A bestiary legendary block may map an action name to a spell in the creature's own list
(`action_spells`) and give it a cost (`action_costs`, default 1) — Zariel's Immolating Gaze
(2 actions) and Teleport. Choosing one arms a creature or cell pick; the spell is cast free,
as the legendary creature, out of turn. An option the creature can't afford is refused."""

import json
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
import helpers
from agent_loader import dict_to_stats
from menus import features

from test_combat_panel import App, MAP_PATH, SEED, _build_scene, _idx, _snapshot_baseline

_SPELLS = {s["name"]: s for s in json.load(open(os.path.join(_ROOT, "gui", "spells.json")))}


def _app():
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    _snapshot_baseline(app)
    return app


def _make_legendary(app, idx, budget=3):
    """Turn idx into a Zariel-style legendary spellcaster with a full budget."""
    s = app.combat.get_agent_stats(app.bm, idx)
    s.cha = 30; s.prof_bonus = 8; s.spellcasting_ability = 5
    s.has_legendary_actions = True
    s.legendary_actions_max = 3
    s.legendary_actions_current = budget
    s.legendary_action_names = ["Immolating Gaze", "Teleport"]
    s.legendary_action_costs = {"Immolating Gaze": 2}
    s.legendary_action_spells = {"Immolating Gaze": "ZarielImmolatingGaze",
                                 "Teleport": "ZarielTeleport"}
    app.combat.set_agent_stats(app.bm, idx, s)
    app.combat.set_agent_spells(app.bm, idx, [helpers._dict_to_spell(_SPELLS[n]) for n in
                                              ("ZarielImmolatingGaze", "ZarielTeleport")])
    app._legendary_queue = [idx]
    app._legendary_actor = idx


def _budget(app, idx):
    return app.combat.get_agent_stats(app.bm, idx).legendary_actions_current


def _weak(app, idx, hp=200):
    s = app.combat.get_agent_stats(app.bm, idx)
    s.wis = 1; s.save_prof_wis = False; s.hp_cur = s.hp_max = hp
    app.combat.set_agent_stats(app.bm, idx, s)


def test_gaze_costs_two_and_burns_the_target():
    app = _app()
    skarn, aria = _idx(app, "Skarn"), _idx(app, "Aria")
    _make_legendary(app, skarn)
    _weak(app, aria)
    app._choose_legendary_action("Immolating Gaze")
    assert app._legendary_spell_pick == "creature", "a Single-target spell arms a creature pick"
    assert _budget(app, skarn) == 3, "nothing is spent until the target is picked"
    app._resolve_legendary_spell(aria, None)
    assert app._legendary_spell_pick == ""
    assert _budget(app, skarn) == 1, "Immolating Gaze costs 2"
    assert app.combat.get_agent_stats(app.bm, aria).hp_cur < 200, "the failed WIS save burns"
    print("✅ test_gaze_costs_two_and_burns_the_target passed")


def test_an_unaffordable_option_is_refused():
    app = _app()
    skarn = _idx(app, "Skarn")
    _make_legendary(app, skarn, budget=1)
    app._choose_legendary_action("Immolating Gaze")
    assert app._legendary_spell_pick == "", "a 2-cost option with 1 left must not arm"
    assert _budget(app, skarn) == 1
    print("✅ test_an_unaffordable_option_is_refused passed")


def test_teleport_moves_the_legendary_creature():
    app = _app()
    skarn = _idx(app, "Skarn")
    _make_legendary(app, skarn)
    app._choose_legendary_action("Teleport")
    assert app._legendary_spell_pick == "cell"
    o = app.bm.placed_agents[skarn].origin
    dest = next(rpg.Cell(o.col + dc, o.row + dr)
                for dc in range(-6, 7) for dr in range(-6, 7)
                if max(abs(dc), abs(dr)) >= 3
                and app.combat.is_valid_teleport_destination(app.bm, o.col + dc, o.row + dr))
    app._resolve_legendary_spell(-1, dest)
    n = app.bm.placed_agents[skarn].origin
    assert (n.col, n.row) == (dest.col, dest.row), "Zariel lands where the DM clicked"
    assert _budget(app, skarn) == 2, "Teleport costs 1"
    print("✅ test_teleport_moves_the_legendary_creature passed")


def test_out_of_range_keeps_the_pick():
    app = _app()
    skarn, aria = _idx(app, "Skarn"), _idx(app, "Aria")
    _make_legendary(app, skarn)
    spells = app.combat.get_agent_spells(app.bm, skarn)
    spells[0].range = 0                       # nobody is in range now
    app.combat.set_agent_spells(app.bm, skarn, spells)
    app._choose_legendary_action("Immolating Gaze")
    app._resolve_legendary_spell(aria, None)
    assert app._legendary_spell_pick == "creature", "an out-of-range click keeps the pick armed"
    assert _budget(app, skarn) == 3
    print("✅ test_out_of_range_keeps_the_pick passed")


def test_menu_labels_show_the_cost():
    app = _app()
    skarn = _idx(app, "Skarn")
    _make_legendary(app, skarn)
    features.show_legendary_action_menu(app, skarn, app.combat.get_agent_stats(app.bm, skarn))
    labels = [o.label for o in app.prompts.live.options]
    assert labels[:2] == ["Immolating Gaze (costs 2)", "Teleport"], labels
    print("✅ test_menu_labels_show_the_cost passed")


def test_loader_reads_costs_and_spells():
    st = dict_to_stats({"legendary": {"actions": 3, "action_names": ["Teleport"],
                                      "action_costs": {"Immolating Gaze": 2},
                                      "action_spells": {"Teleport": "ZarielTeleport"}}})
    assert dict(st.legendary_action_costs) == {"Immolating Gaze": 2}
    assert dict(st.legendary_action_spells) == {"Teleport": "ZarielTeleport"}
    z = json.load(open(os.path.join(_ROOT, "gui", "DND2024_MonsterStats.json")))["Zariel"]
    lg = z["meta"]["legendary"]
    assert lg["action_costs"] == {"Immolating Gaze": 2}
    assert set(lg["action_spells"].values()) <= set(z["spell_indices"])
    print("✅ test_loader_reads_costs_and_spells passed")


if __name__ == "__main__":
    test_gaze_costs_two_and_burns_the_target()
    test_an_unaffordable_option_is_refused()
    test_teleport_moves_the_legendary_creature()
    test_out_of_range_keeps_the_pick()
    test_menu_labels_show_the_cost()
    test_loader_reads_costs_and_spells()
    print("\nAll legendary-spell tests passed ✅")
