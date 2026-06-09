#!/usr/bin/env python3
"""
Test suite for Battle Master Riposte.

Riposte is a DEFENDER reaction modeled on Reckless Attack's post-hoc-on-miss path: when a MELEE
attack misses a Battle Master, the engine flags conditions.riposte_available on the TARGET (the
reactor, not the attacker). The GUI prompts and calls apply_riposte; the auto/RL driver consults
CombatDecider.choose_reaction at an OnMiss window inline (the mirror of the OnHit Shield path).
A riposte spends the reaction + 1 Superiority Die and makes a melee attack defender→attacker,
adding the Superiority Die to the damage on a hit. Because the riposte fires AFTER the triggering
attack fully resolves, it is a fresh top-level attack — no decision stack.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


class RiposteDecider(rpg.CombatDecider):
    """Auto/RL decider: at an OnMiss window, take the Riposte Feature option (if take=True) or skip.
    Records the windows it saw so tests can assert the OnMiss window opened."""
    def __init__(self, take):
        super().__init__()
        self._take = take
        self.windows = []
    def choose_reaction(self, ctx):
        self.windows.append(ctx.window)
        resp = rpg.ReactionResponse()
        resp.option = -1
        if self._take:
            for i, o in enumerate(ctx.options):
                if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "Riposte":
                    resp.option = i
                    break
        return resp


def _melee(name="Greataxe", die=12):
    w = rpg.Weapon(); w.name = name; w.type = rpg.WeaponType.Melee; w.reach_ft = 5
    pr = rpg.PhysicalDamageRoll(); pr.type = rpg.PhysicalDamage.Slashing; pr.num_dice = 1; pr.die_size = die
    w.physical_damage_types = [pr]
    return w


def _ranged():
    w = rpg.Weapon(); w.name = "Longbow"; w.type = rpg.WeaponType.Ranged
    w.range_short_feet = 150; w.range_long_feet = 600
    pr = rpg.PhysicalDamageRoll(); pr.type = rpg.PhysicalDamage.Piercing; pr.num_dice = 1; pr.die_size = 8
    w.physical_damage_types = [pr]
    return w


def _setup(engine, bm, *, defender_level=5, defender_ac=30, attacker_ac=10,
           give_dice=True, ranged_attacker=False):
    """A plain attacker at (5,5) and a Battle Master defender adjacent at (6,5).
    defender_ac defaults high (30) so the attacker reliably MISSES → the riposte window opens.
    Stats are set AFTER both adds (apply_agent_configs resets the earlier agent)."""
    atk = add_agent_to_battle(engine, bm, create_test_agent("Atk", 5, 5))
    dfn = add_agent_to_battle(engine, bm, create_test_agent("BattleMaster", 6, 5))

    # Defender = Battle Master with Superiority Dice + a melee weapon, high AC to force the miss.
    ds = engine.get_agent_stats(bm, dfn)
    ds.set_class_level(rpg.CharacterClass.Fighter, defender_level)
    ds.str = 16; ds.dex = 12; ds.con = 14
    ds.fighter_subclass = rpg.FighterSubclass.BattleMaster
    ds.initialize_class_resources(rpg.CharacterClass.Fighter, defender_level)
    ds.base_ac = defender_ac; ds.hp_max = 60; ds.hp_cur = 60
    if not give_dice:
        sd = ds.get_resource("Superiority Dice")
        if sd is not None:
            sd.current = 0
            ds.resources["Superiority Dice"] = sd
    engine.set_agent_stats(bm, dfn, ds)
    engine.set_agent_weapons(bm, dfn, [_melee("Longsword", 8), rpg.Weapon(), rpg.Weapon()])

    # Attacker = plain creature whose attack misses the high-AC defender.
    a_s = engine.get_agent_stats(bm, atk)
    a_s.base_ac = attacker_ac; a_s.hp_max = 40; a_s.hp_cur = 40
    engine.set_agent_stats(bm, atk, a_s)
    engine.set_agent_weapons(bm, atk, [(_ranged() if ranged_attacker else _melee()), rpg.Weapon(), rpg.Weapon()])
    return atk, dfn


def _cond(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx)


def _dice(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).get_resource("Superiority Dice").current


# ── Tests ────────────────────────────────────────────────────────────────────
def test_melee_miss_flags_defender():
    """GUI path: a melee miss flags riposte_available on the DEFENDER (target), not the attacker."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, dfn = _setup(engine, bm)
    r = engine.execute_action(bm, rpg.Attack(atk, dfn, 0))
    assert not r.hit, f"setup expected a miss (roll {r.total_roll} vs AC {r.target_ac})"
    assert _cond(engine, bm, dfn).riposte_available, "the missed Battle Master should be offered a Riposte"
    assert not _cond(engine, bm, atk).riposte_available, "the flag must be on the defender, never the attacker"
    print("✅ test_melee_miss_flags_defender passed")


def test_apply_riposte_attacks_back_and_spends():
    """apply_riposte spends the reaction + 1 Superiority Die and makes a melee attack back."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, dfn = _setup(engine, bm)
    engine.execute_action(bm, rpg.Attack(atk, dfn, 0))
    assert _cond(engine, bm, dfn).riposte_available
    dice_before = _dice(engine, bm, dfn)
    rip = engine.apply_riposte(bm, dfn, atk, 0)
    c = _cond(engine, bm, dfn)
    assert rip.valid, "the riposte should produce a valid AttackResult"
    assert c.reaction_used, "a riposte spends the defender's reaction"
    assert not c.riposte_available, "the offer flag is consumed"
    assert _dice(engine, bm, dfn) == dice_before - 1, "a riposte spends exactly one Superiority Die"
    print("✅ test_apply_riposte_attacks_back_and_spends passed")


def test_riposte_hit_adds_superiority_die_to_damage():
    """On a hit, the Superiority Die is added to the riposte's damage (a 'riposte' breakdown entry)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, dfn = _setup(engine, bm, attacker_ac=1)   # AC 1 → the riposte reliably hits the attacker
    engine.execute_action(bm, rpg.Attack(atk, dfn, 0))
    assert _cond(engine, bm, dfn).riposte_available
    rip = engine.apply_riposte(bm, dfn, atk, 0)
    assert rip.hit, f"riposte vs AC 1 should hit (roll {rip.total_roll})"
    labels = [label for label, _amt in rip.damage_breakdown]
    assert "riposte" in labels, f"hit riposte should add a Superiority Die ('riposte' entry); got {labels}"
    print("✅ test_riposte_hit_adds_superiority_die_to_damage passed")


def test_apply_without_offer_is_noop():
    """apply_riposte with no pending offer returns an invalid result and spends nothing."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, dfn = _setup(engine, bm)
    dice_before = _dice(engine, bm, dfn)
    rip = engine.apply_riposte(bm, dfn, atk, 0)   # no miss happened yet → no flag
    assert not rip.valid, "no offer → invalid (no-op) result"
    assert not _cond(engine, bm, dfn).reaction_used, "no reaction spent without an offer"
    assert _dice(engine, bm, dfn) == dice_before, "no die spent without an offer"
    print("✅ test_apply_without_offer_is_noop passed")


def test_auto_decider_take_ripostes_inline():
    """Auto driver: a decider taking the OnMiss option ripostes inline during execute_action."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    dec = RiposteDecider(True); engine.set_decider(dec)
    atk, dfn = _setup(engine, bm)
    dice_before = _dice(engine, bm, dfn)
    engine.execute_action(bm, rpg.Attack(atk, dfn, 0))
    c = _cond(engine, bm, dfn)
    assert rpg.ReactionWindow.OnMiss in dec.windows, "the OnMiss window should have opened for the defender"
    assert c.reaction_used, "decider-take ripostes inline (reaction spent)"
    assert not c.riposte_available, "no deferred flag left on the auto path"
    assert _dice(engine, bm, dfn) == dice_before - 1, "the inline riposte spent one Superiority Die"
    print("✅ test_auto_decider_take_ripostes_inline passed")


def test_auto_decider_skip_does_not_riposte():
    """Auto driver: a decider skipping leaves the miss standing (no reaction, no die, flag cleared)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    dec = RiposteDecider(False); engine.set_decider(dec)
    atk, dfn = _setup(engine, bm)
    dice_before = _dice(engine, bm, dfn)
    engine.execute_action(bm, rpg.Attack(atk, dfn, 0))
    c = _cond(engine, bm, dfn)
    assert rpg.ReactionWindow.OnMiss in dec.windows, "the decider should still be consulted"
    assert not c.reaction_used and not c.riposte_available, "decider-skip => nothing spent, flag cleared"
    assert _dice(engine, bm, dfn) == dice_before, "skip spends no Superiority Die"
    print("✅ test_auto_decider_skip_does_not_riposte passed")


def test_ranged_miss_not_offered():
    """Riposte triggers on a MELEE miss only — a ranged miss does not offer it."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, dfn = _setup(engine, bm, ranged_attacker=True)
    r = engine.execute_action(bm, rpg.Attack(atk, dfn, 0))
    assert not r.hit
    assert not _cond(engine, bm, dfn).riposte_available, "a ranged miss must not offer a Riposte"
    print("✅ test_ranged_miss_not_offered passed")


def test_no_superiority_dice_not_offered():
    """A Battle Master with no Superiority Dice left is not offered a Riposte."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, dfn = _setup(engine, bm, give_dice=False)
    r = engine.execute_action(bm, rpg.Attack(atk, dfn, 0))
    assert not r.hit
    assert not _cond(engine, bm, dfn).riposte_available, "no dice => no Riposte offer"
    print("✅ test_no_superiority_dice_not_offered passed")


def test_reaction_used_not_offered():
    """A defender that already spent its reaction is not offered a Riposte."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, dfn = _setup(engine, bm)
    c = _cond(engine, bm, dfn); c.reaction_used = True
    engine.set_agent_conditions(bm, dfn, c)
    r = engine.execute_action(bm, rpg.Attack(atk, dfn, 0))
    assert not r.hit
    assert not _cond(engine, bm, dfn).riposte_available, "no free reaction => no Riposte offer"
    print("✅ test_reaction_used_not_offered passed")


def test_riposte_chain_terminates():
    """Two Battle Masters: an inline riposte uses the defender's reaction, so it cannot riposte again
    against the same swing — the reaction economy caps the chain (no infinite recursion)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    dec = RiposteDecider(True); engine.set_decider(dec)
    atk, dfn = _setup(engine, bm)
    # Make the attacker ALSO a Battle Master so its own miss-of-the-riposte could, in principle, re-trigger.
    a_s = engine.get_agent_stats(bm, atk)
    a_s.set_class_level(rpg.CharacterClass.Fighter, 5)
    a_s.fighter_subclass = rpg.FighterSubclass.BattleMaster
    a_s.initialize_class_resources(rpg.CharacterClass.Fighter, 5)
    a_s.base_ac = 30   # so the defender's riposte against it tends to miss → would re-open OnMiss
    engine.set_agent_stats(bm, atk, a_s)
    # Should return without hanging; the defender spent its reaction on the first riposte.
    engine.execute_action(bm, rpg.Attack(atk, dfn, 0))
    assert _cond(engine, bm, dfn).reaction_used, "the defender's single reaction is spent on its riposte"
    print("✅ test_riposte_chain_terminates passed")


def run_all():
    test_melee_miss_flags_defender()
    test_apply_riposte_attacks_back_and_spends()
    test_riposte_hit_adds_superiority_die_to_damage()
    test_apply_without_offer_is_noop()
    test_auto_decider_take_ripostes_inline()
    test_auto_decider_skip_does_not_riposte()
    test_ranged_miss_not_offered()
    test_no_superiority_dice_not_offered()
    test_reaction_used_not_offered()
    test_riposte_chain_terminates()
    print("\nAll Riposte tests passed ✅")


if __name__ == "__main__":
    run_all()
