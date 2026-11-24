#!/usr/bin/env python3
"""
Test suite for the Banishment spell and the shared CombatEngine.banish helper
(ARCANE_ARCHER_PLAN.md AA0, decision D3).

Banished = a tracked "Banished" condition: Untouchable + Incapacitated (Speed 0, concentration
broken). When it ends the creature reappears in the space it left, or the nearest unoccupied
space. Spell version: CHA save, lasts while concentration holds (≤ 1 minute); an Aberration /
Celestial / Elemental / Fey / Fiend banished for the full minute doesn't return (removed from
play, as Divine Word does).

  · failed save → banished; a success → nothing          (test_failed_save_banishes, test_save_resists)
  · the banished creature's own concentration breaks      (test_breaks_target_concentration)
  · dropped concentration → returns, flags cleared         (test_concentration_drop_returns)
  · full minute, humanoid → returns                        (test_full_minute_humanoid_returns)
  · full minute, Fiend → sent home; early end → returns    (test_full_minute_fiend_*, test_fiend_early_*)
  · occupied space → nearest unoccupied                    (test_returns_to_nearest_unoccupied)
  · DM-set Untouchable survives the round trip             (test_prev_untouchable_restored)
  · upcast: one more target per slot above 4th             (test_upcast_two_targets)
  · the helper with an "until end of its next turn" timer  (test_helper_banishing_shot_timing)
  · survives an engine snapshot / restore                  (test_survives_snapshot)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine
from test_spells_tier2 import (_place, _strong_caster, _weak_caster, _set_ability, _cast,
                               _load_spell, _find_condition_id)


def _setup(foe_kw=None):
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=2)
    _strong_caster(engine, bm, caster)
    _set_ability(engine, bm, foe, cha=1, hp_max=100, hp_cur=100, **(foe_kw or {}))
    return bm, engine, caster, foe


def _banish_spell(engine, bm, caster, targets, slot_level=None):
    return _cast(engine, bm, caster, _load_spell("Banishment"), targets, slot_level=slot_level)


def _cond(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx)


def _banished(engine, bm, idx):
    return _find_condition_id(engine, bm, idx, "Banished") >= 0


def _assert_back(engine, bm, idx):
    c = _cond(engine, bm, idx)
    assert not _banished(engine, bm, idx), "the Banished condition is gone"
    assert not c.untouchable, "no longer Untouchable"
    assert not c.incapacitated, "no longer Incapacitated"
    assert not bm.placed_agents[idx].removed_from_play, "back in play"


def test_failed_save_banishes():
    bm, engine, caster, foe = _setup()
    _banish_spell(engine, bm, caster, [foe])
    c = _cond(engine, bm, foe)
    assert _banished(engine, bm, foe), "failed CHA save → Banished"
    assert c.untouchable and c.incapacitated, "Banished = Untouchable + Incapacitated"
    assert engine.get_walk_remaining(foe) == 0, "Speed 0"
    assert _cond(engine, bm, caster).concentrating, "the caster concentrates on it"
    cid = _find_condition_id(engine, bm, foe, "Banished")
    cond = next(x for x in engine.active_agent_conditions if x.condition_id == cid)
    assert cond.turns_remaining == 10, "lasts up to 1 minute"
    assert cond.banish_sends_home, "the spell version carries the planar clause"
    print("✅ test_failed_save_banishes passed")


def test_save_resists():
    bm, engine = setup_battle_map(), setup_combat_engine()
    caster = _place(engine, bm, "Caster", 5, 5)
    foe = _place(engine, bm, "Foe", 6, 5, faction=2)
    _weak_caster(engine, bm, caster)
    _set_ability(engine, bm, foe, cha=30)
    _banish_spell(engine, bm, caster, [foe])
    assert not _banished(engine, bm, foe), "a successful save resists"
    assert not _cond(engine, bm, foe).untouchable
    print("✅ test_save_resists passed")


def test_breaks_target_concentration():
    bm, engine, caster, foe = _setup()
    c = _cond(engine, bm, foe)
    c.concentrating = True
    c.concentrating_on = "Hold Person"
    engine.set_agent_conditions(bm, foe, c)
    _banish_spell(engine, bm, caster, [foe])
    assert not _cond(engine, bm, foe).concentrating, "Incapacitated breaks its concentration"
    print("✅ test_breaks_target_concentration passed")


def test_concentration_drop_returns():
    bm, engine, caster, foe = _setup()
    home = bm.placed_agents[foe].origin
    _banish_spell(engine, bm, caster, [foe])
    engine.drop_concentration(bm, caster)
    _assert_back(engine, bm, foe)
    o = bm.placed_agents[foe].origin
    assert (o.col, o.row) == (home.col, home.row), "reappears in the space it left"
    print("✅ test_concentration_drop_returns passed")


def _run_full_minute(engine, bm, caster):
    for _ in range(10):
        engine.tick_agent_conditions_for_caster(bm, caster)


def test_full_minute_humanoid_returns():
    bm, engine, caster, foe = _setup()
    _banish_spell(engine, bm, caster, [foe])
    for _ in range(9):
        engine.tick_agent_conditions_for_caster(bm, caster)
    assert _banished(engine, bm, foe), "still away after 9 of the caster's turns"
    engine.tick_agent_conditions_for_caster(bm, caster)
    _assert_back(engine, bm, foe)
    print("✅ test_full_minute_humanoid_returns passed")


def test_full_minute_fiend_sent_home():
    bm, engine, caster, foe = _setup({"is_fiend": True})
    _banish_spell(engine, bm, caster, [foe])
    _run_full_minute(engine, bm, caster)
    assert not _banished(engine, bm, foe)
    assert bm.placed_agents[foe].removed_from_play, "a Fiend banished for a minute doesn't return"
    print("✅ test_full_minute_fiend_sent_home passed")


def test_full_minute_fey_sent_home():
    bm, engine, caster, foe = _setup({"is_fey": True})
    _banish_spell(engine, bm, caster, [foe])
    _run_full_minute(engine, bm, caster)
    assert bm.placed_agents[foe].removed_from_play, "a Fey banished for a minute doesn't return"
    print("✅ test_full_minute_fey_sent_home passed")


def test_fiend_early_end_returns():
    bm, engine, caster, foe = _setup({"is_fiend": True})
    _banish_spell(engine, bm, caster, [foe])
    for _ in range(5):
        engine.tick_agent_conditions_for_caster(bm, caster)
    engine.drop_concentration(bm, caster)
    _assert_back(engine, bm, foe)
    print("✅ test_fiend_early_end_returns passed")


def test_returns_to_nearest_unoccupied():
    bm, engine, caster, foe = _setup()
    home = bm.placed_agents[foe].origin
    squatter = _place(engine, bm, "Squatter", 9, 9, faction=1)
    _banish_spell(engine, bm, caster, [foe])
    assert bm.set_agent_position(squatter, rpg.Cell(home.col, home.row))
    engine.drop_concentration(bm, caster)
    _assert_back(engine, bm, foe)
    o = bm.placed_agents[foe].origin
    assert (o.col, o.row) != (home.col, home.row), "its space is taken — it appears elsewhere"
    assert max(abs(o.col - home.col), abs(o.row - home.row)) == 1, "the nearest unoccupied space"
    for i, pa in enumerate(bm.placed_agents):
        if i != foe:
            assert (pa.origin.col, pa.origin.row) != (o.col, o.row), "never on top of anyone"
    print("✅ test_returns_to_nearest_unoccupied passed")


def test_prev_untouchable_restored():
    bm, engine, caster, foe = _setup()
    c = _cond(engine, bm, foe)
    c.untouchable = True
    engine.set_agent_conditions(bm, foe, c)
    cid = engine.banish(bm, foe, caster, 3)
    assert cid >= 0
    engine.remove_agent_condition(bm, cid)
    assert _cond(engine, bm, foe).untouchable, "the DM's Untouchable setting is kept"
    assert not _cond(engine, bm, foe).incapacitated
    print("✅ test_prev_untouchable_restored passed")


def test_upcast_two_targets():
    bm, engine, caster, foe = _setup()
    foe2 = _place(engine, bm, "Foe2", 5, 6, faction=2)
    _set_ability(engine, bm, foe2, cha=1, hp_max=100, hp_cur=100)
    _banish_spell(engine, bm, caster, [foe, foe2], slot_level=5)
    assert _banished(engine, bm, foe) and _banished(engine, bm, foe2), "5th-level slot: two targets"
    print("✅ test_upcast_two_targets passed")


def test_helper_banishing_shot_timing():
    """Banishing Shot passes the target as source with turns=2 — gone until the END of its next turn."""
    bm, engine, archer, foe = _setup({"is_fiend": True})
    cid = engine.banish(bm, foe, foe, 2)
    assert cid >= 0 and _banished(engine, bm, foe)
    engine.tick_agent_conditions_for_caster(bm, foe)      # start of its next turn
    assert _banished(engine, bm, foe), "still banished during its next turn"
    engine.tick_agent_conditions_for_caster(bm, foe)      # start of the turn after
    _assert_back(engine, bm, foe)   # no planar clause on the helper by default, even for a Fiend
    print("✅ test_helper_banishing_shot_timing passed")


def test_survives_snapshot():
    bm, engine, caster, foe = _setup({"is_fiend": True})
    _banish_spell(engine, bm, caster, [foe])
    snap = engine.snapshot_json()
    engine2 = setup_combat_engine()
    assert engine2.restore_json(snap)
    cid = _find_condition_id(engine2, bm, foe, "Banished")
    cond = next(x for x in engine2.active_agent_conditions if x.condition_id == cid)
    assert cond.banish_sends_home, "the planar clause survives a restore"
    print("✅ test_survives_snapshot passed")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__} failed: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
