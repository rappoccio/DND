#!/usr/bin/env python3
"""
Unit tests for THROWN WEAPONS — hurling a javelin/handaxe/dagger instead of swinging it.

A thrown WEAPON is not a thrown Item (a flask of Acid, see test_items.py). The flask is
consumed; the weapon is not. It leaves the thrower's hand, flies out to long_range_ft as a
ranged attack, and lands on the ground as a MapItem at the target's feet, where anyone can
pick it up again (the same drop/pickup loop the GUI already uses).

The throw is explicit: Attack.thrown. The GUI sets it when the DM targets past the weapon's
melee reach; NPC automation never does, so no monster throws its weapon away.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from helpers import _weapon_to_dict, _dict_to_weapon
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


def _javelin(quantity: int = 1):
    """A Javelin as weapons.json authors it: Melee, Thrown, 30/120 ft, 1d6 piercing."""
    w = rpg.Weapon()
    w.name = "Javelin"
    w.type = rpg.WeaponType.Melee
    w.thrown = True
    w.proficient = True
    w.quantity = quantity
    w.reach_ft = 5
    w.normal_range_ft = 30
    w.long_range_ft = 120
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Piercing
    roll.num_dice = 1
    roll.die_size = 6
    w.physical_damage_types = [roll]
    return w


def _short_throw():
    """A thrown weapon with tiny bands (10 ft normal / 20 ft long) — the test grid is only 12x12
    cells, so a real javelin's 120 ft long range does not fit on it and cannot be overshot."""
    w = _javelin()
    w.name = "Pebble"
    w.normal_range_ft = 10
    w.long_range_ft = 20
    return w


def _three(weapons):
    """set_agent_weapons wants a full slot list; pad with blanks."""
    out = list(weapons)
    while len(out) < 3:
        out.append(rpg.Weapon())
    return out


def _two_agents(gap_cells: int, weapon):
    """A thrower at (2,2) and a target `gap_cells` cells east (keep gap <= 9: the grid is 12x12)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    add_agent_to_battle(engine, bm, create_test_agent("Thrower", 2, 2), hp=30, ac=10)
    add_agent_to_battle(engine, bm, create_test_agent("Target", 2 + gap_cells, 2), hp=30, ac=1)
    engine.set_agent_weapons(bm, 0, _three([weapon]))
    return bm, engine


def _attack(engine, bm, thrown: bool, atk=0, tgt=1, widx=0):
    """Resolve one attack atomically (execute_action: validate → roll → apply, no reaction window)."""
    action = rpg.Attack(atk, tgt, widx)
    action.attack_slot = "action"
    action.thrown = thrown
    return engine.execute_action(bm, action)


def _throw(engine, bm, atk=0, tgt=1, widx=0):
    return _attack(engine, bm, True, atk, tgt, widx)


def _swing(engine, bm, atk=0, tgt=1, widx=0):
    return _attack(engine, bm, False, atk, tgt, widx)


# ── Range ────────────────────────────────────────────────────────────────────────────

def test_melee_weapon_cannot_reach_without_a_throw():
    """A javelin SWUNG is still a 5 ft weapon: the far target is simply out of reach."""
    bm, engine = _two_agents(6, _javelin())          # 30 ft away
    r = _swing(engine, bm)
    assert not r.valid, "a swung javelin should not reach 30 ft"
    print("✅ a javelin swung (not thrown) still only reaches 5 ft")


def test_throw_reaches_far_beyond_melee_reach():
    """Thrown, the same javelin flies right past its 5 ft reach — out to long_range_ft."""
    bm, engine = _two_agents(8, _javelin())          # 40 ft: 8x its reach, well inside long range
    r = _throw(engine, bm)
    assert r.valid, "a thrown javelin should reach 40 ft"
    assert r.weapon_thrown
    print("✅ a thrown javelin flies far beyond its melee reach")


def test_throw_beyond_long_range_is_illegal():
    bm, engine = _two_agents(6, _short_throw())      # 30 ft > the 20 ft long range
    r = _throw(engine, bm)
    assert not r.valid, "30 ft is past this weapon's 20 ft long range"
    assert len(bm.get_all_items()) == 0, "an illegal throw drops nothing"
    print("✅ a throw past long range is refused")


def test_throw_at_long_range_has_disadvantage():
    """Any attack made AT RANGE past normal_range_ft is at Disadvantage — a throw included."""
    bm, engine = _two_agents(8, _javelin())          # 40 ft: past the 30 ft normal range
    r = _throw(engine, bm)
    assert r.valid
    assert r.disadvantage, "a throw past normal range should be at Disadvantage"

    bm2, engine2 = _two_agents(4, _javelin())        # 20 ft: inside normal range
    r2 = _throw(engine2, bm2)
    assert r2.valid
    assert not r2.disadvantage, "a throw inside normal range takes no long-range penalty"
    print("✅ long-range Disadvantage applies to a throw, short range does not")


def test_cannot_throw_a_weapon_without_the_thrown_property():
    w = _javelin()
    w.name = "Longsword"
    w.thrown = False
    bm, engine = _two_agents(4, w)
    r = _throw(engine, bm)
    assert not r.valid, "a longsword has no Thrown property"
    print("✅ a weapon without the Thrown property cannot be thrown")


# ── The weapon leaves your hand (and is NOT destroyed) ───────────────────────────────

def test_thrown_weapon_lands_on_the_ground():
    """The javelin is out of your hand and lying at the target's feet — hit or miss."""
    bm, engine = _two_agents(4, _javelin())
    tgt_cell = bm.placed_agents[1].origin
    assert len(bm.get_all_items()) == 0

    r = _throw(engine, bm)
    assert r.valid and r.weapon_thrown
    assert r.thrown_item_id >= 0, "the thrown javelin should have become a MapItem"

    items = bm.get_all_items()
    assert len(items) == 1, f"expected 1 dropped weapon, got {len(items)}"
    assert items[0].weapon.name == "Javelin"
    assert items[0].cell.col == tgt_cell.col and items[0].cell.row == tgt_cell.row, \
        "the javelin should land at the target's feet"
    assert items[0].weapon.quantity == 1, "one javelin landed, not the whole bundle"
    print("✅ a thrown weapon lands on the ground as a MapItem (not destroyed)")


def test_last_copy_thrown_empties_the_slot():
    bm, engine = _two_agents(4, _javelin(quantity=1))
    _throw(engine, bm)
    held = engine.get_agent_weapons(bm, 0)
    assert held[0].name in ("", "Unarmed"), \
        f"the slot should be empty after throwing the last javelin, got '{held[0].name}'"
    print("✅ throwing your last javelin empties the weapon slot")


def test_bundle_spends_one_copy_per_throw():
    bm, engine = _two_agents(4, _javelin(quantity=3))
    _throw(engine, bm)
    assert engine.get_agent_weapons(bm, 0)[0].quantity == 2
    _throw(engine, bm)
    assert engine.get_agent_weapons(bm, 0)[0].quantity == 1
    assert engine.get_agent_weapons(bm, 0)[0].name == "Javelin", "still holding javelins"
    assert len(bm.get_all_items()) == 2, "each throw leaves its own javelin on the ground"
    _throw(engine, bm)
    assert engine.get_agent_weapons(bm, 0)[0].name in ("", "Unarmed"), "bundle exhausted"
    assert len(bm.get_all_items()) == 3
    print("✅ each throw spends one copy of the bundle")


def test_throwing_an_empty_bundle_is_refused():
    bm, engine = _two_agents(4, _javelin(quantity=1))
    _throw(engine, bm)                     # the last one
    r = _throw(engine, bm)                 # nothing left to throw
    assert not r.valid, "you cannot throw a javelin you no longer have"
    assert len(bm.get_all_items()) == 1, "no phantom javelin was created"
    print("✅ throwing with an empty bundle is refused")


def test_a_swing_never_spends_a_copy():
    """Stabbing with a javelin you could have thrown does not use one up."""
    bm, engine = _two_agents(1, _javelin(quantity=2))   # adjacent
    r = _swing(engine, bm)
    assert r.valid
    assert not r.weapon_thrown
    assert engine.get_agent_weapons(bm, 0)[0].quantity == 2, "a melee swing spends nothing"
    assert len(bm.get_all_items()) == 0, "a melee swing drops nothing"
    print("✅ a melee swing with a thrown weapon spends no copies")


def test_thrown_weapon_can_be_picked_up_again():
    """The whole point: it is not destroyed. Retrieve it and you are armed again."""
    bm, engine = _two_agents(4, _javelin())
    r = _throw(engine, bm)
    assert engine.get_agent_weapons(bm, 0)[0].name in ("", "Unarmed")

    assert bm.pick_up_item(r.thrown_item_id, 1)      # the target picks it out of the dirt
    assert len(bm.get_all_items()) == 0, "the javelin is off the ground now"
    assert any(w.name == "Javelin" for w in engine.get_agent_weapons(bm, 1)), \
        "the target should now be holding the javelin"
    print("✅ a thrown weapon can be picked up again")


def test_returning_weapon_is_never_spent_or_dropped():
    """A Soulknife's Psychic Blade vanishes and re-forms — it never hits the floor."""
    blade = _javelin()
    blade.name = "PsychicBlade"
    blade.returns_after_throw = True
    bm, engine = _two_agents(4, blade)

    r = _throw(engine, bm)
    assert r.valid and r.weapon_thrown, "it was still thrown"
    assert r.thrown_item_id == -1, "a returning blade does not become a MapItem"
    assert len(bm.get_all_items()) == 0, "nothing on the ground"
    held = engine.get_agent_weapons(bm, 0)
    assert held[0].name == "PsychicBlade" and held[0].quantity == 1, "still in hand, undiminished"
    print("✅ a returning weapon is never spent or dropped")


# ── Serialization ────────────────────────────────────────────────────────────────────

def test_quantity_round_trips():
    """Save mid-fight with 2 javelins left and you must NOT reload holding a full bundle."""
    w = _javelin(quantity=2)
    w.sprite_path = "sprites/javelin.png"
    w.returns_after_throw = False
    back = _dict_to_weapon(_weapon_to_dict(w))
    assert back.quantity == 2, f"quantity did not round-trip: {back.quantity}"
    assert back.thrown
    assert back.sprite_path == "sprites/javelin.png"
    assert not back.returns_after_throw
    print("✅ quantity / sprite_path / returns_after_throw round-trip")


def test_weapon_with_no_authored_quantity_defaults_to_one():
    """weapons.json authors no quantity — a weapon in hand is one weapon, never zero."""
    back = _dict_to_weapon({"name": "Handaxe", "type": "melee", "thrown": True})
    assert back.quantity == 1, "a weapon with no authored quantity must default to 1, not 0"
    print("✅ an unauthored quantity defaults to 1")


def run_tests():
    tests = [
        test_melee_weapon_cannot_reach_without_a_throw,
        test_throw_reaches_far_beyond_melee_reach,
        test_throw_beyond_long_range_is_illegal,
        test_throw_at_long_range_has_disadvantage,
        test_cannot_throw_a_weapon_without_the_thrown_property,
        test_thrown_weapon_lands_on_the_ground,
        test_last_copy_thrown_empties_the_slot,
        test_bundle_spends_one_copy_per_throw,
        test_throwing_an_empty_bundle_is_refused,
        test_a_swing_never_spends_a_copy,
        test_thrown_weapon_can_be_picked_up_again,
        test_returning_weapon_is_never_spent_or_dropped,
        test_quantity_round_trips,
        test_weapon_with_no_authored_quantity_defaults_to_one,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"❌ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
