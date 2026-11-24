#!/usr/bin/env python3
"""
Arcane Archer on-hit Arcane Shot options (ARCANE_ARCHER_PLAN.md AA2).

  · a ranged hit flags arcane_shot_available; a melee hit doesn't     (test_flag_on_ranged_hit_only)
  · one use spent, once per turn, only KNOWN on-hit options           (test_spend_once_per_turn, test_unknown_option_refused)
  · Banishing: psychic 1 die, CHA save → banished to end of next turn (test_banishing)
  · Beguiling: psychic 2 dice, WIS save → Charmed by the archer,
    gone at the archer's next turn start, broken by the archer
    attacking it (D6)                                                  (test_beguiling_*)
  · Bursting: force 2 dice to target + each creature within 10 ft     (test_bursting_splash)
  · Grasping: slashing, STR save → Restrained 1 min; STR check escape;
    a 2nd Grasping Shot ends the first (D5)                           (test_grasping_*)
  · Shadow: psychic 1 die, WIS save → Blinded to end of its next turn (test_shadow)
  · a successful save lands nothing; Condition Immunity respected     (test_save_success_no_condition, test_condition_immunity)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

AS = rpg.ArcaneShotOption


def _bow():
    w = rpg.Weapon()
    w.name = "Longbow"
    w.type = rpg.WeaponType.Ranged
    w.proficient = True
    w.range_short_feet = 150
    w.range_long_feet = 600
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Piercing
    roll.num_dice = 1
    roll.die_size = 8
    w.physical_damage_types = [roll]
    return w


def _sword():
    w = rpg.Weapon()
    w.name = "Longsword"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Slashing
    roll.num_dice = 1
    roll.die_size = 8
    w.physical_damage_types = [roll]
    return w


def _target(engine, bm, idx, save_score=1, hp=500):
    s = engine.get_agent_stats(bm, idx)
    s.str = s.dex = s.con = s.intel = s.wis = s.cha = save_score
    s.hp_max = s.hp_cur = hp
    s.base_ac = 1
    engine.set_agent_stats(bm, idx, s)


def _setup(options, intel=20, prof=6, save_score=1, tgt_col=6, extra=()):
    """Archer at (2,5) with a longbow and a sword; target at (tgt_col,5); extra creatures at the
    given (col,row) cells. INT 20 + PB 6 → DC 19, which a save score of 1 can never reach."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    arc = add_agent_to_battle(engine, bm, create_test_agent("Archer", 2, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", tgt_col, 5))
    others = [add_agent_to_battle(engine, bm, create_test_agent(f"X{i}", c, r))
              for i, (c, r) in enumerate(extra)]
    s = engine.get_agent_stats(bm, arc)
    s.dex = 20
    s.intel = intel
    s.hp_max = s.hp_cur = 50
    s.set_class_level(rpg.CharacterClass.Fighter, 5)
    s.fighter_subclass = rpg.FighterSubclass.ArcaneArcher
    s.initialize_multiclass_resources()
    s.prof_bonus = prof
    s.arcane_shot_options = list(options)
    engine.set_agent_stats(bm, arc, s)
    engine.set_agent_weapons(bm, arc, [_bow(), _sword()])
    _target(engine, bm, tgt, save_score)
    for o in others:
        _target(engine, bm, o, 10, hp=500)
    return bm, engine, arc, tgt, others


def _hit(engine, bm, arc, tgt, weapon=0):
    """Attack until it hits (a nat 1 can miss AC 1); returns the hit AttackResult."""
    for _ in range(50):
        r = engine.execute_action(bm, rpg.Attack(arc, tgt, weapon))
        if r.hit:
            return r
    raise AssertionError("never hit")


def _uses(engine, bm, arc):
    return engine.get_agent_stats(bm, arc).get_resource("Arcane Shot").current


def _conds(engine, idx, name):
    return [c for c in engine.active_agent_conditions if c.agent_idx == idx and c.condition_name == name]


def _new_turn(engine, bm, arc):
    c = engine.get_agent_conditions(bm, arc)
    c.arcane_shot_used = False
    engine.set_agent_conditions(bm, arc, c)


def test_flag_on_ranged_hit_only():
    bm, engine, arc, tgt, _ = _setup([AS.Banishing, AS.Shadow], tgt_col=3)
    _hit(engine, bm, arc, tgt, weapon=1)
    assert not engine.get_agent_conditions(bm, arc).arcane_shot_available, "melee hit must not qualify"
    _hit(engine, bm, arc, tgt, weapon=0)
    assert engine.get_agent_conditions(bm, arc).arcane_shot_available, "ranged hit qualifies"
    # A skipped offer doesn't linger onto the next (melee) hit.
    _hit(engine, bm, arc, tgt, weapon=1)
    assert not engine.get_agent_conditions(bm, arc).arcane_shot_available
    # Only Piercing/Seeking known → no on-hit option, no flag.
    bm, engine, arc, tgt, _ = _setup([AS.Piercing, AS.Seeking])
    _hit(engine, bm, arc, tgt)
    assert not engine.get_agent_conditions(bm, arc).arcane_shot_available
    print("✅ test_flag_on_ranged_hit_only passed")


def test_spend_once_per_turn():
    bm, engine, arc, tgt, _ = _setup([AS.Shadow, AS.Grasping])
    before = _uses(engine, bm, arc)
    r = _hit(engine, bm, arc, tgt)
    res = engine.apply_arcane_shot(bm, arc, tgt, AS.Shadow, r)
    assert res.valid and _uses(engine, bm, arc) == before - 1
    c = engine.get_agent_conditions(bm, arc)
    assert c.arcane_shot_used and not c.arcane_shot_available
    r2 = _hit(engine, bm, arc, tgt)
    assert not engine.get_agent_conditions(bm, arc).arcane_shot_available, "once per turn"
    assert not engine.apply_arcane_shot(bm, arc, tgt, AS.Grasping, r2).valid
    assert _uses(engine, bm, arc) == before - 1
    # No uses left → no flag.
    _new_turn(engine, bm, arc)
    s = engine.get_agent_stats(bm, arc)
    res_ = s.get_resource("Arcane Shot"); res_.current = 0; s.resources["Arcane Shot"] = res_
    engine.set_agent_stats(bm, arc, s)
    _hit(engine, bm, arc, tgt)
    assert not engine.get_agent_conditions(bm, arc).arcane_shot_available
    print("✅ test_spend_once_per_turn passed")


def test_unknown_option_refused():
    bm, engine, arc, tgt, _ = _setup([AS.Shadow, AS.Grasping])
    r = _hit(engine, bm, arc, tgt)
    before = _uses(engine, bm, arc)
    assert not engine.apply_arcane_shot(bm, arc, tgt, AS.Banishing, r).valid
    assert not engine.apply_arcane_shot(bm, arc, tgt, AS.Piercing, r).valid, "not an on-hit option"
    assert _uses(engine, bm, arc) == before
    print("✅ test_unknown_option_refused passed")


def test_banishing():
    bm, engine, arc, tgt, _ = _setup([AS.Banishing, AS.Shadow])
    r = _hit(engine, bm, arc, tgt)
    hp0 = engine.get_agent_stats(bm, tgt).hp_cur
    dmg0 = r.total_damage
    res = engine.apply_arcane_shot(bm, arc, tgt, AS.Banishing, r)
    assert res.valid and res.save_dc == 19 and res.condition_applied
    assert 1 <= res.die_total <= 6 and res.damage == res.die_total
    assert r.total_damage == dmg0 + res.damage
    assert engine.get_agent_stats(bm, tgt).hp_cur == hp0 - res.damage
    assert rpg.MagicDamage.Psychic in list(r.magic_damage_types)
    c = engine.get_agent_conditions(bm, tgt)
    assert c.untouchable and c.incapacitated
    engine.tick_agent_conditions_for_caster(bm, tgt)    # its next turn begins
    assert engine.get_agent_conditions(bm, tgt).untouchable, "lasts through its next turn"
    engine.tick_agent_conditions_for_caster(bm, tgt)    # the turn after
    c = engine.get_agent_conditions(bm, tgt)
    assert not c.untouchable and not c.incapacitated
    print("✅ test_banishing passed")


def test_beguiling_charm_and_expiry():
    bm, engine, arc, tgt, _ = _setup([AS.Beguiling, AS.Shadow])
    r = _hit(engine, bm, arc, tgt)
    res = engine.apply_arcane_shot(bm, arc, tgt, AS.Beguiling, r)
    assert res.valid and res.condition_applied and 2 <= res.die_total <= 12
    c = engine.get_agent_conditions(bm, tgt)
    assert c.charmed and c.charmed_by == arc
    assert _conds(engine, tgt, "Charmed")[0].arcane_shot == int(AS.Beguiling)
    engine.tick_agent_conditions_for_caster(bm, tgt)    # the target's own turn: still charmed
    assert engine.get_agent_conditions(bm, tgt).charmed
    engine.tick_agent_conditions_for_caster(bm, arc)    # the archer's next turn starts
    assert not engine.get_agent_conditions(bm, tgt).charmed
    print("✅ test_beguiling_charm_and_expiry passed")


def test_beguiling_broken_by_archer_attack():
    bm, engine, arc, tgt, _ = _setup([AS.Beguiling, AS.Shadow])
    r = _hit(engine, bm, arc, tgt)
    assert engine.apply_arcane_shot(bm, arc, tgt, AS.Beguiling, r).condition_applied
    assert engine.get_agent_conditions(bm, tgt).charmed
    engine.execute_action(bm, rpg.Attack(arc, tgt, 0))   # hit or miss: attacking it breaks the charm
    assert not engine.get_agent_conditions(bm, tgt).charmed
    assert not _conds(engine, tgt, "Charmed")
    print("✅ test_beguiling_broken_by_archer_attack passed")


def test_bursting_splash():
    # Target at (6,5); X0 at (8,5) is 10 ft from it, X1 at (9,5) is 15 ft.
    bm, engine, arc, tgt, (near, far) = _setup([AS.Bursting, AS.Shadow], extra=((8, 5), (9, 5)))
    r = _hit(engine, bm, arc, tgt)
    hp_near = engine.get_agent_stats(bm, near).hp_cur
    hp_far = engine.get_agent_stats(bm, far).hp_cur
    res = engine.apply_arcane_shot(bm, arc, tgt, AS.Bursting, r)
    assert res.valid and res.save_dc == 0 and 2 <= res.die_total <= 12
    assert rpg.MagicDamage.Force in list(r.magic_damage_types)
    assert list(res.splash_targets) == [near], list(res.splash_targets)
    assert engine.get_agent_stats(bm, near).hp_cur == hp_near - res.die_total
    assert engine.get_agent_stats(bm, far).hp_cur == hp_far
    print("✅ test_bursting_splash passed")


def test_grasping_restrains_and_reuse_ends_first():
    bm, engine, arc, tgt, (other,) = _setup([AS.Grasping, AS.Shadow], extra=((6, 8),))
    _target(engine, bm, other, 1)
    r = _hit(engine, bm, arc, tgt)
    res = engine.apply_arcane_shot(bm, arc, tgt, AS.Grasping, r)
    assert res.valid and res.condition_applied
    assert rpg.PhysicalDamage.Slashing in list(r.physical_damage_types)
    assert engine.get_agent_conditions(bm, tgt).restrained and engine.held_by_grasping_shot(tgt)
    cond = _conds(engine, tgt, "Restrained")[0]
    assert cond.turns_remaining == 10 and cond.save_dc == 19 and cond.caster_idx == arc
    # A second Grasping Shot (next turn, another creature) ends the first.
    _new_turn(engine, bm, arc)
    r2 = _hit(engine, bm, arc, other)
    assert engine.apply_arcane_shot(bm, arc, other, AS.Grasping, r2).condition_applied
    assert engine.get_agent_conditions(bm, other).restrained
    assert not engine.get_agent_conditions(bm, tgt).restrained and not engine.held_by_grasping_shot(tgt)
    print("✅ test_grasping_restrains_and_reuse_ends_first passed")


def test_grasping_escape():
    bm, engine, arc, tgt, (helper, far) = _setup([AS.Grasping, AS.Shadow], extra=((7, 5), (11, 5)))
    r = _hit(engine, bm, arc, tgt)
    assert engine.apply_arcane_shot(bm, arc, tgt, AS.Grasping, r).condition_applied
    assert not engine.escape_grasping_shot(bm, far, tgt).valid, "out of reach"
    assert not engine.escape_grasping_shot(bm, helper, helper).valid, "the helper isn't held"
    s = engine.get_agent_stats(bm, helper); s.str = 30; engine.set_agent_stats(bm, helper, s)
    freed = False
    for _ in range(60):
        e = engine.escape_grasping_shot(bm, helper, tgt)
        assert e.valid and e.dc == 19 and e.total == e.d20 + 10
        if e.freed:
            freed = True
            break
        assert engine.get_agent_conditions(bm, tgt).restrained, "a failed check leaves it Restrained"
    assert freed
    assert not engine.get_agent_conditions(bm, tgt).restrained and not engine.held_by_grasping_shot(tgt)
    print("✅ test_grasping_escape passed")


def test_shadow():
    bm, engine, arc, tgt, _ = _setup([AS.Shadow, AS.Grasping])
    r = _hit(engine, bm, arc, tgt)
    res = engine.apply_arcane_shot(bm, arc, tgt, AS.Shadow, r)
    assert res.valid and res.condition_applied
    assert engine.get_agent_conditions(bm, tgt).blinded
    engine.tick_agent_conditions_for_caster(bm, arc)
    engine.tick_agent_conditions_for_caster(bm, tgt)
    assert engine.get_agent_conditions(bm, tgt).blinded, "through the end of its next turn"
    engine.tick_agent_conditions_for_caster(bm, tgt)
    assert not engine.get_agent_conditions(bm, tgt).blinded
    print("✅ test_shadow passed")


def test_save_success_no_condition():
    # INT 1, PB 2 → DC 5; a 30 in every save score always beats it.
    bm, engine, arc, tgt, _ = _setup([AS.Shadow, AS.Grasping], intel=1, prof=2, save_score=30)
    r = _hit(engine, bm, arc, tgt)
    res = engine.apply_arcane_shot(bm, arc, tgt, AS.Shadow, r)
    assert res.valid and res.save_dc == 5 and not res.condition_applied
    assert not engine.get_agent_conditions(bm, tgt).blinded
    assert res.damage == res.die_total, "the damage lands on a save anyway"
    print("✅ test_save_success_no_condition passed")


def test_condition_immunity():
    bm, engine, arc, tgt, _ = _setup([AS.Beguiling, AS.Shadow])
    s = engine.get_agent_stats(bm, tgt); s.condition_immunities = ["Charmed"]; engine.set_agent_stats(bm, tgt, s)
    r = _hit(engine, bm, arc, tgt)
    res = engine.apply_arcane_shot(bm, arc, tgt, AS.Beguiling, r)
    assert res.valid and not res.condition_applied
    assert not engine.get_agent_conditions(bm, tgt).charmed
    print("✅ test_condition_immunity passed")


class _StubApp:
    """Just enough of App for menus.riders.offer_arcane_shot."""
    def __init__(self, bm, engine):
        self.bm, self.combat = bm, engine
        self.log, self.asked, self.overlay = [], None, 0
    def _ask_actor(self, idx, slot, title, options): self.asked = (title, options)
    def _combat_log_add(self, m): self.log.append(m)
    def _flush_combat_log(self): pass
    def _drop_concentration_for_agent(self, i): pass
    def _sync_spell_effect_cache(self): pass
    def _update_attack_overlay(self): self.overlay += 1
    def _spawn_flash(self, *a): pass
    def _get_damage_type_names(self, m, p): return ["x"]
    def _damage_breakdown_str(self, r): return ""


def test_prompt_offers_known_on_hit_options():
    from menus import riders
    bm, engine, arc, tgt, _ = _setup([AS.Grasping, AS.Shadow, AS.Piercing])
    r = _hit(engine, bm, arc, tgt)
    app = _StubApp(bm, engine)
    riders.offer_arcane_shot(app, arc, tgt, "Archer", "Target", r, "HIT")
    title, options = app.asked
    labels = [o[0] for o in options]
    assert "Arcane Shot (5 left)" in title, title       # INT 20 → 5 uses
    assert [l.split(" —")[0] for l in labels] == ["Grasping Shot", "Shadow Shot", "Skip Arcane Shot"], labels
    options[1][1]()                                     # Shadow Shot
    assert engine.get_agent_conditions(bm, tgt).blinded and app.overlay == 1
    assert any("Shadow Shot: save" in m for m in app.log), app.log
    print("✅ test_prompt_offers_known_on_hit_options passed")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
