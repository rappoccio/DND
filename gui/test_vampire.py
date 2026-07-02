#!/usr/bin/env python3
"""
Tests for vampire-support engine features:
  • available_hit_points: a max-HP reduction that mirrors temp HP (effective_max_hp,
    cleared on a long rest, healing capped to it).
  • the "reduceHPMax" on-hit weapon rider (a Vampire's Bite life-drain): on a hit it
    lowers the target's HP maximum by the Necrotic damage dealt and heals the attacker
    by the same amount.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
# Reuse the NPC segmented-multiattack driver utilities (automate a turn + a per-swing render hook)
# so the vampire recipe is exercised through the exact same auto-turn path a placed Vampire uses.
from test_npc_multiattack import _automate, _driver, _fixed_weapon, _set_recipe, _hp


def _bite_weapon():
    """A Vampire's Bite: 1d4 Piercing + 3d6 Necrotic, with the reduceHPMax drain rider."""
    w = rpg.Weapon()
    w.name = "Bite"
    w.reach_ft = 5
    w.proficient = True

    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Piercing
    pr.num_dice = 1
    pr.die_size = 4
    pr.bonus = 0
    w.physical_damage_types = [pr]

    mr = rpg.MagicDamageRoll()
    mr.type = rpg.MagicDamage.Necrotic
    mr.num_dice = 3
    mr.die_size = 6
    mr.bonus = 0
    w.magic_damage_types = [mr]

    c = rpg.AttackCondition()
    c.condition_name = "reduceHPMax"
    w.conditions = [c]
    return w


def _melee_grapple_weapon(escape_dc=14):
    """A Vampire's "Melee (Bludgeoning)": 2d10 Bludgeoning that auto-Grapples the target on a hit
    (the non-contested Grappled rider, matching the bestiary). bonus_hit is huge so the swing always
    lands, making the auto-grapple deterministic for the multiattack combo test."""
    w = rpg.Weapon()
    w.name = "Melee (Bludgeoning)"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.proficient = True
    w.bonus_hit = 50

    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice = 2
    pr.die_size = 10
    pr.bonus = 0
    w.physical_damage_types = [pr]

    c = rpg.AttackCondition()
    c.condition_name = "Grappled"
    c.escape_dc = escape_dc            # non-contested (contested defaults False) → auto-grapple on hit
    w.conditions = [c]
    return w


def test_available_hit_points_basics():
    """effective_max_hp = hp_max - available_hit_points (floored at 0)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Drained", 5, 5), hp=40)

    s = engine.get_agent_stats(bm, idx)
    assert s.available_hit_points == 0, "fresh agent has no max-HP reduction"
    assert s.effective_max_hp == 40

    s.available_hit_points = 15
    engine.set_agent_stats(bm, idx, s)
    s = engine.get_agent_stats(bm, idx)
    assert s.effective_max_hp == 25, f"expected 25, got {s.effective_max_hp}"

    s.available_hit_points = 999  # over-drain floors at 0
    engine.set_agent_stats(bm, idx, s)
    assert engine.get_agent_stats(bm, idx).effective_max_hp == 0
    print("✅ available_hit_points / effective_max_hp math")


def test_long_rest_clears_drain():
    """A long rest clears available_hit_points and restores full HP."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Bitten", 5, 5), hp=50)

    s = engine.get_agent_stats(bm, idx)
    s.available_hit_points = 20
    s.hp_cur = 12
    engine.set_agent_stats(bm, idx, s)

    engine.apply_long_rest(bm)

    s = engine.get_agent_stats(bm, idx)
    assert s.available_hit_points == 0, "long rest clears the max-HP reduction"
    assert s.hp_cur == s.hp_max == 50, f"long rest restores full HP, got {s.hp_cur}/{s.hp_max}"
    print("✅ long rest clears available_hit_points and restores HP")


def test_bite_drains_max_and_heals_attacker():
    """A reduceHPMax hit drains the target's HP maximum by the Necrotic damage and
    heals the attacker by the same amount."""
    bm = setup_battle_map()
    engine = setup_combat_engine()

    # High-STR attacker, started at low HP so the life-drain heal is observable.
    atk = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 5, 5), str=20, hp=100)
    # Target with a soft AC so the bite reliably lands; generous HP so it survives.
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 6, 5), con=10, hp=60, ac=1)

    engine.set_agent_weapons(bm, atk, [_bite_weapon(), rpg.Weapon(), rpg.Weapon()])

    action = rpg.Attack()
    action.attacker_idx = atk
    action.target_idx = tgt
    action.weapon_idx = 0

    result = None
    for _ in range(25):
        # Reset both combatants and retry until a (non-fumble) hit lands. hp_max is set here (not
        # just at add time) because adding the 2nd agent rebuilds all agents from their configs,
        # which would otherwise reset the attacker's max back to the default — capping the heal.
        sa = engine.get_agent_stats(bm, atk); sa.hp_cur = 5; sa.hp_max = 200
        engine.set_agent_stats(bm, atk, sa)
        st = engine.get_agent_stats(bm, tgt)
        st.hp_cur = 60; st.hp_max = 60; st.available_hit_points = 0
        engine.set_agent_stats(bm, tgt, st)
        result = engine.execute_action(bm, action)
        if result.hit:
            break
    assert result is not None and result.hit, "bite never landed in 25 tries"

    tgt_s = engine.get_agent_stats(bm, tgt)
    atk_s = engine.get_agent_stats(bm, atk)

    drain = tgt_s.available_hit_points
    assert 3 <= drain <= 18, f"Necrotic drain should be 3d6 (3..18), got {drain}"
    assert tgt_s.effective_max_hp == tgt_s.hp_max - drain, "effective max reflects the drain"
    # Life-drain heal: attacker regained exactly the drained amount (5 -> 5 + drain).
    assert atk_s.hp_cur == 5 + drain, f"attacker should heal by {drain}, got {atk_s.hp_cur - 5}"
    print(f"✅ Bite drained {drain} max HP and healed the attacker by {drain}")


def test_no_necrotic_no_drain():
    """A reduceHPMax rider on a weapon dealing no Necrotic drains nothing."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Biter", 5, 5), str=20, hp=50)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Prey", 6, 5), hp=40, ac=1)

    w = rpg.Weapon()
    w.name = "Dry Bite"
    w.reach_ft = 5
    w.proficient = True
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Piercing
    pr.num_dice = 1
    pr.die_size = 4
    pr.bonus = 0
    w.physical_damage_types = [pr]
    c = rpg.AttackCondition()
    c.condition_name = "reduceHPMax"
    w.conditions = [c]
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])

    action = rpg.Attack()
    action.attacker_idx = atk
    action.target_idx = tgt
    action.weapon_idx = 0
    for _ in range(15):
        engine.execute_action(bm, action)
    assert engine.get_agent_stats(bm, tgt).available_hit_points == 0, \
        "no Necrotic damage → no max-HP reduction"
    print("✅ reduceHPMax with no Necrotic damage drains nothing")


def test_bite_auto_hits_grappled_target():
    """A Bite weapon with auto_hit_if_grappled lands automatically against a creature the
    attacker has Grappled — even with a hopeless attack bonus vs a sky-high AC."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    # Weak attacker (low STR → low to-hit) vs an unhittable AC: only the auto-hit can land.
    atk = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 5, 5), str=1, hp=50)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 6, 5), hp=60, ac=40)

    w = _bite_weapon()
    w.auto_hit_if_grappled = True
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])

    action = rpg.Attack()
    action.attacker_idx = atk
    action.target_idx = tgt
    action.weapon_idx = 0

    # Not grappled yet: against AC 40 the bite cannot hit (barring a nat 20). Verify the common case.
    misses = 0
    for _ in range(20):
        st = engine.get_agent_stats(bm, tgt); st.hp_cur = 60; st.hp_max = 60
        engine.set_agent_stats(bm, tgt, st)
        r = engine.execute_action(bm, action)
        if not r.hit:
            misses += 1
    assert misses >= 18, f"un-grappled bite vs AC 40 should mostly miss, only {20 - misses} missed"

    # Now grapple the target with this attacker → every bite auto-hits.
    cond = engine.get_agent_conditions(bm, tgt)
    cond.grappled = True
    cond.grappler_idx = atk
    engine.set_agent_conditions(bm, tgt, cond)

    for _ in range(20):
        st = engine.get_agent_stats(bm, tgt); st.hp_cur = 60; st.hp_max = 60
        engine.set_agent_stats(bm, tgt, st)
        r = engine.execute_action(bm, action)
        assert r.hit, "Bite vs a Grappled target must auto-hit"
    print("✅ Bite auto-hits a creature the attacker has Grappled")


def test_bite_no_auto_hit_when_grappled_by_other():
    """auto_hit only applies vs a creature THIS attacker grapples — not one held by someone else."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 5, 5), str=1, hp=50)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 6, 5), hp=60, ac=40)

    w = _bite_weapon()
    w.auto_hit_if_grappled = True
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])

    # Grappled, but by a different creature (index 99, not the attacker).
    cond = engine.get_agent_conditions(bm, tgt)
    cond.grappled = True
    cond.grappler_idx = 99
    engine.set_agent_conditions(bm, tgt, cond)

    action = rpg.Attack()
    action.attacker_idx = atk
    action.target_idx = tgt
    action.weapon_idx = 0

    misses = 0
    for _ in range(20):
        st = engine.get_agent_stats(bm, tgt); st.hp_cur = 60; st.hp_max = 60
        engine.set_agent_stats(bm, tgt, st)
        r = engine.execute_action(bm, action)
        if not r.hit:
            misses += 1
    assert misses >= 18, "no auto-hit when the target is grappled by someone other than the attacker"
    print("✅ no auto-hit when the target is grappled by a different creature")


def _grapple(engine, bm, atk, tgt):
    """Mark tgt as Grappled by atk (the gate for auto_hit_if_grappled / the Bite save)."""
    cond = engine.get_agent_conditions(bm, tgt)
    cond.grappled = True
    cond.grappler_idx = atk
    engine.set_agent_conditions(bm, tgt, cond)


def test_bite_con_save_success_negates():
    """A save-delivered Bite (save_for_damage, SaveCon) vs a Grappled target that easily makes its
    CON save deals NO damage and NO HP-max drain — the 'auto-hit' is a saving throw, not a guaranteed hit."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 5, 5), hp=50)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 6, 5), hp=60, ac=1)

    # Low-CON attacker → low save DC (8 + PB + CON mod). High-CON target → always saves.
    sa = engine.get_agent_stats(bm, atk)
    sa.con = 1; sa.prof_bonus = 2; sa.hp_cur = 50; sa.hp_max = 200
    engine.set_agent_stats(bm, atk, sa)

    w = _bite_weapon()
    w.auto_hit_if_grappled = True
    w.save_for_damage = True
    w.save_for_damage_ability = rpg.SaveAbility.SaveCon
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])
    _grapple(engine, bm, atk, tgt)

    action = rpg.Attack()
    action.attacker_idx = atk; action.target_idx = tgt; action.weapon_idx = 0
    for _ in range(20):
        st = engine.get_agent_stats(bm, tgt)
        st.con = 30; st.hp_cur = 60; st.hp_max = 60; st.available_hit_points = 0
        engine.set_agent_stats(bm, tgt, st)
        r = engine.execute_action(bm, action)
        assert not r.hit, "a Grappled target that makes its CON save takes nothing from the Bite"
        st2 = engine.get_agent_stats(bm, tgt)
        assert st2.hp_cur == 60 and st2.available_hit_points == 0, "no damage, no HP-max drain on a save"
    print("✅ Bite CON-save success negates damage + drain (no longer a guaranteed hit)")


def test_bite_con_save_failure_bites():
    """A save-delivered Bite vs a Grappled target that always fails its CON save lands with full
    damage AND the HP-max drain, and the attacker heals by the drained amount."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 5, 5), hp=200)
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Victim", 6, 5), hp=60, ac=1)

    w = _bite_weapon()
    w.auto_hit_if_grappled = True
    w.save_for_damage = True
    w.save_for_damage_ability = rpg.SaveAbility.SaveCon
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])
    _grapple(engine, bm, atk, tgt)

    action = rpg.Attack()
    action.attacker_idx = atk; action.target_idx = tgt; action.weapon_idx = 0
    for _ in range(20):
        # High-CON attacker → high save DC; tiny-CON target → always fails. Attacker at low HP so the
        # life-drain heal is observable. (Re-set each loop: nothing rebuilds agents here, but it keeps
        # the heal baseline fixed.)
        sa = engine.get_agent_stats(bm, atk)
        sa.con = 30; sa.prof_bonus = 3; sa.hp_cur = 5; sa.hp_max = 200
        engine.set_agent_stats(bm, atk, sa)
        st = engine.get_agent_stats(bm, tgt)
        st.con = 1; st.hp_cur = 60; st.hp_max = 60; st.available_hit_points = 0
        engine.set_agent_stats(bm, tgt, st)

        r = engine.execute_action(bm, action)
        assert r.hit, "a Grappled target that fails its CON save is bitten"
        st2 = engine.get_agent_stats(bm, tgt)
        drain = st2.available_hit_points
        assert 3 <= drain <= 18, f"3d6 Necrotic drain expected (3..18), got {drain}"
        assert engine.get_agent_stats(bm, atk).hp_cur == 5 + drain, \
            f"attacker should heal by the {drain} drained"
    print("✅ Bite CON-save failure lands full damage + drain + heal")


# ── Multiattack ────────────────────────────────────────────────────────────────────────────────────
def test_vampire_multiattack_recipe():
    """A Vampire's authored recipe is 2 Melee + 1 Bite: multiattack=[(0,2),(1,1)]. Run through the NPC
    auto-turn and confirm the recipe drives EXACTLY 3 swings (2 with slot 0, then 1 with slot 1),
    overriding num_attacks. Fixed crit-proof damage decodes the per-slot split (2×Melee + 1×Bite)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 6, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Hero", 7, 5), hp=1000)
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(foe, 2)
    # Distinct fixed damage so total HP loss uniquely decodes the composition: 2×Melee(5) + 1×Bite(9) = 19.
    engine.set_agent_weapons(bm, npc,
                             [_fixed_weapon("Melee (Bludgeoning)", 5), _fixed_weapon("Bite", 9), rpg.Weapon()])
    _set_recipe(engine, bm, npc, [(0, 2), (1, 1)], num_attacks=99)   # recipe overrides num_attacks
    _automate(bm, npc)

    calls = _driver(engine, bm, npc)

    assert calls == [(npc, foe)] * 3, f"Vampire recipe → 3 swings (2 Melee + 1 Bite), got {calls}"
    dmg = 1000 - _hp(engine, bm, foe)
    assert dmg == 2 * 5 + 1 * 9, f"expected 2 Melee + 1 Bite = 19 damage, got {dmg}"
    print("✅ Vampire multiattack recipe drives 2 Melee + 1 Bite (not num_attacks)")


def test_vampire_grapple_then_bite_combo():
    """The whole point of the Vampire's recipe: the two Melee swings Grapple the target, then the Bite
    auto-hits the now-Grappled creature (via its CON save) and drains its HP maximum, healing the Vampire.
    Run end-to-end through the NPC auto-turn with the REAL Melee-grapple + save-delivered Bite weapons."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    npc = add_agent_to_battle(engine, bm, create_test_agent("Vampire", 6, 5))
    foe = add_agent_to_battle(engine, bm, create_test_agent("Victim", 7, 5))
    bm.set_agent_faction(npc, 1); bm.set_agent_faction(foe, 2)

    # Vampire: high STR (Melee lands), high CON + PB (Bite save DC is unbeatable), low HP so the
    # life-drain heal is observable. hp_max is set HERE (not at add time) because both agents are added
    # before this, and the last apply_agent_configs rebuild would otherwise cap the heal at the default max.
    sa = engine.get_agent_stats(bm, npc)
    sa.str = 20; sa.con = 30; sa.prof_bonus = 5; sa.hp_cur = 5; sa.hp_max = 200
    engine.set_agent_stats(bm, npc, sa)

    # Victim: tiny CON (always fails the Bite save), roomy HP (survives all three swings), soft AC.
    st = engine.get_agent_stats(bm, foe)
    st.con = 1; st.hp_cur = 300; st.hp_max = 300; st.base_ac = 1; st.available_hit_points = 0
    engine.set_agent_stats(bm, foe, st)

    bite = _bite_weapon()
    bite.type = rpg.WeaponType.Melee     # the auto-driver positions per-segment weapon by reach
    bite.auto_hit_if_grappled = True
    bite.save_for_damage = True
    bite.save_for_damage_ability = rpg.SaveAbility.SaveCon
    engine.set_agent_weapons(bm, npc, [_melee_grapple_weapon(), bite, rpg.Weapon()])
    _set_recipe(engine, bm, npc, [(0, 2), (1, 1)], num_attacks=3)
    _automate(bm, npc)

    calls = _driver(engine, bm, npc)

    assert calls == [(npc, foe)] * 3, f"2 Melee + 1 Bite = 3 swings expected, got {calls}"
    # The Melee swings grappled the victim (grappler = this Vampire) — the gate the Bite relied on.
    cond = engine.get_agent_conditions(bm, foe)
    assert cond.grappled and cond.grappler_idx == npc, "the Melee swings should Grapple the victim"
    # The Bite auto-hit the Grappled victim: HP-max drained (3d6 Necrotic) and the Vampire healed by it.
    foe_s = engine.get_agent_stats(bm, foe)
    drain = foe_s.available_hit_points
    assert 3 <= drain <= 18, f"Bite should drain 3d6 (3..18) of the victim's HP max, got {drain}"
    assert foe_s.effective_max_hp == foe_s.hp_max - drain, "effective max reflects the Bite drain"
    assert engine.get_agent_stats(bm, npc).hp_cur == 5 + drain, \
        f"Vampire should heal by the {drain} it drained (5 → {5 + drain})"
    print(f"✅ Vampire combo: Melee grapple → Bite auto-hit drained {drain} & healed the Vampire")


if __name__ == "__main__":
    test_available_hit_points_basics()
    test_long_rest_clears_drain()
    test_bite_drains_max_and_heals_attacker()
    test_no_necrotic_no_drain()
    test_bite_auto_hits_grappled_target()
    test_bite_no_auto_hit_when_grappled_by_other()
    test_bite_con_save_success_negates()
    test_bite_con_save_failure_bites()
    test_vampire_multiattack_recipe()
    test_vampire_grapple_then_bite_combo()
    print("\n✅ All vampire-feature tests passed!")
