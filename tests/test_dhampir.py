"""Dhampir species: the passive traits, Vampiric Bite and its Drain / Strengthen empowerment.

Covered: set_species applies Speed 35 / Darkvision 60 / Necrotic Resistance and strips them on
a swap; the bite deals 1d4 + CON Piercing; Drain heals by the Piercing dealt and Strengthen holds
it for the next attack roll or ability check (10 rounds), each spending one of PB uses (Long
Rest refills); no empowerment off a Construct or Undead or with no uses left; Rage of the Gods
ending keeps the species' Necrotic Resistance; the GUI offers the bite to a Dhampir only and
routes Drain through the normal attack path. Spider Climb is not modeled.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)

NECROTIC = 5


def _place(engine, bm, name, col, row):
    return add_agent_to_battle(engine, bm, create_test_agent(name, col, row))


def _bite():
    w = rpg.Weapon()
    w.name = "Vampiric Bite"
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.proficient = True
    w.bonus_hit = 50                       # always lands vs AC 10 unless a natural 1
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Piercing
    pr.num_dice = 1
    pr.die_size = 4
    w.physical_damage_types = [pr]
    return w


def _scene(prof=2, con=16, hp_cur=20):
    """A Dhampir (CON +3) biting a 400-HP target next to it."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Dhampir", 5, 5)
    t = _place(engine, bm, "Tgt", 6, 5)
    s = engine.get_agent_stats(bm, a)
    s.con = con
    s.prof_bonus = prof
    s.hp_max = 80
    s.hp_cur = hp_cur
    s.set_species("Dhampir")
    engine.set_agent_stats(bm, a, s)
    engine.set_agent_weapons(bm, a, [_bite(), rpg.Weapon(), rpg.Weapon()])
    ts = engine.get_agent_stats(bm, t)
    ts.hp_max = ts.hp_cur = 400
    ts.base_ac = 10
    engine.set_agent_stats(bm, t, ts)
    return bm, engine, a, t


def _bite_hit(engine, bm, a, t, empower, tries=60):
    """Land a non-critical bite; return (result, the bite's own damage)."""
    for _ in range(tries):
        atk = rpg.Attack(a, t, 0)
        atk.bite_empower = empower
        r = engine.execute_action(bm, atk)
        if r.hit and not r.critical:
            return r, dict(r.damage_breakdown)["weapon"]
        if r.hit and empower:              # a crit still spent a use; give that one back
            s = engine.get_agent_stats(bm, a)
            s.vampiric_bite_used = max(0, s.vampiric_bite_used - 1)
            s.vampiric_strengthen_bonus = 0
            engine.set_agent_stats(bm, a, s)
    raise AssertionError("no non-crit bite landed")


# ─────────────────────────────────────────────────────────────────────────────

def test_species_traits_apply_and_strip():
    s = rpg.Stats()
    s.speed_walk = 30
    s.set_species("Dhampir")
    assert s.is_dhampir() and s.species == "Dhampir"
    assert s.speed_walk == 35 and s.darkvision_range == 60
    assert s.magic_damage_multipliers[NECROTIC] == 0.5
    s.speed_walk = 40                      # a hand edit survives a re-confirm (no-op swap)
    s.set_species("Dhampir")
    assert s.speed_walk == 40
    s.speed_walk = 35
    s.set_species("")
    assert not s.is_dhampir()
    assert s.speed_walk == 30 and s.darkvision_range == 0
    assert s.magic_damage_multipliers[NECROTIC] == 1.0
    print("✅ test_species_traits_apply_and_strip passed")


def test_species_table_records_and_strips_what_it_applied():
    """SPECIES_PLAN.md D1: set_species records what it changed and a swap undoes that record,
    leaving fields it did not set (or that were edited since) alone."""
    assert list(rpg.species_names()) == ["Dhampir"]
    s = rpg.Stats()
    s.speed_walk, s.darkvision_range = 40, 120          # already faster / sharper than Dhampir
    s.set_species("Dhampir")
    a = s.species_applied
    assert (a.speed_from, a.speed_to, a.darkvision_from, a.darkvision_to) == (40, 40, 120, 120)
    assert a.magic_resist_mask == 1 << NECROTIC and a.save_advantage_bits == 0
    s.set_species("")
    assert (s.speed_walk, s.darkvision_range) == (40, 120), "nothing it didn't set is stripped"
    assert s.species_applied.speed_to == 0 and s.species_applied.magic_resist_mask == 0
    s = rpg.Stats()
    s.set_magic_damage_multiplier(NECROTIC, 0.0)        # already immune: left as it is
    s.set_species("Dhampir")
    assert s.magic_damage_multipliers[NECROTIC] == 0.0 and s.species_applied.magic_resist_mask == 0
    s.set_species("")
    assert s.magic_damage_multipliers[NECROTIC] == 0.0
    assert s.species_magic_mult(rpg.MagicDamage.Necrotic) == 1.0
    s.set_species("Dhampir")
    assert s.species_magic_mult(rpg.MagicDamage.Necrotic) == 0.5
    assert s.species_magic_mult(rpg.MagicDamage.Fire) == 1.0
    print("✅ test_species_table_records_and_strips_what_it_applied passed")


def test_restore_species_rebuilds_a_legacy_record():
    """A save from before D1 names the species with no species_applied: restore_species
    rebuilds it, so the later swap still strips Speed 35 / Darkvision 60 / Resistance."""
    from agent_loader import dict_to_stats
    s = dict_to_stats({"species": "Dhampir", "speed_walk": 35,
                       "magic_resistances": ["Necrotic"]})
    a = s.species_applied
    assert (a.speed_from, a.speed_to, a.darkvision_from, a.darkvision_to) == (30, 35, 0, 60)
    s.set_species("")
    assert (s.speed_walk, s.darkvision_range) == (30, 0)
    assert s.magic_damage_multipliers[NECROTIC] == 1.0
    # A record in the save wins over the rebuilt one.
    s = dict_to_stats({"species": "Dhampir", "speed_walk": 35,
                       "species_applied": {"speed_from": 35, "speed_to": 35,
                                           "darkvision_from": 0, "darkvision_to": 60,
                                           "magic_resist_mask": 1 << NECROTIC}})
    assert s.species_applied.speed_from == 35
    s.set_species("")
    assert s.speed_walk == 35, "the saved record said Speed was 35 before the species"
    t = rpg.Stats()
    t.restore_species("")
    assert t.species == "" and t.species_applied.darkvision_to == 0
    print("✅ test_restore_species_rebuilds_a_legacy_record passed")


def test_bite_is_1d4_plus_con_piercing():
    bm, engine, a, t = _scene(con=16)
    r, dmg = _bite_hit(engine, bm, a, t, empower=0)
    assert 4 <= dmg <= 7, f"1d4 + CON(3) in [4,7], got {dmg}"
    assert rpg.PhysicalDamage.Piercing in list(r.physical_damage_types)
    assert engine.get_agent_stats(bm, a).vampiric_bite_used == 0, "no empowerment, no use spent"
    print("✅ test_bite_is_1d4_plus_con_piercing passed")


def test_drain_heals_and_spends_a_use():
    bm, engine, a, t = _scene(hp_cur=20)
    _, dmg = _bite_hit(engine, bm, a, t, empower=1)
    s = engine.get_agent_stats(bm, a)
    assert s.hp_cur == 20 + dmg, f"Drain heals the Piercing dealt ({dmg}): hp {s.hp_cur}"
    assert s.vampiric_bite_used == 1 and s.vampiric_bite_remaining() == 1
    print("✅ test_drain_heals_and_spends_a_use passed")


def test_strengthen_lands_on_the_next_attack_roll():
    bm, engine, a, t = _scene()
    _, dmg = _bite_hit(engine, bm, a, t, empower=2)
    s = engine.get_agent_stats(bm, a)
    assert s.vampiric_strengthen_bonus == dmg and s.vampiric_strengthen_turns == 10
    r = engine.execute_action(bm, rpg.Attack(a, t, 0))
    assert r.total_roll == r.d20 + r.attack_mod + dmg, \
        f"next roll carries +{dmg}: {r.d20}+{r.attack_mod} -> {r.total_roll}"
    assert engine.get_agent_stats(bm, a).vampiric_strengthen_bonus == 0, "spent on that roll"
    print("✅ test_strengthen_lands_on_the_next_attack_roll passed")


def test_strengthen_lands_on_an_ability_check():
    bm, engine, a, t = _scene()
    s = engine.get_agent_stats(bm, a)
    s.vampiric_strengthen_bonus = 30
    s.vampiric_strengthen_turns = 10
    engine.set_agent_stats(bm, a, s)
    c = engine.get_agent_conditions(bm, a)
    c.grappled = True
    c.grappler_idx = t
    c.grapple_escape_dc = 25
    engine.set_agent_conditions(bm, a, c)
    res = engine.execute_grapple_escape(bm, a)
    assert res.success and res.escape_roll >= 31, f"+30 on the escape check: {res.escape_roll}"
    assert engine.get_agent_stats(bm, a).vampiric_strengthen_bonus == 0
    print("✅ test_strengthen_lands_on_an_ability_check passed")


def test_strengthen_fades_after_a_minute():
    bm, engine, a, t = _scene()
    s = engine.get_agent_stats(bm, a)
    s.vampiric_strengthen_bonus = 4
    s.vampiric_strengthen_turns = 1
    engine.set_agent_stats(bm, a, s)
    engine.begin_turn(bm, a)
    s = engine.get_agent_stats(bm, a)
    assert s.vampiric_strengthen_bonus == 0 and s.vampiric_strengthen_turns == 0
    print("✅ test_strengthen_fades_after_a_minute passed")


def test_no_empowerment_off_undead_or_construct():
    for flag in ("is_undead", "is_construct"):
        bm, engine, a, t = _scene(hp_cur=20)
        ts = engine.get_agent_stats(bm, t)
        setattr(ts, flag, True)
        engine.set_agent_stats(bm, t, ts)
        _bite_hit(engine, bm, a, t, empower=1)
        s = engine.get_agent_stats(bm, a)
        assert s.hp_cur == 20 and s.vampiric_bite_used == 0, f"{flag}: bite must not empower"
    print("✅ test_no_empowerment_off_undead_or_construct passed")


def test_uses_run_out_and_long_rest_refills():
    bm, engine, a, t = _scene(prof=2, hp_cur=20)
    for _ in range(2):
        _bite_hit(engine, bm, a, t, empower=2)
    s = engine.get_agent_stats(bm, a)
    assert s.vampiric_bite_remaining() == 0
    s.vampiric_strengthen_bonus = 0
    engine.set_agent_stats(bm, a, s)
    _bite_hit(engine, bm, a, t, empower=1)
    s = engine.get_agent_stats(bm, a)
    assert s.vampiric_bite_used == 2 and s.hp_cur == 20, "out of uses: the bite lands, no Drain"
    engine.apply_long_rest(bm)
    assert engine.get_agent_stats(bm, a).vampiric_bite_remaining() == 2
    print("✅ test_uses_run_out_and_long_rest_refills passed")


def test_rage_of_the_gods_end_keeps_species_resistance():
    bm, engine, a, t = _scene()
    c = engine.get_agent_conditions(bm, a)
    c.raging = True
    c.rage_of_gods_active = True
    engine.set_agent_conditions(bm, a, c)
    engine.end_rage(bm, a)
    assert engine.get_agent_stats(bm, a).magic_damage_multipliers[NECROTIC] == 0.5, \
        "the divine form ending must not take the Dhampir's own Necrotic Resistance"
    print("✅ test_rage_of_the_gods_end_keeps_species_resistance passed")


def test_loader_round_trip():
    from agent_loader import dict_to_stats
    s = dict_to_stats({"species": "Dhampir", "vampiric_bite_used": 1,
                       "vampiric_strengthen_bonus": 3, "vampiric_strengthen_turns": 7,
                       "is_construct": False})
    assert s.is_dhampir() and s.darkvision_range == 60, "darkvision re-derived from the species"
    assert (s.vampiric_bite_used, s.vampiric_strengthen_bonus, s.vampiric_strengthen_turns) == (1, 3, 7)
    assert dict_to_stats({"is_construct": True}).is_construct
    print("✅ test_loader_round_trip passed")


def test_gui_offers_the_bite_and_drains():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from actions import ActionMenu, GROUP_ACTION
    from test_combat_panel import App, MAP_PATH, SEED, _build_scene, _idx, _goto

    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    aria = _goto(app, "Aria")
    skarn = _idx(app, "Skarn")

    def offered():
        return [x.id for x in ActionMenu.build(app, aria) if x.group == GROUP_ACTION]

    assert "vampiric_bite" not in offered(), "only a Dhampir bites"
    s = app.combat.get_agent_stats(app.bm, aria)
    s.set_species("Dhampir")
    s.hp_cur = max(1, s.hp_max - 30)
    app.combat.set_agent_stats(app.bm, aria, s)
    ids = offered()
    assert ids.index("vampiric_bite") == ids.index("unarmed") + 1, ids
    assert hasattr(app, "btn_cbt_vampiric_bite")
    ts = app.combat.get_agent_stats(app.bm, skarn)
    ts.base_ac = 1
    ts.hp_max = ts.hp_cur = 500
    ts.is_undead = ts.is_construct = False
    app.combat.set_agent_stats(app.bm, skarn, ts)

    names = [w.name for w in app.combat.get_agent_weapons(app.bm, aria)]
    for _ in range(20):
        _goto(app, "Aria")
        app._start_vampiric_bite(1)
        assert app.combat.get_agent_weapons(app.bm, aria)[0].name == "Vampiric Bite"
        assert app.pending_bite_empower == 1
        hp0 = app.combat.get_agent_stats(app.bm, aria).hp_cur
        app._resolve_combat_attack(skarn)
        r = app.combat.last_attack_result()
        if r.hit:
            break
    assert r.hit, "the bite never landed"
    s = app.combat.get_agent_stats(app.bm, aria)
    assert s.vampiric_bite_used == 1, "Drain spent a use"
    assert s.hp_cur > hp0, f"Drain healed: {hp0} -> {s.hp_cur}"
    assert [w.name for w in app.combat.get_agent_weapons(app.bm, aria)] == names, "weapons restored"
    assert app.pending_bite_empower == 0
    print("✅ test_gui_offers_the_bite_and_drains passed")


def test_gui_stats_ok_applies_species():
    """The Stats dialog's OK: species "Dhampir" applies the traits; "NONE" strips them; a
    legacy caller passing no species leaves it alone."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    from main import App
    from dialogs import StatsDialog
    from test_combat_panel import MAP_PATH, SEED, _build_scene, _idx
    assert StatsDialog.SPECIES == ["NONE", "Dhampir"]
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    aria = _idx(app, "Aria")

    class _V:
        def __init__(self, value):
            self.value = value

    def ok(**kw):
        st = app.combat.get_agent_stats(app.bm, aria)
        steppers = {k: _V(getattr(st, k)) for k in
                    ("str", "dex", "con", "intel", "wis", "cha", "hp_cur", "hp_max", "base_ac",
                     "speed_walk", "speed_swim", "speed_fly", "speed_burrow", "prof_bonus",
                     "num_attacks")}
        steppers["speed_walk"] = _V(30)
        app._on_stats_ok(aria, steppers, {}, "Fighter", 5, None, **kw)
        return app.combat.get_agent_stats(app.bm, aria)

    s = ok(species="Dhampir")
    assert s.is_dhampir() and s.speed_walk == 35 and s.darkvision_range == 60
    assert s.magic_damage_multipliers[NECROTIC] == 0.5
    s = ok()                               # legacy caller: species untouched
    assert s.is_dhampir()
    s = ok(species="NONE")
    assert not s.is_dhampir() and s.magic_damage_multipliers[NECROTIC] == 1.0
    print("✅ test_gui_stats_ok_applies_species passed")


def main():
    print("Running Dhampir tests...\n")
    test_species_traits_apply_and_strip()
    test_species_table_records_and_strips_what_it_applied()
    test_restore_species_rebuilds_a_legacy_record()
    test_bite_is_1d4_plus_con_piercing()
    test_drain_heals_and_spends_a_use()
    test_strengthen_lands_on_the_next_attack_roll()
    test_strengthen_lands_on_an_ability_check()
    test_strengthen_fades_after_a_minute()
    test_no_empowerment_off_undead_or_construct()
    test_uses_run_out_and_long_rest_refills()
    test_rage_of_the_gods_end_keeps_species_resistance()
    test_loader_round_trip()
    test_gui_offers_the_bite_and_drains()
    test_gui_stats_ok_applies_species()
    print("\n" + "=" * 60)
    print("✅ All Dhampir tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
