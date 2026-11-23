"""Edit Stats: an Initiative field, and a layout with room for everything.

Covered: Stats.initiative_bonus adds to initiative_modifier and to a rolled entry; the dialog
shows the total modifier and OK stores a changed value as initiative_bonus, while an untouched
one keeps the bonus so a DEX edit still moves initiative; the bonus survives save/load; the
layout keeps the skill row clear of the save row, the HP bar clear of Class Level, and the NPC
N/day spells inside the dialog.
"""

import json
import os
import sys
import tempfile

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine, create_test_agent,
                          add_agent_to_battle)


def test_bonus_adds_to_modifier_and_roll():
    bm, engine = setup_battle_map(), setup_combat_engine()
    i = add_agent_to_battle(engine, bm, create_test_agent("Strahd", 1, 1))
    s = engine.get_agent_stats(bm, i)
    s.dex = 18
    s.initiative_prof = False
    base = s.initiative_modifier
    assert base == 4, base
    s.initiative_bonus = 10
    assert s.initiative_modifier == 14
    engine.set_agent_stats(bm, i, s)
    entry = next(e for e in engine.roll_initiative(bm) if e.agent_idx == i)
    assert entry.modifier == 14, entry.modifier
    print("✅ test_bonus_adds_to_modifier_and_roll passed")


def _app():
    from main import App
    from test_combat_panel import MAP_PATH, SEED, _build_scene, _idx
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    return app, _idx(app, "Aria")


def _open(app, idx, **kw):
    dlg = app.stats_dialog
    st = app.combat.get_agent_stats(app.bm, idx)
    dlg.open(app.screen, idx, "Aria", st, "Fighter", 5, app._on_stats_ok, **kw)
    return dlg


def test_dialog_sets_initiative():
    app, aria = _app()
    st = app.combat.get_agent_stats(app.bm, aria)
    st.initiative_bonus = 0
    app.combat.set_agent_stats(app.bm, aria, st)
    base = app.combat.get_agent_stats(app.bm, aria).initiative_modifier

    dlg = _open(app, aria)
    assert dlg.steppers["initiative"].value == base
    dlg.steppers["initiative"].value = base + 7
    dlg._confirm()
    s = app.combat.get_agent_stats(app.bm, aria)
    assert s.initiative_modifier == base + 7 and s.initiative_bonus == 7, (s.initiative_modifier, s.initiative_bonus)

    # Untouched initiative keeps the bonus: +2 DEX mod moves the total by 2.
    dlg = _open(app, aria)
    assert dlg.steppers["initiative"].value == base + 7
    dlg.steppers["dex"].value = dlg.steppers["dex"].value + 4
    dlg._confirm()
    s = app.combat.get_agent_stats(app.bm, aria)
    assert s.initiative_bonus == 7 and s.initiative_modifier == base + 9, (s.initiative_bonus, s.initiative_modifier)
    print("✅ test_dialog_sets_initiative passed")


def test_bonus_survives_save_load():
    from agent_loader import dict_to_stats
    assert dict_to_stats({"initiative_bonus": 7}).initiative_bonus == 7
    assert dict_to_stats({}).initiative_bonus == 0
    app, aria = _app()
    st = app.combat.get_agent_stats(app.bm, aria)
    st.initiative_bonus = 5
    app.combat.set_agent_stats(app.bm, aria, st)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "agents.json")
        app._save_agents(path)
        data = json.load(open(path))
    rows = data if isinstance(data, list) else data.get("agents", [])
    aria_row = next(r for r in rows if r.get("name") == "Aria")
    assert aria_row["stats"]["initiative_bonus"] == 5
    print("✅ test_bonus_survives_save_load passed")


def test_layout_has_room():
    app, aria = _app()
    long_groups = {"1": ["Wall of Fire", "Polymorph", "Greater Invisibility"],
                   "2": ["Fireball", "Scrying", "Gust of Wind", "Animate Dead", "Mirror Image"],
                   "99": ["Detect Magic", "Detect Thoughts", "Dispel Magic", "Fog Cloud",
                          "Charm Person", "Hold Person", "Misty Step"]}
    dlg = _open(app, aria, is_npc=True, npc_spell_groups=long_groups)
    surf = pygame.Surface((dlg.DLG_W, dlg.DLG_H), pygame.SRCALPHA)
    dlg._draw_body(surf)
    PAD = dlg.PAD

    # Skill boxes sit below the save boxes (and the modifier text above them), clear of each.
    save_bottom = max(r.bottom for r in dlg._prof_rects.values())
    for r in (dlg._athletics_rect, dlg._sleight_rect):
        assert r.y > save_bottom, (r, save_bottom)
    assert not dlg._athletics_rect.colliderect(dlg._sleight_rect)
    # The combat stats start below the skill row.
    assert min(st.rect.y for k, st in dlg.steppers.items()
               if k in {c[1] for c in dlg.COMBAT}) - 14 > dlg._sleight_rect.bottom

    # HP bar (10 below the last combat row, 18 tall) is clear of the Class Level label.
    last_bottom = max(dlg.steppers[c[1]].rect.bottom for c in dlg.COMBAT)
    assert last_bottom + 10 + 18 < dlg._char_level_stepper.rect.y - 14

    # Every N/day spell control stays inside the dialog, and above OK/Cancel.
    rects = list(dlg._npc_spell_rects["remove"].values()) + list(dlg._npc_spell_rects["add"].values())
    for r in rects:
        assert r.right <= dlg.DLG_W - PAD, r
    assert dlg._npc_add_group_rect.bottom < dlg._ok_rect(dlg._dlg()).y
    print("✅ test_layout_has_room passed")


def main():
    print("Running Edit Stats initiative tests...\n")
    test_bonus_adds_to_modifier_and_roll()
    test_dialog_sets_initiative()
    test_bonus_survives_save_load()
    test_layout_has_room()
    print("\nAll Edit Stats initiative tests passed.")


if __name__ == "__main__":
    main()
