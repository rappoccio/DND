#!/usr/bin/env python3
"""
General feat tests — phase G0 + G1 (2024 PHB).

G0: Weapon.heavy / Weapon.light flags; multi-select general-feat plumbing (App._set_general_feats).
G1: damage-type on-hit riders + Great Weapon Master, all in applyAttackResult —
    Crusher (Bludgeoning push), Piercer (Puncture reroll + crit die), Slasher (Hamstring −10 Speed),
    Great Weapon Master (Heavy-weapon +PB damage).

Deferred (noted in known_limitations.md): Crusher/Slasher enhanced-crit advantage effects (G1b),
GWM Hew bonus attack (bonus-attack phase), every other general feat.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from test_feats import _place, _three, _target, _land_hit, _reset_turn_flags, _arm


def _wpn(name, dmg, die=8, heavy=False, light=False, bonus_hit=50):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.heavy = heavy
    w.light = light
    w.bonus_hit = bonus_hit
    pr = rpg.PhysicalDamageRoll()
    pr.type = dmg
    pr.num_dice = 1
    pr.die_size = die
    w.physical_damage_types = [pr]
    return w


def _breakdown(r):
    return [tuple(x) for x in r.damage_breakdown]


# ─────────────────────────────────────────────────────────────────────────────
#  G0 — Weapon flags
# ─────────────────────────────────────────────────────────────────────────────

def test_weapon_heavy_light_flags():
    w = rpg.Weapon()
    assert not w.heavy and not w.light, "default weapon is neither heavy nor light"
    w.heavy = True
    w.light = True
    assert w.heavy and w.light
    print("✅ test_weapon_heavy_light_flags passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Great Weapon Master — Heavy Weapon Mastery (+PB damage)
# ─────────────────────────────────────────────────────────────────────────────

def test_gwm_adds_prof_bonus_on_heavy_hit():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "GWM", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_wpn("Greatsword", rpg.PhysicalDamage.Slashing, die=12, heavy=True)],
         feats=["Great Weapon Master"], prof=3)
    _target(engine, bm, t)
    r = _land_hit(engine, bm, a, t)
    assert ("GWM", 3) in _breakdown(r), f"expected +PB(3) GWM entry, got {_breakdown(r)}"
    print("✅ test_gwm_adds_prof_bonus_on_heavy_hit passed")


def test_gwm_not_on_nonheavy_or_bonus_action():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "GWM", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    # Non-heavy weapon in main hand, heavy weapon in slot 1 for the bonus-action test.
    _arm(engine, bm, a, [_wpn("Longsword", rpg.PhysicalDamage.Slashing, heavy=False),
                         _wpn("Greataxe", rpg.PhysicalDamage.Slashing, die=12, heavy=True)],
         feats=["Great Weapon Master"], prof=3)
    _target(engine, bm, t)

    r = _land_hit(engine, bm, a, t, weapon_idx=0)
    assert all(k != "GWM" for k, _ in _breakdown(r)), "GWM must not fire on a non-Heavy weapon"

    # Heavy weapon but flagged as a bonus-action attack → not "part of the Attack action".
    for _ in range(30):
        atk = rpg.Attack(a, t, 1)
        atk.attack_slot = "bonus"
        rr = engine.execute_action(bm, atk)
        if rr.hit:
            assert all(k != "GWM" for k, _ in _breakdown(rr)), "GWM must not fire on a bonus-action attack"
            break
    print("✅ test_gwm_not_on_nonheavy_or_bonus_action passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Crusher — Bludgeoning push
# ─────────────────────────────────────────────────────────────────────────────

def test_crusher_push_and_once_per_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Crusher", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_wpn("Maul", rpg.PhysicalDamage.Bludgeoning, die=6, heavy=True)],
         feats=["Crusher"])
    _target(engine, bm, t)

    _land_hit(engine, bm, a, t)
    assert bm.placed_agents[t].origin.col == 7, "Crusher pushes the target 5 ft east"
    assert engine.get_agent_conditions(bm, a).crusher_push_used_this_turn
    print("✅ test_crusher_push_and_once_per_turn passed")


def test_crusher_size_gate():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Crusher", 5, 5)
    # Target two sizes larger (size 3 vs attacker size 1) → no push.
    cfg = create_test_agent("Big", 6, 5); cfg.size = 3
    t = add_agent_to_battle(engine, bm, cfg)
    _arm(engine, bm, a, [_wpn("Mace", rpg.PhysicalDamage.Bludgeoning, die=6)], feats=["Crusher"])
    _target(engine, bm, t)

    _land_hit(engine, bm, a, t)
    assert not engine.get_agent_conditions(bm, a).crusher_push_used_this_turn, \
        "Crusher must not push a target more than one size larger"
    print("✅ test_crusher_size_gate passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Piercer — Puncture reroll (once/turn) + crit extra die
# ─────────────────────────────────────────────────────────────────────────────

def test_piercer_reroll_once_per_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Piercer", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_wpn("Rapier", rpg.PhysicalDamage.Piercing, die=8)], feats=["Piercer"])
    _target(engine, bm, t)

    _land_hit(engine, bm, a, t)
    assert engine.get_agent_conditions(bm, a).piercer_reroll_used_this_turn, \
        "Piercer marks its reroll used after a Piercing hit"
    _land_hit(engine, bm, a, t)  # still used (once per turn)
    assert engine.get_agent_conditions(bm, a).piercer_reroll_used_this_turn
    print("✅ test_piercer_reroll_once_per_turn passed")


def test_piercer_crit_adds_damage():
    # Force every hit to crit (crit_threshold=1) and compare mean damage with vs without Piercer.
    N = 200
    def mean(feats):
        bm = setup_battle_map(); engine = setup_combat_engine()
        a = _place(engine, bm, "A", 5, 5)
        t = _place(engine, bm, "T", 6, 5)
        _arm(engine, bm, a, [_wpn("Pike", rpg.PhysicalDamage.Piercing, die=10)], feats=feats, strv=10)
        s = engine.get_agent_stats(bm, a); s.crit_threshold = 1; engine.set_agent_stats(bm, a, s)
        # Huge HP so the target never drops — an unconscious target's auto-crit re-rolls damage
        # without the feat riders, which would dilute the comparison.
        _target(engine, bm, t, hp=10_000_000)
        tot = 0
        for _ in range(N):
            _reset_turn_flags_general(engine, bm, a)
            r = engine.execute_action(bm, rpg.Attack(a, t, 0))
            tot += r.total_damage
        return tot / N
    base = mean([])
    pierc = mean(["Piercer"])
    assert pierc > base + 1.0, f"Piercer crit+reroll mean {pierc:.2f} should beat base {base:.2f}"
    print(f"✅ test_piercer_crit_adds_damage passed (base={base:.2f}, piercer={pierc:.2f})")


def _reset_turn_flags_general(engine, bm, idx):
    c = engine.get_agent_conditions(bm, idx)
    c.piercer_reroll_used_this_turn = False
    c.crusher_push_used_this_turn = False
    c.slasher_slow_used_this_turn = False
    engine.set_agent_conditions(bm, idx, c)


# ─────────────────────────────────────────────────────────────────────────────
#  Slasher — Hamstring (−10 Speed)
# ─────────────────────────────────────────────────────────────────────────────

def _force_crit(engine, bm, idx):
    s = engine.get_agent_stats(bm, idx); s.crit_threshold = 1; engine.set_agent_stats(bm, idx, s)


def test_crusher_crit_grants_advantage_until_your_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Crusher", 5, 5)      # feat-user
    t = _place(engine, bm, "Tgt", 6, 5)
    b = _place(engine, bm, "Ally", 6, 6)         # another attacker (diagonally adjacent to T,
                                                 # stays adjacent after the Crusher push to (7,5))
    _arm(engine, bm, a, [_wpn("Maul", rpg.PhysicalDamage.Bludgeoning, die=6, heavy=True)], feats=["Crusher"])
    _arm(engine, bm, b, [_wpn("Club", rpg.PhysicalDamage.Bludgeoning, die=4)], feats=[])
    _force_crit(engine, bm, a)
    _target(engine, bm, t, hp=10_000_000)

    engine.execute_action(bm, rpg.Attack(a, t, 0))   # crit → marks target
    assert engine.get_agent_conditions(bm, t).crusher_marked
    assert engine.get_agent_conditions(bm, t).crusher_marked_by == a

    # The ally's attack against the marked target has Advantage.
    rb = engine.execute_action(bm, rpg.Attack(b, t, 0))
    assert rb.advantage, "attacks against a Crusher-marked target have Advantage"

    # The mark expires at the start of the Crusher's next turn.
    engine.begin_turn(bm, a)
    assert not engine.get_agent_conditions(bm, t).crusher_marked, "mark cleared at feat-user's next turn"
    rb2 = engine.execute_action(bm, rpg.Attack(b, t, 0))
    assert not rb2.advantage, "advantage gone after the mark expires"
    print("✅ test_crusher_crit_grants_advantage_until_your_turn passed")


def test_slasher_crit_imposes_disadvantage_until_your_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Slasher", 5, 5)      # feat-user
    t = _place(engine, bm, "Tgt", 6, 5)
    v = _place(engine, bm, "Victim2", 7, 5)      # someone the target can attack
    _arm(engine, bm, a, [_wpn("Longsword", rpg.PhysicalDamage.Slashing, die=8)], feats=["Slasher"])
    _arm(engine, bm, t, [_wpn("Shortsword", rpg.PhysicalDamage.Slashing, die=6)], feats=[])
    _force_crit(engine, bm, a)
    _target(engine, bm, t, hp=10_000_000)
    _target(engine, bm, v, hp=10_000_000)

    engine.execute_action(bm, rpg.Attack(a, t, 0))   # crit → marks target
    assert engine.get_agent_conditions(bm, t).slasher_marked
    assert engine.get_agent_conditions(bm, t).slasher_marked_by == a

    # The marked target's own attack has Disadvantage.
    rt = engine.execute_action(bm, rpg.Attack(t, v, 0))
    assert rt.disadvantage, "a Slasher-marked creature attacks at Disadvantage"

    # Expires at the start of the Slasher's next turn.
    engine.begin_turn(bm, a)
    assert not engine.get_agent_conditions(bm, t).slasher_marked
    rt2 = engine.execute_action(bm, rpg.Attack(t, v, 0))
    assert not rt2.disadvantage, "disadvantage gone after the mark expires"
    print("✅ test_slasher_crit_imposes_disadvantage_until_your_turn passed")


def test_slasher_slows_target():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Slasher", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_wpn("Longsword", rpg.PhysicalDamage.Slashing, die=8)], feats=["Slasher"])
    _target(engine, bm, t)

    assert not engine.get_agent_conditions(bm, t).slowed
    _land_hit(engine, bm, a, t)
    assert engine.get_agent_conditions(bm, t).slowed, "Slasher slows the target (−10 ft)"
    assert engine.get_agent_conditions(bm, a).slasher_slow_used_this_turn
    print("✅ test_slasher_slows_target passed")


# ─────────────────────────────────────────────────────────────────────────────
#  GUI multi-select plumbing — App._set_general_feats
# ─────────────────────────────────────────────────────────────────────────────

def test_gui_set_general_feats():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from main import App

    s = rpg.Stats()
    s.add_feat("Tough")          # an origin feat — must be preserved
    App._set_general_feats(s, ["Crusher", "Piercer"])
    assert s.has_feat("Crusher") and s.has_feat("Piercer")
    assert s.has_feat("Tough"), "general-feat update must not touch the origin feat"

    # Re-select a different set: dropped general feats are removed, origin feat stays.
    App._set_general_feats(s, ["Slasher"])
    assert s.has_feat("Slasher")
    assert not s.has_feat("Crusher") and not s.has_feat("Piercer")
    assert s.has_feat("Tough")
    print("✅ test_gui_set_general_feats passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Grappler (G2) — Punch-and-Grab (unarmed hit → also Grapple) + Advantage vs grappled
# ─────────────────────────────────────────────────────────────────────────────

def _unarmed(bonus_hit=50):
    w = rpg.Weapon()
    w.name = "Unarmed"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = bonus_hit
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice = 1
    pr.die_size = 4
    w.physical_damage_types = [pr]
    return w


def _set_ability(engine, bm, idx, strv=None, dexv=None):
    s = engine.get_agent_stats(bm, idx)
    if strv is not None:
        s.str = strv
    if dexv is not None:
        s.dex = dexv
    engine.set_agent_stats(bm, idx, s)


def test_grappler_punch_grab_flag_set_on_unarmed_hit():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Grappler", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_unarmed()], feats=["Grappler"])
    _target(engine, bm, t)
    r = _land_hit(engine, bm, a, t)
    assert r.hit
    c = engine.get_agent_conditions(bm, a)
    assert c.grappler_punch_grab_available, "an Unarmed-Strike hit by a Grappler arms Punch-and-Grab"
    print("✅ test_grappler_punch_grab_flag_set_on_unarmed_hit passed")


def test_grappler_punch_grab_grapples_through_resolve_grapple():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Grappler", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    # Overwhelming contested-check edge: attacker STR 30 (+10) & prof 6 vs target STR/DEX 1 (−4) →
    # min attacker 17 > max defender 16, so the grapple always lands deterministically.
    _arm(engine, bm, a, [_unarmed()], feats=["Grappler"], strv=30, prof=6)
    _target(engine, bm, t)
    _set_ability(engine, bm, t, strv=1, dexv=1)
    r = _land_hit(engine, bm, a, t)
    assert r.hit
    grab = engine.apply_punch_and_grab(bm, a, t)
    assert grab.valid and grab.success, f"Punch-and-Grab should grapple, got {grab.log_message}"
    tc = engine.get_agent_conditions(bm, t)
    assert tc.grappled and tc.grappler_idx == a, "target should be Grappled by the Grappler"
    ac = engine.get_agent_conditions(bm, a)
    assert ac.grappler_punch_grab_used, "Punch-and-Grab is marked used for the turn"
    assert not ac.grappler_punch_grab_available, "the available flag is cleared after use"
    # Once per turn: a second qualifying hit must NOT re-arm it.
    r2 = _land_hit(engine, bm, a, t)
    assert not engine.get_agent_conditions(bm, a).grappler_punch_grab_available, \
        "Punch-and-Grab is once per turn — not re-armed after use"
    print("✅ test_grappler_punch_grab_grapples_through_resolve_grapple passed")


def test_grappler_punch_grab_not_on_regular_weapon():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Grappler", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_wpn("Mace", rpg.PhysicalDamage.Bludgeoning)], feats=["Grappler"])
    _target(engine, bm, t)
    r = _land_hit(engine, bm, a, t)
    assert r.hit
    assert not engine.get_agent_conditions(bm, a).grappler_punch_grab_available, \
        "Punch-and-Grab only triggers on an Unarmed Strike, not a regular weapon"
    print("✅ test_grappler_punch_grab_not_on_regular_weapon passed")


def test_grappler_punch_grab_not_on_bonus_action():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Grappler", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_unarmed()], feats=["Grappler"])
    _target(engine, bm, t)
    # A bonus-action unarmed strike is not "part of the Attack action" → no Punch-and-Grab.
    r = None
    for _ in range(30):
        act = rpg.Attack(a, t, 0)
        act.attack_slot = "bonus"
        r = engine.execute_action(bm, act)
        if r.hit:
            break
    assert r.hit
    assert not engine.get_agent_conditions(bm, a).grappler_punch_grab_available, \
        "a bonus-action Unarmed Strike does not arm Punch-and-Grab"
    print("✅ test_grappler_punch_grab_not_on_bonus_action passed")


def test_grappler_advantage_vs_creature_it_grappled():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Grappler", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_unarmed()], feats=["Grappler"])
    _target(engine, bm, t)
    # Mark the target as grappled BY the attacker.
    tc = engine.get_agent_conditions(bm, t)
    tc.grappled = True
    tc.grappler_idx = a
    engine.set_agent_conditions(bm, t, tc)
    r = _land_hit(engine, bm, a, t)
    assert r.advantage, "a Grappler has Advantage attacking a creature it has grappled"
    print("✅ test_grappler_advantage_vs_creature_it_grappled passed")


def test_grappler_no_advantage_without_feat():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Plain", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    _arm(engine, bm, a, [_unarmed()])   # no Grappler feat
    _target(engine, bm, t)
    tc = engine.get_agent_conditions(bm, t)
    tc.grappled = True
    tc.grappler_idx = a
    engine.set_agent_conditions(bm, t, tc)
    r = _land_hit(engine, bm, a, t)
    assert not r.advantage, "grappling alone grants no Advantage without the Grappler feat"
    print("✅ test_grappler_no_advantage_without_feat passed")


def main():
    print("Running General feat tests (G0 + G1 + G2)...\n")
    test_weapon_heavy_light_flags()
    test_gwm_adds_prof_bonus_on_heavy_hit()
    test_gwm_not_on_nonheavy_or_bonus_action()
    test_crusher_push_and_once_per_turn()
    test_crusher_size_gate()
    test_piercer_reroll_once_per_turn()
    test_piercer_crit_adds_damage()
    test_crusher_crit_grants_advantage_until_your_turn()
    test_slasher_crit_imposes_disadvantage_until_your_turn()
    test_slasher_slows_target()
    test_gui_set_general_feats()
    test_grappler_punch_grab_flag_set_on_unarmed_hit()
    test_grappler_punch_grab_grapples_through_resolve_grapple()
    test_grappler_punch_grab_not_on_regular_weapon()
    test_grappler_punch_grab_not_on_bonus_action()
    test_grappler_advantage_vs_creature_it_grappled()
    test_grappler_no_advantage_without_feat()
    print("\n" + "=" * 60)
    print("✅ All General feat (G0+G1+G2) tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
