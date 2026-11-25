"""More species, MS3: Bugbear and Reborn actives (plans/MORE_SPECIES_PLAN.md D10, D12, D13).

Covered: Bugbear Long-Limbed reaches 10 ft with a 5-ft melee weapon on its own turn, but not
on another creature's turn, not on an Opportunity Attack, and not for a non-Bugbear (D12).
Surprise Attack adds 2d6 to a weapon hit on a creature that hasn't taken a turn yet, once per
combat; a creature that has acted gets none; the used flag survives a snapshot; a spell attack
takes it too (D13). Reborn Knowledge from a Past Life: after a failed engine-rolled check it
is offered; arming it spends a use and the same check, run again, replays the d20s (the
defender's too) plus the d6; it isn't offered again on the re-evaluated check, on a success,
to a non-Reborn or with no uses left; PB uses, back on a Long Rest; the tracker spend; a chest
pick failed by 5+ holds its trap for the offer, and the re-evaluated failure sets it off (D10).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
import helpers
from test_helpers import setup_battle_map, create_test_agent, add_agent_to_battle

CATALOG = {d["name"]: d for d in json.load(
    open(os.path.join(os.path.dirname(rpg.__file__), "spells.json")))}


def _blade():
    w = rpg.Weapon()
    w.name = "Sure Blade"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.proficient = True
    w.bonus_hit = 60          # only a natural 1 misses
    w.bonus_damage = 1        # no dice, STR 10: a plain hit deals exactly 1
    return [w, rpg.Weapon(), rpg.Weapon()]


def _pc(engine, bm, idx, species="", option="", level=1):
    s = engine.get_agent_stats(bm, idx)
    s.add_class_level(rpg.CharacterClass.Fighter, level)
    s.char_level = level
    s.prof_bonus = 2
    s.is_npc = False
    s.speed_walk = 30
    if species:
        s.set_species(species, option)
    engine.set_agent_stats(bm, idx, s)


def _scene(species="Bugbear", gap=1, seed=7):
    """A PC at (4,5) and a foe `gap` cells east."""
    bm = setup_battle_map()
    engine = rpg.CombatEngine(seed)
    a = add_agent_to_battle(engine, bm, create_test_agent("Pc", 4, 5), hp=80)
    t = add_agent_to_battle(engine, bm, create_test_agent("Foe", 4 + gap, 5), hp=500)
    bm.set_agent_faction(t, 1)
    _pc(engine, bm, a, species)
    engine.set_agent_weapons(bm, a, _blade())
    return bm, engine, a, t


def _swing(engine, bm, a, t, opportunity=False):
    atk = rpg.Attack(a, t, 0)
    atk.opportunity = opportunity
    r = engine.execute_action(bm, atk)
    c = engine.get_agent_conditions(bm, a)
    c.action_used = False
    engine.set_agent_conditions(bm, a, c)
    return r


def _hit(engine, bm, a, t):
    for _ in range(50):
        r = _swing(engine, bm, a, t)
        if r.hit:
            return r
    raise AssertionError("never hit")


def _mark_acted(engine, bm, idx):
    c = engine.get_agent_conditions(bm, idx)
    c.has_taken_turn_this_combat = True
    engine.set_agent_conditions(bm, idx, c)


# ── Long-Limbed (D12) ─────────────────────────────────────────────────────────

def test_long_limbed_reach():
    bm, engine, a, t = _scene(gap=2)                        # 10 ft apart
    _mark_acted(engine, bm, t)                              # keep Surprise Attack out of it
    assert engine.get_agent_stats(bm, a).has_long_limbed()
    engine.begin_turn(bm, a)
    r = _hit(engine, bm, a, t)
    assert r.valid and r.hit, "own turn: a 5-ft blade reaches 10 ft"
    assert not _swing(engine, bm, a, t, opportunity=True).valid, "an Opportunity Attack doesn't"
    engine.begin_turn(bm, t)                                # someone else's turn
    assert not _swing(engine, bm, a, t).valid, "off-turn the reach is 5 ft"
    bm2, e2, h, t2 = _scene(species="Human", gap=2)
    e2.begin_turn(bm2, h)
    assert not _swing(e2, bm2, h, t2).valid, "a non-Bugbear has no extra reach"
    assert not rpg.Stats().has_long_limbed()
    print("✅ test_long_limbed_reach passed")


# ── Surprise Attack (D13) ─────────────────────────────────────────────────────

def test_surprise_attack_once_per_combat():
    bm, engine, a, t = _scene()
    r = _hit(engine, bm, a, t)
    extra = dict(r.damage_breakdown).get("Surprise Attack")
    assert extra is not None and 2 <= extra <= 12, list(r.damage_breakdown)
    assert r.total_damage == 1 + extra
    assert engine.get_agent_conditions(bm, a).surprise_attack_used
    r = _hit(engine, bm, a, t)
    assert "Surprise Attack" not in dict(r.damage_breakdown) and r.total_damage == 1, \
        "once per combat"
    # The flag rides the board snapshot (it lasts the combat).
    snap = bm.snapshot_json()
    c = engine.get_agent_conditions(bm, a)
    c.surprise_attack_used = False
    engine.set_agent_conditions(bm, a, c)
    assert bm.restore_json(snap)
    assert engine.get_agent_conditions(bm, a).surprise_attack_used
    # A creature that has already acted gives none.
    bm, engine, a, t = _scene()
    _mark_acted(engine, bm, t)
    r = _hit(engine, bm, a, t)
    assert "Surprise Attack" not in dict(r.damage_breakdown)
    assert not engine.get_agent_conditions(bm, a).surprise_attack_used, "not spent when it doesn't apply"
    # A non-Bugbear never gets it.
    bm, engine, h, t = _scene(species="Human")
    assert "Surprise Attack" not in dict(_hit(engine, bm, h, t).damage_breakdown)
    print("✅ test_surprise_attack_once_per_combat passed")


def test_surprise_attack_spell():
    bm, engine, a, t = _scene(gap=3)
    engine.set_agent_spells(bm, a, [helpers._dict_to_spell(CATALOG["Fire Bolt"])])
    s = engine.get_agent_stats(bm, a)
    s.spellcasting_ability = 5
    s.cha = 20
    s.spell_attack_bonus = 60
    engine.set_agent_stats(bm, a, s)
    sp = rpg.SpellAction()
    sp.caster_idx, sp.spell_idx, sp.slot_level = a, 0, 0
    sp.target_indices = [t]
    tc = bm.placed_agents[t].origin
    sp.aoe_col, sp.aoe_row = tc.col, tc.row
    for _ in range(20):
        res = engine.execute_spell(bm, sp)
        if res.target_results and res.target_results[0].hit:
            break
        c = engine.get_agent_conditions(bm, a)
        c.action_used = False
        engine.set_agent_conditions(bm, a, c)
    tr = res.target_results[0]
    assert tr.hit and engine.get_agent_conditions(bm, a).surprise_attack_used
    assert 1 + 2 <= tr.total_damage <= 10 + 12, tr.total_damage
    print("✅ test_surprise_attack_spell passed")


# ── Knowledge from a Past Life (D10) ─────────────────────────────────────────

def _door_scene(species="Reborn", dc=30):
    bm = setup_battle_map()
    engine = rpg.CombatEngine(5)
    r = add_agent_to_battle(engine, bm, create_test_agent("Reb", 3, 3), str=6)
    _pc(engine, bm, r, species, "Cold")
    did = bm.add_door(rpg.Cell(7, 7), False, True, 15, False, dc)
    return bm, engine, r, did


def test_past_life_door_replay_and_pool():
    bm, engine, r, did = _door_scene()
    assert engine.get_agent_stats(bm, r).past_life_remaining() == 2
    res = engine.attempt_break_door(bm, r, did)
    assert res.valid and not res.success
    assert engine.can_past_life(bm, r)
    d6 = engine.arm_past_life(bm, r)
    assert 1 <= d6 <= 6 and engine.get_agent_stats(bm, r).past_life_used == 1
    res2 = engine.attempt_break_door(bm, r, did)
    assert res2.roll == res.roll and res2.total == res.total + d6, (res.total, res2.total, d6)
    assert not engine.can_past_life(bm, r), "the re-evaluated check is not offered again"
    # A fresh check rolls a fresh d20 and is offered again; then the pool runs dry.
    engine.attempt_break_door(bm, r, did)
    assert engine.can_past_life(bm, r)
    engine.arm_past_life(bm, r)
    engine.attempt_break_door(bm, r, did)
    engine.attempt_break_door(bm, r, did)
    assert engine.get_agent_stats(bm, r).past_life_remaining() == 0
    assert not engine.can_past_life(bm, r) and engine.arm_past_life(bm, r) == 0
    # A Long Rest brings the uses back.
    s = engine.get_agent_stats(bm, r)
    s.restore_resources_long_rest()
    assert s.past_life_used == 0 and s.past_life_remaining() == 2
    print("✅ test_past_life_door_replay_and_pool passed")


def test_past_life_not_offered():
    bm, engine, r, did = _door_scene(species="Human")
    assert not engine.attempt_break_door(bm, r, did).success
    assert not engine.can_past_life(bm, r), "not a Reborn"
    bm, engine, r, did = _door_scene(dc=1)
    s = engine.get_agent_stats(bm, r)
    s.str = 30
    engine.set_agent_stats(bm, r, s)
    assert engine.attempt_break_door(bm, r, did).success
    assert not engine.can_past_life(bm, r), "the check succeeded"
    print("✅ test_past_life_not_offered passed")


def test_past_life_contest_keeps_defender_roll():
    bm, engine, r, t = _scene(species="Reborn")
    ts = engine.get_agent_stats(bm, t)
    ts.str = 30                                   # the defender wins the first contest
    engine.set_agent_stats(bm, t, ts)
    sh = rpg.ShoveAction()
    sh.attacker_idx, sh.target_idx, sh.knock_prone = r, t, True
    first = engine.execute_shove(bm, sh)
    assert first.valid and not first.success
    d6 = engine.arm_past_life(bm, r)
    again = engine.execute_shove(bm, sh)
    assert again.defender_roll == first.defender_roll
    assert again.attacker_roll == first.attacker_roll + d6
    # Grapple escape replays both of its d20s.
    c = engine.get_agent_conditions(bm, r)
    c.grappled, c.grappler_idx, c.grapple_escape_dc = True, t, 40
    engine.set_agent_conditions(bm, r, c)
    e1 = engine.execute_grapple_escape(bm, r)
    assert e1.valid and not e1.success and engine.can_past_life(bm, r)
    d6 = engine.arm_past_life(bm, r)
    e2 = engine.execute_grapple_escape(bm, r)
    assert e2.escape_roll == e1.escape_roll + d6
    print("✅ test_past_life_contest_keeps_defender_roll passed")


def test_past_life_chest_trap_waits():
    bm = setup_battle_map()
    engine = rpg.CombatEngine(3)
    r = add_agent_to_battle(engine, bm, create_test_agent("Reb", 3, 3), dex=1, hp=200)
    _pc(engine, bm, r, "Reborn", "Cold")
    s = engine.get_agent_stats(bm, r)
    s.hp_max = s.hp_cur = 200
    engine.set_agent_stats(bm, r, s)
    ch = rpg.Chest()
    ch.cell, ch.locked, ch.lock_dc = rpg.Cell(1, 1), True, 40
    cid = bm.add_chest(ch)
    t = rpg.ChestTrap()
    t.armed, t.num_dice, t.die_size, t.bonus, t.save_dc, t.half_on_save = True, 1, 1, 4, 40, False
    bm.set_chest_trap(cid, t)
    res = engine.attempt_pick_chest_lock(bm, r, cid)
    assert not res.success and res.total <= res.dc - 5
    assert res.trap_deferred and not res.trap.fired, "the trap waits on the Past Life offer"
    assert engine.get_agent_stats(bm, r).hp_cur == 200
    engine.arm_past_life(bm, r)
    res2 = engine.attempt_pick_chest_lock(bm, r, cid)
    assert not res2.success and not res2.trap_deferred and res2.trap.fired, \
        "the re-evaluated failure sets it off"
    assert engine.get_agent_stats(bm, r).hp_cur == 195
    print("✅ test_past_life_chest_trap_waits passed")


def test_past_life_tracker_spend():
    bm, engine, r, did = _door_scene()
    assert engine.spend_past_life(bm, r) and engine.spend_past_life(bm, r)
    assert not engine.spend_past_life(bm, r), "PB uses only"
    bm, engine, h, did = _door_scene(species="Human")
    assert not engine.spend_past_life(bm, h)
    print("✅ test_past_life_tracker_spend passed")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    print(f"\n✅ All {len(tests)} MS3 tests passed")
