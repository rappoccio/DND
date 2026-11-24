#!/usr/bin/env python3
"""
Arcane Archer Curving Shot (L7) and Ever-Ready Shot (L10) (ARCANE_ARCHER_PLAN.md AA4).

  · a ranged miss flags curving_shot_available at Fighter 7+, not at 6,
    not on a melee miss, not without a Bonus Action                    (test_flag_*)
  · targets: seen, in range, within 60 ft of the original target,
    never the archer or the original target                            (test_targets)
  · the reroll spends the Bonus Action, clears the offer, attacks the
    new creature; an illegal target or no offer is refused             (test_apply_*)
  · a rerolled hit can then take an on-hit Arcane Shot                 (test_reroll_hit_offers_arcane_shot)
  · the GUI prompt lists the legal creatures and resolves the pick     (test_prompt_*)
  · Ever-Ready Shot: L10+ with no uses regains one; not with a use
    left, not below L10 (D8)                                           (test_ever_ready_*)
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


def _setup(level=7, tgt_col=10, near_col=14, far_col=24, options=(AS.Banishing, AS.Shadow)):
    """A 36×36 open grid. Archer (2,5); Target (tgt_col,5) at AC 100; Near (near_col,5) at AC 1,
    within 60 ft of Target; Far (far_col,5) more than 60 ft from Target (but in bow range)."""
    bm = setup_battle_map()
    bm.set_uniform_grid(bm.cell_pixel_size // 3, 0, 0)
    bm.detect_walls()
    engine = setup_combat_engine()
    arc = add_agent_to_battle(engine, bm, create_test_agent("Archer", 2, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Target", tgt_col, 5))
    near = add_agent_to_battle(engine, bm, create_test_agent("Near", near_col, 5))
    far = add_agent_to_battle(engine, bm, create_test_agent("Far", far_col, 5))
    s = engine.get_agent_stats(bm, arc)
    s.dex = 20
    s.intel = 16
    s.hp_max = s.hp_cur = 50
    s.set_class_level(rpg.CharacterClass.Fighter, level)
    s.fighter_subclass = rpg.FighterSubclass.ArcaneArcher
    s.initialize_multiclass_resources()
    s.arcane_shot_options = list(options)
    s.bonus_actions_max = s.bonus_actions_remaining = 1
    engine.set_agent_stats(bm, arc, s)
    engine.set_agent_weapons(bm, arc, [_bow(), _sword()])
    for idx, ac in ((tgt, 100), (near, 1), (far, 1)):
        t = engine.get_agent_stats(bm, idx)
        t.hp_max = t.hp_cur = 500
        t.base_ac = ac
        t.wis = t.cha = 1
        engine.set_agent_stats(bm, idx, t)
    return bm, engine, arc, tgt, near, far


def _miss(engine, bm, arc, tgt, weapon=0):
    """Attack until it misses (a nat 20 hits even AC 100); returns the miss AttackResult."""
    for _ in range(50):
        r = engine.execute_action(bm, rpg.Attack(arc, tgt, weapon))
        if r.valid and not r.hit:
            return r
    raise AssertionError("never missed")


def _flag(engine, bm, arc):
    return engine.get_agent_conditions(bm, arc).curving_shot_available


def _bonus(engine, bm, arc):
    return engine.get_agent_stats(bm, arc).bonus_actions_remaining


def _rearm(engine, bm, arc):
    s = engine.get_agent_stats(bm, arc)
    s.bonus_actions_remaining = 1
    engine.set_agent_stats(bm, arc, s)
    c = engine.get_agent_conditions(bm, arc)
    c.curving_shot_available = True
    c.arcane_shot_used = False
    engine.set_agent_conditions(bm, arc, c)


def test_flag_on_ranged_miss_at_l7():
    bm, engine, arc, tgt, near, far = _setup(level=7)
    _miss(engine, bm, arc, tgt)
    assert _flag(engine, bm, arc), "a L7 ranged miss offers Curving Shot"
    print("✅ test_flag_on_ranged_miss_at_l7 passed")


def test_flag_not_below_l7():
    bm, engine, arc, tgt, near, far = _setup(level=6)
    _miss(engine, bm, arc, tgt)
    assert not _flag(engine, bm, arc)
    print("✅ test_flag_not_below_l7 passed")


def test_flag_not_on_melee_miss():
    bm, engine, arc, tgt, near, far = _setup(level=7, tgt_col=3)
    _miss(engine, bm, arc, tgt, weapon=1)
    assert not _flag(engine, bm, arc), "a melee miss must not qualify"
    print("✅ test_flag_not_on_melee_miss passed")


def test_flag_needs_bonus_action():
    bm, engine, arc, tgt, near, far = _setup(level=7)
    s = engine.get_agent_stats(bm, arc)
    s.bonus_actions_remaining = 0
    engine.set_agent_stats(bm, arc, s)
    _miss(engine, bm, arc, tgt)
    assert not _flag(engine, bm, arc)
    print("✅ test_flag_needs_bonus_action passed")


def test_flag_cleared_by_next_attack():
    bm, engine, arc, tgt, near, far = _setup(level=7)
    _miss(engine, bm, arc, tgt)
    assert _flag(engine, bm, arc)
    for _ in range(50):                       # a hit on Near clears the skipped offer
        if engine.execute_action(bm, rpg.Attack(arc, near, 0)).hit:
            break
    assert not _flag(engine, bm, arc)
    print("✅ test_flag_cleared_by_next_attack passed")


def test_targets():
    bm, engine, arc, tgt, near, far = _setup(level=7)
    got = list(engine.curving_shot_targets(bm, arc, tgt, 0))
    assert got == [near], got
    assert list(engine.curving_shot_targets(bm, arc, tgt, 1)) == [], "melee weapon: none"
    print("✅ test_targets passed")


def test_apply_spends_bonus_and_attacks_new_target():
    bm, engine, arc, tgt, near, far = _setup(level=7)
    _miss(engine, bm, arc, tgt)
    hp0 = engine.get_agent_stats(bm, near).hp_cur
    r = engine.apply_curving_shot(bm, arc, tgt, near, 0)
    assert r.valid, "reroll resolves"
    assert _bonus(engine, bm, arc) == 0, "Bonus Action spent"
    assert not _flag(engine, bm, arc), "offer gone (no second Curving Shot on a miss)"
    if r.hit:
        assert engine.get_agent_stats(bm, near).hp_cur == hp0 - r.total_damage
    print("✅ test_apply_spends_bonus_and_attacks_new_target passed")


def test_apply_refuses_illegal():
    bm, engine, arc, tgt, near, far = _setup(level=7)
    assert not engine.apply_curving_shot(bm, arc, tgt, near, 0).valid, "no offer → refused"
    _miss(engine, bm, arc, tgt)
    assert not engine.apply_curving_shot(bm, arc, tgt, far, 0).valid, "beyond 60 ft of the target"
    assert not engine.apply_curving_shot(bm, arc, tgt, tgt, 0).valid, "same creature"
    assert _bonus(engine, bm, arc) == 1 and _flag(engine, bm, arc), "a refusal spends nothing"
    print("✅ test_apply_refuses_illegal passed")


def test_reroll_hit_offers_arcane_shot():
    bm, engine, arc, tgt, near, far = _setup(level=7)
    _miss(engine, bm, arc, tgt)
    for _ in range(50):
        r = engine.apply_curving_shot(bm, arc, tgt, near, 0)
        if r.hit:
            break
        _rearm(engine, bm, arc)
    assert r.hit
    assert engine.get_agent_conditions(bm, arc).arcane_shot_available
    res = engine.apply_arcane_shot(bm, arc, near, AS.Shadow, r)
    assert res.valid
    print("✅ test_reroll_hit_offers_arcane_shot passed")


class _FakeApp:
    """Just enough of App for menus.riders.offer_curving_shot."""
    def __init__(self, bm, engine):
        self.bm, self.combat = bm, engine
        self.log, self.asked, self.continued = [], [], 0

    def _combat_log_add(self, m):
        self.log.append(m)

    def _ask_actor(self, idx, kind, title, options, **kw):
        self.asked.append((title, options))

    def _continue_attack_sequence_after_rider(self, idx):
        self.continued += 1

    def _get_damage_type_names(self, *a):
        return []

    def _damage_breakdown_str(self, r):
        return ""

    def __getattr__(self, name):                 # flush / sync / overlay / flash / concentration
        return lambda *a, **k: None


def _prompt(engine, bm, arc, tgt):
    from menus import riders
    app = _FakeApp(bm, engine)
    action = rpg.Attack(arc, tgt, 0)
    r = _miss(engine, bm, arc, tgt)
    riders.offer_curving_shot(app, action, arc, tgt, "Archer", "Target", r, "Archer→Target: miss")
    return app


def test_prompt_lists_legal_targets_and_resolves():
    bm, engine, arc, tgt, near, far = _setup(level=7)
    app = _prompt(engine, bm, arc, tgt)
    title, options = app.asked[-1]
    labels = [o[0] for o in options]
    assert labels == ["Curve to Near (Bonus Action)", "Skip Curving Shot"], labels
    options[0][1]()
    assert _bonus(engine, bm, arc) == 0
    assert any(m.startswith("Curving Shot → Archer→Near") for m in app.log) or app.asked[-1][0] != title, app.log
    print("✅ test_prompt_lists_legal_targets_and_resolves passed")


def test_prompt_skip_clears_offer():
    bm, engine, arc, tgt, near, far = _setup(level=7)
    app = _prompt(engine, bm, arc, tgt)
    app.asked[-1][1][-1][1]()
    assert not _flag(engine, bm, arc) and _bonus(engine, bm, arc) == 1
    assert app.continued == 1 and app.log == ["Archer→Target: miss"]
    print("✅ test_prompt_skip_clears_offer passed")


def _uses_after_ever_ready(level, start):
    bm, engine, arc, tgt, near, far = _setup(level=level)
    s = engine.get_agent_stats(bm, arc)
    r = s.get_resource("Arcane Shot")
    r.current = start
    s.resources["Arcane Shot"] = r
    engine.set_agent_stats(bm, arc, s)
    engine.apply_ever_ready_shot(bm)
    return engine.get_agent_stats(bm, arc).get_resource("Arcane Shot").current


def test_ever_ready_regains_one_when_empty():
    assert _uses_after_ever_ready(10, 0) == 1
    print("✅ test_ever_ready_regains_one_when_empty passed")


def test_ever_ready_not_with_use_left():
    assert _uses_after_ever_ready(10, 1) == 1
    print("✅ test_ever_ready_not_with_use_left passed")


def test_ever_ready_not_below_l10():
    assert _uses_after_ever_ready(9, 0) == 0
    print("✅ test_ever_ready_not_below_l10 passed")


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
