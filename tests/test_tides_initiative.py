#!/usr/bin/env python3
"""Tides of Chaos spent for Advantage on Initiative (2024: Initiative is a D20 Test).

The engine half: `arm_tides_for_initiative` checks and spends the use like
`activate_tides_of_chaos`, but holds the Advantage for that one agent, and the next
`roll_initiative` / `roll_initiative_for` uses it and clears it. The GUI half: Begin Combat
asks each eligible PC before rolling, and combat starts from the last answer.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg

from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from test_sorcerer import _sorcerer

WILD = rpg.SorcererSubclass.WildMagic


def _tides(eng, bm, idx):
    return eng.get_agent_stats(bm, idx).resources["Tides of Chaos"].current


def _solo(level=3, subclass=WILD):
    bm = setup_battle_map(); eng = setup_combat_engine()
    idx = add_agent_to_battle(eng, bm, create_test_agent("WildSorc", 5, 5))
    _sorcerer(eng, bm, idx, level, subclass=subclass)
    return bm, eng, idx


# ── Engine ───────────────────────────────────────────────────────────────────

def test_armed_initiative_rolls_with_advantage_once():
    # Twin seeded engines: arming consumes no RNG, so the d20 draws stay aligned.
    bm_c, ctrl, _ = _solo()
    a, b, c = ctrl.roll(20), ctrl.roll(20), ctrl.roll(20)

    bm, eng, idx = _solo()
    assert eng.arm_tides_for_initiative(bm, idx) is True
    assert _tides(eng, bm, idx) == 0, "arming spends the use"
    first = eng.roll_initiative(bm)[0]
    assert first.d20 == max(a, b), f"armed roll {first.d20}, expected max({a}, {b})"
    assert first.total == first.d20 + first.modifier

    # The flag is spent with the roll: the next Initiative is one d20 again.
    again = eng.roll_initiative(bm)[0]
    assert again.d20 == c, f"second roll {again.d20}, expected the single d20 {c}"
    print("✅ test_armed_initiative_rolls_with_advantage_once")


def test_unarmed_initiative_rolls_once():
    bm_c, ctrl, _ = _solo()
    a = ctrl.roll(20)
    bm, eng, idx = _solo()
    assert eng.roll_initiative(bm)[0].d20 == a
    assert _tides(eng, bm, idx) == 1, "an unarmed roll leaves the use alone"
    print("✅ test_unarmed_initiative_rolls_once")


def test_armed_reinforcement_roll_uses_it_too():
    bm_c, ctrl, _ = _solo()
    a, b = ctrl.roll(20), ctrl.roll(20)
    bm, eng, idx = _solo()
    assert eng.arm_tides_for_initiative(bm, idx)
    assert eng.roll_initiative_for(bm, idx).d20 == max(a, b)
    print("✅ test_armed_reinforcement_roll_uses_it_too")


def test_arming_is_refused_when_ineligible():
    bm, eng, idx = _solo(subclass=rpg.SorcererSubclass.Draconic)
    assert eng.arm_tides_for_initiative(bm, idx) is False, "wrong subclass"

    bm, eng, idx = _solo(level=2)
    assert eng.arm_tides_for_initiative(bm, idx) is False, "level 2"

    bm, eng, idx = _solo()
    assert eng.activate_tides_of_chaos(bm, idx)          # the one use, spent elsewhere
    assert eng.arm_tides_for_initiative(bm, idx) is False, "no use left"

    bm, eng, idx = _solo()
    assert eng.arm_tides_for_initiative(bm, idx)
    assert eng.arm_tides_for_initiative(bm, idx) is True, "arming twice is one spend"
    assert _tides(eng, bm, idx) == 0
    print("✅ test_arming_is_refused_when_ineligible")


# ── GUI ──────────────────────────────────────────────────────────────────────

def _app(cyra_npc=False, cyra_wild=True):
    from main import App
    from test_combat_panel import _build_scene, _idx
    from constants import PC_FACTION
    app = App(os.path.join(_ROOT, "maps", "TestGrid12x12.png"), seed=20261026)
    _build_scene(app)
    cyra = _idx(app, "Cyra")
    if cyra_wild:
        _sorcerer(app.combat, app.bm, cyra, 3, subclass=WILD)
    if cyra_npc:
        app.bm.set_agent_faction(cyra, 1)
    assert (app.bm.placed_agents[cyra].faction == PC_FACTION) != cyra_npc
    return app, cyra


def _with_logs(fn):
    from test_combat_panel import _preserve_cwd_logs, _restore_cwd_logs
    saved = _preserve_cwd_logs()
    try:
        fn()
    finally:
        _restore_cwd_logs(saved)


def test_begin_combat_asks_and_yes_arms():
    def run():
        app, cyra = _app()
        app._start_combat()
        p = app.prompts.live
        assert not app.combat_active, "combat began before the sorcerer answered"
        assert p is not None and "Tides of Chaos" in p.title and p.actor_idx == cyra, \
            f"no Tides prompt for Cyra: {p and p.title}"
        assert p.kind == "reaction" and p.on_cancel is not None, \
            "the ask must be a reaction with a cancel, so a seated player's times out as No"

        app._start_combat()                       # a second Start while asking: ignored
        assert app.prompts.live is p and not app.combat_active

        assert app.prompts.choose_label("Yes").ok
        assert app.combat_active, "combat did not begin after the last answer"
        assert _tides(app.combat, app.bm, cyra) == 0
        app._flush_combat_log()
        assert any("uses Tides of Chaos on Initiative" in m for m in app.combat_log), \
            "the roll did not log Tides of Chaos"
        assert f"TIDES_INITIATIVE: [{cyra}]" in open(app.replay_log_file).read()
        app.combat.stop_recording()
    _with_logs(run)
    print("✅ test_begin_combat_asks_and_yes_arms")


def test_no_and_cancel_leave_the_use():
    def run():
        for answer in ("No", None):
            app, cyra = _app()
            app._start_combat()
            if answer:
                assert app.prompts.choose_label(answer).ok
            else:
                app.prompts.cancel()
            assert app.combat_active
            assert _tides(app.combat, app.bm, cyra) == 1, f"{answer or 'Cancel'} spent the use"
            assert "TIDES_INITIATIVE: []" in open(app.replay_log_file).read()
            app.combat.stop_recording()
    _with_logs(run)
    print("✅ test_no_and_cancel_leave_the_use")


def test_a_superseded_ask_is_reasked_by_start():
    def run():
        app, cyra = _app()
        app._start_combat()
        first = app.prompts.live
        app._ask_dm("dm", "Something else", [("OK", lambda: None)])
        assert not first.is_live
        app._start_combat()
        again = app.prompts.live
        assert again is not first and "Tides of Chaos" in again.title
        assert app.prompts.choose_label("No").ok and app.combat_active
        app.combat.stop_recording()
    _with_logs(run)
    print("✅ test_a_superseded_ask_is_reasked_by_start")


def test_no_one_eligible_starts_at_once():
    def run():
        for kw in ({"cyra_wild": False}, {"cyra_npc": True}):
            app, _ = _app(**kw)
            app._start_combat()
            assert app.combat_active, f"{kw}: combat should begin with no prompt"
            live = app.prompts.live
            assert live is None or "Tides of Chaos" not in live.title
            app.combat.stop_recording()
    _with_logs(run)
    print("✅ test_no_one_eligible_starts_at_once")


if __name__ == "__main__":
    test_armed_initiative_rolls_with_advantage_once()
    test_unarmed_initiative_rolls_once()
    test_armed_reinforcement_roll_uses_it_too()
    test_arming_is_refused_when_ineligible()
    test_begin_combat_asks_and_yes_arms()
    test_no_and_cancel_leave_the_use()
    test_a_superseded_ask_is_reasked_by_start()
    test_no_one_eligible_starts_at_once()
    sys.exit(0)
