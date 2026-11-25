"""More species, MS5: Aasimar Healing Hands and Celestial Revelation (plans/MORE_SPECIES_PLAN.md D5, D6).

Covered: Healing Hands heals a creature within 5 ft by PB d4, once per Long Rest; out of reach
is refused with nothing spent; a creature that can't regain HP gets nothing; the tracker button
spends the use; a non-Aasimar has none (D5). Celestial Revelation unlocks at level 3, once per
Long Rest; Heavenly Wings gives fly Speed = Speed and puts it back on a dismiss; it lasts 10
rounds and Incapacitated does not end it; every form adds PB damage once per turn to the first
damaging hit (Radiant, or Necrotic for the Shroud); Inner Radiance sears non-allies within 10 ft
at the end of the Aasimar's turn; Necrotic Shroud Frightens failing non-allies within 10 ft until
the end of the Aasimar's next turn (D6).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, create_test_agent, add_agent_to_battle

WINGS, RADIANCE, SHROUD = 1, 2, 3


def _pc(engine, bm, idx, species="Aasimar", level=3, cha=30):
    s = engine.get_agent_stats(bm, idx)
    s.add_class_level(rpg.CharacterClass.Fighter, level)
    s.char_level = level
    s.prof_bonus = 2
    s.is_npc = False
    s.cha = cha
    if species:
        s.set_species(species, "")
    engine.set_agent_stats(bm, idx, s)


def _foe(engine, bm, name, col, row, cha=1):
    t = add_agent_to_battle(engine, bm, create_test_agent(name, col, row), hp=500)
    bm.set_agent_faction(t, 1)
    s = engine.get_agent_stats(bm, t)
    s.cha = cha
    engine.set_agent_stats(bm, t, s)
    return t


def _scene(species="Aasimar", level=3):
    """Aasimar at (4,5); foes 1 and 2 cells east (in 10 ft) and 4 cells west (20 ft); an ally."""
    bm = setup_battle_map()
    engine = rpg.CombatEngine(7)
    a = add_agent_to_battle(engine, bm, create_test_agent("Aasimar", 4, 5), hp=80)
    near = _foe(engine, bm, "Near", 5, 5)
    edge = _foe(engine, bm, "Edge", 6, 5)
    far = _foe(engine, bm, "Far", 0, 5)
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 4, 6), hp=50)
    _pc(engine, bm, a, species, level)
    bm.set_agent_faction(a, 2)
    bm.set_agent_faction(ally, 2)
    return bm, engine, a, near, edge, far, ally


def _hp(engine, bm, i):
    return engine.get_agent_stats(bm, i).hp_cur


def _wound(engine, bm, i, hp):
    s = engine.get_agent_stats(bm, i)
    s.hp_cur = hp
    engine.set_agent_stats(bm, i, s)


# ── Healing Hands (D5) ────────────────────────────────────────────────────────

def test_healing_hands_heals_once():
    bm, engine, a, near, edge, far, ally = _scene()
    _wound(engine, bm, ally, 10)
    assert engine.can_healing_hands(bm, a)
    healed = engine.use_healing_hands(bm, a, ally)
    assert 2 <= healed <= 8, f"PB (2) d4: {healed}"
    assert _hp(engine, bm, ally) == 10 + healed
    assert not engine.can_healing_hands(bm, a), "once per Long Rest"
    assert engine.use_healing_hands(bm, a, ally) == -1
    s = engine.get_agent_stats(bm, a)
    s.restore_resources_long_rest()
    engine.set_agent_stats(bm, a, s)
    assert engine.can_healing_hands(bm, a), "back on a Long Rest"
    print("✅ test_healing_hands_heals_once passed")


def test_healing_hands_reach_and_cant_heal():
    bm, engine, a, near, edge, far, ally = _scene()
    _wound(engine, bm, far, 100)
    assert engine.use_healing_hands(bm, a, far) == -1, "20 ft is out of reach"
    assert engine.can_healing_hands(bm, a), "a refused click spends nothing"
    _wound(engine, bm, a, 40)
    s = engine.get_agent_stats(bm, a)
    s.cant_heal = True
    engine.set_agent_stats(bm, a, s)
    assert engine.use_healing_hands(bm, a, a) == 0, "can't regain HP (Chill Touch)"
    assert _hp(engine, bm, a) == 40
    assert not engine.can_healing_hands(bm, a), "the use is still spent"
    print("✅ test_healing_hands_reach_and_cant_heal passed")


def test_healing_hands_tracker_and_non_aasimar():
    bm, engine, a, *_ = _scene()
    assert engine.spend_healing_hands(bm, a)
    assert not engine.spend_healing_hands(bm, a), "already spent"
    bm, engine, h, near, edge, far, ally = _scene(species="Human")
    assert not engine.can_healing_hands(bm, h)
    assert engine.use_healing_hands(bm, h, ally) == -1
    assert not engine.spend_healing_hands(bm, h)
    print("✅ test_healing_hands_tracker_and_non_aasimar passed")


# ── Celestial Revelation (D6) ─────────────────────────────────────────────────

def test_revelation_level_and_uses():
    bm, engine, a, *_ = _scene(level=2)
    assert not engine.can_celestial_revelation(bm, a), "level 3"
    bm, engine, a, *_ = _scene()
    assert engine.can_celestial_revelation(bm, a)
    assert not engine.start_celestial_revelation(bm, a, 0), "a form must be picked"
    assert engine.start_celestial_revelation(bm, a, RADIANCE)
    st = engine.get_agent_stats(bm, a)
    assert st.celestial_form() == RADIANCE and st.celestial_revelation_rounds == 10
    engine.end_celestial_revelation(bm, a)
    assert engine.get_agent_stats(bm, a).celestial_form() == 0
    assert not engine.can_celestial_revelation(bm, a), "once per Long Rest"
    assert not engine.start_celestial_revelation(bm, a, WINGS)
    s = engine.get_agent_stats(bm, a)
    s.restore_resources_long_rest()
    engine.set_agent_stats(bm, a, s)
    assert engine.can_celestial_revelation(bm, a)
    bm, engine, h, *_ = _scene(species="Human")
    assert not engine.can_celestial_revelation(bm, h)
    print("✅ test_revelation_level_and_uses passed")


def test_heavenly_wings_fly_speed():
    bm, engine, a, *_ = _scene()
    st = engine.get_agent_stats(bm, a)
    assert st.speed_fly == 0 and st.speed_walk == 30, (st.speed_fly, st.speed_walk)
    assert engine.start_celestial_revelation(bm, a, WINGS)
    assert engine.get_agent_stats(bm, a).speed_fly == 30
    engine.end_celestial_revelation(bm, a)
    assert engine.get_agent_stats(bm, a).speed_fly == 0, "the fly Speed goes back"
    print("✅ test_heavenly_wings_fly_speed passed")


def test_revelation_duration_survives_incapacitated():
    bm, engine, a, *_ = _scene()
    assert engine.start_celestial_revelation(bm, a, WINGS)
    c = engine.get_agent_conditions(bm, a)
    c.incapacitated = True
    engine.set_agent_conditions(bm, a, c)
    for _ in range(9):
        engine.begin_turn(bm, a)
    st = engine.get_agent_stats(bm, a)
    assert st.celestial_revelation_rounds == 1 and st.speed_fly == 30, "Incapacitated doesn't end it"
    engine.begin_turn(bm, a)
    st = engine.get_agent_stats(bm, a)
    assert st.celestial_form() == 0 and st.speed_fly == 0, "1 minute is up"
    print("✅ test_revelation_duration_survives_incapacitated passed")


def _club():
    w = rpg.Weapon()
    w.name = "Club"
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


def _hit(engine, bm, a, t):
    for _ in range(50):
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        c = engine.get_agent_conditions(bm, a)
        c.action_used = False
        engine.set_agent_conditions(bm, a, c)
        if r.hit:
            return r
    raise AssertionError("never hit")


def test_revelation_extra_damage_once_per_turn():
    for form, kind in ((RADIANCE, rpg.MagicDamage.Radiant), (SHROUD, rpg.MagicDamage.Necrotic)):
        bm, engine, a, near, *_ = _scene()
        engine.set_agent_weapons(bm, a, [_club(), rpg.Weapon(), rpg.Weapon()])
        r = _hit(engine, bm, a, near)
        assert "Celestial Revelation" not in dict(r.damage_breakdown), "not transformed yet"
        engine.begin_turn(bm, a)
        assert engine.start_celestial_revelation(bm, a, form)
        r = _hit(engine, bm, a, near)
        assert dict(r.damage_breakdown).get("Celestial Revelation") == 2, list(r.damage_breakdown)
        assert kind in list(r.magic_damage_types), list(r.magic_damage_types)
        r = _hit(engine, bm, a, near)
        assert "Celestial Revelation" not in dict(r.damage_breakdown), "once per turn"
        engine.begin_turn(bm, near)
        r = _hit(engine, bm, a, near)
        assert "Celestial Revelation" not in dict(r.damage_breakdown), "on the Aasimar's own turns"
        engine.begin_turn(bm, a)
        r = _hit(engine, bm, a, near)
        assert dict(r.damage_breakdown).get("Celestial Revelation") == 2, "a new turn"
    print("✅ test_revelation_extra_damage_once_per_turn passed")


def test_inner_radiance_end_of_turn():
    bm, engine, a, near, edge, far, ally = _scene()
    engine.begin_turn(bm, a)
    assert engine.start_celestial_revelation(bm, a, RADIANCE)
    before = {i: _hp(engine, bm, i) for i in (near, edge, far, ally)}
    engine.end_turn(bm, a)
    assert _hp(engine, bm, near) == before[near] - 2 and _hp(engine, bm, edge) == before[edge] - 2, \
        "PB Radiant within 10 ft"
    assert _hp(engine, bm, far) == before[far], "20 ft is out of range"
    assert _hp(engine, bm, ally) == before[ally], "allies are skipped"
    engine.end_turn(bm, near)
    assert _hp(engine, bm, near) == before[near] - 2, "only the Aasimar's turn end"
    print("✅ test_inner_radiance_end_of_turn passed")


def _frightened(engine, bm, i):
    return engine.get_agent_conditions(bm, i).frightened


def test_necrotic_shroud_frightens_until_next_turn_end():
    bm, engine, a, near, edge, far, ally = _scene()
    s = engine.get_agent_stats(bm, edge)
    s.cha = 30                                       # +10 vs DC 8 + 10 + 2 = 20: may save
    engine.set_agent_stats(bm, edge, s)
    assert engine.celestial_revelation_dc(bm, a) == 20
    engine.begin_turn(bm, a)
    assert engine.start_celestial_revelation(bm, a, SHROUD)
    assert _frightened(engine, bm, near), "CHA 1 vs DC 20 fails"
    assert not _frightened(engine, bm, far), "20 ft is out of range"
    assert not _frightened(engine, bm, ally), "allies are not targets"
    engine.end_turn(bm, a)
    assert _frightened(engine, bm, near), "lasts past the turn it began"
    engine.begin_turn(bm, near)
    engine.end_turn(bm, near)
    assert _frightened(engine, bm, near)
    engine.begin_turn(bm, a)
    engine.tick_agent_conditions_for_caster(bm, a)
    assert _frightened(engine, bm, near), "through the Aasimar's next turn"
    engine.end_turn(bm, a)
    assert not _frightened(engine, bm, near), "ends as the Aasimar's next turn ends"
    print("✅ test_necrotic_shroud_frightens_until_next_turn_end passed")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    print(f"\n✅ All {len(tests)} MS5 tests passed")
