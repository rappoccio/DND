#!/usr/bin/env python3
"""
Ranger subclasses — the gap-closing phases of plans/RANGER_SUBCLASSES_PLAN.md.

R1 — Hunter (D10):
  · Horde Breaker arms on making a weapon attack, hit OR miss, only on the Hunter's own turn,
    remembering the original target and weapon.
  · horde_breaker_targets: within 5 ft of the original target, not it, not attacked this turn,
    in reach of the armed weapon; empty once used.
  · The NpcDriver takes the extra attack after its attack loop (automated Hunters).
  · Superior Hunter's Defense: Resistance to the triggering damage type until the end of the
    current turn (cleared as the next turn begins).
  · Hunter's Lore: marking a creature logs its immunities / resistances / vulnerabilities.

R2 — Gloom Stalker (D3–D6 + the spell list):
  · Gloom Stalker Spells are always prepared at L3/5/9/13/17.
  · Dreadful Strike is offered on a weapon hit; the NpcDriver spends it, and at L11 takes Sudden
    Strike when a second target stands within 5 ft, else Mass Fear.
  · Mass Fear: the target and each other creature within 10 ft (allies too, never the Ranger).
  · Ambusher's Leap: +10 ft walk on the first turn of combat only.
  · Umbral Sight: Darkvision 60 / +60 (once); Invisible in Darkness to Darkvision-only viewers.
  · Shadowy Dodge: a pre-roll reaction (Disadvantage), then a ≤30 ft teleport — parked for the
    GUI/arena, inline for a decider; the automated cell is out of every enemy's reach or sight.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

SLASHING = 2   # PhysicalDamage_t::Slashing
FIRE     = 2   # MagicDamage_t::Fire


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _place(engine, bm, name, col, row, faction=0):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    if faction:
        bm.set_agent_faction(idx, faction)
    return idx


def _weapon(name="Sword", bonus_hit=50, bonus_damage=0):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = bonus_hit
    w.bonus_damage = bonus_damage
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 1
    pr.die_size = 6
    w.physical_damage_types = [pr]
    return w


def _hp(engine, bm, idx, hp=400, ac=10):
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = hp
    s.hp_cur = hp
    s.base_ac = ac
    engine.set_agent_stats(bm, idx, s)


def _make_hunter(engine, bm, idx, level, prey=None, weapon=None):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Ranger, level)
    s.ranger_subclass = rpg.RangerSubclass.Hunter
    if prey is not None:
        s.hunter_prey = prey
    s.str = 14
    s.prof_bonus = 2 + (level - 1) // 4
    s.hp_max = 200
    s.hp_cur = 200
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [weapon or _weapon(), rpg.Weapon(), rpg.Weapon()])


def _attack(engine, bm, a, t):
    return engine.execute_action(bm, rpg.Attack(a, t, 0))


def _horde(engine, bm, a, level=3):
    _make_hunter(engine, bm, a, level, prey=rpg.HunterPrey.HordeBreaker)


# ─────────────────────────────────────────────────────────────────────────────
#  R1 — Horde Breaker
# ─────────────────────────────────────────────────────────────────────────────

def test_horde_breaker_arms_on_a_miss():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Hunter", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    _horde(engine, bm, a)
    _hp(engine, bm, t, ac=999)                         # every swing misses
    r = _attack(engine, bm, a, t)
    assert r.valid and not r.hit, "the attack should miss"
    c = engine.get_agent_conditions(bm, a)
    assert c.horde_breaker_available, "Horde Breaker triggers on making an attack — a miss counts"
    assert c.horde_breaker_origin == t and c.horde_breaker_weapon == 0
    assert t in list(c.attacked_this_turn)
    print("✅ test_horde_breaker_arms_on_a_miss")


def test_horde_breaker_only_on_own_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Hunter", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    _horde(engine, bm, a)
    _hp(engine, bm, t)
    engine.begin_turn(bm, t)                           # the quarry's turn: an OA-style swing
    _attack(engine, bm, a, t)
    assert not engine.get_agent_conditions(bm, a).horde_breaker_available, \
        "Horde Breaker is once on each of YOUR turns — not on another creature's"
    engine.begin_turn(bm, a)
    _attack(engine, bm, a, t)
    assert engine.get_agent_conditions(bm, a).horde_breaker_available, "armed on the Hunter's own turn"
    print("✅ test_horde_breaker_only_on_own_turn")


def test_horde_breaker_not_on_an_opportunity_attack():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Hunter", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    _horde(engine, bm, a)
    _hp(engine, bm, t)
    act = rpg.Attack(a, t, 0)
    act.opportunity = True
    engine.execute_action(bm, act)
    assert not engine.get_agent_conditions(bm, a).horde_breaker_available
    print("✅ test_horde_breaker_not_on_an_opportunity_attack")


def test_horde_breaker_targets():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a     = _place(engine, bm, "Hunter", 5, 5)
    t     = _place(engine, bm, "Quarry", 5, 6)
    near  = _place(engine, bm, "Near", 6, 6)           # within 5 ft of t AND in the Hunter's reach
    far   = _place(engine, bm, "Far", 9, 9)            # nowhere near t
    nbr_t = _place(engine, bm, "Behind", 5, 7)         # within 5 ft of t, out of the Hunter's reach
    _horde(engine, bm, a)
    for i in (t, near, far, nbr_t):
        _hp(engine, bm, i)
    assert list(engine.horde_breaker_targets(bm, a)) == [], "nothing before an attack arms it"
    _attack(engine, bm, a, t)
    assert list(engine.horde_breaker_targets(bm, a)) == [near], list(engine.horde_breaker_targets(bm, a))

    # A creature already attacked this turn is not eligible.
    c = engine.get_agent_conditions(bm, a)
    c.attacked_this_turn = list(c.attacked_this_turn) + [near]
    engine.set_agent_conditions(bm, a, c)
    assert list(engine.horde_breaker_targets(bm, a)) == []

    # Used → empty, even with a valid creature.
    c.attacked_this_turn = [t]
    c.horde_breaker_used = True
    engine.set_agent_conditions(bm, a, c)
    assert list(engine.horde_breaker_targets(bm, a)) == []
    print("✅ test_horde_breaker_targets")


def test_horde_breaker_used_does_not_rearm():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Hunter", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    _horde(engine, bm, a)
    _hp(engine, bm, t)
    c = engine.get_agent_conditions(bm, a)
    c.horde_breaker_used = True
    engine.set_agent_conditions(bm, a, c)
    _attack(engine, bm, a, t)
    assert not engine.get_agent_conditions(bm, a).horde_breaker_available
    print("✅ test_horde_breaker_used_does_not_rearm")


def test_horde_breaker_turn_reset():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Hunter", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    _horde(engine, bm, a)
    _hp(engine, bm, t)
    _attack(engine, bm, a, t)
    engine.begin_turn(bm, a)
    c = engine.get_agent_conditions(bm, a)
    assert not c.horde_breaker_available and not c.horde_breaker_used
    assert c.horde_breaker_origin == -1 and list(c.attacked_this_turn) == []
    print("✅ test_horde_breaker_turn_reset")


def test_npc_driver_takes_horde_breaker():
    """An automated Hunter (L3, one attack) swings at its target, then takes the Horde Breaker
    extra attack against the other enemy standing next to that target."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a  = _place(engine, bm, "Hunter", 5, 5, faction=1)
    t1 = _place(engine, bm, "Goblin A", 5, 6, faction=2)
    t2 = _place(engine, bm, "Goblin B", 6, 6, faction=2)
    _horde(engine, bm, a)
    for i in (t1, t2):
        _hp(engine, bm, i, hp=300)
    engine.begin_turn(bm, a)
    status = engine.run_npc_turn(bm, a)
    assert status == rpg.FlowStatus.Completed, status
    c = engine.get_agent_conditions(bm, a)
    assert sorted(c.attacked_this_turn) == sorted([t1, t2]), \
        f"both goblins should have been attacked, got {list(c.attacked_this_turn)}"
    assert c.horde_breaker_used and not c.horde_breaker_available
    print("✅ test_npc_driver_takes_horde_breaker")


def test_npc_driver_no_horde_breaker_without_a_second_target():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a  = _place(engine, bm, "Hunter", 5, 5, faction=1)
    t1 = _place(engine, bm, "Goblin A", 5, 6, faction=2)
    _horde(engine, bm, a)
    _hp(engine, bm, t1, hp=300)
    engine.begin_turn(bm, a)
    engine.run_npc_turn(bm, a)
    c = engine.get_agent_conditions(bm, a)
    assert list(c.attacked_this_turn) == [t1] and not c.horde_breaker_used
    print("✅ test_npc_driver_no_horde_breaker_without_a_second_target")


# ─────────────────────────────────────────────────────────────────────────────
#  R1 — Superior Hunter's Defense: Resistance until the end of the turn
# ─────────────────────────────────────────────────────────────────────────────

class _SHDOnce(rpg.CombatDecider):
    def __init__(self):
        super().__init__()
        self.taken = 0
    def choose_reaction(self, ctx):
        resp = rpg.ReactionResponse(); resp.option = -1
        if ctx.window == rpg.ReactionWindow.OnHit:
            for i, o in enumerate(ctx.options):
                if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "SuperiorHuntersDefense":
                    resp.option = i
                    self.taken += 1
                    break
        return resp


def _land(engine, bm, a, t, tries=40):
    for _ in range(tries):
        r = _attack(engine, bm, a, t)
        if r.hit:
            return r
    raise AssertionError("attack never landed")


def test_superior_hunters_defense_lasts_the_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk    = _place(engine, bm, "Brute", 5, 5)
    hunter = _place(engine, bm, "Hunter", 6, 5)
    engine.set_agent_weapons(bm, atk, [_weapon(bonus_damage=100), rpg.Weapon(), rpg.Weapon()])
    _make_hunter(engine, bm, hunter, 15)
    _hp(engine, bm, hunter, hp=2000)

    dec = _SHDOnce(); engine.set_decider(dec)
    engine.begin_turn(bm, atk)
    _land(engine, bm, atk, hunter)
    assert dec.taken == 1, "the Hunter takes Superior Hunter's Defense on the first hit"
    c = engine.get_agent_conditions(bm, hunter)
    assert c.shd_resist_physical_mask & (1 << SLASHING), "Slashing is resisted for the rest of the turn"

    # Same turn, reaction spent: the next Slashing hit is still halved by the Resistance.
    r2 = _land(engine, bm, atk, hunter)
    assert dec.taken == 1, "no second reaction"
    assert r2.total_damage <= (106 + 2) // 2 + 1, f"second hit should be resisted, dealt {r2.total_damage}"

    # The next turn begins → the Resistance is gone.
    engine.begin_turn(bm, hunter)
    c = engine.get_agent_conditions(bm, hunter)
    assert c.shd_resist_physical_mask == 0 and c.shd_resist_magic_mask == 0
    c.reaction_used = True                              # keep the reaction out of the next hit
    engine.set_agent_conditions(bm, hunter, c)
    r3 = _land(engine, bm, atk, hunter)
    assert r3.total_damage >= 100, f"no Resistance once the turn has ended, dealt {r3.total_damage}"
    engine.set_decider(None)
    print("✅ test_superior_hunters_defense_lasts_the_turn")


# ─────────────────────────────────────────────────────────────────────────────
#  R1 — Hunter's Lore
# ─────────────────────────────────────────────────────────────────────────────

def _hunters_mark_spell():
    sp = rpg.Spell()
    sp.name = "Hunter's Mark"
    sp.level = 1
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 90
    sp.duration = 1
    sp.requires_concentration = True
    return sp


def _mark(engine, bm, ranger, quarry):
    engine.set_agent_spells(bm, ranger, [_hunters_mark_spell()])
    rs = engine.get_agent_stats(bm, ranger)
    rs.spell_slots_remaining = [9, 0, 0, 0, 0, 0, 0, 0, 0]
    rs.spellcasting_ability = 4
    engine.set_agent_stats(bm, ranger, rs)
    action = rpg.SpellAction()
    action.caster_idx = ranger
    action.spell_idx = 0
    action.target_indices = [quarry]
    engine.resolve_cast(bm, action)


def test_hunters_lore_logs_the_quarry():
    bm = setup_battle_map(); engine = setup_combat_engine()
    logger = rpg.MessageLogger(); engine.set_logger(logger)
    ranger = _place(engine, bm, "Ranger", 5, 5)
    quarry = _place(engine, bm, "Quarry", 6, 5)
    _make_hunter(engine, bm, ranger, 3)
    qs = engine.get_agent_stats(bm, quarry)
    pm = list(qs.physical_damage_multipliers); pm[SLASHING] = 0.5
    mm = list(qs.magic_damage_multipliers); mm[FIRE] = 0.0; mm[7] = 2.0   # Fire immune, Psychic vuln
    qs.physical_damage_multipliers = pm
    qs.magic_damage_multipliers = mm
    engine.set_agent_stats(bm, quarry, qs)
    logger.flush()
    _mark(engine, bm, ranger, quarry)
    lore = [ln for ln in logger.flush() if "Hunter's Lore" in ln]
    assert len(lore) == 1, lore
    assert "Immunities: Fire" in lore[0] and "Resistances: Slashing" in lore[0] \
        and "Vulnerabilities: Psychic" in lore[0], lore[0]
    print("✅ test_hunters_lore_logs_the_quarry")


def test_hunters_lore_not_for_other_rangers():
    bm = setup_battle_map(); engine = setup_combat_engine()
    logger = rpg.MessageLogger(); engine.set_logger(logger)
    ranger = _place(engine, bm, "Ranger", 5, 5)
    quarry = _place(engine, bm, "Quarry", 6, 5)
    s = engine.get_agent_stats(bm, ranger)
    s.set_class_level(rpg.CharacterClass.Ranger, 5)
    s.ranger_subclass = rpg.RangerSubclass.GloomStalker
    engine.set_agent_stats(bm, ranger, s)
    logger.flush()
    _mark(engine, bm, ranger, quarry)
    assert not [ln for ln in logger.flush() if "Hunter's Lore" in ln]
    print("✅ test_hunters_lore_not_for_other_rangers")


# ─────────────────────────────────────────────────────────────────────────────
#  R2 — Gloom Stalker
# ─────────────────────────────────────────────────────────────────────────────

def _make_gloom(engine, bm, idx, level, wis=16):
    s = engine.get_agent_stats(bm, idx)
    s.wis = wis
    s.set_class_level(rpg.CharacterClass.Ranger, level)
    s.ranger_subclass = rpg.RangerSubclass.GloomStalker
    s.initialize_class_resources(rpg.CharacterClass.Ranger, level)
    s.str = 14
    s.prof_bonus = 2 + (level - 1) // 4
    s.hp_max = 200
    s.hp_cur = 200
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [_weapon(), rpg.Weapon(), rpg.Weapon()])


def _dread_left(engine, bm, idx):
    return engine.get_agent_stats(bm, idx).get_resource("Dread Ambusher").current


def _timid(engine, bm, idx):
    """A creature that always fails a WIS save against a Gloom Stalker's DC."""
    s = engine.get_agent_stats(bm, idx)
    s.wis = 1
    engine.set_agent_stats(bm, idx, s)


def test_gloom_stalker_spells_always_prepared():
    import json
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import main
    table = main.App._RANGER_SUBCLASS_SPELLS["GloomStalker"]
    assert table == {3: ["Disguise Self"], 5: ["Rope Trick"], 9: ["Fear"],
                     13: ["Greater Invisibility"], 17: ["Seeming"]}, table
    gui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui")
    with open(os.path.join(gui, "spells.json")) as f:
        data = json.load(f)
    names = {sp.get("name") for sp in (data if isinstance(data, list) else data.get("spells", []))}
    missing = [n for lst in table.values() for n in lst if n not in names]
    assert not missing, f"Gloom Stalker spells missing from spells.json: {missing}"
    print("✅ test_gloom_stalker_spells_always_prepared")


def test_npc_driver_spends_dreadful_strike():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Stalker", 5, 5, faction=1)
    t = _place(engine, bm, "Goblin", 5, 6, faction=2)
    _make_gloom(engine, bm, a, 3)
    _hp(engine, bm, t, hp=300)
    engine.begin_turn(bm, a)
    assert engine.run_npc_turn(bm, a) == rpg.FlowStatus.Completed
    c = engine.get_agent_conditions(bm, a)
    assert c.dreadful_strike_used and not c.dreadful_strike_available, "the hit's Dreadful Strike is spent"
    assert _dread_left(engine, bm, a) == 2, "one use spent"
    assert engine.get_agent_stats(bm, t).hp_cur < 300
    print("✅ test_npc_driver_spends_dreadful_strike")


def test_npc_driver_takes_sudden_strike():
    """An automated L11 Gloom Stalker with a second enemy next to its target takes Sudden Strike."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a  = _place(engine, bm, "Stalker", 5, 5, faction=1)
    t1 = _place(engine, bm, "Goblin A", 5, 6, faction=2)
    t2 = _place(engine, bm, "Goblin B", 6, 6, faction=2)
    _make_gloom(engine, bm, a, 11)
    for i in (t1, t2):
        _hp(engine, bm, i, hp=300)
    engine.begin_turn(bm, a)
    assert engine.run_npc_turn(bm, a) == rpg.FlowStatus.Completed
    c = engine.get_agent_conditions(bm, a)
    assert sorted(c.attacked_this_turn) == sorted([t1, t2]), list(c.attacked_this_turn)
    assert not c.sudden_strike_available and not c.stalkers_flurry_pending
    assert not engine.get_agent_conditions(bm, t1).frightened, "Sudden Strike was chosen, not Mass Fear"
    print("✅ test_npc_driver_takes_sudden_strike")


def test_npc_driver_falls_back_to_mass_fear():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Stalker", 5, 5, faction=1)
    t = _place(engine, bm, "Goblin", 5, 6, faction=2)
    _make_gloom(engine, bm, a, 11, wis=20)
    _hp(engine, bm, t, hp=300)
    _timid(engine, bm, t)
    engine.begin_turn(bm, a)
    engine.run_npc_turn(bm, a)
    assert engine.get_agent_conditions(bm, t).frightened, "no second target → Mass Fear"
    print("✅ test_npc_driver_falls_back_to_mass_fear")


def test_mass_fear_radius_and_allies():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a    = _place(engine, bm, "Stalker", 5, 5, faction=1)
    t    = _place(engine, bm, "Goblin", 5, 6, faction=2)
    ally = _place(engine, bm, "Friend", 7, 6, faction=1)    # 10 ft from the target
    far  = _place(engine, bm, "Far Goblin", 9, 6, faction=2)  # 20 ft away
    _make_gloom(engine, bm, a, 11, wis=20)
    for i in (t, ally, far):
        _hp(engine, bm, i)
        _timid(engine, bm, i)
    n = engine.apply_mass_fear(bm, a, t)
    assert n == 2, n
    assert engine.get_agent_conditions(bm, t).frightened
    assert engine.get_agent_conditions(bm, ally).frightened, "each creature within 10 ft — allies too"
    assert not engine.get_agent_conditions(bm, far).frightened
    assert not engine.get_agent_conditions(bm, a).frightened, "never the Ranger itself"
    engine.tick_agent_conditions_for_caster(bm, a)            # the Ranger's next turn begins
    assert not engine.get_agent_conditions(bm, t).frightened, "lasts until the start of the Ranger's next turn"
    print("✅ test_mass_fear_radius_and_allies")


def test_ambushers_leap_first_turn_only():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Stalker", 5, 5)
    _make_gloom(engine, bm, a, 3)
    base = engine.get_agent_stats(bm, a).speed_walk
    engine.begin_turn(bm, a)
    assert engine.get_agent_conditions(bm, a).ambushers_leap
    assert engine.get_walk_remaining(a) == base + 10, engine.get_walk_remaining(a)
    engine.begin_turn(bm, a)
    assert not engine.get_agent_conditions(bm, a).ambushers_leap
    assert engine.get_walk_remaining(a) == base
    print("✅ test_ambushers_leap_first_turn_only")


def test_umbral_sight_darkvision_once():
    s = rpg.Stats()
    s.set_class_level(rpg.CharacterClass.Ranger, 3)
    s.ranger_subclass = rpg.RangerSubclass.GloomStalker
    s.darkvision_range = 0
    s.initialize_class_resources(rpg.CharacterClass.Ranger, 3)
    assert s.darkvision_range == 60 and s.umbral_sight_dv
    s2 = rpg.Stats()
    s2.set_class_level(rpg.CharacterClass.Ranger, 3)
    s2.ranger_subclass = rpg.RangerSubclass.GloomStalker
    s2.darkvision_range = 60
    s2.initialize_class_resources(rpg.CharacterClass.Ranger, 3)
    assert s2.darkvision_range == 120, "+60 when it already has Darkvision"
    s2.initialize_class_resources(rpg.CharacterClass.Ranger, 3)
    assert s2.darkvision_range == 120, "a re-init (save/load) doesn't stack it"
    print("✅ test_umbral_sight_darkvision_once")


def _umbral_scene():
    bm = setup_battle_map(); engine = setup_combat_engine()
    r = _place(engine, bm, "Stalker", 5, 5, faction=1)
    o = _place(engine, bm, "Orc", 5, 6, faction=2)
    _make_gloom(engine, bm, r, 3)
    _hp(engine, bm, o)
    engine.set_agent_weapons(bm, o, [_weapon(), rpg.Weapon(), rpg.Weapon()])
    so = engine.get_agent_stats(bm, o)
    so.darkvision_range = 60; so.blindsight_range = 0; so.truesight_range = 0; so.devilssight_range = 0
    engine.set_agent_stats(bm, o, so)
    return bm, engine, r, o


def test_umbral_sight_hides_in_darkness():
    bm, engine, r, o = _umbral_scene()
    assert not engine.umbral_sight_hides(bm, o, r), "bright light: plain view"
    bm.set_light_level(rpg.Cell(5, 5), rpg.VisibilityLevel.Dark)
    assert engine.umbral_sight_hides(bm, o, r), "Darkness + a Darkvision-only viewer"
    ra = engine.execute_action(bm, rpg.Attack(o, r, 0))
    assert ra.disadvantage, "attacks against the unseen Ranger have Disadvantage"
    rr = engine.execute_action(bm, rpg.Attack(r, o, 0))
    assert rr.advantage, "the unseen Ranger's attacks have Advantage"
    so = engine.get_agent_stats(bm, o); so.blindsight_range = 10; engine.set_agent_stats(bm, o, so)
    assert not engine.umbral_sight_hides(bm, o, r), "Blindsight doesn't rely on Darkvision"
    so.blindsight_range = 0; so.darkvision_range = 0; engine.set_agent_stats(bm, o, so)
    assert not engine.umbral_sight_hides(bm, o, r), "no Darkvision: it doesn't rely on Darkvision"
    print("✅ test_umbral_sight_hides_in_darkness")


def _dodge_scene(level=15):
    bm = setup_battle_map(); engine = setup_combat_engine()
    r = _place(engine, bm, "Stalker", 5, 5, faction=1)
    o = _place(engine, bm, "Orc", 5, 6, faction=2)
    _make_gloom(engine, bm, r, level)
    _hp(engine, bm, o)
    engine.set_agent_weapons(bm, o, [_weapon(), rpg.Weapon(), rpg.Weapon()])
    return bm, engine, r, o


def _option(ctx, feature):
    return next(i for i, op in enumerate(ctx.options) if op.feature == feature)


def _skip(ctx):
    return next(i for i, op in enumerate(ctx.options) if op.kind == rpg.ReactionOptionKind.Skip)


def test_shadowy_dodge_parked_windows():
    bm, engine, r, o = _dodge_scene()
    status = engine.begin_attack(bm, rpg.Attack(o, r, 0))
    pd = engine.pending_decision()
    assert status == rpg.FlowStatus.AwaitingDecision and pd.ctx.window == rpg.ReactionWindow.OnAttackDeclared
    assert pd.ctx.reactor_idx == r and pd.ctx.source_idx == o
    resp = rpg.ReactionResponse(); resp.option = _option(pd.ctx, "ShadowyDodge")
    status = engine.submit_decision(bm, resp)
    assert engine.last_attack_result().disadvantage, "Shadowy Dodge imposes Disadvantage on the roll"
    assert engine.get_agent_conditions(bm, r).reaction_used
    pd = engine.pending_decision()
    assert status == rpg.FlowStatus.AwaitingDecision and pd.ctx.window == rpg.ReactionWindow.AfterAttack
    expect = engine.shadowy_dodge_destination(bm, r)
    assert expect.col >= 0
    resp = rpg.ReactionResponse(); resp.option = _option(pd.ctx, "ShadowyDodgeTeleport")
    assert engine.submit_decision(bm, resp) == rpg.FlowStatus.Completed
    at = bm.placed_agents[r].origin
    assert (at.col, at.row) == (expect.col, expect.row), "teleported to the safe cell"
    assert max(abs(at.col - 5), abs(at.row - 6)) > 1, "out of the orc's reach"
    print("✅ test_shadowy_dodge_parked_windows")


def test_shadowy_dodge_picked_cell_and_skip():
    bm, engine, r, o = _dodge_scene()
    engine.begin_attack(bm, rpg.Attack(o, r, 0))
    resp = rpg.ReactionResponse(); resp.option = _option(engine.pending_decision().ctx, "ShadowyDodge")
    engine.submit_decision(bm, resp)
    ctx = engine.pending_decision().ctx
    assert not engine.is_shadowy_dodge_destination(bm, r, rpg.Cell(5, 6)), "occupied"
    assert not engine.is_shadowy_dodge_destination(bm, r, rpg.Cell(5, 12)), "beyond 30 ft"
    resp = rpg.ReactionResponse(); resp.option = _option(ctx, "ShadowyDodgeTeleportPick")
    resp.cell_col, resp.cell_row = 8, 5
    engine.submit_decision(bm, resp)
    at = bm.placed_agents[r].origin
    assert (at.col, at.row) == (8, 5), (at.col, at.row)

    bm, engine, r, o = _dodge_scene()
    engine.begin_attack(bm, rpg.Attack(o, r, 0))
    resp = rpg.ReactionResponse(); resp.option = _skip(engine.pending_decision().ctx)
    status = engine.submit_decision(bm, resp)
    assert status == rpg.FlowStatus.Completed, "skipped: no teleport window"
    assert not engine.last_attack_result().disadvantage
    assert not engine.get_agent_conditions(bm, r).reaction_used
    print("✅ test_shadowy_dodge_picked_cell_and_skip")


class _TakeAll(rpg.CombatDecider):
    def __init__(self):
        super().__init__()
        self.windows = []
    def choose_reaction(self, ctx):
        self.windows.append(ctx.window)
        resp = rpg.ReactionResponse(); resp.option = -1
        for i, o in enumerate(ctx.options):
            if o.kind == rpg.ReactionOptionKind.Feature:
                resp.option = i
                break
        return resp


def test_shadowy_dodge_inline_with_a_decider():
    bm, engine, r, o = _dodge_scene()
    dec = _TakeAll(); engine.set_decider(dec)
    expect = engine.shadowy_dodge_destination(bm, r)
    res = engine.execute_action(bm, rpg.Attack(o, r, 0))
    engine.set_decider(None)
    assert rpg.ReactionWindow.OnAttackDeclared in dec.windows and rpg.ReactionWindow.AfterAttack in dec.windows
    assert res.disadvantage
    at = bm.placed_agents[r].origin
    assert (at.col, at.row) == (expect.col, expect.row)
    print("✅ test_shadowy_dodge_inline_with_a_decider")


def test_shadowy_dodge_gates():
    bm, engine, r, o = _dodge_scene(level=14)
    assert not engine.can_shadowy_dodge(bm, r, o), "Shadowy Dodge is L15"
    assert engine.begin_attack(bm, rpg.Attack(o, r, 0)) == rpg.FlowStatus.Completed
    bm, engine, r, o = _dodge_scene()
    c = engine.get_agent_conditions(bm, r); c.reaction_used = True; engine.set_agent_conditions(bm, r, c)
    assert not engine.can_shadowy_dodge(bm, r, o), "needs the Reaction"
    bm, engine, r, o = _dodge_scene()
    bm.set_agent_position(r, rpg.Cell(5, 3))                 # 10 ft from the orc: out of its reach
    d = engine.shadowy_dodge_destination(bm, r)
    assert (d.col, d.row) == (-1, -1), "already safe → stay put"
    print("✅ test_shadowy_dodge_gates")


# ─────────────────────────────────────────────────────────────────────────────

def run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\n🎉 All {len(fns)} Ranger subclass tests passed")


if __name__ == "__main__":
    run_all()
