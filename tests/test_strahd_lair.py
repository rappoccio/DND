#!/usr/bin/env python3
"""Strahd's Castle Ravenloft lair actions (plans/STRAHD_LAIR_PLAN.md), headless App.

L1: the Strahd Specter / Strahd Shadow stat blocks (+7 to hit, 30 HP, CR 5), the Shadow's
Strength Drain rider (reduceStr1d4: Str −1d4, Str 0 → dead) and Strahd's lair_actions list.
L2–L6: the Lair entry at initiative 20, Phase, Doors (lair lock), Apparition, Shadow Theft."""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
import lair
import run_state

from test_combat_panel import App, MAP_PATH, SEED, _build_scene, _idx, _snapshot_baseline


def _app():
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    _snapshot_baseline(app)
    return app


def _as_monster(app, idx, monster):
    """Give agent idx the bestiary stat block + weapons of `monster`."""
    rec = app.mob_stats_json[monster]
    app.combat.set_agent_stats(app.bm, idx, app._mob_stats_to_d_d_stats(rec))
    app.combat.set_agent_weapons(app.bm, idx, app._auto_weapons_from_mob_stats(rec))


def test_strahd_minions_hit_at_plus_seven():
    app = _app()
    for monster, rider in (("Strahd Specter", "reduceHPMax"), ("Strahd Shadow", "reduceStr1d4")):
        rec = app.mob_stats_json[monster]
        assert rec["meta"]["cr"] == "5", monster
        st = app._mob_stats_to_d_d_stats(rec)
        assert st.hp_max == 30 and st.hp_cur == 30, monster
        w = app._auto_weapons_from_mob_stats(rec)[0]
        to_hit = rpg.CombatEngine.attack_modifier(w, st) + w.bonus_hit   # as the engine's r.attack_mod
        assert to_hit == 7, (monster, to_hit)
        assert [c.condition_name for c in w.conditions] == [rider], monster
    print("✅ test_strahd_minions_hit_at_plus_seven passed")


def test_strahd_has_lair_actions():
    app = _app()
    st = app._mob_stats_to_d_d_stats(app.mob_stats_json["Strahd von Zarovich"])
    assert list(st.lair_action_names) == ["Phase", "Doors", "Apparition", "Shadow Theft"]
    print("✅ test_strahd_has_lair_actions passed")


def _drain_attack(app, attacker, target):
    """One forced-hit Strahd Shadow swing from attacker at target, out of turn."""
    _as_monster(app, attacker, "Strahd Shadow")
    ws = list(app.combat.get_agent_weapons(app.bm, attacker))
    ws[0].bonus_hit = 60                     # always hits
    app.combat.set_agent_weapons(app.bm, attacker, ws)
    a = rpg.Attack(attacker, target, 0)
    a.attack_slot = "legendary"
    status = app.combat.begin_attack(app.bm, a)
    while status == rpg.FlowStatus.AwaitingDecision:          # decline every reaction window
        status = app.combat.submit_decision(app.bm, rpg.ReactionResponse())


def test_strength_drain_lowers_strength():
    app = _app()
    skarn, aria = _idx(app, "Skarn"), _idx(app, "Aria")
    before = app.combat.get_agent_stats(app.bm, aria).str
    _drain_attack(app, skarn, aria)
    after = app.combat.get_agent_stats(app.bm, aria).str
    assert 1 <= before - after <= 4, (before, after)
    print("✅ test_strength_drain_lowers_strength passed")


def test_strength_drain_to_zero_kills():
    app = _app()
    skarn, aria = _idx(app, "Skarn"), _idx(app, "Aria")
    s = app.combat.get_agent_stats(app.bm, aria)
    s.str = 1; s.hp_cur = s.hp_max = 500
    app.combat.set_agent_stats(app.bm, aria, s)
    _drain_attack(app, skarn, aria)
    assert app.combat.get_agent_stats(app.bm, aria).str == 0
    assert app.combat.get_agent_conditions(app.bm, aria).dead, "Strength 0 kills"
    print("✅ test_strength_drain_to_zero_kills passed")



# ── L2–L6: the Lair turn ─────────────────────────────────────────────────────

LAIR_ACTIONS = ["Phase", "Doors", "Apparition", "Shadow Theft"]


def _lair_app():
    """The panel scene with Skarn (the foe) holding Strahd's lair actions, combat started.
    Initiative (SEED): Aria 21, Cyra 19, Brannor 16, Skarn 15 → the Lair slots in after Aria."""
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    skarn = _idx(app, "Skarn")
    s = app.combat.get_agent_stats(app.bm, skarn)
    s.lair_action_names = LAIR_ACTIONS
    app.combat.set_agent_stats(app.bm, skarn, s)
    app._start_combat()
    app.combat.stop_recording()
    _snapshot_baseline(app)
    return app, skarn


def _to_lair_turn(app):
    """End Aria's turn: the next entry is the Lair."""
    app._advance_turn()
    assert lair.on_lair_turn(app), [(e.agent_idx, e.total) for e in app.initiative_order]


def _decline_reactions(app):
    while app.combat.pending_decision().active:
        app._submit_reaction_skip()


def _weak_cha(app, idx):
    s = app.combat.get_agent_stats(app.bm, idx)
    s.cha = 1; s.save_prof_cha = False; s.legendary_resistance_current = 0
    app.combat.set_agent_stats(app.bm, idx, s)


def test_lair_entry_at_twenty_losing_ties():
    app, skarn = _lair_app()
    totals = [(e.agent_idx, e.total) for e in app.initiative_order]
    pos = next(i for i, e in enumerate(app.initiative_order) if lair.is_lair_entry(e))
    assert app.initiative_order[pos].total == 20
    assert all(e.total >= 20 for e in app.initiative_order[:pos]), totals
    assert all(e.total < 20 for e in app.initiative_order[pos + 1:]), totals
    assert app.turn_idx == 0 and app._current_agent_idx() == _idx(app, "Aria")
    print("✅ test_lair_entry_at_twenty_losing_ties passed")


def test_no_lair_creature_no_entry():
    app = _app()
    assert not any(lair.is_lair_entry(e) for e in app.initiative_order)
    print("✅ test_no_lair_creature_no_entry passed")


def test_lair_turn_offers_menu_then_passes():
    app, skarn = _lair_app()
    _to_lair_turn(app)
    assert app._lair_actor == skarn
    assert app._current_agent_idx() == -1, "no creature acts on the Lair turn"
    lair.finish(app)                                  # Pass
    assert app._current_agent_idx() == _idx(app, "Cyra")
    assert app._lair_actor == -1
    print("✅ test_lair_turn_offers_menu_then_passes passed")


def test_lair_skipped_when_owner_down():
    app, skarn = _lair_app()
    s = app.combat.get_agent_stats(app.bm, skarn)
    s.hp_cur = 0
    app.combat.set_agent_stats(app.bm, skarn, s)
    app._advance_turn()
    assert not lair.on_lair_turn(app)
    assert app._current_agent_idx() == _idx(app, "Cyra")
    print("✅ test_lair_skipped_when_owner_down passed")


def _door_wall(app, col):
    """A full column of closed doors at `col` (doors hold up to 4 cells each)."""
    rows = app.bm.grid_rows
    for r0 in range(0, rows, 4):
        app.bm.add_door([rpg.Cell(col, r) for r in range(r0, min(r0 + 4, rows))])


def test_phase_passes_walls_until_next_lair_turn():
    app, skarn = _lair_app()
    _door_wall(app, 6)
    o = app.bm.placed_agents[skarn].origin
    beyond = rpg.Cell(7, o.row)
    reach = lambda: {(c.col, c.row) for c in app.bm.reachable_cells(
        o, 1, 30, rpg.MovementType.Walk, skarn)}
    assert (7, o.row) not in reach(), "the wall blocks before Phase"
    _to_lair_turn(app)
    lair.choose(app, "Phase")
    assert app.bm.is_agent_phasing(skarn)
    assert app._current_agent_idx() == _idx(app, "Cyra"), "Phase ends the lair turn"
    r = reach()
    assert (7, o.row) in r, "Phase passes the wall"
    assert (6, o.row) not in r, "but can't stop inside it"
    app.bm.placed_agents[skarn].init_movement(30, 0, 0, 0)
    assert not app.bm.move_agent(skarn, rpg.Cell(6, o.row), rpg.MovementType.Walk)
    assert app.bm.move_agent(skarn, beyond, rpg.MovementType.Walk)
    lair.begin_turn(app)                              # count 20 of the next round
    assert not app.bm.is_agent_phasing(skarn), "Phase ends at the next Lair turn"
    print("✅ test_phase_passes_walls_until_next_lair_turn passed")


def _door_near(app):
    """A single closed door in Skarn's sight."""
    return app.bm.add_door([rpg.Cell(5, 5)])


def _door(app, did):
    return next(d for d in app.bm.doors if d.id == did)


def test_doors_cycle_and_lock():
    app, skarn = _lair_app()
    did = _door_near(app)
    _to_lair_turn(app)
    lair.choose(app, "Doors")
    assert app._pick_data("lair") == "doors"
    for want in ("open", "close", "lock"):
        lair.resolve_click(app, -1, rpg.Cell(5, 5))
        assert app._lair_doors.get(did) == want, app._lair_doors
    lair.apply_doors(app)
    d = _door(app, did)
    assert d.lair_lock and not d.open
    assert app._current_agent_idx() == _idx(app, "Cyra")
    assert not app.bm.open_door(did), "a lair-locked door won't open"
    assert not app.bm.knock_door(did), "Knock doesn't lift Strahd's lock"
    pr = app.combat.attempt_pick_lock(app.bm, _idx(app, "Aria"), did)
    assert not pr.success, "nor can it be picked"
    print("✅ test_doors_cycle_and_lock passed")


def test_lair_lock_forced_open_at_dc_twenty():
    app, skarn = _lair_app()
    did = _door_near(app)
    app.bm.set_door_lair_lock(did, True)
    aria = _idx(app, "Aria")
    s = app.combat.get_agent_stats(app.bm, aria)
    s.str = 10
    app.combat.set_agent_stats(app.bm, aria, s)
    r = app.combat.attempt_break_door(app.bm, aria, did)
    assert r.dc == 20, r.dc
    s.str = 60                                         # +25: always makes DC 20
    app.combat.set_agent_stats(app.bm, aria, s)
    for _ in range(3):
        if _door(app, did).open:
            break
        app.combat.attempt_break_door(app.bm, aria, did)
    d = _door(app, did)
    assert d.open and not d.broken and not d.lair_lock, d
    assert app.bm.close_door(did), "forced open, not off its frame: it shuts again"
    print("✅ test_lair_lock_forced_open_at_dc_twenty passed")


def test_doors_again_ends_old_locks():
    app, skarn = _lair_app()
    did = _door_near(app)
    app.bm.set_door_lair_lock(did, True)
    _to_lair_turn(app)
    lair.choose(app, "Doors")
    lair.apply_doors(app)                             # no doors chosen this time
    assert not _door(app, did).lair_lock
    print("✅ test_doors_again_ends_old_locks passed")


def test_lair_lock_saves_with_play_state():
    terrain = {"doors": [{"cells": [[5, 5]], "open": False, "lair_lock": True},
                         {"cells": [[1, 1]], "open": True}]}
    map_doc, extras, state = run_state.split_terrain(terrain)
    assert "lair_lock" not in map_doc["doors"][0], "the lock is play state, not design"
    assert state["doors"][0].get("lair_lock") is True
    assert "lair_lock" not in state["doors"][1], "only a locked door carries the key"
    merged = run_state.merge_terrain(map_doc, extras, state)
    assert merged["doors"][0].get("lair_lock") is True
    assert not merged["doors"][1].get("lair_lock")
    print("✅ test_lair_lock_saves_with_play_state passed")


def _vanished(app, name):
    return [i for i, pt in enumerate(app.bm.placed_agents) if pt.name == name]


def test_apparition_attacks_and_vanishes():
    app, skarn = _lair_app()
    brannor = _idx(app, "Brannor")
    _to_lair_turn(app)
    lair.choose(app, "Apparition")
    lair.resolve_click(app, skarn, None)
    assert app._pick_data("lair") == "apparition", "Strahd's own side is refused"
    lair.resolve_click(app, brannor, None)
    _decline_reactions(app)
    sp = _vanished(app, "Strahd Specter")
    assert len(sp) == 1 and app.bm.is_agent_removed_from_play(sp[0])
    assert app.bm.get_agent_faction(sp[0]) == app.bm.get_agent_faction(skarn)
    assert app._current_agent_idx() == _idx(app, "Cyra")
    print("✅ test_apparition_attacks_and_vanishes passed")


def test_shadow_theft_fail_spawns_shadow_attack():
    app, skarn = _lair_app()
    aria = _idx(app, "Aria")                          # adjacent to Skarn
    _weak_cha(app, aria)                              # d20 − 5 never reaches 17
    _to_lair_turn(app)
    lair.choose(app, "Shadow Theft")
    lair.resolve_click(app, aria, None)
    _decline_reactions(app)
    sh = _vanished(app, "Strahd Shadow")
    assert len(sh) == 1 and app.bm.is_agent_removed_from_play(sh[0])
    assert app._current_agent_idx() == _idx(app, "Cyra")
    print("✅ test_shadow_theft_fail_spawns_shadow_attack passed")


def test_shadow_theft_refusals():
    app, skarn = _lair_app()
    aria, cyra = _idx(app, "Aria"), _idx(app, "Cyra")
    s = app.combat.get_agent_stats(app.bm, aria)
    s.is_vampire = True
    app.combat.set_agent_stats(app.bm, aria, s)
    assert "vampire" in lair.shadow_theft_refusal(app, skarn, aria)
    s.is_vampire = False
    app.combat.set_agent_stats(app.bm, aria, s)
    assert lair.shadow_theft_refusal(app, skarn, aria) == ""
    app.combat.teleport_agent(app.bm, cyra, 10, 10)
    assert app._footprint_dist_ft(skarn, cyra) > 30
    assert "range" in lair.shadow_theft_refusal(app, skarn, cyra)
    print("✅ test_shadow_theft_refusals passed")


def test_shadow_theft_legendary_resistance():
    app, skarn = _lair_app()
    aria = _idx(app, "Aria")
    _weak_cha(app, aria)
    s = app.combat.get_agent_stats(app.bm, aria)
    s.legendary_resistance_current = 1
    app.combat.set_agent_stats(app.bm, aria, s)
    assert app.combat.roll_fixed_dc_save(app.bm, aria, rpg.SaveAbility.SaveCha, 17, "test")
    assert app.combat.get_agent_stats(app.bm, aria).legendary_resistance_current == 0
    assert not app.combat.roll_fixed_dc_save(app.bm, aria, rpg.SaveAbility.SaveCha, 17, "test")
    print("✅ test_shadow_theft_legendary_resistance passed")


def test_phase_ends_with_combat():
    app, skarn = _lair_app()
    app.bm.set_agent_phasing(skarn, True)
    app._end_combat(award_xp=False)
    assert not app.bm.is_agent_phasing(skarn)
    print("✅ test_phase_ends_with_combat passed")


def test_tracker_mode_lair_reminder_row():
    """Real-dice tracker mode: a "Lair" row at 20, after the ties, that Next steps onto and
    past and that does nothing (no menu, no lair state)."""
    import tempfile
    import test_tracker_mode as TM
    with tempfile.TemporaryDirectory() as tmp:
        app = TM._setup(tmp, tracker=True)
        skarn = TM._idx(app, "Skarn")
        s = app.combat.get_agent_stats(app.bm, skarn)
        s.lair_action_names = LAIR_ACTIONS
        app.combat.set_agent_stats(app.bm, skarn, s)
        app._begin_encounter()
        assert app.tracker.index_of(-1) < 0, "no Lair row while the totals are typed in"
        totals = dict(TM.TOTALS, Gnasher=20)
        for name, tot in totals.items():
            app.tracker.set_total(TM._idx(app, name), tot)
        app._tracker_start()
        order = [(e.agent_idx, e.total) for e in app.tracker.entries]
        gn = TM._idx(app, "Gnasher")
        assert order[:2] == [(gn, 20), (-1, 20)], order
        app._draw_combat_panel()                          # the row draws
        app._tracker_step(1)
        assert app.tracker.current() == -1 and app._current_agent_idx() == -1
        assert app._lair_actor == -1 and not app.context_menu.visible, "it does nothing"
        app._tracker_step(1)
        assert app._current_agent_idx() == TM._idx(app, "Aria")
    print("✅ test_tracker_mode_lair_reminder_row passed")


if __name__ == "__main__":
    test_strahd_minions_hit_at_plus_seven()
    test_strahd_has_lair_actions()
    test_strength_drain_lowers_strength()
    test_strength_drain_to_zero_kills()
    test_lair_entry_at_twenty_losing_ties()
    test_no_lair_creature_no_entry()
    test_lair_turn_offers_menu_then_passes()
    test_lair_skipped_when_owner_down()
    test_phase_passes_walls_until_next_lair_turn()
    test_doors_cycle_and_lock()
    test_lair_lock_forced_open_at_dc_twenty()
    test_doors_again_ends_old_locks()
    test_lair_lock_saves_with_play_state()
    test_apparition_attacks_and_vanishes()
    test_shadow_theft_fail_spawns_shadow_attack()
    test_shadow_theft_refusals()
    test_shadow_theft_legendary_resistance()
    test_phase_ends_with_combat()
    test_tracker_mode_lair_reminder_row()
    print("\nAll Strahd lair tests passed.")
