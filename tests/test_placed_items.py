#!/usr/bin/env python3
"""Placed items and chests through the app (plans/ITEMS_AND_CHESTS_PLAN.md I3–I5).

I3 — persistence: design (map data) vs play state, through ``run_state`` and the app's
terrain save / load; a reset (no state) puts the design back; agent reloads keep the
design items, and the creatures document never carries them.
I4 — the Items menu's DM operations: click-to-place items / keys / chests, an item placed
on a chest goes in it, a DM drag moves a design item (onto a chest: into it), chest edits
reach the live chest.
I5 — play: taking items of every kind (armor into a chosen slot, swapping the worn piece
onto the floor), opening a trapped chest, keys for chests and doors, Use Item skips keys.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json
import shutil
import tempfile

import rpg_battle_map as rpg

import items_play
import placed_items as pi
import run_state as rs
from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20261109


# ── Fixtures ─────────────────────────────────────────────────────────────────
def _app(tmpdir, names=("Aria",)):
    app = App(MAP_PATH, seed=SEED)
    app._set_encounter_base(os.path.join(tmpdir, "items_test_agents.json"))
    for i, nm in enumerate(names):
        cfg = rpg.AgentConfig()
        cfg.name = nm
        cfg.start_col = 2 + i * 4
        cfg.start_row = 3
        cfg.size = 1
        cfg.sprite_path = ""
        app.combat.add_agent_config(app.bm, cfg)
        app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)
    app.selected_idx = 0
    return app


def _record(app, kind, name):
    table = {"weapon": app.weapon_name_to_dict, "armor": app.armor_name_to_dict,
             "item": app.item_name_to_dict}[kind]
    return dict(table[name])


def _rows(rows):
    return {label: cb for label, cb in rows}


def _row(rows, prefix):
    for label, cb in rows:
        if label.startswith(prefix):
            return cb
    raise AssertionError(f"no row starting {prefix!r} in {[l for l, _ in rows]}")


def _terrain_file(app):
    with open(app._terrain_path) as f:
        return json.load(f)


def _with_tmp(fn):
    def run():
        tmp = tempfile.mkdtemp()
        try:
            fn(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    run.__name__ = fn.__name__
    return run


# ── I3: records and run_state ────────────────────────────────────────────────
def test_run_state_carries_items_and_chests():
    terrain = {"regions": [], "doors": [],
               "items": [{"pid": 1, "kind": "item", "record": {"name": "Key"}, "cell": [1, 1]}],
               "chests": [{"id": 1, "cell": [2, 2]}],
               "items_state": [{"pid": 1, "cell": [3, 3]}],
               "chests_state": [{"id": 1, "open": True}]}
    map_doc, _, state = rs.split_terrain(terrain)
    assert map_doc["items"] == terrain["items"] and map_doc["chests"] == terrain["chests"]
    assert state["items"] == terrain["items_state"] and state["chests"] == terrain["chests_state"]
    back = rs.merge_terrain(map_doc, {}, state)
    assert back["items_state"] == terrain["items_state"]
    assert back["chests_state"] == terrain["chests_state"]
    fresh = rs.merge_terrain(map_doc, {}, {})
    assert "items_state" not in fresh and "chests_state" not in fresh, "no state ⇒ as designed"
    print("✅ run_state splits / merges item and chest design + state")


def test_chest_record_round_trip():
    d = pi.make_chest(3, (4, 5), locked=True, lock_dc=18)
    d["trap"].update(armed=True, damage_type="Piercing", save="Con")
    d["contents"] = [pi.make_item("item", {"name": "Key", "type": "Key", "opens": ["chest:3"]}, 7)]
    c = pi.to_chest(d)
    assert c.id == 3 and c.locked and c.lock_dc == 18 and c.trap.armed
    assert c.trap.physical and c.trap.damage_type == int(rpg.PhysicalDamage.Piercing)
    assert c.trap.save_ability == rpg.SaveAbility.SaveCon
    assert [m.pid for m in c.contents] == [7] and list(c.contents[0].item.opens) == ["chest:3"]
    c.open = True
    c.contents = []
    st = pi.chest_state(c)
    again = pi.to_chest(d, st)
    assert again.open and not again.contents, "state: open, the key taken"
    print("✅ chest design + state round trip")


# ── I3: through the app ──────────────────────────────────────────────────────
@_with_tmp
def test_design_and_state_survive_save_load_and_reset(tmp):
    app = _app(tmp)
    potion = _record(app, "item", "Potion of Healing")
    pid = items_play.add_floor_item(app, "item", potion, (3, 4))
    cid = items_play.add_chest(app, (3, 2))
    items_play.add_chest_content(app, cid, "weapon", _record(app, "weapon", "Dagger"))
    assert any(m.pid == pid for m in app.bm.get_all_items())

    # Play: Aria (2,3) picks up the potion and empties the chest.
    floor = [m for m in app.bm.get_all_items() if m.pid == pid][0]
    items_play.pick_up_floor_item(app, floor, 0)
    assert [it.name for it in app.combat.get_agent_items(app.bm, 0)] == ["Potion of Healing"]
    items_play.open_chest(app, 0, cid)
    ch = items_play.live_chest(app, cid)
    items_play.take_from_chest(app, 0, cid, ch.contents[0].id)
    assert not items_play.live_chest(app, cid).contents
    assert "Dagger" in [w.name for w in app.combat.get_agent_weapons(app.bm, 0)]
    app._save_terrain()

    t = _terrain_file(app)
    assert [r["pid"] for r in t["items"]] == [pid], "the design keeps the potion"
    assert t["items_state"] == [], "…but it is gone from the floor in play"
    assert t["chests_state"][0]["open"] and t["chests_state"][0]["contents"] == []

    app._load_terrain()
    assert not [m for m in app.bm.get_all_items() if m.pid >= 0]
    ch = items_play.live_chest(app, cid)
    assert ch.open and not ch.contents, "play state reloads"

    # A reset is a terrain document with no play state.
    for k in ("items_state", "chests_state"):
        t.pop(k)
    with open(app._terrain_path, "w") as f:
        json.dump(t, f)
    app._load_terrain()
    assert [m.pid for m in app.bm.get_all_items() if m.pid >= 0] == [pid]
    ch = items_play.live_chest(app, cid)
    assert not ch.open and [m.name for m in ch.contents] == ["Dagger"], "design is back"
    print("✅ design + play state survive save / load; reset restores the design")


@_with_tmp
def test_agents_reload_keeps_design_items(tmp):
    app = _app(tmp)
    pid = items_play.add_floor_item(app, "weapon", _record(app, "weapon", "Dagger"), (5, 5))
    app.bm.place_item(rpg.Cell(6, 6), app.combat.get_agent_weapons(app.bm, 0)[0], "")
    app._save_agents()
    with open(app._save_path) as f:
        doc = json.load(f)
    assert len(doc["map_items"]) == 1, "the creatures document holds only the dropped weapon"
    app._load_agents()
    pids = sorted(m.pid for m in app.bm.get_all_items())
    assert pids == [-1, pid], f"design item survives an agents reload: {pids}"
    app._clear_agents()
    assert [m.pid for m in app.bm.get_all_items()] == [pid], "Clear keeps the map's items"
    print("✅ agents reload / clear keep design items; map_items excludes them")


# ── I4: the Items menu ───────────────────────────────────────────────────────
@_with_tmp
def test_click_to_place_and_into_chest(tmp):
    app = _app(tmp)
    items_play.arm_placement(app, ("chest", None))
    assert items_play.place_at(app, rpg.Cell(5, 2))
    assert app.bm.chest_at(rpg.Cell(5, 2)) >= 0 and len(app._design_chests) == 1
    assert app.bm.is_blocked(rpg.Cell(5, 2), 1), "the chest blocks its cell"
    cid = app._design_chests[0]["id"]

    items_play.arm_placement(app, ("item", dict(items_play.KEY_RECORD)))
    items_play.place_at(app, rpg.Cell(5, 2))                       # onto the chest
    items_play.place_at(app, rpg.Cell(6, 6))                       # on the floor
    assert [r["kind"] for r in app._design_chests[0]["contents"]] == ["item"]
    assert len(items_play.live_chest(app, cid).contents) == 1
    floor = [m for m in app.bm.get_all_items() if m.pid >= 0]
    assert len(floor) == 1 and floor[0].item.type == rpg.ItemType.Key
    items_play.disarm_placement(app)
    assert app._item_placing is None

    # A DM drag moves the design cell; onto the chest it goes in.
    app._begin_item_drag(floor[0])
    app._drop_dragged_item(rpg.Cell(7, 7))
    assert app._design_items[0]["cell"] == [7, 7]
    moved = [m for m in app.bm.get_all_items() if m.pid >= 0][0]
    app._begin_item_drag(moved)
    app._drop_dragged_item(rpg.Cell(5, 2))
    assert not app._design_items and len(app._design_chests[0]["contents"]) == 2
    assert len(items_play.live_chest(app, cid).contents) == 2
    print("✅ click-to-place chests / items / keys; drags move and fill chests")


@_with_tmp
def test_chest_edits_reach_live_chest(tmp):
    app = _app(tmp)
    cid = items_play.add_chest(app, (3, 2))
    items_play.edit_chest(app, cid, locked=True, lock_dc=20)
    ch = items_play.live_chest(app, cid)
    assert ch.locked and ch.lock_dc == 20
    items_play.edit_trap(app, cid, armed=True, num_dice=1, die_size=4)
    assert items_play.live_chest(app, cid).trap.armed
    items_play.edit_chest(app, cid, name="Strongbox")
    assert items_play.live_chest(app, cid).name == "Strongbox"
    items_play.remove_chest(app, cid)
    assert app.bm.chest_at(rpg.Cell(3, 2)) < 0 and not app._design_chests
    print("✅ chest edits reach the live chest")


# ── I5: play ─────────────────────────────────────────────────────────────────
@_with_tmp
def test_armor_into_slot_swaps_worn(tmp):
    app = _app(tmp)
    cid = items_play.add_chest(app, (3, 2))
    items_play.add_chest_content(app, cid, "armor", _record(app, "armor", "Chain Mail"))
    armor = list(app.combat.get_agent_armor(app.bm, 0))
    armor[1] = _dict_to_armor_rec(app, "Leather")
    app.combat.set_agent_armor(app.bm, 0, armor)
    app.bm.open_chest(cid)
    got = app.bm.take_from_chest(cid, items_play.live_chest(app, cid).contents[0].id)
    assert items_play.give_item(app, 0, got, armor_slot=1)
    assert app.combat.get_agent_armor(app.bm, 0)[1].name == "Chain Mail"
    dropped = [m for m in app.bm.get_all_items() if m.kind == rpg.MapItemKind.Armor]
    assert [m.name for m in dropped] == ["Leather"], "the worn piece lands on the floor"
    app._save_agents()
    app._load_agents()
    assert [m.name for m in app.bm.get_all_items() if m.kind == rpg.MapItemKind.Armor] == ["Leather"]
    assert not items_play.give_item(app, 0, got, armor_slot=None), "armor needs a slot"
    print("✅ armor goes into the chosen slot; the swapped piece drops and saves")


def _dict_to_armor_rec(app, name):
    from helpers import _dict_to_armor
    return _dict_to_armor(app.armor_name_to_dict[name])


@_with_tmp
def test_trapped_chest_fires_on_open_and_menu_rows(tmp):
    app = _app(tmp)
    s = app.combat.get_agent_stats(app.bm, 0)
    s.hp_max = s.hp_cur = 100
    app.combat.set_agent_stats(app.bm, 0, s)
    cid = items_play.add_chest(app, (3, 2))
    items_play.edit_trap(app, cid, armed=True, num_dice=1, die_size=1, bonus=5, save_dc=40,
                         half_on_save=False)
    rows = items_play.chest_options(app, 0, items_play.live_chest(app, cid))
    labels = [l for l, _ in rows]
    assert "Open chest" in labels and "Search for traps" in labels
    assert not any(l.startswith("Disarm") for l in labels), "an unfound trap offers no Disarm"
    _row(rows, "Open chest")()
    assert app.combat.get_agent_stats(app.bm, 0).hp_cur == 94
    assert items_play.live_chest(app, cid).trap.fired
    print("✅ opening a trapped chest sets it off; menu rows follow the state")


@_with_tmp
def test_keys_open_chests_and_doors(tmp):
    app = _app(tmp)
    cid = items_play.add_chest(app, (3, 2))
    items_play.edit_chest(app, cid, locked=True)
    did = app.bm.add_door(rpg.Cell(2, 5), False, True, 25, False)
    door = [d for d in app.bm.doors if d.id == did][0]
    kpid = items_play.add_floor_item(app, "item", dict(items_play.KEY_RECORD), (2, 4))
    items_play.set_key_opens(app, kpid, f"chest:{cid}", True)
    items_play.set_key_opens(app, kpid, items_play.door_ref(door), True)
    assert set(items_play.key_opens(app, kpid)) == {f"chest:{cid}", items_play.door_ref(door)}

    rows = items_play.chest_options(app, 0, items_play.live_chest(app, cid))
    assert not any(l == "Unlock with key" for l, _ in rows), "no key carried yet"
    key = [m for m in app.bm.get_all_items() if m.pid == kpid][0]
    items_play.pick_up_floor_item(app, key, 0)
    inv = app.combat.get_agent_items(app.bm, 0)
    assert inv[0].type == rpg.ItemType.Key and len(inv[0].opens) == 2

    rows = items_play.chest_options(app, 0, items_play.live_chest(app, cid))
    _row(rows, "Unlock with key")()
    assert not items_play.live_chest(app, cid).locked

    from menus import dm
    drows = dm.door_options(app, 0, door)
    _row(drows, "Unlock with key")()
    assert not [d for d in app.bm.doors if d.id == did][0].locked
    print("✅ a carried key unlocks its chest and its door")


@_with_tmp
def test_player_view_under_fog(tmp):
    from net.roster import DM_PRINCIPAL_ID, Role
    from net.view import build_view
    app = _app(tmp)
    seen = items_play.add_chest(app, (1, 1))
    items_play.edit_chest(app, seen, locked=True, lock_dc=17)
    items_play.edit_trap(app, seen, armed=True)
    items_play.add_chest_content(app, seen, "item", _record(app, "item", "Potion of Healing"))
    items_play.add_chest(app, (9, 9))
    items_play.add_floor_item(app, "weapon", _record(app, "weapon", "Dagger"), (2, 2))
    items_play.add_floor_item(app, "weapon", _record(app, "weapon", "Dagger"), (9, 8))
    kira = app.roster.add_principal("Kira", role=Role.PLAYER)
    app._set_fog(True)
    app.bm.set_explored_cells([rpg.Cell(c, r) for c in range(4) for r in range(4)])

    t = build_view(app, kira)["terrain"]
    assert [c["id"] for c in t["chests"]] == [seen], "an unexplored chest stays hidden"
    rec = t["chests"][0]
    assert rec["locked"] and rec["trap"] is None and "lock_dc" not in rec
    assert "contents" not in rec, "a shut chest keeps its contents to itself"
    assert t["items"] == [{"cell": [2, 2], "name": "Dagger"}]

    dm_t = build_view(app, app.roster.get(DM_PRINCIPAL_ID))["terrain"]
    dm_rec = next(c for c in dm_t["chests"] if c["id"] == seen)
    assert dm_rec["lock_dc"] == 17 and dm_rec["trap"] == "hidden"
    assert dm_rec["contents"] == ["Potion of Healing"]

    ch = items_play.live_chest(app, seen)
    trap = ch.trap
    trap.found = True
    app.bm.set_chest_trap(seen, trap)
    app.bm.unlock_chest(seen)
    app.bm.open_chest(seen)
    rec = build_view(app, kira)["terrain"]["chests"][0]
    assert rec["trap"] == "found" and rec["contents"] == ["Potion of Healing"]
    print("✅ player view: chests and items under fog; DCs and hidden traps stay DM-side")


@_with_tmp
def test_use_item_menu_skips_keys(tmp):
    app = _app(tmp)
    from helpers import _dict_to_item
    app.combat.set_agent_items(app.bm, 0, [_dict_to_item(items_play.KEY_RECORD)])
    shown = []
    app._ask_actor = lambda *a, **k: shown.append(a)
    logged = []
    app._combat_log_add = lambda msg: logged.append(msg)
    app._current_agent_idx = lambda: 0
    from menus import features
    features.show_use_item_menu(app, (0, 0))
    assert not shown, "a key alone gives Use Item nothing to offer"
    print("✅ Use Item never offers a key")


if __name__ == "__main__":
    tests = [
        test_run_state_carries_items_and_chests,
        test_chest_record_round_trip,
        test_design_and_state_survive_save_load_and_reset,
        test_agents_reload_keeps_design_items,
        test_click_to_place_and_into_chest,
        test_chest_edits_reach_live_chest,
        test_armor_into_slot_swaps_worn,
        test_trapped_chest_fires_on_open_and_menu_rows,
        test_keys_open_chests_and_doors,
        test_player_view_under_fog,
        test_use_item_menu_skips_keys,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} placed-item tests passed")
    sys.exit(1 if failed else 0)
