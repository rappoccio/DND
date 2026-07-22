#!/usr/bin/env python3
"""
General feat tests — phase G5 (2024 PHB): damage/resistance/saves + movement passives.

  · Heavy Armor Master  — B/P/S damage from attacks reduced by PB while in Heavy armor (dex_mod_cap 0).
  · Medium Armor Master — DEX-to-AC cap is +3 (not +2) while in Medium armor (dex_mod_cap 2).
  · Durable             — Advantage on Death Saving Throws (Defy Death).
  · Speedy              — +10 ft walking Speed; Opportunity Attacks against you have Disadvantage.
  · Athlete             — stand up from Prone for only 5 ft of movement.
  · Skulker             — Blindsight 10 ft (pierces the Invisible condition like Blind Fighting).
  · Telekinetic         — Telekinetic Shove: Bonus Action, 30 ft, STR save or pushed 5 ft.
  · Weapon Master       — GUI-only gate (satisfies the Weapon Mastery / Nick gate); not tested here.
  · Resilient           — marker only (the save proficiency is set via the StatsDialog checkboxes).

Also covers a binding fix: Armor.dex_mod_cap now round-trips into the C++ Armor (was always 30),
without which calculateAC could not cap DEX and the armor-master feats could not detect the category.

Deferred to G5b (known_limitations.md): Elemental Adept (chosen-element picker, shared with Chromatic
Orb / Sorcerous Burst), Poisoner Potent Poison.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine
from test_feats import _place, _target, _arm


# ─────────────────────────────────────────────────────────────────────────────
#  Builders
# ─────────────────────────────────────────────────────────────────────────────

def _flat_slashing(total=20, bonus_hit=50):
    """A weapon dealing a deterministic `total` Slashing damage (num_dice d1 each = 1)."""
    w = rpg.Weapon()
    w.name = "TestBlade"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.proficient = True
    w.bonus_hit = bonus_hit
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = total          # each d1 always rolls 1 → `total` damage, deterministic
    pr.die_size = 1
    w.physical_damage_types = [pr]
    return w


def _armor(name, dex_cap, ac_bonus=6):
    a = rpg.Armor()
    a.name = name
    a.ac_bonus = ac_bonus
    a.dex_mod_cap = dex_cap
    return a


def _equip(engine, bm, idx, armor):
    """Put one armor piece in the chest slot (other 5 slots empty)."""
    arr = [rpg.Armor() for _ in range(6)]
    arr[1] = armor
    engine.set_agent_armor(bm, idx, arr)


# ─────────────────────────────────────────────────────────────────────────────
#  Armor.dex_mod_cap binding round-trips (foundation for the armor-master feats)
# ─────────────────────────────────────────────────────────────────────────────

def test_armor_dex_mod_cap_binding():
    a = rpg.Armor()
    assert a.dex_mod_cap == 30, "default DEX cap is 30 (light/unarmored)"
    a.dex_mod_cap = 2
    assert a.dex_mod_cap == 2, "dex_mod_cap is settable from Python"
    print("✅ test_armor_dex_mod_cap_binding passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Heavy Armor Master
# ─────────────────────────────────────────────────────────────────────────────

def _ham_damage(engine, bm, a, t, with_feat):
    ts = engine.get_agent_stats(bm, t)
    ts.prof_bonus = 3
    ts.feats = ["Heavy Armor Master"] if with_feat else []
    engine.set_agent_stats(bm, t, ts)
    r = engine.execute_action(bm, rpg.Attack(a, t, 0))
    assert r.hit
    return r.total_damage


def test_heavy_armor_master_reduces_bps():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Attacker", 5, 5)
    t = _place(engine, bm, "Tank", 6, 5)
    _arm(engine, bm, a, [_flat_slashing(total=20)], strv=10, prof=2)   # STR +0 → flat 20 damage
    _target(engine, bm, t, hp=10_000, ac=10)
    _equip(engine, bm, t, _armor("Plate", dex_cap=0))                  # Heavy armor

    base = _ham_damage(engine, bm, a, t, with_feat=False)
    reduced = _ham_damage(engine, bm, a, t, with_feat=True)
    assert base == 20, f"control damage should be the deterministic 20, got {base}"
    assert reduced == base - 3, f"Heavy Armor Master should cut B/P/S by PB (3): {base} → {reduced}"
    print("✅ test_heavy_armor_master_reduces_bps passed")


def test_heavy_armor_master_needs_heavy_armor():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Attacker", 5, 5)
    t = _place(engine, bm, "Tank", 6, 5)
    _arm(engine, bm, a, [_flat_slashing(total=20)], strv=10, prof=2)
    _target(engine, bm, t, hp=10_000, ac=10)
    _equip(engine, bm, t, _armor("Breastplate", dex_cap=2))           # Medium, NOT Heavy

    assert _ham_damage(engine, bm, a, t, with_feat=True) == 20, \
        "Heavy Armor Master does nothing without Heavy armor (dex_mod_cap 0)"
    print("✅ test_heavy_armor_master_needs_heavy_armor passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Medium Armor Master
# ─────────────────────────────────────────────────────────────────────────────

def test_medium_armor_master_raises_dex_cap():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Skirmisher", 5, 5)
    s = engine.get_agent_stats(bm, a); s.dex = 18; s.base_ac = 0   # DEX +4, exceeds both caps
    engine.set_agent_stats(bm, a, s)
    _equip(engine, bm, a, _armor("Breastplate", dex_cap=2, ac_bonus=4))

    without = engine.calculate_ac(bm, a)                            # DEX capped at +2
    s = engine.get_agent_stats(bm, a); s.feats = ["Medium Armor Master"]
    engine.set_agent_stats(bm, a, s)
    with_feat = engine.calculate_ac(bm, a)                          # DEX capped at +3
    assert with_feat == without + 1, f"Medium Armor Master should add +1 AC (cap 2→3): {without} → {with_feat}"
    print("✅ test_medium_armor_master_raises_dex_cap passed")


def test_medium_armor_master_no_effect_in_heavy():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Knight", 5, 5)
    s = engine.get_agent_stats(bm, a); s.dex = 18; s.base_ac = 0    # DEX +4, but Heavy gives no DEX
    engine.set_agent_stats(bm, a, s)
    _equip(engine, bm, a, _armor("Plate", dex_cap=0, ac_bonus=8))   # Heavy: cap 0

    without = engine.calculate_ac(bm, a)
    s = engine.get_agent_stats(bm, a); s.feats = ["Medium Armor Master"]
    engine.set_agent_stats(bm, a, s)
    assert engine.calculate_ac(bm, a) == without, "Medium Armor Master must not touch Heavy armor (cap 0)"
    print("✅ test_medium_armor_master_no_effect_in_heavy passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Durable — Advantage on Death Saving Throws
# ─────────────────────────────────────────────────────────────────────────────

def _death_save_success_rate(engine, bm, idx, with_feat, n=500):
    s = engine.get_agent_stats(bm, idx)
    s.con = 10                                  # +0, so DC 10 needs a raw d20 ≥ 10
    s.hp_cur = 0; s.hp_max = 50
    s.feats = ["Durable"] if with_feat else []
    engine.set_agent_stats(bm, idx, s)
    successes = 0
    for _ in range(n):
        c = engine.get_agent_conditions(bm, idx)
        c.unconscious = True; c.dead = False; c.stabilized = False
        c.death_save_successes = 0; c.death_save_failures = 0
        engine.set_agent_conditions(bm, idx, c)
        engine.begin_turn(bm, idx)              # rolls one death save (Durable = Advantage here)
        after = engine.get_agent_conditions(bm, idx)
        if after.death_save_successes > 0 or after.stabilized:
            successes += 1
    return successes / n


def test_durable_advantage_on_death_saves():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Dying", 5, 5)
    without = _death_save_success_rate(engine, bm, a, with_feat=False)
    with_feat = _death_save_success_rate(engine, bm, a, with_feat=True)
    # P(success) ≈ 0.55 flat vs ≈ 0.80 with Advantage — the gap dwarfs sampling noise.
    assert with_feat > without + 0.1, \
        f"Durable should raise death-save success rate: without={without:.2f}, with={with_feat:.2f}"
    print(f"✅ test_durable_advantage_on_death_saves passed (without={without:.2f}, with={with_feat:.2f})")


# ─────────────────────────────────────────────────────────────────────────────
#  Speedy — +10 ft Speed; OA Disadvantage
# ─────────────────────────────────────────────────────────────────────────────

def test_speedy_adds_ten_feet():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Runner", 5, 5)
    s = engine.get_agent_stats(bm, a); s.speed_walk = 30; engine.set_agent_stats(bm, a, s)
    engine.begin_turn(bm, a)
    base = engine.get_walk_remaining(a)
    s = engine.get_agent_stats(bm, a); s.feats = ["Speedy"]; engine.set_agent_stats(bm, a, s)
    engine.begin_turn(bm, a)
    assert engine.get_walk_remaining(a) == base + 10, "Speedy adds +10 ft to the walking budget"
    print("✅ test_speedy_adds_ten_feet passed")


def test_speedy_opportunity_attack_disadvantage():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Reactor", 5, 5)
    t = _place(engine, bm, "Mover", 6, 5)
    _arm(engine, bm, a, [_flat_slashing(total=1)], strv=10, prof=2)
    _target(engine, bm, t, hp=10_000, ac=10)

    oa = rpg.Attack(a, t, 0); oa.opportunity = True
    assert not engine.execute_action(bm, oa).disadvantage, "no feat → an OA is not at Disadvantage"

    ts = engine.get_agent_stats(bm, t); ts.feats = ["Speedy"]; engine.set_agent_stats(bm, t, ts)
    oa2 = rpg.Attack(a, t, 0); oa2.opportunity = True
    assert engine.execute_action(bm, oa2).disadvantage, "a Speedy target imposes Disadvantage on OAs"

    # A normal (non-OA) attack against the Speedy creature is unaffected.
    assert not engine.execute_action(bm, rpg.Attack(a, t, 0)).disadvantage, \
        "Speedy only affects Opportunity Attacks, not normal attacks"
    print("✅ test_speedy_opportunity_attack_disadvantage passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Athlete — stand from Prone for 5 ft
# ─────────────────────────────────────────────────────────────────────────────

def _standup_cost(engine, bm, idx, with_feat):
    s = engine.get_agent_stats(bm, idx); s.speed_walk = 30
    s.feats = ["Athlete"] if with_feat else []
    engine.set_agent_stats(bm, idx, s)
    c = engine.get_agent_conditions(bm, idx); c.prone = True
    engine.set_agent_conditions(bm, idx, c)
    engine.begin_turn(bm, idx)                       # seeds 30 ft of walk
    before = engine.get_walk_remaining(idx)
    engine.standup(bm, idx)
    return before - engine.get_walk_remaining(idx)


def test_athlete_stand_from_prone_costs_five():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Tumbler", 5, 5)
    assert _standup_cost(engine, bm, a, with_feat=False) == 15, "normal stand-up costs half speed (15 ft)"
    assert _standup_cost(engine, bm, a, with_feat=True) == 5, "Athlete stands up for only 5 ft"
    print("✅ test_athlete_stand_from_prone_costs_five passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Skulker — Blindsight 10 ft
# ─────────────────────────────────────────────────────────────────────────────

def _make_invisible(engine, bm, idx):
    c = engine.get_agent_conditions(bm, idx); c.invisible = True
    engine.set_agent_conditions(bm, idx, c)


def test_skulker_blindsight_pierces_invisible_within_10ft():
    bm = setup_battle_map(); engine = setup_combat_engine()
    viewer = _place(engine, bm, "Scout", 5, 5)
    hidden = _place(engine, bm, "Sneak", 7, 5)        # 2 cells = 10 ft
    _make_invisible(engine, bm, hidden)

    assert not engine.can_perceive_target(bm, viewer, hidden), \
        "without the feat, an Invisible creature can't be perceived"
    s = engine.get_agent_stats(bm, viewer); s.feats = ["Skulker"]; engine.set_agent_stats(bm, viewer, s)
    assert engine.can_perceive_target(bm, viewer, hidden), \
        "Skulker's Blindsight 10 ft pierces Invisible at 10 ft"
    print("✅ test_skulker_blindsight_pierces_invisible_within_10ft passed")


def test_skulker_blindsight_limited_to_10ft():
    bm = setup_battle_map(); engine = setup_combat_engine()
    viewer = _place(engine, bm, "Scout", 5, 5)
    hidden = _place(engine, bm, "Sneak", 8, 5)        # 3 cells = 15 ft, beyond 10 ft
    _make_invisible(engine, bm, hidden)
    s = engine.get_agent_stats(bm, viewer); s.feats = ["Skulker"]; engine.set_agent_stats(bm, viewer, s)
    assert not engine.can_perceive_target(bm, viewer, hidden), \
        "Skulker's Blindsight does not reach beyond 10 ft"
    print("✅ test_skulker_blindsight_limited_to_10ft passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Telekinetic — Telekinetic Shove (STR save, push 5 ft, 30 ft range)
# ─────────────────────────────────────────────────────────────────────────────

def test_telekinetic_shove_pushes_on_failed_save():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = _place(engine, bm, "Psion", 5, 5)
    tgt = _place(engine, bm, "Goblin", 6, 5)
    cs = engine.get_agent_stats(bm, caster); cs.intel = 20; cs.prof_bonus = 6   # DC = 8+6+5 = 19
    engine.set_agent_stats(bm, caster, cs)
    ts = engine.get_agent_stats(bm, tgt); ts.str = 1; ts.save_prof_str = False  # save ≤ 15 < 19 → always fails
    engine.set_agent_stats(bm, tgt, ts)

    before = engine.get_agent_position(tgt) if hasattr(engine, "get_agent_position") else bm.placed_agents[tgt].origin
    res = engine.apply_telekinetic_shove(bm, caster, tgt)
    after = bm.placed_agents[tgt].origin
    assert res.valid and res.success, f"a failed STR save should land the shove: {res.log_message}"
    assert res.push_ft_applied == 5, f"Telekinetic Shove moves 5 ft, got {res.push_ft_applied}"
    assert (after.col, after.row) != (before.col, before.row), "the target should have moved"
    print("✅ test_telekinetic_shove_pushes_on_failed_save passed")


def test_telekinetic_shove_resisted_on_success():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = _place(engine, bm, "Psion", 5, 5)
    tgt = _place(engine, bm, "Ogre", 6, 5)
    cs = engine.get_agent_stats(bm, caster); cs.intel = 10; cs.wis = 10; cs.cha = 10; cs.prof_bonus = 2  # DC 10
    engine.set_agent_stats(bm, caster, cs)
    ts = engine.get_agent_stats(bm, tgt); ts.str = 30; ts.save_prof_str = True   # save ≥ 13 ≥ 10 → always saves
    engine.set_agent_stats(bm, tgt, ts)

    before = bm.placed_agents[tgt].origin
    res = engine.apply_telekinetic_shove(bm, caster, tgt)
    after = bm.placed_agents[tgt].origin
    assert res.valid and not res.success, "a made STR save resists the shove"
    assert res.push_ft_applied == 0 and (after.col, after.row) == (before.col, before.row), \
        "a resisted shove moves the target 0 ft"
    print("✅ test_telekinetic_shove_resisted_on_success passed")


def test_telekinetic_shove_out_of_range():
    bm = setup_battle_map(); engine = setup_combat_engine()
    caster = _place(engine, bm, "Psion", 5, 5)
    tgt = _place(engine, bm, "FarOff", 12, 5)         # 7 cells = 35 ft > 30 ft
    res = engine.apply_telekinetic_shove(bm, caster, tgt)
    assert not res.valid, "a target beyond 30 ft is out of range"
    print("✅ test_telekinetic_shove_out_of_range passed")


def main():
    print("Running General feat tests (G5 — armor/saves/movement passives + Telekinetic Shove)...\n")
    test_armor_dex_mod_cap_binding()
    test_heavy_armor_master_reduces_bps()
    test_heavy_armor_master_needs_heavy_armor()
    test_medium_armor_master_raises_dex_cap()
    test_medium_armor_master_no_effect_in_heavy()
    test_durable_advantage_on_death_saves()
    test_speedy_adds_ten_feet()
    test_speedy_opportunity_attack_disadvantage()
    test_athlete_stand_from_prone_costs_five()
    test_skulker_blindsight_pierces_invisible_within_10ft()
    test_skulker_blindsight_limited_to_10ft()
    test_telekinetic_shove_pushes_on_failed_save()
    test_telekinetic_shove_resisted_on_success()
    test_telekinetic_shove_out_of_range()
    print("\n" + "=" * 60)
    print("✅ All General feat (G5) tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
