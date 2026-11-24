#!/usr/bin/env python3
"""
Arcane Archer no-attack-roll Arcane Shot options (ARCANE_ARCHER_PLAN.md AA3).

Engine:
  · Piercing Shot: every creature in the 30-ft line makes a DEX save; fail = weapon + 2 dice
    Piercing, success = half; walls don't stop the line; beyond 30 ft is untouched
                                                                     (test_piercing_line, test_piercing_through_wall)
  · Seeking Shot: DEX save; fail = weapon + 2 dice Force, success = half the weapon damage;
    no line of sight needed; limited to the weapon's long range     (test_seeking_*)
  · gates: known option, a use left, once per turn, ranged weapon only (test_gates)
GUI (headless App):
  · the weapon picker lists the known shots per ranged weapon; Seeking Shot picks a creature,
    spends one attack of the Attack action and the use             (test_gui_seeking_spends_an_attack)
  · Piercing Shot aims at a cell; clicking the archer cancels        (test_gui_piercing_aim_and_cancel)
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

AS = rpg.ArcaneShotOption


def _bow(long_ft=600):
    w = rpg.Weapon()
    w.name = "Longbow"
    w.type = rpg.WeaponType.Ranged
    w.proficient = True
    w.range_short_feet = 150
    w.range_long_feet = long_ft
    w.normal_range_ft = 150
    w.long_range_ft = long_ft
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


def _make_archer(engine, bm, idx, options, weapons):
    s = engine.get_agent_stats(bm, idx)
    s.dex = 20
    s.intel = 20
    s.hp_max = s.hp_cur = 50
    s.set_class_level(rpg.CharacterClass.Fighter, 5)
    s.fighter_subclass = rpg.FighterSubclass.ArcaneArcher
    s.initialize_multiclass_resources()
    s.arcane_shot_options = list(options)
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, weapons)


def _target(engine, bm, idx, dex):
    s = engine.get_agent_stats(bm, idx)
    s.str = s.con = s.intel = s.wis = s.cha = 10
    s.dex = dex
    s.hp_max = s.hp_cur = 500
    engine.set_agent_stats(bm, idx, s)


def _setup(options=(AS.Piercing, AS.Seeking), creatures=(), prof=6, long_ft=600):
    """Archer at (2,5) with a longbow and a sword; each creature (col, row, dex)."""
    bm = setup_battle_map()
    engine = setup_combat_engine()
    arc = add_agent_to_battle(engine, bm, create_test_agent("Archer", 2, 5))
    idxs = []
    for i, (c, r, dex) in enumerate(creatures):
        t = add_agent_to_battle(engine, bm, create_test_agent(f"T{i}", c, r))
        _target(engine, bm, t, dex)
        idxs.append(t)
    _make_archer(engine, bm, arc, options, [_bow(long_ft), _sword()])
    s = engine.get_agent_stats(bm, arc)
    s.prof_bonus = prof                    # DC 8 + 5 + 6 = 19
    engine.set_agent_stats(bm, arc, s)
    return bm, engine, arc, idxs


def _uses(engine, bm, arc):
    return engine.get_agent_stats(bm, arc).get_resource("Arcane Shot").current


def _hp(engine, bm, i):
    return engine.get_agent_stats(bm, i).hp_cur


def _new_turn(engine, bm, arc):
    c = engine.get_agent_conditions(bm, arc)
    c.arcane_shot_used = False
    engine.set_agent_conditions(bm, arc, c)


def test_piercing_line():
    # DEX 1 always fails DC 19; T2 sits beyond 30 ft; T3 is off the line.
    bm, engine, arc, (t0, t1, t2, t3) = _setup(creatures=((4, 5, 1), (7, 5, 1), (12, 5, 1), (4, 8, 1)))
    before = _uses(engine, bm, arc)
    res = engine.piercing_shot(bm, arc, 0, 8, 5)
    assert res.valid and res.save_dc == 19, (res.valid, res.save_dc)
    assert sorted(res.targets) == [t0, t1], res.targets
    assert _uses(engine, bm, arc) == before - 1
    assert engine.get_agent_conditions(bm, arc).arcane_shot_used
    for i, dmg, ok in zip(res.targets, res.damage, res.saved):
        assert not ok
        # 1d8 + DEX 5 + 2d6 (L5 die): 2 + 5 + 7 = at least 9 when the dice are low... at least 1+5+2.
        assert dmg >= 1 + 5 + 2 and dmg >= res.die_total + 6, (dmg, res.die_total)
        assert _hp(engine, bm, i) == 500 - dmg
    assert _hp(engine, bm, t2) == 500 and _hp(engine, bm, t3) == 500
    print("✅ test_piercing_line passed")


def _next_shot(engine, bm, arc):
    """A fresh turn with a full Arcane Shot pool (the engine's seed is fixed per setup)."""
    _new_turn(engine, bm, arc)
    s = engine.get_agent_stats(bm, arc)
    r = s.get_resource("Arcane Shot"); r.current = r.max; s.resources["Arcane Shot"] = r
    engine.set_agent_stats(bm, arc, s)


def test_piercing_success_halves():
    # DEX 30 → +10, the save (d20+10 ≥ 19) succeeds 60% of the time; sample until it does.
    bm, engine, arc, (t0,) = _setup(creatures=((4, 5, 30),))
    for _ in range(40):
        _next_shot(engine, bm, arc)
        res = engine.piercing_shot(bm, arc, 0, 8, 5)
        if res.saved[0]:
            assert res.damage[0] <= (8 + 5 + res.die_total) // 2, (res.damage[0], res.die_total)
            assert res.damage[0] >= (1 + 5 + res.die_total) // 2
            print("✅ test_piercing_success_halves passed")
            return
    raise AssertionError("never saved")


def test_piercing_through_wall():
    bm, engine, arc, (t0,) = _setup(creatures=((5, 5, 1),))
    bm.set_terrain_type(rpg.Cell(4, 5), rpg.TerrainType.Wall)   # a wall between archer and target
    res = engine.piercing_shot(bm, arc, 0, 8, 5)
    assert res.valid and res.targets == [t0], res.targets
    print("✅ test_piercing_through_wall passed")


def test_seeking_fail_and_save():
    bm, engine, arc, (t0,) = _setup(creatures=((20, 5, 1),))
    assert engine.seeking_shot_target_valid(bm, arc, 0, t0)
    res = engine.seeking_shot(bm, arc, 0, t0)
    assert res.valid and res.targets == [t0] and not res.saved[0]
    assert res.damage[0] >= 1 + 5 + res.die_total, (res.damage[0], res.die_total)
    bm, engine, arc, (t0,) = _setup(creatures=((20, 5, 30),))
    for _ in range(40):
        _next_shot(engine, bm, arc)
        res = engine.seeking_shot(bm, arc, 0, t0)
        if res.saved[0]:
            assert res.damage[0] <= (8 + 5) // 2, res.damage[0]   # half the weapon damage, no Force
            print("✅ test_seeking_fail_and_save passed")
            return
    raise AssertionError("never saved")


def test_seeking_no_los_but_range():
    bm, engine, arc, (t0,) = _setup(creatures=((10, 5, 1),), long_ft=30)
    for r in range(0, 12):
        bm.set_terrain_type(rpg.Cell(6, r), rpg.TerrainType.Wall)    # a wall the archer can't see past
    assert not bm.has_line_of_sight(bm.placed_agents[arc].origin, 1, bm.placed_agents[t0].origin, 1)
    assert not engine.seeking_shot_target_valid(bm, arc, 0, t0), "40 ft is beyond a 30-ft long range"
    bm, engine, arc, (t0,) = _setup(creatures=((10, 5, 1),))
    for r in range(0, 12):
        bm.set_terrain_type(rpg.Cell(6, r), rpg.TerrainType.Wall)
    assert engine.seeking_shot_target_valid(bm, arc, 0, t0), "no line of sight needed"
    assert engine.seeking_shot(bm, arc, 0, t0).valid
    print("✅ test_seeking_no_los_but_range passed")


def test_gates():
    bm, engine, arc, (t0,) = _setup(options=(AS.Piercing,), creatures=((5, 5, 1),))
    assert engine.can_use_arcane_shot(bm, arc, AS.Piercing)
    assert not engine.can_use_arcane_shot(bm, arc, AS.Seeking), "unknown option"
    assert not engine.seeking_shot(bm, arc, 0, t0).valid
    assert not engine.piercing_shot(bm, arc, 1, 8, 5).valid, "melee weapon"
    assert engine.piercing_shot(bm, arc, 0, 8, 5).valid
    assert not engine.piercing_shot(bm, arc, 0, 8, 5).valid, "once per turn"
    _new_turn(engine, bm, arc)
    s = engine.get_agent_stats(bm, arc)
    r = s.get_resource("Arcane Shot"); r.current = 0; s.resources["Arcane Shot"] = r
    engine.set_agent_stats(bm, arc, s)
    assert not engine.can_use_arcane_shot(bm, arc, AS.Piercing), "no uses left"
    print("✅ test_gates passed")


# ── GUI ───────────────────────────────────────────────────────────────────────

def _gui():
    from test_combat_panel import App, MAP_PATH, SEED, _build_scene, _idx, _goto, _snapshot_baseline
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    _snapshot_baseline(app)
    aria = _goto(app, "Aria")
    _make_archer(app.combat, app.bm, aria, (AS.Piercing, AS.Seeking), [_bow(), _sword()])
    skarn = _idx(app, "Skarn")
    s = app.combat.get_agent_stats(app.bm, skarn)
    s.dex = 1; s.hp_cur = s.hp_max = 300
    app.combat.set_agent_stats(app.bm, skarn, s)
    return app, aria, skarn


def _labels(app):
    live = app.prompts.live
    return [o.label for o in live.options] if live else []


def test_gui_seeking_spends_an_attack():
    app, aria, skarn = _gui()
    app._start_attack("action")
    labels = _labels(app)
    assert "🏹 Piercing Shot (Longbow)" in labels and "🏹 Seeking Shot (Longbow)" in labels, labels
    assert not any("Longsword)" in l for l in labels if l.startswith("🏹")), labels
    budget = app.attack_seq.remaining
    assert app.prompts.choose_label("🏹 Seeking Shot (Longbow)").ok
    assert app._picking("seeking_shot")
    hp = app.combat.get_agent_stats(app.bm, skarn).hp_cur
    assert app.resolve_pick(app.bm.placed_agents[skarn].origin)
    assert not app._picking("seeking_shot")
    assert app.combat.get_agent_stats(app.bm, skarn).hp_cur < hp
    assert app.attack_seq.remaining == budget - 1 and app.action_used
    # Once per turn: the next picker offers no Arcane Shot.
    app._start_attack("action")
    assert not any(l.startswith("🏹") for l in _labels(app)), _labels(app)
    print("✅ test_gui_seeking_spends_an_attack passed")


def test_gui_piercing_aim_and_cancel():
    app, aria, skarn = _gui()
    app._start_attack("action")
    assert app.prompts.choose_label("🏹 Piercing Shot (Longbow)").ok
    assert app._picking("piercing_shot")
    uses = app.combat.get_agent_stats(app.bm, aria).get_resource("Arcane Shot").current
    app.resolve_pick(app.bm.placed_agents[aria].origin)           # the archer's own cell cancels
    assert not app._picking("piercing_shot")
    assert app.combat.get_agent_stats(app.bm, aria).get_resource("Arcane Shot").current == uses
    app._start_attack("action")
    assert app.prompts.choose_label("🏹 Piercing Shot (Longbow)").ok
    hp = app.combat.get_agent_stats(app.bm, skarn).hp_cur
    assert app.resolve_pick(app.bm.placed_agents[skarn].origin)  # aim through Skarn
    assert app.combat.get_agent_stats(app.bm, skarn).hp_cur < hp
    assert app.combat.get_agent_stats(app.bm, aria).get_resource("Arcane Shot").current == uses - 1
    print("✅ test_gui_piercing_aim_and_cancel passed")


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
