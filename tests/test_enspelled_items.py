#!/usr/bin/env python3
"""Enspelled items E1 — data model + loaders (plans/ENSPELLED_ITEMS_PLAN.md).

The three example items parse from the catalogs (Mace of Terror, Doss Lute, Icon of
Ravenloft); every ItemSpells field round-trips through the dict helpers for items,
weapons and armor; the engine carries the state by value; and an app save → load keeps
uses, charges and `attuned` on carried items, wielded weapons, worn armor and items on
the floor (D0).
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GUI = os.path.join(_ROOT, "gui")
sys.path.insert(0, _GUI)

import json
import shutil
import tempfile

import rpg_battle_map as rpg

from helpers import (_dict_to_armor, _armor_to_dict, _dict_to_item, _item_to_dict,
                     _dict_to_weapon, _weapon_to_dict)

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20261110


def _catalog(fname, name):
    with open(os.path.join(_GUI, fname)) as f:
        return next(r for r in json.load(f) if r["name"] == name)


# A pool item (D4): no catalog entry uses one yet, so it is authored here.
WAND = {
    "name": "Test Wand of Fire", "type": "Wondrous", "action_type": "NoAction",
    "range": 0, "quantity": 1, "consumable": False,
    "requires_attunement": True, "spell_attack": 7,
    "item_spell_groups": {"99": ["Light"]},
    "charges": {"max": 7, "regain": "long_rest"},
    "charge_spells": {"1": ["Burning Hands"], "3": ["Fireball"]},
}


def _with_tmp(fn):
    def run():
        tmp = tempfile.mkdtemp()
        try:
            fn(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    run.__name__ = fn.__name__
    return run


# ── Catalog parse ────────────────────────────────────────────────────────────
def test_examples_parse():
    mace = _dict_to_weapon(_catalog("weapons.json", "Mace of Terror")).item_spells
    assert mace.requires_attunement and not mace.attuned
    assert mace.spell_dc == 15 and mace.spell_attack == 0
    assert mace.spell_groups == {2: ["Fear"]} and mace.uses_remaining == {"Fear": 2}
    assert mace.spell_names() == ["Fear"] and mace.uses_per_day("Fear") == 2
    assert not mace.active(), "unattuned: grants nothing (D5)"

    lute_it = _dict_to_item(_catalog("items.json", "Doss Lute"))
    assert lute_it.type == rpg.ItemType.Wondrous
    assert lute_it.action_type == rpg.ItemAction.NoAction
    lute = lute_it.item_spells
    assert len(lute.spell_names()) == 7
    assert all(n == 1 for n in lute.uses_remaining.values()) and len(lute.uses_remaining) == 7
    assert lute.spell_dc == 0, "the lute uses the bard's own DC"

    icon = _dict_to_item(_catalog("items.json", "Icon of Ravenloft")).item_spells
    assert icon.spell_groups == {99: ["Protection from Evil and Good"], 1: ["Cure Wounds"]}
    assert icon.uses_remaining == {"Cure Wounds": 1}, "at will is never tracked (D3)"
    assert rpg.ItemSpells.AT_WILL == 99
    assert json.loads(icon.spell_overrides_json) == {
        "Protection from Evil and Good": {"requires_concentration": False}}

    wand = _dict_to_item(WAND).item_spells
    assert wand.charges_max == 7 and wand.charges == 7 and wand.charges_regain == "long_rest"
    assert wand.charge_spells == {1: ["Burning Hands"], 3: ["Fireball"]}
    assert wand.spell_names() == ["Light", "Burning Hands", "Fireball"]

    plain = _dict_to_item(_catalog("items.json", "Potion of Healing"))
    assert plain.item_spells.empty() and not plain.item_spells.active()
    for k in ("item_spell_groups", "attuned", "charges", "item_spell_uses"):
        assert k not in _item_to_dict(plain), f"an ordinary item's save carries no {k}"
    assert "item_spell_groups" not in _weapon_to_dict(_dict_to_weapon(_catalog("weapons.json", "Dagger")))
    print("✅ the three example items (and a pool item) parse")


# ── Dict round trips ─────────────────────────────────────────────────────────
def _spent_mace():
    w = _dict_to_weapon(_catalog("weapons.json", "Mace of Terror"))
    w.item_spells.attuned = True
    w.item_spells.uses_remaining = {"Fear": 1}
    return w


def _spent_wand():
    it = _dict_to_item(WAND)
    it.item_spells.attuned = True
    it.item_spells.charges = 4
    return it


def _spells_state(s):
    return (s.requires_attunement, s.attuned, s.spell_dc, s.spell_attack,
            dict(s.spell_groups), dict(s.charge_spells), s.charges_max, s.charges_regain,
            s.charges, dict(s.uses_remaining), s.spell_overrides_json)


def test_dict_round_trips():
    w = _spent_mace()
    w2 = _dict_to_weapon(_weapon_to_dict(w))
    assert _spells_state(w2.item_spells) == _spells_state(w.item_spells)
    assert w2.item_spells.uses_remaining == {"Fear": 1} and w2.item_spells.attuned

    it = _spent_wand()
    it2 = _dict_to_item(_item_to_dict(it))
    assert _spells_state(it2.item_spells) == _spells_state(it.item_spells)
    assert it2.item_spells.charges == 4 and it2.type == rpg.ItemType.Wondrous

    icon = _dict_to_item(_catalog("items.json", "Icon of Ravenloft"))
    icon.item_spells.uses_remaining = {"Cure Wounds": 0}
    icon2 = _dict_to_item(json.loads(json.dumps(_item_to_dict(icon))))   # through real JSON text
    assert _spells_state(icon2.item_spells) == _spells_state(icon.item_spells)

    rec = dict(_catalog("armor.json", "Leather"), item_spell_groups={"1": ["Shield"]},
               spell_dc=13)
    a = _dict_to_armor(rec)
    a.item_spells.uses_remaining = {"Shield": 0}
    a2 = _dict_to_armor(_armor_to_dict(a))
    assert _spells_state(a2.item_spells) == _spells_state(a.item_spells)
    assert a2.ac_bonus == a.ac_bonus

    # Saved state is clamped to the item's own maxima, and stale spell names are ignored.
    d = _weapon_to_dict(w)
    d["item_spell_uses"] = {"Fear": 9, "Fireball": 3}
    assert _dict_to_weapon(d).item_spells.uses_remaining == {"Fear": 2}
    print("✅ item / weapon / armor dicts round-trip every ItemSpells field")


def test_refill():
    it = _spent_wand()
    it.item_spells.refill()
    assert it.item_spells.charges == 7
    w = _spent_mace()
    w.item_spells.refill()
    assert w.item_spells.uses_remaining == {"Fear": 2}
    assert w.item_spells.attuned, "a refill never touches attunement"
    print("✅ refill() fills N/day uses and the pool")


# ── Through the engine and the app ───────────────────────────────────────────
def _app(tmpdir):
    from main import App
    app = App(MAP_PATH, seed=SEED)
    app._set_encounter_base(os.path.join(tmpdir, "enspelled_agents.json"))
    cfg = rpg.AgentConfig()
    cfg.name, cfg.start_col, cfg.start_row, cfg.size = "Aria", 2, 3, 1
    cfg.sprite_path = ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)
    app.selected_idx = 0
    return app


@_with_tmp
def test_engine_and_save_load_keep_state(tmp):
    app = _app(tmp)
    c, bm = app.combat, app.bm

    weapons = list(c.get_agent_weapons(bm, 0))
    weapons[0] = _spent_mace()
    c.set_agent_weapons(bm, 0, weapons)

    lute = _dict_to_item(_catalog("items.json", "Doss Lute"))
    lute.item_spells.attuned = True
    uses = dict(lute.item_spells.uses_remaining)
    uses["Fly"] = 0
    lute.item_spells.uses_remaining = uses
    c.set_agent_items(bm, 0, [lute, _spent_wand()])

    armor = list(c.get_agent_armor(bm, 0))
    cloak = _dict_to_armor(dict(_catalog("armor.json", "Leather"), name="Test Cloak",
                                item_spell_groups={"1": ["Shield"]}))
    cloak.item_spells.uses_remaining = {"Shield": 0}
    armor[5] = cloak
    c.set_agent_armor(bm, 0, armor)

    # A Mace on the floor keeps its spent use too.
    floor = _spent_mace()
    floor.item_spells.uses_remaining = {"Fear": 0}
    bm.place_item(rpg.Cell(6, 6), floor, "")

    def check(when):
        w = c.get_agent_weapons(bm, 0)[0]
        assert w.name == "Mace of Terror", when
        assert w.item_spells.attuned and w.item_spells.uses_remaining == {"Fear": 1}, when
        items = c.get_agent_items(bm, 0)
        assert [i.name for i in items] == ["Doss Lute", "Test Wand of Fire"], when
        assert items[0].item_spells.attuned and items[0].item_spells.uses_remaining["Fly"] == 0, when
        assert items[0].item_spells.uses_remaining["Levitate"] == 1, when
        assert items[1].item_spells.charges == 4 and items[1].item_spells.attuned, when
        a = c.get_agent_armor(bm, 0)[5]
        assert a.name == "Test Cloak" and a.item_spells.uses_remaining == {"Shield": 0}, when
        on_floor = [m for m in bm.get_all_items() if m.weapon.name == "Mace of Terror"]
        assert len(on_floor) == 1, when
        assert on_floor[0].weapon.item_spells.uses_remaining == {"Fear": 0}, when

    check("in the engine")

    # Wondrous (D8): no Use Item effect — the engine refuses, and nothing is spent.
    assert not c.use_item(bm, 0, 0, 0).valid, "a lute can't be 'used'"
    # Unknown types still load as Heal (the Manual of Bodily Health, until it is implemented).
    assert _dict_to_item(_catalog("items.json", "Manual of Bodily Health")).type == rpg.ItemType.Heal
    app._save_agents()
    with open(app._save_path) as f:
        doc = json.load(f)
    assert isinstance(doc["agents"][0]["armor"]["cloak"], dict), "enspelled armor saved whole"
    assert isinstance(doc["agents"][0]["armor"]["helmet"], str), "ordinary slots stay names"
    app._load_agents()
    check("after save → load")
    print("✅ engine + save → load keep uses, charges and attuned (weapon, items, armor, floor); "
          "Wondrous can't be used")


if __name__ == "__main__":
    tests = [test_examples_parse, test_dict_round_trips, test_refill,
             test_engine_and_save_load_keep_state]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
