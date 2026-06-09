#!/usr/bin/env python3
"""
Test suite for Reckless Attack.

Two entry points:
  • Pre-declared (set reckless_attack before attacking) — RAW.
  • Post-hoc on a miss — the engine flags reckless_reroll_available; the GUI prompts and calls
    apply_reckless_reroll; the auto/RL driver consults CombatDecider.choose_reckless inline.
Both incur the downside (enemies have advantage vs you until the start of your next turn) and the
flag clears at the Barbarian's next turn start.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


class RecklessDecider(rpg.CombatDecider):
    """Auto/RL decider that answers choose_reckless with a fixed yes/no, recording calls."""
    def __init__(self, say_yes):
        super().__init__()
        self._yes = say_yes
        self.calls = 0
    def choose_reckless(self, ctx):
        self.calls += 1
        return self._yes


def _setup_barb_vs_target(engine, bm, atk_level=5, target_ac=30):
    """Barbarian attacker at (5,5), a high-AC target adjacent at (6,5) so the attack reliably misses.
    Stats are set AFTER both adds (apply_agent_configs resets the earlier agent)."""
    atk = add_agent_to_battle(engine, bm, create_test_agent("Barb", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Dummy", 6, 5))
    s = engine.get_agent_stats(bm, atk)
    s.character_class = rpg.CharacterClass.Barbarian
    s.char_level = atk_level
    engine.set_agent_stats(bm, atk, s)
    ts = engine.get_agent_stats(bm, tgt)
    ts.base_ac = target_ac
    ts.hp_max = 100; ts.hp_cur = 100
    engine.set_agent_stats(bm, tgt, ts)
    w = rpg.Weapon(); w.name = "Greataxe"; w.type = rpg.WeaponType.Melee; w.reach_ft = 5
    pr = rpg.PhysicalDamageRoll(); pr.type = rpg.PhysicalDamage.Slashing; pr.num_dice = 1; pr.die_size = 12
    w.physical_damage_types = [pr]
    engine.set_agent_weapons(bm, atk, [w, rpg.Weapon(), rpg.Weapon()])
    return atk, tgt


def _attack(engine, bm, atk, tgt):
    return engine.execute_action(bm, rpg.Attack(atk, tgt, 0))


def _cond(engine, bm, idx):
    return engine.get_agent_conditions(bm, idx)


# ── Tests ────────────────────────────────────────────────────────────────────
def test_miss_with_no_decider_sets_deferred_flag():
    """GUI path: a miss flags reckless_reroll_available but does NOT auto-commit Reckless."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup_barb_vs_target(engine, bm)
    r = _attack(engine, bm, atk, tgt)
    assert not r.hit, f"setup expected a miss (roll {r.total_roll} vs AC {r.target_ac})"
    c = _cond(engine, bm, atk)
    assert c.reckless_reroll_available, "miss should offer a reckless reroll (deferred flag)"
    assert not c.reckless_attack, "no decider must NOT auto-commit Reckless"
    print("✅ test_miss_with_no_decider_sets_deferred_flag passed")


def test_apply_reckless_reroll_commits_and_rerolls():
    """apply_reckless_reroll commits Reckless (downside) and re-resolves with advantage."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup_barb_vs_target(engine, bm)
    r = _attack(engine, bm, atk, tgt)
    assert not r.hit and _cond(engine, bm, atk).reckless_reroll_available
    new_r = engine.apply_reckless_reroll(bm, atk, tgt, 0)
    c = _cond(engine, bm, atk)
    assert new_r.valid, "reroll should produce a valid AttackResult"
    assert c.reckless_attack, "reroll commits Reckless (enemies gain advantage vs you)"
    assert not c.reckless_reroll_available, "the offer flag is consumed"
    print("✅ test_apply_reckless_reroll_commits_and_rerolls passed")


def test_apply_without_offer_is_noop():
    """apply_reckless_reroll with no pending offer returns an invalid result and changes nothing."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup_barb_vs_target(engine, bm)
    # No miss yet → no flag.
    new_r = engine.apply_reckless_reroll(bm, atk, tgt, 0)
    assert not new_r.valid, "no offer → invalid (no-op) result"
    assert not _cond(engine, bm, atk).reckless_attack
    print("✅ test_apply_without_offer_is_noop passed")


def test_auto_decider_yes_rerolls_inline():
    """Auto driver: a decider returning True commits Reckless inline during execute_action."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    dec = RecklessDecider(True); engine.set_decider(dec)
    atk, tgt = _setup_barb_vs_target(engine, bm)
    _attack(engine, bm, atk, tgt)
    c = _cond(engine, bm, atk)
    assert dec.calls >= 1, "decider should have been consulted on the miss"
    assert c.reckless_attack, "decider-yes commits Reckless inline"
    assert not c.reckless_reroll_available, "no deferred flag on the auto path"
    print("✅ test_auto_decider_yes_rerolls_inline passed")


def test_auto_decider_no_does_not_reroll():
    """Auto driver: a decider returning False leaves the miss standing (no Reckless, no flag)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    dec = RecklessDecider(False); engine.set_decider(dec)
    atk, tgt = _setup_barb_vs_target(engine, bm)
    _attack(engine, bm, atk, tgt)
    c = _cond(engine, bm, atk)
    assert dec.calls >= 1, "decider should have been consulted"
    assert not c.reckless_attack and not c.reckless_reroll_available, "decider-no => nothing happens"
    print("✅ test_auto_decider_no_does_not_reroll passed")


def test_level1_barbarian_not_offered():
    """Reckless Attack is a L2 feature — a L1 Barbarian gets no offer on a miss."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup_barb_vs_target(engine, bm, atk_level=1)
    r = _attack(engine, bm, atk, tgt)
    assert not r.hit
    assert not _cond(engine, bm, atk).reckless_reroll_available, "L1 Barbarian must not be offered Reckless"
    print("✅ test_level1_barbarian_not_offered passed")


def test_non_barbarian_not_offered():
    """A non-Barbarian gets no reckless offer on a miss."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup_barb_vs_target(engine, bm)
    s = engine.get_agent_stats(bm, atk); s.character_class = rpg.CharacterClass.Fighter
    engine.set_agent_stats(bm, atk, s)
    r = _attack(engine, bm, atk, tgt)
    assert not r.hit
    assert not _cond(engine, bm, atk).reckless_reroll_available, "non-Barbarian must not be offered Reckless"
    print("✅ test_non_barbarian_not_offered passed")


def test_downside_clears_at_next_turn_start():
    """reckless_attack (the downside) is cleared at the start of the Barbarian's next turn."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt = _setup_barb_vs_target(engine, bm)
    c = _cond(engine, bm, atk); c.reckless_attack = True
    engine.set_agent_conditions(bm, atk, c)
    engine.begin_turn(bm, atk)
    assert not _cond(engine, bm, atk).reckless_attack, "Reckless downside must clear at turn start"
    print("✅ test_downside_clears_at_next_turn_start passed")


def run_all():
    test_miss_with_no_decider_sets_deferred_flag()
    test_apply_reckless_reroll_commits_and_rerolls()
    test_apply_without_offer_is_noop()
    test_auto_decider_yes_rerolls_inline()
    test_auto_decider_no_does_not_reroll()
    test_level1_barbarian_not_offered()
    test_non_barbarian_not_offered()
    test_downside_clears_at_next_turn_start()
    print("\nAll Reckless Attack tests passed ✅")


if __name__ == "__main__":
    run_all()
