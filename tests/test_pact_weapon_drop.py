#!/usr/bin/env python3
"""A Pact of the Blade Warlock who falls asleep keeps attacking with CHA after picking the
pact weapon back up.

Bug: falling Unconscious (Sleep) drops held weapons onto the map. Map items were saved by NAME
only and rebuilt from the weapons.json catalog, so any save/reload in between (page switch,
autosave restore, …) turned the bonded Longsword back into a plain one — pact_weapon=False, so
the Warlock swung with STR/DEX again — and a conjured PactBlade (not in the catalog) vanished.

Fix: map items save the full weapon dict; picking a weapon up into the main hand re-bonds it.
"""

import os
import sys
import shutil
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import rpg_battle_map as rpg
from helpers import _dict_to_weapon
from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20261105


def _warlock_app(tmpdir):
    app = App(MAP_PATH, seed=SEED)
    app.autosave_enabled = False
    app._set_encounter_base(os.path.join(tmpdir, "pact_test_agents.json"))
    cfg = rpg.AgentConfig()
    cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = "Hexa", 3, 3, 1, ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)

    s = app.combat.get_agent_stats(app.bm, 0)
    s.set_class_level(rpg.CharacterClass.Warlock, 5)
    s.eldritch_invocations = [13]
    s.str, s.dex, s.cha = 10, 10, 18
    s.hp_max = s.hp_cur = 30
    app.combat.set_agent_stats(app.bm, 0, s)

    weapons = list(app.combat.get_agent_weapons(app.bm, 0))
    weapons[0] = _dict_to_weapon(app.weapon_name_to_dict["Longsword"])
    assert app._bond_pact_weapon(weapons)
    app.combat.set_agent_weapons(app.bm, 0, weapons)
    assert app.combat.get_agent_weapons(app.bm, 0)[0].pact_weapon
    return app


def test_sleep_drop_save_reload_pickup_keeps_pact():
    tmp = tempfile.mkdtemp()
    try:
        app = _warlock_app(tmp)
        app.combat.apply_unconscious(app.bm, 0)            # Sleep: HP intact, weapons dropped
        assert app.combat.get_agent_stats(app.bm, 0).hp_cur > 0
        items = list(app.bm.get_all_items())
        assert len(items) == 1 and items[0].weapon.name == "Longsword"
        assert items[0].weapon.pact_weapon

        app._save_agents()
        app._load_agents()

        items = list(app.bm.get_all_items())
        assert len(items) == 1, "the dropped weapon did not survive save/reload"
        assert items[0].weapon.pact_weapon, "save/reload stripped pact_weapon from the dropped weapon"

        # The reload re-conjured a PactBlade into the empty main hand; the real pact weapon
        # must replace it there, not land in the off-hand.
        assert app.combat.get_agent_weapons(app.bm, 0)[0].name == "PactBlade"
        app._pickup_item(items[0], 0)
        ws = list(app.combat.get_agent_weapons(app.bm, 0))
        assert ws[0].name == "Longsword" and ws[0].pact_weapon, [(w.name, w.pact_weapon) for w in ws]
        assert not any(w.name == "PactBlade" for w in ws), "the conjured PactBlade was not dismissed"
        print("✅ test_sleep_drop_save_reload_pickup_keeps_pact")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pickup_rebonds_legacy_item():
    """An item saved before the fix (plain catalog Longsword) is re-bonded on pickup."""
    tmp = tempfile.mkdtemp()
    try:
        app = _warlock_app(tmp)
        app.combat.apply_unconscious(app.bm, 0)
        item = list(app.bm.get_all_items())[0]
        plain = item.weapon
        plain.pact_weapon = False
        app.bm.remove_item(item.id)
        app.bm.place_item(item.cell, plain, "")

        app._pickup_item(list(app.bm.get_all_items())[0], 0)
        assert app.combat.get_agent_weapons(app.bm, 0)[0].pact_weapon, "pickup did not re-bond"
        print("✅ test_pickup_rebonds_legacy_item")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    test_sleep_drop_save_reload_pickup_keeps_pact()
    test_pickup_rebonds_legacy_item()
    print("✅ All pact-weapon drop tests passed!")


if __name__ == "__main__":
    main()
