#!/usr/bin/env python3
"""
Test suite for NPC N/day attacks + Recharge (NPC_USES_RECHARGE_PLAN.md, Step 4).

Two mechanics, on both Weapons and Spells:

  • N/day  — `uses_max > 0` caps total uses; each commit decrements
    `uses_remaining`; at 0 the action is blocked. Refilled by a long rest.
  • Recharge — `recharge_min > 0`: once committed the action is `expended`
    and unusable until, at the owner's turn start (`begin_turn`), a d6 ≥
    `recharge_min` clears `expended`. `recharge_min == 0` ⇒ never recharges
    on its own; `uses_max == 0` ⇒ unlimited.

The recharge roll is a d6, so determinism comes for free without seeding the
RNG: `recharge_min = 1` ALWAYS recharges (any d6 ≥ 1), `recharge_min = 99`
NEVER recharges (no d6 ≥ 99). The N/day cap and the expend-on-commit are
deterministic already.

Engine ownership (all in C++):
  • gate    — determineAdvantage (weapons) / availableSpells (spells) block an
              expended/depleted action; a blocked weapon attack returns an
              AttackResult with valid == False.
  • spend   — applyAttackResult (weapons) / executeSpell NPC branch (spells)
              decrement uses + set expended, hit OR miss.
  • recharge— beginTurn rolls the d6 and clears expended / refills uses.

Long-rest reset is a GUI operation (main._on_long_rest); this file exercises
the same field-level reset the GUI performs and the save/reload round-trip
through helpers.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
import helpers
from test_helpers import (
    setup_battle_map,
    setup_combat_engine,
    create_test_agent,
    add_agent_to_battle,
)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def _two_agents():
    """Attacker at (10,10), a sturdy target adjacent at (11,10)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Attacker", 10, 10, str=18), hp=40)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", 11, 10, con=8), hp=200, ac=1)
    return bm, engine, atk, tgt


def _recharge_weapon(name="Breath Weapon", uses_max=1, recharge_min=5):
    """A breath-weapon-as-attack: recharge gated, optionally N/day capped."""
    w = rpg.Weapon()
    w.name = name
    w.damage_dice_count = 1
    w.damage_dice = 6
    w.reach_ft = 5
    w.proficient = True
    w.uses_max = uses_max
    w.uses_remaining = uses_max
    w.recharge_min = recharge_min
    w.expended = False
    return w


def _set_weapon(engine, bm, idx, w):
    """set_agent_weapons needs a fixed-size [main, off, ranged] triple; pad with blanks."""
    engine.set_agent_weapons(bm, idx, [w, rpg.Weapon(), rpg.Weapon()])


def _attack(atk, tgt, weapon_idx=0):
    a = rpg.Attack()
    a.attacker_idx = atk
    a.target_idx = tgt
    a.weapon_idx = weapon_idx
    return a


def _recharge_spell(name="BreathFireConeTest", uses_max=1, recharge_min=5):
    """A save-based breath modelled as a recharge spell (a Burning-Hands reskin)."""
    s = rpg.Spell()
    s.name = name
    s.level = 0
    s.type = rpg.SpellType.Harm
    s.attack_type = rpg.SpellAttack.Save
    s.save_ability = rpg.SaveAbility.SaveDex
    s.geometry = rpg.SpellGeometry.Cone
    s.range = 0
    s.radius = 30
    s.duration = 1
    dmg = rpg.MagicDamageRoll()
    dmg.type = rpg.MagicDamage.Fire
    dmg.num_dice = 6
    dmg.die_size = 6
    s.magic_damage_rolls = [dmg]
    s.uses_max = uses_max
    s.uses_remaining = uses_max
    s.recharge_min = recharge_min
    s.expended = False
    return s


def _cast(engine, bm, caster, tgt, spell_idx=0):
    a = rpg.SpellAction()
    a.caster_idx = caster
    a.spell_idx = spell_idx
    a.target_indices = [tgt]
    return engine.execute_spell(bm, a)


# ─────────────────────────────────────────────────────────────────────────────
# N/day weapon
# ─────────────────────────────────────────────────────────────────────────────
def test_nday_weapon_depletes_and_blocks():
    """A 3/day weapon (no recharge) allows exactly 3 attacks; the 4th is blocked."""
    bm, engine, atk, tgt = _two_agents()
    w = _recharge_weapon("Triple Spit", uses_max=3, recharge_min=0)
    _set_weapon(engine, bm, atk, w)

    for i in range(3):
        r = engine.execute_action(bm, _attack(atk, tgt))
        assert r.valid, f"use {i + 1}/3 should be allowed, got invalid"
        rem = engine.get_agent_weapons(bm, atk)[0].uses_remaining
        assert rem == 3 - (i + 1), f"after use {i + 1}, uses_remaining should be {3 - (i + 1)}, got {rem}"

    blocked = engine.execute_action(bm, _attack(atk, tgt))
    assert not blocked.valid, "4th attack must be blocked once N/day uses hit 0"
    # No recharge on a pure N/day weapon: begin_turn does NOT refill it.
    engine.begin_turn(bm, atk)
    assert engine.get_agent_weapons(bm, atk)[0].uses_remaining == 0, \
        "recharge_min==0 means begin_turn never refills an N/day weapon"
    print("✅ test_nday_weapon_depletes_and_blocks passed")


# ─────────────────────────────────────────────────────────────────────────────
# Recharge weapon
# ─────────────────────────────────────────────────────────────────────────────
def test_recharge_weapon_expends_on_use():
    """One commit spends the use AND marks the recharge weapon expended (hit or miss)."""
    bm, engine, atk, tgt = _two_agents()
    _set_weapon(engine, bm, atk, _recharge_weapon(uses_max=1, recharge_min=5))

    r = engine.execute_action(bm, _attack(atk, tgt))
    assert r.valid, "first breath should be allowed"
    w = engine.get_agent_weapons(bm, atk)[0]
    assert w.expended, "recharge weapon must be expended after one use"
    assert w.uses_remaining == 0, "uses_remaining should be 0 after the single use"

    blocked = engine.execute_action(bm, _attack(atk, tgt))
    assert not blocked.valid, "an expended recharge weapon must be blocked"
    print("✅ test_recharge_weapon_expends_on_use passed")


def test_recharge_weapon_stays_expended_on_low_roll():
    """recharge_min=99 can never be met by a d6 → begin_turn leaves it expended."""
    bm, engine, atk, tgt = _two_agents()
    _set_weapon(engine, bm, atk, _recharge_weapon(uses_max=1, recharge_min=99))
    engine.execute_action(bm, _attack(atk, tgt))
    assert engine.get_agent_weapons(bm, atk)[0].expended, "should be expended after use"

    for _ in range(20):                       # no d6 ever reaches 99
        engine.begin_turn(bm, atk)
    assert engine.get_agent_weapons(bm, atk)[0].expended, \
        "recharge_min above max d6 must keep the weapon expended forever"
    print("✅ test_recharge_weapon_stays_expended_on_low_roll passed")


def test_recharge_weapon_restores_on_high_roll():
    """recharge_min=1 is met by any d6 → begin_turn restores it on the first roll."""
    bm, engine, atk, tgt = _two_agents()
    _set_weapon(engine, bm, atk, _recharge_weapon(uses_max=1, recharge_min=1))
    engine.execute_action(bm, _attack(atk, tgt))
    assert engine.get_agent_weapons(bm, atk)[0].expended, "should be expended after use"

    engine.begin_turn(bm, atk)
    w = engine.get_agent_weapons(bm, atk)[0]
    assert not w.expended, "any d6 ≥ 1 must clear expended"
    assert w.uses_remaining == w.uses_max == 1, "recharge must refill N/day uses to the cap"

    r = engine.execute_action(bm, _attack(atk, tgt))
    assert r.valid, "a recharged weapon is usable again"
    print("✅ test_recharge_weapon_restores_on_high_roll passed")


# ─────────────────────────────────────────────────────────────────────────────
# Recharge spell (save-based breath)
# ─────────────────────────────────────────────────────────────────────────────
def _setup_caster_spell(recharge_min):
    bm = setup_battle_map()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Dragon", 10, 10), hp=100)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 11, 10, dex=8), hp=200)
    cs = engine.get_agent_stats(bm, caster)
    cs.can_cast_spell = True
    cs.is_npc = True                          # the expend branch lives under the NPC path
    engine.set_agent_stats(bm, caster, cs)
    engine.set_agent_spells(bm, caster, [_recharge_spell(uses_max=1, recharge_min=recharge_min)])
    return bm, engine, caster, tgt


def test_recharge_spell_expends_on_cast():
    bm, engine, caster, tgt = _setup_caster_spell(recharge_min=5)
    res = _cast(engine, bm, caster, tgt)
    assert res.valid, "first breath cast should succeed"
    sp = engine.get_agent_spells(bm, caster)[0]
    assert sp.expended, "recharge spell must be expended after one cast"
    assert sp.uses_remaining == 0, "N/day uses should be spent alongside expended"
    print("✅ test_recharge_spell_expends_on_cast passed")


def test_recharge_spell_stays_expended_on_low_roll():
    bm, engine, caster, tgt = _setup_caster_spell(recharge_min=99)
    _cast(engine, bm, caster, tgt)
    assert engine.get_agent_spells(bm, caster)[0].expended
    for _ in range(20):
        engine.begin_turn(bm, caster)
    assert engine.get_agent_spells(bm, caster)[0].expended, \
        "recharge_min above max d6 must keep the spell expended"
    print("✅ test_recharge_spell_stays_expended_on_low_roll passed")


def test_recharge_spell_restores_on_high_roll():
    bm, engine, caster, tgt = _setup_caster_spell(recharge_min=1)
    _cast(engine, bm, caster, tgt)
    assert engine.get_agent_spells(bm, caster)[0].expended
    engine.begin_turn(bm, caster)
    sp = engine.get_agent_spells(bm, caster)[0]
    assert not sp.expended, "any d6 ≥ 1 must clear the spell's expended flag"
    assert sp.uses_remaining == sp.uses_max == 1, "recharge must refill the spell's N/day uses"
    print("✅ test_recharge_spell_restores_on_high_roll passed")


# ─────────────────────────────────────────────────────────────────────────────
# Long-rest reset (mirrors main._on_long_rest's field reset)
# ─────────────────────────────────────────────────────────────────────────────
def test_long_rest_resets_weapon_and_spell():
    bm, engine, atk, tgt = _two_agents()
    _set_weapon(engine, bm, atk, _recharge_weapon("Spent", uses_max=3, recharge_min=5))
    cs = engine.get_agent_stats(bm, atk)
    cs.can_cast_spell = True
    cs.is_npc = True
    engine.set_agent_stats(bm, atk, cs)
    engine.set_agent_spells(bm, atk, [_recharge_spell(uses_max=1, recharge_min=5)])

    engine.execute_action(bm, _attack(atk, tgt))      # spend weapon: -1 use + expended
    _cast(engine, bm, atk, tgt)                        # spend spell:  -1 use + expended

    # The reset main._on_long_rest performs: refill uses_remaining, clear expended.
    ws = engine.get_agent_weapons(bm, atk)
    for w in ws:
        w.uses_remaining = w.uses_max
        w.expended = False
    engine.set_agent_weapons(bm, atk, ws)
    sps = engine.get_agent_spells(bm, atk)
    for s in sps:
        s.uses_remaining = s.uses_max
        s.expended = False
    engine.set_agent_spells(bm, atk, sps)

    w = engine.get_agent_weapons(bm, atk)[0]
    s = engine.get_agent_spells(bm, atk)[0]
    assert w.uses_remaining == 3 and not w.expended, "long rest refills + un-expends the weapon"
    assert s.uses_remaining == 1 and not s.expended, "long rest refills + un-expends the spell"
    assert engine.execute_action(bm, _attack(atk, tgt)).valid, "weapon usable after the rest"
    print("✅ test_long_rest_resets_weapon_and_spell passed")


# ─────────────────────────────────────────────────────────────────────────────
# Serializer round-trip (save → reload preserves usage/recharge state)
# ─────────────────────────────────────────────────────────────────────────────
def test_weapon_recharge_roundtrip():
    """helpers._weapon_to_dict ↔ _dict_to_weapon preserves the four usage fields."""
    w = _recharge_weapon("Mid-fight Breath", uses_max=3, recharge_min=5)
    w.uses_remaining = 1
    w.expended = True
    d = helpers._weapon_to_dict(w)
    assert d["uses_max"] == 3 and d["uses_remaining"] == 1
    assert d["recharge_min"] == 5 and d["expended"] is True

    w2 = helpers._dict_to_weapon(d)
    assert w2.uses_max == 3, "uses_max lost on reload"
    assert w2.uses_remaining == 1, "uses_remaining (mid-fight) lost on reload"
    assert w2.recharge_min == 5, "recharge_min lost on reload"
    assert w2.expended is True, "expended state lost on reload"
    print("✅ test_weapon_recharge_roundtrip passed")


def test_spell_recharge_roundtrip():
    """helpers._spell_to_dict ↔ _dict_to_spell preserves the four usage fields."""
    s = _recharge_spell("BreathColdConeRoundtrip", uses_max=1, recharge_min=6)
    s.uses_remaining = 0
    s.expended = True
    d = helpers._spell_to_dict(s)
    assert d["uses_max"] == 1 and d["uses_remaining"] == 0
    assert d["recharge_min"] == 6 and d["expended"] is True

    s2 = helpers._dict_to_spell(d)
    assert s2.uses_max == 1, "spell uses_max lost on reload"
    assert s2.uses_remaining == 0, "spell uses_remaining lost on reload"
    assert s2.recharge_min == 6, "spell recharge_min lost on reload"
    assert s2.expended is True, "spell expended state lost on reload"
    print("✅ test_spell_recharge_roundtrip passed")


# ─────────────────────────────────────────────────────────────────────────────
def main():
    tests = [
        test_nday_weapon_depletes_and_blocks,
        test_recharge_weapon_expends_on_use,
        test_recharge_weapon_stays_expended_on_low_roll,
        test_recharge_weapon_restores_on_high_roll,
        test_recharge_spell_expends_on_cast,
        test_recharge_spell_stays_expended_on_low_roll,
        test_recharge_spell_restores_on_high_roll,
        test_long_rest_resets_weapon_and_spell,
        test_weapon_recharge_roundtrip,
        test_spell_recharge_roundtrip,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            print(f"❌ {t.__name__} FAILED: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} recharge tests passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
