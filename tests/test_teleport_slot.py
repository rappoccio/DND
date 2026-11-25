"""A teleportation spell cast from the DM console pays for itself.

Teleport spells (Misty Step, Dimension Door, …) resolve outside execute_spell: the GUI takes a
destination click and calls place_teleported_agents. That path used to charge only the action
economy, so the spell slot was never spent. Covered: the GUI path (app_spells.resolve_teleport_spell)
spends the chosen slot, marks the leveled spell, or spends a granted free cast instead (SPECIES D3);
the engine's pay_teleport_cast also pays an NPC's N/day use, and refuses a PC with no slot.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
import pending
import app_spells
from helpers import _dict_to_spell
from test_combat_panel import App, MAP_PATH, SEED, _build_scene, _idx, _goto


def _misty(app):
    d = next(s for s in app.all_spells if s.get("name") == "Misty Step")
    return _dict_to_spell(d)


def _scene():
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    name = app.bm.placed_agents[0].name
    _goto(app, name)
    idx = _idx(app, name)
    app.combat.set_agent_spells(app.bm, idx, [_misty(app)])
    s = app.combat.get_agent_stats(app.bm, idx)
    s.is_npc = False
    s.spell_slots_max = [4, 3, 0, 0, 0, 0, 0, 0, 0]
    s.spell_slots_remaining = [4, 3, 0, 0, 0, 0, 0, 0, 0]
    app.combat.set_agent_stats(app.bm, idx, s)
    return app, idx


def _free_cell(app, idx):
    """An open cell a few squares from the caster, for the destination click."""
    o = app.bm.placed_agents[idx].origin
    taken = {(p.origin.col, p.origin.row) for p in app.bm.placed_agents}
    for dc in range(-3, 4):
        for dr in range(-3, 4):
            c = rpg.Cell(o.col + dc, o.row + dr)
            if (abs(dc) + abs(dr) >= 2 and (c.col, c.row) not in taken
                    and app.combat.is_valid_teleport_destination(app.bm, c.col, c.row)):
                return c
    raise AssertionError("no free cell near the caster")


def _cast(app, idx, slot_level, use_grant=False):
    app.pending = pending.Spell("bonus", idx=0, slot_level=slot_level, is_aoe=True)
    app.cast_setup.use_grant = use_grant
    cell = _free_cell(app, idx)
    app_spells.resolve_teleport_spell(app, cell)
    o = app.bm.placed_agents[idx].origin
    assert (o.col, o.row) == (cell.col, cell.row), "the caster teleported"


def test_gui_teleport_spends_the_slot():
    app, idx = _scene()
    _cast(app, idx, 2)
    s = app.combat.get_agent_stats(app.bm, idx)
    assert list(s.spell_slots_remaining)[:2] == [4, 2], list(s.spell_slots_remaining)
    assert not s.can_cast_leveled_spell(), "the one-leveled-spell rule sees it"
    print("✅ test_gui_teleport_spends_the_slot passed")


def test_gui_teleport_granted_free_cast():
    app, idx = _scene()
    s = app.combat.get_agent_stats(app.bm, idx)
    s.char_level = 5
    s.set_species("Elf", "High Elf")              # Misty Step at 5, once per Long Rest
    app.combat.set_agent_stats(app.bm, idx, s)
    assert s.granted_free_left("Misty Step") == 1
    _cast(app, idx, 0, use_grant=True)
    s = app.combat.get_agent_stats(app.bm, idx)
    assert list(s.spell_slots_remaining)[:2] == [4, 3], "no slot spent"
    assert s.granted_free_left("Misty Step") == 0
    assert not app.cast_setup.use_grant
    print("✅ test_gui_teleport_granted_free_cast passed")


def test_engine_pay_npc_and_refusal():
    app, idx = _scene()
    sp = app.combat.get_agent_spells(app.bm, idx)
    sp[0].uses_max = 2
    sp[0].uses_remaining = 2
    app.combat.set_agent_spells(app.bm, idx, sp)
    s = app.combat.get_agent_stats(app.bm, idx)
    s.is_npc = True
    app.combat.set_agent_stats(app.bm, idx, s)
    assert app.combat.pay_teleport_cast(app.bm, idx, 0, 0, False)
    assert app.combat.get_agent_spells(app.bm, idx)[0].uses_remaining == 1
    s = app.combat.get_agent_stats(app.bm, idx)
    s.is_npc = False
    s.spell_slots_remaining = [0] * 9
    app.combat.set_agent_stats(app.bm, idx, s)
    assert not app.combat.pay_teleport_cast(app.bm, idx, 0, 2, False), "a PC with no slot"
    print("✅ test_engine_pay_npc_and_refusal passed")


def main():
    test_gui_teleport_spends_the_slot()
    test_gui_teleport_granted_free_cast()
    test_engine_pay_npc_and_refusal()
    print("All teleport slot tests passed.")


if __name__ == "__main__":
    main()
