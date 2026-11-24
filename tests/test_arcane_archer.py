#!/usr/bin/env python3
"""
Arcane Archer core setup (ARCANE_ARCHER_PLAN.md AA1).

  · FighterSubclass.ArcaneArcher + ArcaneShotOption are bound     (test_enums_bound)
  · "Arcane Shot" uses = max(1, INT mod), Short + Long Rest regen  (test_arcane_shot_resource, …_min_one, …_short_rest)
  · no resource below Fighter 3 or for another subclass            (test_no_resource_below_l3_or_other_subclass)
  · die d6/d8/d10/d12 at L3/10/15/18                               (test_die_size_scales)
  · DC = 8 + INT mod + proficiency                                 (test_save_dc)
  · known count 2/3/4/5/6 at L3/7/10/15/18                         (test_known_count)
  · knows_arcane_shot reads the known list (and the subclass)      (test_knows_arcane_shot)
  · the known list survives the board snapshot and the save dict   (test_snapshot_roundtrip, test_save_dict_roundtrip)
  · the Stats dialog's OK stores, caps and clears the list (D2)    (test_stats_ok_*)
  · the picker caps at the Fighter level's count                   (test_picker_caps)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

AS = rpg.ArcaneShotOption


def _archer(level, intel=16, prof=None, subclass=rpg.FighterSubclass.ArcaneArcher):
    s = rpg.Stats()
    s.intel = intel
    s.set_class_level(rpg.CharacterClass.Fighter, level)
    if prof is not None:
        s.prof_bonus = prof
    s.fighter_subclass = subclass
    s.initialize_multiclass_resources()
    return s


def test_enums_bound():
    assert int(rpg.FighterSubclass.ArcaneArcher) == 5
    names = [n for n in AS.__members__ if n != "NONE"]
    assert names == ["Banishing", "Beguiling", "Bursting", "Grasping", "Piercing",
                     "Seeking", "Shadow"], names
    from actions import ARCANE_SHOT_OPTIONS
    assert [r[0] for r in ARCANE_SHOT_OPTIONS] == [AS.__members__[n] for n in names]
    print("✅ test_enums_bound passed")


def test_arcane_shot_resource():
    s = _archer(3, intel=16)            # +3
    r = s.get_resource("Arcane Shot")
    assert r is not None and r.max == 3 and r.current == 3, (r and (r.current, r.max))
    assert r.short_rest_regen == 3 and r.long_rest_regen == 3
    print("✅ test_arcane_shot_resource passed")


def test_arcane_shot_resource_min_one():
    for intel in (10, 8, 12):           # mod 0, -1, +1 → 1 use
        r = _archer(3, intel=intel).get_resource("Arcane Shot")
        assert r.max == 1, (intel, r.max)
    print("✅ test_arcane_shot_resource_min_one passed")


def test_arcane_shot_short_rest():
    s = _archer(5, intel=14)
    r = s.get_resource("Arcane Shot")
    r.current = 0
    s.resources["Arcane Shot"] = r
    s.restore_resources_short_rest()
    assert s.get_resource("Arcane Shot").current == 2
    print("✅ test_arcane_shot_short_rest passed")


def test_no_resource_below_l3_or_other_subclass():
    assert _archer(2).get_resource("Arcane Shot") is None
    assert _archer(5, subclass=rpg.FighterSubclass.Champion).get_resource("Arcane Shot") is None
    print("✅ test_no_resource_below_l3_or_other_subclass passed")


def test_die_size_scales():
    for lvl, die in ((3, 6), (9, 6), (10, 8), (14, 8), (15, 10), (17, 10), (18, 12), (20, 12)):
        assert _archer(lvl).arcane_shot_die_size == die, (lvl, _archer(lvl).arcane_shot_die_size)
        assert rpg.Stats.arcane_shot_die_for_level(lvl) == die
    print("✅ test_die_size_scales passed")


def test_save_dc():
    s = _archer(5, intel=16, prof=3)
    assert s.arcane_shot_dc == 8 + 3 + 3
    s = _archer(5, intel=9, prof=3)     # floor mod -1
    assert s.arcane_shot_dc == 8 + 3 - 1
    print("✅ test_save_dc passed")


def test_known_count():
    for lvl, n in ((1, 0), (2, 0), (3, 2), (6, 2), (7, 3), (9, 3), (10, 4), (14, 4),
                   (15, 5), (17, 5), (18, 6), (20, 6)):
        assert rpg.Stats.arcane_shot_known_count(lvl) == n, (lvl, n)
    print("✅ test_known_count passed")


def test_knows_arcane_shot():
    s = _archer(3)
    s.arcane_shot_options = [AS.Banishing, AS.Shadow]
    assert s.knows_arcane_shot(AS.Banishing) and s.knows_arcane_shot(AS.Shadow)
    assert not s.knows_arcane_shot(AS.Seeking)
    s.fighter_subclass = rpg.FighterSubclass.Champion
    assert not s.knows_arcane_shot(AS.Banishing), "only an Arcane Archer knows options"
    print("✅ test_knows_arcane_shot passed")


def test_snapshot_roundtrip():
    bm, engine = setup_battle_map(), setup_combat_engine()
    idx = add_agent_to_battle(engine, bm, create_test_agent("Archer", 5, 5))
    s = engine.get_agent_stats(bm, idx)
    s.intel = 16
    s.set_class_level(rpg.CharacterClass.Fighter, 10)
    s.fighter_subclass = rpg.FighterSubclass.ArcaneArcher
    s.initialize_multiclass_resources()
    s.arcane_shot_options = [AS.Bursting, AS.Piercing, AS.Seeking]
    engine.set_agent_stats(bm, idx, s)
    snap = bm.snapshot_json()
    s = engine.get_agent_stats(bm, idx)
    s.arcane_shot_options = []
    s.arcane_shot_die_size = 6
    engine.set_agent_stats(bm, idx, s)
    assert bm.restore_json(snap)
    s = engine.get_agent_stats(bm, idx)
    assert list(s.arcane_shot_options) == [AS.Bursting, AS.Piercing, AS.Seeking]
    assert s.arcane_shot_die_size == 8
    print("✅ test_snapshot_roundtrip passed")


def test_save_dict_roundtrip():
    from agent_loader import dict_to_stats, restore_class_resources
    s = dict_to_stats({"intel": 14, "arcane_shot_options": [int(AS.Grasping), int(AS.Beguiling)]})
    assert list(s.arcane_shot_options) == [AS.Grasping, AS.Beguiling]
    restore_class_resources(s, {"agent_class_levels": {"Fighter": 15},
                                "agent_fighter_subclass": "ArcaneArcher"}, rpg)
    assert s.fighter_subclass == rpg.FighterSubclass.ArcaneArcher
    assert s.get_resource("Arcane Shot").max == 2 and s.arcane_shot_die_size == 10
    assert list(s.arcane_shot_options) == [AS.Grasping, AS.Beguiling], "restore keeps the list"
    print("✅ test_save_dict_roundtrip passed")


# ── Stats dialog OK path ─────────────────────────────────────────────────────

def _app_and_ok():
    from main import App
    from test_combat_panel import MAP_PATH, SEED, _build_scene, _idx
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    aria = _idx(app, "Aria")

    class _V:
        def __init__(self, value):
            self.value = value

    def ok(level, subclass, **kw):
        st = app.combat.get_agent_stats(app.bm, aria)
        steppers = {k: _V(getattr(st, k)) for k in
                    ("str", "dex", "con", "intel", "wis", "cha", "hp_cur", "hp_max", "base_ac",
                     "speed_walk", "speed_swim", "speed_fly", "speed_burrow", "prof_bonus",
                     "num_attacks")}
        steppers["intel"] = _V(16)
        app._on_stats_ok(aria, steppers, {}, "Fighter", level, None,
                         class_levels={"Fighter": level}, subclasses={"Fighter": subclass}, **kw)
        return app.combat.get_agent_stats(app.bm, aria)
    return ok


def test_stats_ok_stores_and_caps():
    ok = _app_and_ok()
    picks = [int(AS.Banishing), int(AS.Shadow), int(AS.Seeking)]
    s = ok(5, "ArcaneArcher", arcane_shot_options=picks)
    assert s.fighter_subclass == rpg.FighterSubclass.ArcaneArcher
    assert list(s.arcane_shot_options) == [AS.Banishing, AS.Shadow], "capped at 2 for L5"
    assert s.get_resource("Arcane Shot").max == 3
    s = ok(7, "ArcaneArcher", arcane_shot_options=picks)
    assert list(s.arcane_shot_options) == [AS.Banishing, AS.Shadow, AS.Seeking]
    s = ok(7, "ArcaneArcher")             # a caller that doesn't pass the list: kept
    assert len(s.arcane_shot_options) == 3
    s = ok(7, "Champion", arcane_shot_options=picks)
    assert list(s.arcane_shot_options) == [], "cleared off-subclass"
    assert s.get_resource("Arcane Shot") is None
    print("✅ test_stats_ok_stores_and_caps passed")


def test_picker_caps():
    import pygame
    pygame.init()
    pygame.display.set_mode((1200, 800))
    from dialogs import ArcaneShotDialog, StatsDialog
    assert "ArcaneArcher" in StatsDialog._get_available_subclasses(None, "Fighter")
    got = []
    d = ArcaneShotDialog()
    d.show(got.append, [], 7)
    assert d._cap == 3 and d._tag(None) == "d6"
    for v in (AS.Banishing, AS.Beguiling, AS.Bursting):
        assert d._row_enabled(v)
        d._selected.add(int(v))
    assert not d._row_enabled(AS.Shadow), "cap reached"
    assert d._row_enabled(AS.Banishing), "a pick can always be removed (the swap)"
    d._commit_and_dismiss()
    assert got == [sorted([int(AS.Banishing), int(AS.Beguiling), int(AS.Bursting)])]
    d.show(got.append, [], 2)
    assert d._cap == 0 and not d._row_enabled(AS.Shadow), "nothing below L3"
    d.show(got.append, [], 18)
    assert d._cap == 6 and d._tag(None) == "d12"
    print("✅ test_picker_caps passed")


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
