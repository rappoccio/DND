#!/usr/bin/env python3
"""Enspelled items E3 — the grant / revoke lifecycle (plans/ENSPELLED_ITEMS_PLAN.md).

A creature's item-granted spells are derived from what it carries (D9) and rebuilt whenever
that changes: an unattuned item grants nothing, attuning grants, dropping removes, and a
different creature picking the item up gets the uses it has left (D0). spell_overrides (D3a)
are applied to the granted record. In the App: a pickup, a chest/floor take, a weapon drop
and a mob spawn re-derive; a save never writes the item entries as known spells, and a load
re-derives them from the restored inventory; an enspelled item never stacks.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import shutil
import tempfile

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)
from helpers import (_dict_to_item, _dict_to_spell, _dict_to_weapon, is_item_spell,
                     item_spell_entries, sync_item_spells)

_GUI = os.path.join(_ROOT, "gui")
with open(os.path.join(_GUI, "spells.json")) as f:
    CATALOG = {d["name"]: d for d in json.load(f)}
_records = {}


def _record(fname, name):
    if fname not in _records:
        with open(os.path.join(_GUI, fname)) as f:
            _records[fname] = json.load(f)
    return next(r for r in _records[fname] if r["name"] == name)


def _board():
    bm, engine = setup_battle_map(), setup_combat_engine()
    a = add_agent_to_battle(engine, bm, create_test_agent("Holder", 5, 5), hp=40)
    b = add_agent_to_battle(engine, bm, create_test_agent("Other", 6, 5), hp=40)
    foe = add_agent_to_battle(engine, bm, create_test_agent("Foe", 7, 5), wis=1, hp=200)
    bm.set_agent_faction(a, 1)
    bm.set_agent_faction(b, 1)
    bm.set_agent_faction(foe, 2)
    return bm, engine, a, b, foe


def _sync(engine, bm, idx):
    return sync_item_spells(engine, bm, idx, CATALOG)


def _set_mace(engine, bm, idx, mace):
    weapons = list(engine.get_agent_weapons(bm, idx))
    weapons[0] = mace
    engine.set_agent_weapons(bm, idx, weapons)


def _item_spells(engine, bm, idx):
    return [(sp.name, sp.item_name, sp.item_slot, sp.item_charge_cost)
            for sp in engine.get_agent_spells(bm, idx) if is_item_spell(sp)]


def _attune_weapon(engine, bm, idx, slot, on):
    weapons = list(engine.get_agent_weapons(bm, idx))
    weapons[slot].item_spells.attuned = on
    engine.set_agent_weapons(bm, idx, weapons)


def test_unattuned_grants_nothing_attuning_grants():
    bm, engine, a, _, _ = _board()
    _set_mace(engine, bm, a, _dict_to_weapon(_record("weapons.json", "Mace of Terror")))
    assert _sync(engine, bm, a) is None, "unattuned: nothing to grant, nothing changes"
    assert _item_spells(engine, bm, a) == []

    _attune_weapon(engine, bm, a, 0, True)
    assert _sync(engine, bm, a) == [None]
    assert _item_spells(engine, bm, a) == [("Fear", "Mace of Terror", 0, 0)]
    sp = engine.get_agent_spells(bm, a)[0]
    assert sp.item_source == rpg.SpellItemSource.FromWeapon
    assert engine.available_castable_spells(bm, a) == [0]
    assert _sync(engine, bm, a) is None, "idempotent"

    _attune_weapon(engine, bm, a, 0, False)
    _sync(engine, bm, a)
    assert _item_spells(engine, bm, a) == [], "un-attuning revokes"
    print("✅ test_unattuned_grants_nothing_attuning_grants")


def test_own_spells_keep_their_place():
    bm, engine, a, _, _ = _board()
    own = [_dict_to_spell(CATALOG["Bane"]), _dict_to_spell(CATALOG["Fear"])]
    engine.set_agent_spells(bm, a, own)
    mace = _dict_to_weapon(_record("weapons.json", "Mace of Terror"))
    mace.item_spells.attuned = True
    _set_mace(engine, bm, a, mace)
    assert _sync(engine, bm, a) == [0, 1, None]
    names = [(s.name, is_item_spell(s)) for s in engine.get_agent_spells(bm, a)]
    assert names == [("Bane", False), ("Fear", False), ("Fear", True)], names

    # The mace moves to the off hand: the stale entry goes, a re-tagged one is appended.
    weapons = list(engine.get_agent_weapons(bm, a))
    weapons[0], weapons[1] = weapons[1], weapons[0]
    engine.set_agent_weapons(bm, a, weapons)
    assert _sync(engine, bm, a) == [0, 1, None]
    assert _item_spells(engine, bm, a) == [("Fear", "Mace of Terror", 1, 0)]
    print("✅ test_own_spells_keep_their_place")


def test_dropping_removes_and_another_holder_gets_remaining_uses():
    bm, engine, a, b, foe = _board()
    mace = _dict_to_weapon(_record("weapons.json", "Mace of Terror"))
    mace.item_spells.attuned = True
    _set_mace(engine, bm, a, mace)
    _sync(engine, bm, a)
    act = rpg.SpellAction()
    act.caster_idx, act.spell_idx, act.target_indices = a, 0, [foe]
    act.aoe_col, act.aoe_row = 7, 5
    assert engine.execute_spell(bm, act).valid
    assert engine.get_agent_weapons(bm, a)[0].item_spells.uses_remaining == {"Fear": 1}

    # Drop it on the floor (the engine's map item carries the Weapon by value).
    pt = bm.placed_agents[a]
    dropped = engine.get_agent_weapons(bm, a)[0]
    iid = bm.place_item(pt.origin, dropped, "")
    weapons = list(engine.get_agent_weapons(bm, a))
    weapons[0] = rpg.Weapon()
    engine.set_agent_weapons(bm, a, weapons)
    _sync(engine, bm, a)
    assert _item_spells(engine, bm, a) == [], "dropping removes"

    # The other creature picks it up: one use left, not a fresh two (D0).
    assert bm.pick_up_item(iid, b, 0)
    got = engine.get_agent_weapons(bm, b)[0]
    assert got.name == "Mace of Terror"
    assert got.item_spells.uses_remaining == {"Fear": 1}
    _sync(engine, bm, b)
    assert _item_spells(engine, bm, b) == [("Fear", "Mace of Terror", 0, 0)]
    act.caster_idx, act.spell_idx = b, 0
    assert engine.execute_spell(bm, act).valid
    _sync(engine, bm, b)
    assert engine.available_castable_spells(bm, b) == [], "the last use is gone"
    print("✅ test_dropping_removes_and_another_holder_gets_remaining_uses")


def test_overrides_and_pool_entries():
    bm, engine, a, _, _ = _board()
    icon = _dict_to_item(_record("items.json", "Icon of Ravenloft"))
    icon.item_spells.attuned = True
    wand = _dict_to_item({
        "name": "Test Wand", "type": "Wondrous", "action_type": "NoAction",
        "item_spell_groups": {"99": ["Fire Bolt"]},
        "charges": {"max": 4}, "charge_spells": {"1": ["Burning Hands"], "3": ["Fireball"]},
        "spell_overrides": {"Fireball": {"range": 999}},
    })
    engine.set_agent_items(bm, a, [icon, wand])
    entries = item_spell_entries(engine, bm, a, CATALOG)
    by = {(sp.name, sp.item_slot): sp for sp in entries}
    pfeg = by[("Protection from Evil and Good", 0)]
    assert CATALOG["Protection from Evil and Good"]["requires_concentration"]
    assert not pfeg.requires_concentration, "D3a: the Icon's override applies"
    assert by[("Fire Bolt", 1)].item_charge_cost == 0
    assert by[("Burning Hands", 1)].item_charge_cost == 1
    assert by[("Fireball", 1)].item_charge_cost == 3
    assert by[("Fireball", 1)].range == 999
    assert all(sp.item_source == rpg.SpellItemSource.FromItem for sp in entries)
    print("✅ test_overrides_and_pool_entries")


def test_worn_armor_grants():
    bm, engine, a, _, _ = _board()
    armor = list(engine.get_agent_armor(bm, a))
    cloak = armor[5]
    cloak.name = "Test Cloak"
    cloak.item_spells.spell_groups = {1: ["Fear"]}
    cloak.item_spells.refill()
    armor[5] = cloak
    engine.set_agent_armor(bm, a, armor)
    _sync(engine, bm, a)
    assert _item_spells(engine, bm, a) == [("Fear", "Test Cloak", 5, 0)]
    armor[5] = rpg.Armor()
    engine.set_agent_armor(bm, a, armor)
    _sync(engine, bm, a)
    assert _item_spells(engine, bm, a) == [], "taking it off revokes"
    print("✅ test_worn_armor_grants")


def test_npc_groups_leave_item_spells_alone():
    bm, engine, a, _, _ = _board()
    engine.set_agent_spells(bm, a, [_dict_to_spell(CATALOG["Fear"])])
    mace = _dict_to_weapon(_record("weapons.json", "Mace of Terror"))
    mace.item_spells.attuned = True
    _set_mace(engine, bm, a, mace)
    _sync(engine, bm, a)
    engine.init_npc_spell_groups(bm, a, {1: ["Fear"]})
    own, item = engine.get_agent_spells(bm, a)
    assert own.uses_max == 1 and item.uses_max == 0, "the innate group is not the mace's"
    print("✅ test_npc_groups_leave_item_spells_alone")


# ── In the App ────────────────────────────────────────────────────────────────
def _app(tmp):
    from main import App
    from test_restore_oracle import MAP_PATH, SEED, _place
    app = App(MAP_PATH, seed=SEED)
    app.autosave_enabled = False
    app._set_encounter_base(os.path.join(tmp, "e3_agents.json"))
    _place(app, "Aria", 2, 3)
    _place(app, "Brannor", 2, 5)
    app.combat.apply_agent_configs(app.bm)
    return app


def test_app_take_drop_save_load():
    import items_play
    tmp = tempfile.mkdtemp()
    try:
        app = _app(tmp)
        aria, bran = 0, 1
        app.combat.set_agent_spells(app.bm, aria, [_dict_to_spell(CATALOG["Bane"])])

        # Taking an attuned Doss Lute off the floor grants its spells at once.
        lute = rpg.MapItem()
        lute.kind = rpg.MapItemKind.Consumable
        it = _dict_to_item(_record("items.json", "Doss Lute"))
        it.item_spells.attuned = True
        lute.item = it
        assert items_play.give_item(app, aria, lute)
        granted = {sp.name for sp in app.combat.get_agent_spells(app.bm, aria) if is_item_spell(sp)}
        assert granted == set(it.item_spells.spell_names()), granted
        assert app.combat.get_agent_spells(app.bm, aria)[0].name == "Bane"

        # A second lute is its own row, not a stack.
        lute2 = rpg.MapItem()
        lute2.kind = rpg.MapItemKind.Consumable
        it = _dict_to_item(_record("items.json", "Doss Lute"))
        it.item_spells.attuned = True
        lute2.item = it
        items_play.give_item(app, aria, lute2)
        assert [it.quantity for it in app.combat.get_agent_items(app.bm, aria)] == [1, 1]

        # The mace, attuned, through the weapon pickup path.
        mace = _dict_to_weapon(_record("weapons.json", "Mace of Terror"))
        mace.item_spells.attuned = True
        mace.item_spells.uses_remaining = {"Fear": 1}
        pt = app.bm.placed_agents[bran]
        iid = app.bm.place_item(pt.origin, mace, "")
        placed = next(x for x in app.bm.get_all_items() if x.id == iid)
        app._pickup_item(placed, bran)
        assert ("Fear", True) in [(s.name, is_item_spell(s))
                                  for s in app.combat.get_agent_spells(app.bm, bran)]

        # Save: item entries are not known spells; load re-derives them, uses intact.
        app._save_agents()
        with open(app._save_path) as f:
            saved = json.load(f)
        by_name = {a["name"]: a for a in saved["agents"]} if isinstance(saved, dict) else \
                  {a["name"]: a for a in saved}
        assert by_name["Aria"]["spell_indices"] == ["Bane"], by_name["Aria"]["spell_indices"]
        assert by_name["Brannor"]["spell_indices"] == []

        app2 = _app(tmp)
        app2._load_agents(app._save_path)
        spells = [(s.name, is_item_spell(s)) for s in app2.combat.get_agent_spells(app2.bm, aria)]
        assert spells[0] == ("Bane", False)
        assert {n for n, tagged in spells if tagged} == granted
        assert sum(1 for _, tagged in spells if tagged) == 2 * len(granted), "two lutes, two sets"
        bspells = app2.combat.get_agent_spells(app2.bm, bran)
        assert [(s.name, s.item_name) for s in bspells if is_item_spell(s)] == \
               [("Fear", "Mace of Terror")]
        w = next(w for w in app2.combat.get_agent_weapons(app2.bm, bran) if w.name == "Mace of Terror")
        assert w.item_spells.uses_remaining == {"Fear": 1}

        # The Spells dialog shows own spells only; Done keeps the item entries derived.
        app2._on_spell_done(aria, [dict(CATALOG["Bane"]), dict(CATALOG["Bless"])])
        after = [(s.name, is_item_spell(s)) for s in app2.combat.get_agent_spells(app2.bm, aria)]
        assert after[:2] == [("Bane", False), ("Bless", False)]
        assert sum(1 for _, tagged in after if tagged) == 2 * len(granted)

        # Dropping the mace revokes Fear.
        app2.turn_order = []
        slot = next(i for i, w in enumerate(app2.combat.get_agent_weapons(app2.bm, bran))
                    if w.name == "Mace of Terror")
        app2._current_agent_idx = lambda: bran
        app2._drop_weapon(slot)
        assert not any(is_item_spell(s) for s in app2.combat.get_agent_spells(app2.bm, bran))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ test_app_take_drop_save_load")


if __name__ == "__main__":
    test_unattuned_grants_nothing_attuning_grants()
    test_own_spells_keep_their_place()
    test_dropping_removes_and_another_holder_gets_remaining_uses()
    test_overrides_and_pool_entries()
    test_worn_armor_grants()
    test_npc_groups_leave_item_spells_alone()
    test_app_take_drop_save_load()
    print("\nAll enspelled-items E3 tests passed.")
