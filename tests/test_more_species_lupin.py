"""More species, MS4: Lupin Howl and Feral Pounce (plans/MORE_SPECIES_PLAN.md D8, D9).

Covered: Howl's DC is 8 + CON mod + PB; every hostile within 15 ft that fails its WIS save is
Howled (howled_by), while an ally, a foe out of range and a Deafened foe are not; a Howled
creature has Disadvantage on attack rolls and saves until the start of the Lupin's next turn;
PB uses, refused when spent, back on a Long Rest; a non-Lupin can't Howl (D8). Feral Pounce:
a Lupin's Unarmed Strike deals Slashing (a non-Lupin's stays Bludgeoning); an Unarmed hit in the
Attack action offers a Shove, once per turn, which Prones the target through the shove contest;
a weapon hit, a Bonus Action strike and an Opportunity Attack don't offer it (D9).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, create_test_agent, add_agent_to_battle


def _pc(engine, bm, idx, species="Lupin", con=30, str_=10):
    s = engine.get_agent_stats(bm, idx)
    s.add_class_level(rpg.CharacterClass.Fighter, 1)
    s.char_level = 1
    s.prof_bonus = 2
    s.is_npc = False
    s.con = con
    s.str = str_
    if species:
        s.set_species(species, "")
    engine.set_agent_stats(bm, idx, s)


def _foe(engine, bm, name, col, row, wis=1, str_=1, dex=1):
    t = add_agent_to_battle(engine, bm, create_test_agent(name, col, row), hp=500)
    bm.set_agent_faction(t, 1)
    s = engine.get_agent_stats(bm, t)
    s.wis, s.str, s.dex = wis, str_, dex
    engine.set_agent_stats(bm, t, s)
    return t


def _howl_scene(species="Lupin"):
    """Lupin at (4,5); foes 1 and 3 cells east (in 15 ft) and 4 cells west (20 ft); an ally."""
    bm = setup_battle_map()
    engine = rpg.CombatEngine(11)
    a = add_agent_to_battle(engine, bm, create_test_agent("Lupin", 4, 5), hp=80)
    _pc(engine, bm, a, species)
    near = _foe(engine, bm, "Near", 5, 5)
    edge = _foe(engine, bm, "Edge", 7, 5)
    far = _foe(engine, bm, "Far", 0, 5)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 4, 6), hp=50)
    bm.set_agent_faction(a, 2)
    bm.set_agent_faction(ally, 2)
    return bm, engine, a, near, edge, far, ally


def _howled(engine, bm, i):
    return engine.get_agent_conditions(bm, i).howled_by


# ── Howl (D8) ─────────────────────────────────────────────────────────────────

def test_howl_dc_and_targets():
    bm, engine, a, near, edge, far, ally = _howl_scene()
    assert engine.howl_dc(bm, a) == 8 + 10 + 2, "8 + CON mod + PB"
    assert engine.can_howl(bm, a)
    # WIS 1 vs DC 20: a failure every time.
    assert engine.use_howl(bm, a) == 2
    assert _howled(engine, bm, near) == a and _howled(engine, bm, edge) == a
    assert _howled(engine, bm, far) == -1, "20 ft is out of range"
    assert _howled(engine, bm, ally) == -1, "allies are not targets"
    print("✅ test_howl_dc_and_targets passed")


def test_howl_skips_deafened_and_saves():
    bm, engine, a, near, edge, far, ally = _howl_scene()
    c = engine.get_agent_conditions(bm, near)
    c.deafened = True
    engine.set_agent_conditions(bm, near, c)
    s = engine.get_agent_stats(bm, edge)
    s.wis = 30                          # +10: 11+ on the d20 saves vs DC 20 — make it certain
    engine.set_agent_stats(bm, edge, s)
    ls = engine.get_agent_stats(bm, a)
    ls.con = 1                          # DC 8 - 5 + 2 = 5: WIS 30 always saves
    engine.set_agent_stats(bm, a, ls)
    assert engine.use_howl(bm, a) == 0
    assert _howled(engine, bm, near) == -1, "a Deafened creature can't hear the Howl"
    assert _howled(engine, bm, edge) == -1, "a success shrugs it off"
    print("✅ test_howl_skips_deafened_and_saves passed")


def test_howled_disadvantage_and_duration():
    bm, engine, a, near, edge, far, ally = _howl_scene()
    engine.use_howl(bm, a)
    assert engine.curse_save_disadvantage(bm, near, rpg.SaveAbility.Dexterity)
    assert not engine.curse_save_disadvantage(bm, far, rpg.SaveAbility.Dexterity)
    r = engine.execute_action(bm, rpg.Attack(near, a, 0))
    assert r.valid and r.disadvantage, "a Howled creature attacks at Disadvantage"
    engine.begin_turn(bm, near)
    assert _howled(engine, bm, near) == a, "lasts through other turns"
    engine.begin_turn(bm, a)
    assert _howled(engine, bm, near) == -1, "ends at the start of the Lupin's next turn"
    assert not engine.curse_save_disadvantage(bm, near, rpg.SaveAbility.Dexterity)
    print("✅ test_howled_disadvantage_and_duration passed")


def test_howl_uses():
    bm, engine, a, *_ = _howl_scene()
    assert engine.use_howl(bm, a) >= 0 and engine.use_howl(bm, a) >= 0
    assert engine.get_agent_stats(bm, a).howl_remaining() == 0
    assert not engine.can_howl(bm, a) and engine.use_howl(bm, a) == -1, "PB uses only"
    s = engine.get_agent_stats(bm, a)
    s.restore_resources_long_rest()
    engine.set_agent_stats(bm, a, s)
    assert engine.get_agent_stats(bm, a).howl_remaining() == 2, "back on a Long Rest"
    bm, engine, h, near, *_ = _howl_scene(species="Human")
    assert not engine.can_howl(bm, h) and engine.use_howl(bm, h) == -1
    assert _howled(engine, bm, near) == -1
    print("✅ test_howl_uses passed")


# ── Feral Pounce (D9) ─────────────────────────────────────────────────────────

def _fist():
    w = rpg.Weapon()
    w.name = "Unarmed"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.proficient = True
    w.bonus_hit = 60                    # only a natural 1 misses
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Bludgeoning
    roll.num_dice = 1
    roll.die_size = 4
    w.physical_damage_types = [roll]
    return w


def _club():
    w = _fist()
    w.name = "Club"
    return w


def _pounce_scene(species="Lupin", weapon=None):
    bm = setup_battle_map()
    engine = rpg.CombatEngine(5)
    a = add_agent_to_battle(engine, bm, create_test_agent("Lupin", 4, 5), hp=80)
    _pc(engine, bm, a, species, con=10, str_=30)   # STR +10 vs a STR/DEX 1 foe: the shove wins
    t = _foe(engine, bm, "Foe", 5, 5)
    engine.set_agent_weapons(bm, a, [weapon or _fist(), rpg.Weapon(), rpg.Weapon()])
    return bm, engine, a, t


def _hit(engine, bm, a, t, slot="", opportunity=False):
    for _ in range(50):
        atk = rpg.Attack(a, t, 0)
        atk.attack_slot = slot
        atk.opportunity = opportunity
        r = engine.execute_action(bm, atk)
        c = engine.get_agent_conditions(bm, a)
        c.action_used = False
        engine.set_agent_conditions(bm, a, c)
        if r.hit:
            return r
    raise AssertionError("never hit")


def test_feral_pounce_slashing():
    bm, engine, a, t = _pounce_scene()
    r = _hit(engine, bm, a, t)
    assert list(r.physical_damage_types) == [rpg.PhysicalDamage.Slashing], r.physical_damage_types
    bm, engine, h, t = _pounce_scene(species="Human")
    r = _hit(engine, bm, h, t)
    assert list(r.physical_damage_types) == [rpg.PhysicalDamage.Bludgeoning]
    print("✅ test_feral_pounce_slashing passed")


def test_feral_pounce_shove_once_per_turn():
    bm, engine, a, t = _pounce_scene()
    _hit(engine, bm, a, t)
    assert engine.get_agent_conditions(bm, a).feral_pounce_available
    sh = engine.apply_feral_pounce(bm, a, t, True)
    assert sh.valid and sh.success and sh.knocked_prone
    assert engine.get_agent_conditions(bm, t).prone
    c = engine.get_agent_conditions(bm, a)
    assert c.feral_pounce_used and not c.feral_pounce_available
    _hit(engine, bm, a, t)
    assert not engine.get_agent_conditions(bm, a).feral_pounce_available, "once per turn"
    assert not engine.apply_feral_pounce(bm, a, t, False).valid
    print("✅ test_feral_pounce_shove_once_per_turn passed")


def test_feral_pounce_not_offered():
    bm, engine, a, t = _pounce_scene(weapon=_club())
    _hit(engine, bm, a, t)
    assert not engine.get_agent_conditions(bm, a).feral_pounce_available, "weapon, not Unarmed"
    bm, engine, a, t = _pounce_scene()
    _hit(engine, bm, a, t, slot="bonus")
    assert not engine.get_agent_conditions(bm, a).feral_pounce_available, "Bonus Action strike"
    bm, engine, a, t = _pounce_scene()
    _hit(engine, bm, a, t, opportunity=True)
    assert not engine.get_agent_conditions(bm, a).feral_pounce_available, "Opportunity Attack"
    bm, engine, h, t = _pounce_scene(species="Human")
    _hit(engine, bm, h, t)
    assert not engine.get_agent_conditions(bm, h).feral_pounce_available, "not a Lupin"
    print("✅ test_feral_pounce_not_offered passed")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    print(f"\n✅ All {len(tests)} MS4 tests passed")
