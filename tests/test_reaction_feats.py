#!/usr/bin/env python3
"""
G3 reaction-feat tests (2024 PHB) + the shield-in-off-hand foundation.

Foundation: Weapon.is_shield → a Shield held in a weapon (off-hand) slot grants ac_bonus and counts as
"holding a Shield" (is_holding_shield). calculate_ac folds in the shield bonus.

Feats:
  · War Caster              — Advantage on concentration saves.
  · Mage Slayer             — Concentration Breaker: a Mage Slayer damager imposes Disadvantage on the
                              concentrator's save. (Guarded Mind deferred — see known_limitations.md.)
  · Defensive Duelist       — OnHit defender reaction: +PB AC vs a melee hit (finesse), flips hit→miss.
  · Shield Master           — Shield Bash gate (can_shield_bash); the shove reuses execute_shove.
                              (Interpose deferred — see known_limitations.md.)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle
from test_feats import _place, _arm, _target, _land_hit


def _shield():
    w = rpg.Weapon()
    w.name = "Shield"
    w.type = rpg.WeaponType.Melee
    w.off_hand = True
    w.is_shield = True
    w.ac_bonus = 2
    return w


def _finesse_blade(bonus_hit=50):
    w = rpg.Weapon()
    w.name = "Rapier"
    w.type = rpg.WeaponType.Melee
    w.finesse = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = bonus_hit
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Piercing
    pr.num_dice = 1
    pr.die_size = 8
    w.physical_damage_types = [pr]
    return w


# ── Scripted OnHit decider (mirrors test_reactions' pattern) ──────────────────
class FeaturePickDecider(rpg.CombatDecider):
    """Picks the first Feature option whose `feature` is in `wanted`; else Skip."""
    def __init__(self, wanted):
        super().__init__()
        self._wanted = set(wanted)
        self.seen = []

    def choose_reaction(self, ctx):
        self.seen.append((ctx.reactor_idx, ctx.window, [o.feature for o in ctx.options]))
        resp = rpg.ReactionResponse()
        resp.option = -1
        for i, o in enumerate(ctx.options):
            if o.kind == rpg.ReactionOptionKind.Feature and o.feature in self._wanted:
                resp.option = i
                break
        return resp


# ─────────────────────────────────────────────────────────────────────────────
#  Shield-in-off-hand foundation
# ─────────────────────────────────────────────────────────────────────────────

def test_weapon_is_shield_flag():
    w = rpg.Weapon()
    assert not w.is_shield, "default weapon is not a shield"
    w.is_shield = True
    w.ac_bonus = 2
    assert w.is_shield and w.ac_bonus == 2
    print("✅ test_weapon_is_shield_flag passed")


def test_is_holding_shield_detects_offhand_shield():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Knight", 5, 5)
    _arm(engine, bm, a, [_finesse_blade()])
    assert not engine.is_holding_shield(bm, a), "no shield equipped yet"
    engine.set_agent_weapons(bm, a, [_finesse_blade(), _shield(), rpg.Weapon()])
    assert engine.is_holding_shield(bm, a), "a Shield in the off-hand slot counts as holding a shield"
    print("✅ test_is_holding_shield_detects_offhand_shield passed")


def test_calculate_ac_includes_offhand_shield():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Knight", 5, 5)
    s = engine.get_agent_stats(bm, a); s.base_ac = 16; s.dex = 10
    engine.set_agent_stats(bm, a, s)
    engine.set_agent_weapons(bm, a, [_finesse_blade(), rpg.Weapon(), rpg.Weapon()])
    ac_no_shield = engine.calculate_ac(bm, a)
    engine.set_agent_weapons(bm, a, [_finesse_blade(), _shield(), rpg.Weapon()])
    ac_shield = engine.calculate_ac(bm, a)
    assert ac_shield == ac_no_shield + 2, f"off-hand shield should add +2 AC, got {ac_no_shield}->{ac_shield}"
    print("✅ test_calculate_ac_includes_offhand_shield passed")


# ─────────────────────────────────────────────────────────────────────────────
#  War Caster + Mage Slayer Concentration Breaker (advantage/disadvantage on the
#  concentration save). Tested via hold-rate over a fixed-seed engine at a borderline
#  DC (CON mod 0, damage 22 → DC 11, a clean 50% baseline so adv/dis swings hard).
# ─────────────────────────────────────────────────────────────────────────────

def _conc_breaks(con_feat=None, damager_feat=None, trials=300):
    bm = setup_battle_map(); engine = setup_combat_engine()   # fixed seed → deterministic counts
    dmgr = _place(engine, bm, "Striker", 5, 5)
    conc = _place(engine, bm, "Caster", 6, 5)
    cs = engine.get_agent_stats(bm, conc); cs.con = 10; cs.save_prof_con = False
    if con_feat:
        cs.add_feat(con_feat)
    engine.set_agent_stats(bm, conc, cs)
    ds = engine.get_agent_stats(bm, dmgr)
    if damager_feat:
        ds.add_feat(damager_feat)
    engine.set_agent_stats(bm, dmgr, ds)
    breaks = 0
    for _ in range(trials):
        c = engine.get_agent_conditions(bm, conc)
        c.concentrating = True
        c.concentrating_on = "Bless"
        engine.set_agent_conditions(bm, conc, c)
        if engine.check_concentration_on_damage(bm, conc, 22, dmgr):   # DC = max(10, 11) = 11
            breaks += 1
    return breaks


def test_war_caster_advantage_holds_concentration_more():
    plain = _conc_breaks()
    war   = _conc_breaks(con_feat="War Caster")
    # Advantage roughly halves the break rate; require a wide, deterministic margin.
    assert war + 40 < plain, f"War Caster should break concentration far less often (war={war}, plain={plain})"
    print(f"✅ test_war_caster_advantage_holds_concentration_more passed (war={war} < plain={plain})")


def test_mage_slayer_concentration_breaker_breaks_more():
    plain = _conc_breaks()
    mage  = _conc_breaks(damager_feat="Mage Slayer")
    # Disadvantage roughly raises the break rate; require a wide, deterministic margin.
    assert mage > plain + 40, f"Mage Slayer should break concentration far more often (mage={mage}, plain={plain})"
    print(f"✅ test_mage_slayer_concentration_breaker_breaks_more passed (mage={mage} > plain={plain})")


def test_mage_slayer_only_when_damager_has_feat():
    # Passing the damager but with no feat → baseline (no disadvantage).
    plain = _conc_breaks()
    no_feat = _conc_breaks(damager_feat=None)
    assert plain == no_feat, "no Mage Slayer feat → identical (no disadvantage applied)"
    print("✅ test_mage_slayer_only_when_damager_has_feat passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Defensive Duelist (OnHit defender reaction)
# ─────────────────────────────────────────────────────────────────────────────

def _setup_duelist(engine, bm, defender_feat=True, defender_finesse=True):
    a = _place(engine, bm, "Attacker", 5, 5)
    d = _place(engine, bm, "Duelist", 6, 5)
    # Attacker: a guaranteed-hit melee weapon. Defender AC modest so +PB can flip a marginal hit.
    _arm(engine, bm, a, [_finesse_blade(bonus_hit=0)])   # bonus_hit ignored by engine to-hit
    dweap = _finesse_blade(bonus_hit=0) if defender_finesse else _nonfinesse_blade()
    feats = ["Defensive Duelist"] if defender_feat else []
    _arm(engine, bm, d, [dweap], feats=feats, prof=4)
    ds = engine.get_agent_stats(bm, d); ds.base_ac = 10; ds.hp_max = 80; ds.hp_cur = 80
    engine.set_agent_stats(bm, d, ds)
    return a, d


def _nonfinesse_blade():
    w = rpg.Weapon()
    w.name = "Mace"
    w.type = rpg.WeaponType.Melee
    w.finesse = False
    w.proficient = True
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Bludgeoning
    pr.num_dice = 1
    pr.die_size = 6
    w.physical_damage_types = [pr]
    return w


def _find_marginal_hit(engine, bm, a, d, tries=200):
    """Find an attack that hits but would miss if AC were +PB higher (so Defensive Duelist applies)."""
    pb = engine.get_agent_stats(bm, d).prof_bonus
    for _ in range(tries):
        r = engine.execute_action(bm, rpg.Attack(a, d, 0))
        if r.hit and not r.critical and r.total_roll < r.target_ac + pb:
            return r
    return None


def test_defensive_duelist_eligibility_and_apply():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a, d = _setup_duelist(engine, bm)
    r = _find_marginal_hit(engine, bm, a, d)
    assert r is not None, "should produce a marginal hit"
    action = rpg.Attack(a, d, 0)
    assert engine.can_defensive_duelist(bm, action, r), "duelist with a finesse weapon + free reaction is eligible"
    assert engine.apply_defensive_duelist(bm, d), "applying spends the reaction"
    assert engine.get_agent_conditions(bm, d).reaction_used, "reaction consumed"
    # Reaction now used → no longer eligible.
    assert not engine.can_defensive_duelist(bm, action, r), "a spent reaction blocks Defensive Duelist"
    print("✅ test_defensive_duelist_eligibility_and_apply passed")


def test_defensive_duelist_requires_finesse_weapon():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a, d = _setup_duelist(engine, bm, defender_finesse=False)
    r = _find_marginal_hit(engine, bm, a, d)
    assert r is not None
    assert not engine.can_defensive_duelist(bm, rpg.Attack(a, d, 0), r), \
        "Defensive Duelist needs a Finesse melee weapon in hand"
    print("✅ test_defensive_duelist_requires_finesse_weapon passed")


def test_defensive_duelist_requires_feat():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a, d = _setup_duelist(engine, bm, defender_feat=False)
    r = _find_marginal_hit(engine, bm, a, d)
    assert r is not None
    assert not engine.can_defensive_duelist(bm, rpg.Attack(a, d, 0), r), "no feat → not eligible"
    print("✅ test_defensive_duelist_requires_feat passed")


def test_defensive_duelist_auto_path_flips_hit_to_miss():
    """Auto/RL: with a decider that takes Defensive Duelist, a marginal hit becomes a miss."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a, d = _setup_duelist(engine, bm)
    dec = FeaturePickDecider({"DefensiveDuelist"})
    engine.set_decider(dec)
    pb = engine.get_agent_stats(bm, d).prof_bonus
    flipped = False
    for _ in range(200):
        # Reset the defender's reaction each attempt so the window can open.
        c = engine.get_agent_conditions(bm, d); c.reaction_used = False
        engine.set_agent_conditions(bm, d, c)
        r = engine.execute_action(bm, rpg.Attack(a, d, 0))
        if any(s[1] == rpg.ReactionWindow.OnHit and "DefensiveDuelist" in s[2] for s in dec.seen):
            # On a window that offered it, the inline decider flips the hit to a miss.
            assert not r.hit, "Defensive Duelist should flip the marginal hit to a miss"
            flipped = True
            break
        dec.seen.clear()
    assert flipped, "should have encountered and applied a Defensive Duelist window"
    print("✅ test_defensive_duelist_auto_path_flips_hit_to_miss passed")


# ─────────────────────────────────────────────────────────────────────────────
#  Shield Master — Shield Bash gate (the shove reuses execute_shove)
# ─────────────────────────────────────────────────────────────────────────────

def test_can_shield_bash_requires_feat_shield_and_bonus_action():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Fighter", 5, 5)
    _arm(engine, bm, a, [_nonfinesse_blade()])
    engine.begin_turn(bm, a)   # refresh the bonus-action budget
    assert not engine.can_shield_bash(bm, a), "no feat, no shield → no Shield Bash"
    s = engine.get_agent_stats(bm, a); s.add_feat("Shield Master")
    engine.set_agent_stats(bm, a, s)
    assert not engine.can_shield_bash(bm, a), "feat but no shield → no Shield Bash"
    engine.set_agent_weapons(bm, a, [_nonfinesse_blade(), _shield(), rpg.Weapon()])
    engine.begin_turn(bm, a)
    assert engine.can_shield_bash(bm, a), "feat + shield + bonus action → Shield Bash available"
    # Spend the bonus action → no longer available.
    engine.spend_bonus_action(bm, a)
    assert not engine.can_shield_bash(bm, a), "no bonus action left → no Shield Bash"
    print("✅ test_can_shield_bash_requires_feat_shield_and_bonus_action passed")


def main():
    print("Running G3 reaction-feat + shield-foundation tests...\n")
    test_weapon_is_shield_flag()
    test_is_holding_shield_detects_offhand_shield()
    test_calculate_ac_includes_offhand_shield()
    test_war_caster_advantage_holds_concentration_more()
    test_mage_slayer_concentration_breaker_breaks_more()
    test_mage_slayer_only_when_damager_has_feat()
    test_defensive_duelist_eligibility_and_apply()
    test_defensive_duelist_requires_finesse_weapon()
    test_defensive_duelist_requires_feat()
    test_defensive_duelist_auto_path_flips_hit_to_miss()
    test_can_shield_bash_requires_feat_shield_and_bonus_action()
    print("\n" + "=" * 60)
    print("✅ All G3 reaction-feat + shield-foundation tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
