#!/usr/bin/env python3
"""
Direct calls for the 15 bound CombatEngine methods no other suite named
(plans/COMBAT_CLASS_SPLIT_PLAN.md, D6 follow-up list). Each test pins what the binding does today
when called on its own, so a later move or refactor that changes a body shows up here.

  Ranger   · vanish_orphaned_companions: a Primal Companion whose Ranger is dead, removed, or
             missing is removed from play; a living Ranger's, and other summons, stay
           · misty_wanderer_ally_cell / is_misty_wanderer_ally_cell: the first free space
             within 5 ft of the Ranger's landing cell; overlap, distance, occupants, map edge
  Fighter  · apply_precision_attack_effect: spends a die, adds it, can turn a miss into a hit;
             no flag or no dice does nothing
  Feats    · can_peerless_aim: feat + alive + unused
           · apply_sentinel_guard: a melee attack at the attacker that spends the Reaction
  Monk     · apply_open_hand_rider: Knockdown / Push / Deny Reaction, Focus Point, no-flag refusal
  Shared   · consume_bonus_attack: counts down, True while attacks remain
           · tick_light_effects_for_turn: ticks own + DM lights, re-evaluates blinding on expiry
  Wizard   · regenerate_portent_dice: Diviners only, one d20 per Portent Die use
  Druid    · activate/deactivate_starry_form, activate/deactivate_wrath_of_sea,
             apply_dragon_min_roll
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'gui'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, add_agent_to_battle,
                          create_test_agent)
from test_fighter import _setup as _battle_master_scene


# ── shared scene ────────────────────────────────────────────────────────────

def _scene(*names_at):
    """Open 36×36 grid with one agent per (name, col, row); returns bm, engine, [indices]."""
    bm = setup_battle_map()
    bm.set_uniform_grid(bm.cell_pixel_size // 3, 0, 0)
    bm.detect_walls()
    engine = setup_combat_engine()
    idx = [add_agent_to_battle(engine, bm, create_test_agent(n, c, r)) for n, c, r in names_at]
    return bm, engine, idx


def _melee(bonus_hit=50):
    w = rpg.Weapon()
    w.name = "Sword"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.bonus_hit = bonus_hit
    d = rpg.PhysicalDamageRoll()
    d.type = rpg.PhysicalDamage.Slashing
    d.num_dice = 1
    d.die_size = 6
    w.physical_damage_types = [d]
    return [w, rpg.Weapon(), rpg.Weapon()]


def _hp(engine, bm, i, hp=300, ac=10):
    s = engine.get_agent_stats(bm, i)
    s.hp_max = s.hp_cur = hp
    s.base_ac = ac
    engine.set_agent_stats(bm, i, s)


def _cond(engine, bm, i, **kw):
    c = engine.get_agent_conditions(bm, i)
    for k, v in kw.items():
        setattr(c, k, v)
    engine.set_agent_conditions(bm, i, c)


def _at(bm, i):
    o = bm.placed_agents[i].origin
    return (o.col, o.row)


# ── Ranger: vanish_orphaned_companions ──────────────────────────────────────

def _companion_scene():
    bm, engine, (rng, comp, fam_owner, fam) = _scene(
        ("Ranger", 5, 5), ("Companion", 6, 5), ("Wizard", 10, 10), ("Familiar", 11, 10))
    bm.set_agent_summoner_idx(comp, rng)
    bm.set_agent_summon_spell(comp, "Primal Companion")
    bm.set_agent_summoner_idx(fam, fam_owner)
    bm.set_agent_summon_spell(fam, "Find Familiar")
    return bm, engine, rng, comp, fam_owner, fam


def test_vanish_living_ranger_keeps_companion():
    bm, engine, rng, comp, _, _ = _companion_scene()
    engine.vanish_orphaned_companions(bm)
    assert not bm.is_agent_removed_from_play(comp), "the Ranger lives: the companion stays"
    print("✅ test_vanish_living_ranger_keeps_companion")


def test_vanish_dead_ranger():
    bm, engine, rng, comp, owner, fam = _companion_scene()
    _cond(engine, bm, rng, dead=True)
    _cond(engine, bm, owner, dead=True)
    engine.vanish_orphaned_companions(bm)
    assert bm.is_agent_removed_from_play(comp), "a dead Ranger's companion vanishes"
    assert not bm.is_agent_removed_from_play(fam), "only Primal Companions vanish"
    assert not bm.is_agent_removed_from_play(rng), "the Ranger's body is left alone"
    print("✅ test_vanish_dead_ranger")


def test_vanish_removed_or_missing_ranger():
    bm, engine, rng, comp, _, _ = _companion_scene()
    bm.set_agent_removed_from_play(rng, True)
    engine.vanish_orphaned_companions(bm)
    assert bm.is_agent_removed_from_play(comp), "a Ranger out of play leaves no companion"

    bm, engine, rng, comp, _, _ = _companion_scene()
    bm.set_agent_summoner_idx(comp, -1)
    engine.vanish_orphaned_companions(bm)
    assert bm.is_agent_removed_from_play(comp), "no owner at all: vanishes"
    print("✅ test_vanish_removed_or_missing_ranger")


# ── Ranger: Misty Wanderer passenger cells ──────────────────────────────────

def test_misty_ally_cell_first_free():
    bm, engine, (rng, ally) = _scene(("Ranger", 5, 5), ("Ally", 6, 5))
    c = engine.misty_wanderer_ally_cell(bm, ally, rng, rpg.Cell(20, 20))
    assert (c.col, c.row) == (19, 19), "scan starts at the up-left neighbour"
    print("✅ test_misty_ally_cell_first_free")


def test_misty_ally_cell_skips_occupied_and_edge():
    bm, engine, (rng, ally, other) = _scene(("Ranger", 5, 5), ("Ally", 6, 5), ("Other", 19, 19))
    c = engine.misty_wanderer_ally_cell(bm, ally, rng, rpg.Cell(20, 20))
    assert (c.col, c.row) == (20, 19), "an occupied space is skipped"

    c = engine.misty_wanderer_ally_cell(bm, ally, rng, rpg.Cell(0, 0))
    assert (c.col, c.row) == (1, 0), "off-map cells are skipped at the corner"
    print("✅ test_misty_ally_cell_skips_occupied_and_edge")


def test_misty_ally_cell_bad_index():
    bm, engine, (rng, ally) = _scene(("Ranger", 5, 5), ("Ally", 6, 5))
    c = engine.misty_wanderer_ally_cell(bm, 99, rng, rpg.Cell(20, 20))
    assert (c.col, c.row) == (-1, -1)
    c = engine.misty_wanderer_ally_cell(bm, -1, rng, rpg.Cell(20, 20))
    assert (c.col, c.row) == (-1, -1)
    print("✅ test_misty_ally_cell_bad_index")


def test_is_misty_ally_cell():
    bm, engine, (rng, ally, other) = _scene(("Ranger", 5, 5), ("Ally", 6, 5), ("Other", 21, 20))
    dest = rpg.Cell(20, 20)
    ok = lambda col, row: engine.is_misty_wanderer_ally_cell(bm, ally, rpg.Cell(col, row), rng, dest)
    assert ok(19, 20) and ok(20, 21) and ok(19, 19), "adjacent free spaces are legal"
    assert not ok(20, 20), "the Ranger's own landing space overlaps"
    assert not ok(18, 20), "10 ft away is too far"
    assert not ok(21, 20), "occupied by a third creature"

    bm.set_agent_position(rng, rpg.Cell(19, 20))
    assert ok(19, 20), "the Ranger's old square does not block (it has left)"
    bm.set_agent_position(ally, rpg.Cell(20, 21))
    assert ok(20, 21), "the passenger's own square does not block"

    _cond(engine, bm, other, dead=True)
    assert ok(21, 20), "a dead creature does not block"

    assert not engine.is_misty_wanderer_ally_cell(bm, 99, rpg.Cell(19, 20), rng, dest)
    assert not engine.is_misty_wanderer_ally_cell(bm, ally, rpg.Cell(19, 20), 99, dest)
    print("✅ test_is_misty_ally_cell")


# ── Fighter: apply_precision_attack_effect ──────────────────────────────────

def _dice(engine, bm, i):
    return engine.get_agent_stats(bm, i).get_resource("Superiority Dice").current


def _miss_by(engine, bm, atk, tgt, short_by, ac=15, tries=600):
    """Attack until a non-fumble miss that falls exactly short_by below AC; re-arms the flag."""
    for _ in range(tries):
        _hp(engine, bm, tgt, hp=100, ac=ac)
        r = engine.execute_action(bm, rpg.Attack(atk, tgt, 0))
        if not r.hit and not r.fumble and r.target_ac - r.total_roll == short_by:
            _cond(engine, bm, atk, maneuver_precision_available=True)
            return r
    raise AssertionError(f"no miss by {short_by} in {tries} attacks")


def test_precision_turns_near_miss_into_hit():
    bm, engine, atk, tgt = _battle_master_scene(3)
    r = _miss_by(engine, bm, atk, tgt, 1)
    dice0, roll0 = _dice(engine, bm, atk), r.total_roll
    hp0 = engine.get_agent_stats(bm, tgt).hp_cur
    engine.apply_precision_attack_effect(bm, rpg.Attack(atk, tgt, 0), r)
    assert _dice(engine, bm, atk) == dice0 - 1, "spends one Superiority Die"
    assert 1 <= r.total_roll - roll0 <= 8, "adds a d8 at L3"
    assert r.hit, "a miss by 1 always becomes a hit"
    assert r.total_damage > 0 and r.hp_before == hp0
    assert engine.get_agent_stats(bm, tgt).hp_cur == hp0 - r.total_damage == r.hp_after
    assert not engine.get_agent_conditions(bm, atk).maneuver_precision_available, "flag cleared"
    print("✅ test_precision_turns_near_miss_into_hit")


def test_precision_far_miss_stays_miss():
    bm, engine, atk, tgt = _battle_master_scene(3)
    r = _miss_by(engine, bm, atk, tgt, 9, ac=25)
    dice0, roll0 = _dice(engine, bm, atk), r.total_roll
    hp0 = engine.get_agent_stats(bm, tgt).hp_cur
    engine.apply_precision_attack_effect(bm, rpg.Attack(atk, tgt, 0), r)
    assert _dice(engine, bm, atk) == dice0 - 1, "the die is spent anyway"
    assert r.total_roll > roll0 and not r.hit, "a d8 cannot close a gap of 9"
    assert engine.get_agent_stats(bm, tgt).hp_cur == hp0
    assert not engine.get_agent_conditions(bm, atk).maneuver_precision_available
    print("✅ test_precision_far_miss_stays_miss")


def test_precision_refused():
    bm, engine, atk, tgt = _battle_master_scene(3)
    r = _miss_by(engine, bm, atk, tgt, 1)
    _cond(engine, bm, atk, maneuver_precision_available=False)
    dice0, roll0 = _dice(engine, bm, atk), r.total_roll
    engine.apply_precision_attack_effect(bm, rpg.Attack(atk, tgt, 0), r)
    assert _dice(engine, bm, atk) == dice0 and r.total_roll == roll0 and not r.hit, "no flag"

    _cond(engine, bm, atk, maneuver_precision_available=True)
    s = engine.get_agent_stats(bm, atk)
    sd = s.get_resource("Superiority Dice"); sd.current = 0
    s.resources["Superiority Dice"] = sd
    engine.set_agent_stats(bm, atk, s)
    engine.apply_precision_attack_effect(bm, rpg.Attack(atk, tgt, 0), r)
    assert r.total_roll == roll0 and not r.hit, "no dice"
    assert engine.get_agent_conditions(bm, atk).maneuver_precision_available, "flag kept"

    engine.apply_precision_attack_effect(bm, rpg.Attack(atk, 99, 0), r)
    assert r.total_roll == roll0, "bad target index"
    print("✅ test_precision_refused")


# ── Feats: can_peerless_aim, apply_sentinel_guard ───────────────────────────

def test_can_peerless_aim():
    bm, engine, (a, b) = _scene(("Champion", 5, 5), ("Plain", 6, 5))
    s = engine.get_agent_stats(bm, a)
    s.feats = ["Boon of Combat Prowess"]
    engine.set_agent_stats(bm, a, s)
    _hp(engine, bm, a)
    _hp(engine, bm, b)
    assert engine.can_peerless_aim(bm, a)
    assert not engine.can_peerless_aim(bm, b), "no boon"
    assert not engine.can_peerless_aim(bm, 99) and not engine.can_peerless_aim(bm, -1)

    _cond(engine, bm, a, peerless_aim_used=True)
    assert not engine.can_peerless_aim(bm, a), "once per turn"
    _cond(engine, bm, a, peerless_aim_used=False)
    s = engine.get_agent_stats(bm, a); s.hp_cur = 0; engine.set_agent_stats(bm, a, s)
    assert not engine.can_peerless_aim(bm, a), "at 0 HP"
    print("✅ test_can_peerless_aim")


def test_sentinel_guard():
    bm, engine, (sen, foe) = _scene(("Sentinel", 5, 5), ("Foe", 6, 5))
    bm.set_agent_faction(sen, 1)
    bm.set_agent_faction(foe, 2)
    _hp(engine, bm, sen)
    _hp(engine, bm, foe, hp=300, ac=1)
    engine.set_agent_weapons(bm, sen, _melee())
    r = engine.apply_sentinel_guard(bm, sen, foe, 0)
    assert r.valid and r.hit, "a +50 sword lands on AC 1 short of a fumble"
    assert engine.get_agent_stats(bm, foe).hp_cur == 300 - r.total_damage
    assert engine.get_agent_conditions(bm, sen).reaction_used, "spends the Reaction"

    hp1 = engine.get_agent_stats(bm, foe).hp_cur
    r = engine.apply_sentinel_guard(bm, sen, foe, 0)
    assert not r.valid, "no Reaction left"
    assert engine.get_agent_stats(bm, foe).hp_cur == hp1
    assert not engine.apply_sentinel_guard(bm, 99, foe, 0).valid
    assert not engine.apply_sentinel_guard(bm, sen, 99, 0).valid
    print("✅ test_sentinel_guard")


# ── Monk: apply_open_hand_rider ─────────────────────────────────────────────

def _open_hand_scene():
    bm, engine, (monk, tgt) = _scene(("Monk", 10, 10), ("Target", 11, 10))
    s = engine.get_agent_stats(bm, monk)
    s.set_class_level(rpg.CharacterClass.Monk, 3)
    s.initialize_class_resources(rpg.CharacterClass.Monk, 3)
    s.dex = 20
    s.prof_bonus = 6                       # DC 8 + 5 + 6 = 19
    s.hp_max = s.hp_cur = 50
    engine.set_agent_stats(bm, monk, s)
    t = engine.get_agent_stats(bm, tgt)
    t.str = 1                              # STR save d20 - 5: at most 15 < 19
    t.save_prof_str = False
    t.hp_max = t.hp_cur = 50
    engine.set_agent_stats(bm, tgt, t)
    _cond(engine, bm, monk, open_hand_rider_available=True)
    return bm, engine, monk, tgt


def _fp(engine, bm, i):
    return engine.get_agent_stats(bm, i).get_resource("Focus Points").current


def test_open_hand_knockdown():
    bm, engine, monk, tgt = _open_hand_scene()
    fp0 = _fp(engine, bm, monk)
    r = engine.apply_open_hand_rider(bm, monk, tgt, 0)
    assert r.valid and r.option == 0
    assert r.knockdown_save_dc == 19 and r.knockdown_save_roll < 19
    assert r.target_knocked_prone and engine.get_agent_conditions(bm, tgt).prone
    assert _fp(engine, bm, monk) == fp0 - 1, "spends 1 Focus Point"
    print("✅ test_open_hand_knockdown")


def test_open_hand_push():
    bm, engine, monk, tgt = _open_hand_scene()
    r = engine.apply_open_hand_rider(bm, monk, tgt, 1)
    assert r.valid and r.option == 1 and r.push_distance == 5
    assert _at(bm, tgt) == (12, 10), "pushed 5 ft straight away from the Monk"
    print("✅ test_open_hand_push")


def test_open_hand_deny_reaction():
    bm, engine, monk, tgt = _open_hand_scene()
    r = engine.apply_open_hand_rider(bm, monk, tgt, 2)
    assert r.valid and r.reaction_denied
    assert engine.get_agent_conditions(bm, tgt).reaction_used
    assert not engine.get_agent_conditions(bm, tgt).prone and _at(bm, tgt) == (11, 10)
    print("✅ test_open_hand_deny_reaction")


def test_open_hand_refused():
    bm, engine, monk, tgt = _open_hand_scene()
    _cond(engine, bm, monk, open_hand_rider_available=False)
    fp0 = _fp(engine, bm, monk)
    r = engine.apply_open_hand_rider(bm, monk, tgt, 2)
    assert not r.valid and not r.reaction_denied
    assert not engine.get_agent_conditions(bm, tgt).reaction_used
    assert _fp(engine, bm, monk) == fp0
    assert not engine.apply_open_hand_rider(bm, monk, 99, 0).valid
    print("✅ test_open_hand_refused")


# ── Shared: consume_bonus_attack ────────────────────────────────────────────

def test_consume_bonus_attack():
    bm, engine, (a,) = _scene(("Monk", 5, 5))
    s = engine.get_agent_stats(bm, a); s.bonus_attacks_remaining = 2; engine.set_agent_stats(bm, a, s)
    left = lambda: engine.get_agent_stats(bm, a).bonus_attacks_remaining
    assert engine.consume_bonus_attack(bm, a) is True and left() == 1, "one more queued"
    assert engine.consume_bonus_attack(bm, a) is False and left() == 0, "sequence exhausted"
    assert engine.consume_bonus_attack(bm, a) is False and left() == 0, "never below zero"
    assert engine.consume_bonus_attack(bm, 99) is False
    print("✅ test_consume_bonus_attack")


# ── Shared: tick_light_effects_for_turn ─────────────────────────────────────

_DARKISH = (rpg.VisibilityLevel.Dark, rpg.VisibilityLevel.MagicalDark,
            rpg.VisibilityLevel.HeavilyObscured)


def _light_scene():
    bm, engine, (caster, near, far) = _scene(("Caster", 5, 5), ("Near", 10, 10), ("Far", 25, 25))
    for i in (near, far):
        assert bm.get_light_level_for(bm.placed_agents[i].origin, i) not in _DARKISH, \
            "precondition: the test map is lit"
    return bm, engine, caster, near, far


def _ids(bm):
    return sorted(e.id for e in bm.active_light_effects)


def test_light_tick_expiry_reevaluates_blinding():
    bm, engine, caster, near, far = _light_scene()
    eid = bm.place_light_effect("Darkness", [rpg.Cell(10, 10)], rpg.VisibilityLevel.MagicalDark,
                                1, caster)
    _cond(engine, bm, near, blinded=True)
    _cond(engine, bm, far, blinded=True)       # every agent is re-evaluated, not just those inside
    engine.tick_light_effects_for_turn(bm, caster)
    assert eid not in _ids(bm), "1 turn left: expires"
    assert not engine.get_agent_conditions(bm, near).blinded
    assert not engine.get_agent_conditions(bm, far).blinded
    print("✅ test_light_tick_expiry_reevaluates_blinding")


def test_light_tick_no_expiry_no_reevaluation():
    bm, engine, caster, near, far = _light_scene()
    eid = bm.place_light_effect("Darkness", [rpg.Cell(10, 10)], rpg.VisibilityLevel.MagicalDark,
                                2, caster)
    _cond(engine, bm, far, blinded=True)
    engine.tick_light_effects_for_turn(bm, caster)
    left = next(e for e in bm.active_light_effects if e.id == eid)
    assert left.turns_remaining == 1, "ticked once"
    assert engine.get_agent_conditions(bm, far).blinded, "nothing expired: blinding untouched"
    print("✅ test_light_tick_no_expiry_no_reevaluation")


def test_light_tick_sources():
    bm, engine, caster, near, far = _light_scene()
    mine = bm.place_light_effect("Mine", [rpg.Cell(1, 1)], rpg.VisibilityLevel.MagicalDark, 3, caster)
    theirs = bm.place_light_effect("Theirs", [rpg.Cell(2, 2)], rpg.VisibilityLevel.MagicalDark, 3, near)
    dm = bm.place_light_effect("DM", [rpg.Cell(3, 3)], rpg.VisibilityLevel.MagicalDark, 3, -1)
    forever = bm.place_light_effect("Lamp", [rpg.Cell(4, 4)], rpg.VisibilityLevel.MagicalDark, -1, caster)
    engine.tick_light_effects_for_turn(bm, caster)
    turns = {e.id: e.turns_remaining for e in bm.active_light_effects}
    assert turns[mine] == 2, "the agent's own effect ticks"
    assert turns[theirs] == 3, "another agent's effect does not"
    assert turns[dm] == 2, "DM-placed effects tick on every turn"
    assert turns[forever] == -1, "permanent effects never tick"
    print("✅ test_light_tick_sources")


# ── Wizard: regenerate_portent_dice ─────────────────────────────────────────

def _wizard(engine, bm, i, level, subclass):
    s = engine.get_agent_stats(bm, i)
    s.set_class_level(rpg.CharacterClass.Wizard, level)
    s.wizard_subclass = subclass
    s.initialize_class_resources(rpg.CharacterClass.Wizard, level)
    s.portent_dice = [7]
    engine.set_agent_stats(bm, i, s)


def test_regenerate_portent_dice():
    bm, engine, (div, evo, ftr) = _scene(("Diviner", 5, 5), ("Evoker", 7, 5), ("Fighter", 9, 5))
    _wizard(engine, bm, div, 3, rpg.WizardSubclass.Diviner)
    _wizard(engine, bm, evo, 3, rpg.WizardSubclass.Evoker)
    s = engine.get_agent_stats(bm, ftr); s.portent_dice = [7]; engine.set_agent_stats(bm, ftr, s)

    engine.regenerate_portent_dice(bm, div)
    dice = list(engine.get_agent_stats(bm, div).portent_dice)
    assert len(dice) == 2, "L3 Diviner: 2 Portent Dice"
    assert all(1 <= d <= 20 for d in dice)

    engine.regenerate_portent_dice(bm, evo)
    assert list(engine.get_agent_stats(bm, evo).portent_dice) == [7], "not a Diviner"
    engine.regenerate_portent_dice(bm, ftr)
    assert list(engine.get_agent_stats(bm, ftr).portent_dice) == [7], "not a Wizard"
    engine.regenerate_portent_dice(bm, 99)                     # no crash
    print("✅ test_regenerate_portent_dice")


def test_regenerate_portent_dice_counts_current_uses():
    bm, engine, (div,) = _scene(("Diviner", 5, 5))
    _wizard(engine, bm, div, 14, rpg.WizardSubclass.Diviner)
    s = engine.get_agent_stats(bm, div)
    assert s.resources["Portent Dice"].current == 3, "Greater Portent: 3 uses"
    pd = s.get_resource("Portent Dice"); pd.current = 1
    s.resources["Portent Dice"] = pd
    engine.set_agent_stats(bm, div, s)
    engine.regenerate_portent_dice(bm, div)
    assert len(engine.get_agent_stats(bm, div).portent_dice) == 1, "rolls the current uses, not max"
    print("✅ test_regenerate_portent_dice_counts_current_uses")


# ── Druid: Starry Form, Wrath of the Sea, Dragon min roll ───────────────────

ARCHER, CHALICE, DRAGON = 1, 2, 3
PHYS = (0, 1, 2)          # bludgeoning, piercing, slashing
SEA = (1, 4, 9)           # cold, lightning, thunder


def _druid(level):
    bm, engine, (d,) = _scene(("Druid", 5, 5))
    s = engine.get_agent_stats(bm, d)
    s.set_class_level(rpg.CharacterClass.Druid, level)
    s.initialize_class_resources(rpg.CharacterClass.Druid, level)
    s.speed_walk = 30
    s.speed_fly = 0
    engine.set_agent_stats(bm, d, s)
    return bm, engine, d


def _ws(engine, bm, d):
    return engine.get_agent_stats(bm, d).get_resource("Wild Shape").current


def test_starry_form_low_level():
    bm, engine, d = _druid(3)
    ws0 = _ws(engine, bm, d)
    assert engine.activate_starry_form(bm, d, DRAGON)
    s = engine.get_agent_stats(bm, d)
    assert s.starry_form_active and s.starry_constellation == DRAGON
    assert _ws(engine, bm, d) == ws0 - 1, "spends a Wild Shape use"
    assert s.speed_fly == 0, "no Dragon flight below L10"
    assert all(s.get_physical_damage_multiplier(t) == 1.0 for t in PHYS), "no resistance below L14"
    print("✅ test_starry_form_low_level")


def test_starry_form_l10_dragon_flies():
    bm, engine, d = _druid(10)
    assert engine.activate_starry_form(bm, d, DRAGON)
    s = engine.get_agent_stats(bm, d)
    assert s.speed_fly == 30, "fly speed = walk speed"
    assert all(s.get_physical_damage_multiplier(t) == 1.0 for t in PHYS)

    bm, engine, d = _druid(10)
    assert engine.activate_starry_form(bm, d, ARCHER)
    assert engine.get_agent_stats(bm, d).speed_fly == 0, "only the Dragon flies"
    print("✅ test_starry_form_l10_dragon_flies")


def test_starry_form_l14_resistances_and_deactivate():
    bm, engine, d = _druid(14)
    assert engine.activate_starry_form(bm, d, CHALICE)
    s = engine.get_agent_stats(bm, d)
    assert all(s.get_physical_damage_multiplier(t) == 0.5 for t in PHYS), "Full of Stars: B/P/S"
    assert engine.deactivate_starry_form(bm, d)
    s = engine.get_agent_stats(bm, d)
    assert not s.starry_form_active and s.starry_constellation == 0
    assert s.speed_fly == 0
    assert all(s.get_physical_damage_multiplier(t) == 1.0 for t in PHYS)
    print("✅ test_starry_form_l14_resistances_and_deactivate")


def test_starry_form_refused():
    bm, engine, d = _druid(3)
    s = engine.get_agent_stats(bm, d)
    ws = s.get_resource("Wild Shape"); ws.current = 0
    s.resources["Wild Shape"] = ws
    engine.set_agent_stats(bm, d, s)
    assert not engine.activate_starry_form(bm, d, DRAGON), "no Wild Shape use"
    assert not engine.get_agent_stats(bm, d).starry_form_active
    assert not engine.activate_starry_form(bm, 99, DRAGON)
    assert not engine.deactivate_starry_form(bm, 99)
    print("✅ test_starry_form_refused")


def test_wrath_of_sea():
    bm, engine, d = _druid(3)
    ws0 = _ws(engine, bm, d)
    assert engine.activate_wrath_of_sea(bm, d)
    s = engine.get_agent_stats(bm, d)
    assert s.wrath_of_sea_active and _ws(engine, bm, d) == ws0 - 1
    assert s.speed_fly == 0 and all(s.get_magic_damage_multiplier(t) == 1.0 for t in SEA)

    bm, engine, d = _druid(10)
    assert engine.activate_wrath_of_sea(bm, d)
    s = engine.get_agent_stats(bm, d)
    assert s.speed_fly == 30, "Stormborn: fly speed"
    assert all(s.get_magic_damage_multiplier(t) == 0.5 for t in SEA), "Stormborn: cold/lightning/thunder"
    assert engine.deactivate_wrath_of_sea(bm, d)
    s = engine.get_agent_stats(bm, d)
    assert not s.wrath_of_sea_active and s.speed_fly == 0
    assert all(s.get_magic_damage_multiplier(t) == 1.0 for t in SEA)
    print("✅ test_wrath_of_sea")


def test_wrath_of_sea_refused():
    bm, engine, d = _druid(10)
    s = engine.get_agent_stats(bm, d)
    ws = s.get_resource("Wild Shape"); ws.current = 0
    s.resources["Wild Shape"] = ws
    engine.set_agent_stats(bm, d, s)
    assert not engine.activate_wrath_of_sea(bm, d)
    s = engine.get_agent_stats(bm, d)
    assert not s.wrath_of_sea_active and s.speed_fly == 0
    assert not engine.activate_wrath_of_sea(bm, 99)
    assert not engine.deactivate_wrath_of_sea(bm, 99)
    print("✅ test_wrath_of_sea_refused")


def test_dragon_min_roll():
    bm, engine, d = _druid(10)
    assert engine.apply_dragon_min_roll(bm, d, 3) == 3, "not in Starry Form"
    engine.activate_starry_form(bm, d, DRAGON)
    assert engine.apply_dragon_min_roll(bm, d, 3) == 10, "Dragon: 9 or lower counts as 10"
    assert engine.apply_dragon_min_roll(bm, d, 10) == 10
    assert engine.apply_dragon_min_roll(bm, d, 17) == 17
    assert engine.apply_dragon_min_roll(bm, 99, 3) == 3

    bm, engine, d = _druid(10)
    engine.activate_starry_form(bm, d, ARCHER)
    assert engine.apply_dragon_min_roll(bm, d, 3) == 3, "another constellation"
    print("✅ test_dragon_min_roll")


if __name__ == "__main__":
    test_vanish_living_ranger_keeps_companion()
    test_vanish_dead_ranger()
    test_vanish_removed_or_missing_ranger()
    test_misty_ally_cell_first_free()
    test_misty_ally_cell_skips_occupied_and_edge()
    test_misty_ally_cell_bad_index()
    test_is_misty_ally_cell()
    test_precision_turns_near_miss_into_hit()
    test_precision_far_miss_stays_miss()
    test_precision_refused()
    test_can_peerless_aim()
    test_sentinel_guard()
    test_open_hand_knockdown()
    test_open_hand_push()
    test_open_hand_deny_reaction()
    test_open_hand_refused()
    test_consume_bonus_attack()
    test_light_tick_expiry_reevaluates_blinding()
    test_light_tick_no_expiry_no_reevaluation()
    test_light_tick_sources()
    test_regenerate_portent_dice()
    test_regenerate_portent_dice_counts_current_uses()
    test_starry_form_low_level()
    test_starry_form_l10_dragon_flies()
    test_starry_form_l14_resistances_and_deactivate()
    test_starry_form_refused()
    test_wrath_of_sea()
    test_wrath_of_sea_refused()
    test_dragon_min_roll()
    print("\nAll unnamed-binding direct-call tests passed ✅")
