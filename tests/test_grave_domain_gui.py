#!/usr/bin/env python3
"""Grave Domain Cleric — the GUI flows (headless App): the Path to the Grave pick and its
end-the-curse prompt ahead of the attack's rider chain, the Keeper of Souls prompt poll, and
Spare the Dying in the Bonus Action spell menu. Engine rules live in test_grave_domain.py."""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg

from test_combat_panel import (App, MAP_PATH, SEED, _build_scene, _idx, _goto, _reclass,
                               _set_res, _snapshot_baseline, _spell)


def _app():
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    _snapshot_baseline(app)
    return app


def _grave(app, level):
    return _reclass(app, "Brannor", rpg.CharacterClass.Cleric, level,
                    cleric_subclass=rpg.ClericSubclass.GraveDomain)


def _labels(app):
    live = app.prompts.live
    return [o.label for o in live.options] if live else []


def _swing(app, attacker, target):
    """Aria's Attack action against `target`, through the GUI's begin_attack path, until one hits."""
    s = app.combat.get_agent_stats(app.bm, target); s.base_ac = 1; s.hp_cur = s.hp_max = 200
    app.combat.set_agent_stats(app.bm, target, s)
    for _ in range(20):
        _goto(app, app.bm.placed_agents[attacker].name)
        app.pending_attack_slot = "action"
        app._attack_sequence_slot = "action"
        app.pending_weapon_idx = 0
        app.attacks_remaining = 2
        app._resolve_combat_attack(target)
        if app.combat.last_attack_result().hit:
            return app.combat.last_attack_result()
        while app.prompts.live is not None:      # a miss's own prompts (none expected)
            app.prompts.cancel_as(app.prompts.live.id, "dm")
    raise AssertionError("never hit")


def _curse(app, cleric, target):
    _goto(app, "Brannor")
    app.pending_path_to_the_grave = True
    app._resolve_path_to_the_grave(target)
    assert not app.pending_path_to_the_grave
    assert app.combat.get_agent_conditions(app.bm, target).grave_cursed_by == cleric


def test_path_pick_curses_the_target():
    app = _app()
    brannor = _grave(app, 5)
    skarn = _idx(app, "Skarn")
    assert app.combat.can_path_to_the_grave(app.bm, brannor, skarn)
    _curse(app, brannor, skarn)
    assert app.bonus_used, "the engine spent Brannor's Bonus Action"
    print("✅ test_path_pick_curses_the_target passed")


def test_ally_hit_offers_the_detonation_first():
    app = _app()
    brannor = _grave(app, 5)
    skarn, aria = _idx(app, "Skarn"), _idx(app, "Aria")
    _curse(app, brannor, skarn)
    hp = app.combat.get_agent_stats(app.bm, skarn).hp_cur
    _swing(app, aria, skarn)
    labels = _labels(app)
    assert labels and labels[0].startswith("Path to the Grave: Radiant"), labels
    assert app.prompts.live.actor_idx == brannor, "the cleric owns the prompt, not the attacker"
    lost_before = hp - app.combat.get_agent_stats(app.bm, skarn).hp_cur
    assert app.prompts.choose_label(labels[0]).ok
    lost = hp - app.combat.get_agent_stats(app.bm, skarn).hp_cur
    assert lost == lost_before + 5, f"+cleric level (5) Radiant: {lost_before} -> {lost}"
    assert app.combat.get_agent_conditions(app.bm, skarn).grave_cursed_by == -1
    # The attack's own chain resumed: the Action's second attack is still owed.
    assert app.attacks_remaining == 1, app.attacks_remaining
    assert app.prompts.live is None or not _labels(app)[0].startswith("Path to the Grave")
    print("✅ test_ally_hit_offers_the_detonation_first passed")


def test_keeping_the_curse_leaves_it():
    app = _app()
    brannor = _grave(app, 5)
    skarn, aria = _idx(app, "Skarn"), _idx(app, "Aria")
    _curse(app, brannor, skarn)
    _swing(app, aria, skarn)
    assert app.prompts.choose_label("Keep the curse").ok
    assert app.combat.get_agent_conditions(app.bm, skarn).grave_cursed_by == brannor
    assert app.attacks_remaining == 1
    print("✅ test_keeping_the_curse_leaves_it passed")


def test_keeper_of_souls_prompt_is_polled():
    app = _app()
    brannor = _grave(app, 17)
    aria = _idx(app, "Aria")
    s = app.combat.get_agent_stats(app.bm, aria); s.hp_cur = 10
    app.combat.set_agent_stats(app.bm, aria, s)
    c = app.combat.get_agent_conditions(app.bm, brannor); c.keeper_of_souls_pending = True
    app.combat.set_agent_conditions(app.bm, brannor, c)
    while app.prompts.live is not None:
        app.prompts.cancel_as(app.prompts.live.id, "dm")
    app._offer_keeper_of_souls_if_pending()
    labels = _labels(app)
    heal = next((l for l in labels if l.startswith("Heal Aria +34")), None)
    assert heal, labels
    assert app.prompts.choose_label(heal).ok
    assert app.combat.get_agent_stats(app.bm, aria).hp_cur == 44, "10 + 34, capped at 44"
    assert not app.combat.get_agent_conditions(app.bm, brannor).keeper_of_souls_pending
    app._offer_keeper_of_souls_if_pending()
    assert app.prompts.live is None, "nothing left to offer"
    print("✅ test_keeper_of_souls_prompt_is_polled passed")


def test_spare_the_dying_in_the_bonus_menu():
    app = _app()
    brannor = _grave(app, 3)
    app.combat.set_agent_spells(app.bm, brannor, [_spell(app, "Spare the Dying")])
    _goto(app, "Brannor")
    app._start_cast_spell("bonus")
    # One castable spell: the menu skips the list and arms it straight away, in the bonus slot.
    assert app.pending_spell_slot == "bonus" or any(
        l.startswith("Spare the Dying") for l in _labels(app)), (app.pending_spell_slot, _labels(app))
    app.pending_spell_slot = ""
    while app.prompts.live is not None:
        app.prompts.cancel_as(app.prompts.live.id, "dm")
    # Any other domain: Spare the Dying stays an Action.
    brannor = _reclass(app, "Brannor", rpg.CharacterClass.Cleric, 3,
                       cleric_subclass=rpg.ClericSubclass.LifeDomain)
    app.combat.set_agent_spells(app.bm, brannor, [_spell(app, "Spare the Dying")])
    _goto(app, "Brannor")
    app._start_cast_spell("bonus")
    assert app.pending_spell_slot != "bonus" and not any(
        l.startswith("Spare the Dying") for l in _labels(app)), (app.pending_spell_slot, _labels(app))
    print("✅ test_spare_the_dying_in_the_bonus_menu passed")


def test_sentinel_through_the_reaction_menu():
    app = _app()
    brannor = _grave(app, 6)
    aria, skarn = _idx(app, "Aria"), _idx(app, "Skarn")
    s = app.combat.get_agent_stats(app.bm, aria); s.hp_cur = 20; s.base_ac = 1   # Bloodied (20/44)
    app.combat.set_agent_stats(app.bm, aria, s)
    for _ in range(20):
        _goto(app, "Skarn")
        app.pending_attack_slot = "action"
        app._attack_sequence_slot = "action"
        app.pending_weapon_idx = 0
        app.attacks_remaining = 1
        app._resolve_combat_attack(aria)
        if app.combat.pending_decision().active:
            break
    pd = app.combat.pending_decision()
    assert pd.active and pd.ctx.reactor_idx == brannor, "Brannor's Sentinel window"
    label = next(l for l in _labels(app) if l.startswith("Sentinel at Death's Door"))
    assert app.prompts.choose_label(label).ok
    r = app.combat.last_attack_result()
    assert r.hit and r.total_damage == dict(r.damage_breakdown)["weapon"] // 2, list(r.damage_breakdown)
    assert app.combat.get_agent_stats(app.bm, brannor).resources["Sentinel at Death's Door"].current == 2
    print("✅ test_sentinel_through_the_reaction_menu passed")


if __name__ == "__main__":
    test_path_pick_curses_the_target()
    test_ally_hit_offers_the_detonation_first()
    test_keeping_the_curse_leaves_it()
    test_keeper_of_souls_prompt_is_polled()
    test_spare_the_dying_in_the_bonus_menu()
    test_sentinel_through_the_reaction_menu()
    print("\n✅ All Grave Domain GUI tests passed!")
