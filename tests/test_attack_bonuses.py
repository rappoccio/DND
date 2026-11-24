"""DM-set +Hit / +Spell Attack / +Spell Save DC, on a character and on items.

Covered: Stats.attack_bonus reaches weapon to-hit (roll_to_hit) and spell attacks
(npc_spell_hit_chance); spell_attack_bonus reaches spells but not weapons; the Edit Stats
dialog writes all three; they survive save/load; the Weapon dialog's +Hit / +Dmg fields take
clicks (they used to be dead) and its Spell Atk / Spell DC fields become the weapon's
item_bonuses; the Items dialog's Bonus editor writes an item's item_bonuses, which the engine
then counts (carried_item_bonuses).
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
from helpers import _dict_to_item, _dict_to_weapon, _weapon_to_dict


def _app():
    from main import App
    from test_combat_panel import MAP_PATH, SEED, _build_scene, _idx
    app = App(MAP_PATH, seed=SEED)
    app.autosave_enabled = False
    _build_scene(app)
    return app, _idx(app, "Aria")


def _click(dialog, rect, screen):
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=rect.center)
    return dialog.handle(ev, screen)


def _key(dialog, key, screen, uni=""):
    return dialog.handle(pygame.event.Event(pygame.KEYDOWN, key=key, unicode=uni, mod=0), screen)


def test_weapon_to_hit():
    eng = rpg.CombatEngine(1)
    w = rpg.Weapon()
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    s = rpg.Stats()
    s.str, s.prof_bonus = 10, 2
    base = eng.roll_to_hit(w, s, 10).attack_mod
    s.attack_bonus = 3
    assert eng.roll_to_hit(w, s, 10).attack_mod == base + 3
    s.spell_attack_bonus = 5            # spells only
    assert eng.roll_to_hit(w, s, 10).attack_mod == base + 3
    w.bonus_hit = 1                     # the weapon's own, stacked
    assert eng.roll_to_hit(w, s, 10).attack_mod == base + 4
    print("✅ test_weapon_to_hit passed")


def test_spell_hit_chance_rises():
    app, aria = _app()
    target = next(i for i, p in enumerate(app.bm.placed_agents) if i != aria)
    fb = rpg.Spell()
    for sp in json.load(open(os.path.join(os.path.dirname(rpg.__file__), "spells.json"))):
        if sp["name"] == "Fire Bolt":
            from helpers import _dict_to_spell
            fb = _dict_to_spell(sp)
            break
    st = app.combat.get_agent_stats(app.bm, aria)
    st.attack_bonus = st.spell_attack_bonus = 0
    app.combat.set_agent_stats(app.bm, aria, st)
    p0 = app.combat.npc_spell_hit_chance(app.bm, aria, target, fb)
    st.attack_bonus = 2
    app.combat.set_agent_stats(app.bm, aria, st)
    p1 = app.combat.npc_spell_hit_chance(app.bm, aria, target, fb)
    st.spell_attack_bonus = 2
    app.combat.set_agent_stats(app.bm, aria, st)
    p2 = app.combat.npc_spell_hit_chance(app.bm, aria, target, fb)
    assert p0 < p1 < p2, (p0, p1, p2)
    print("✅ test_spell_hit_chance_rises passed")


def test_stats_dialog_and_save_load():
    from agent_loader import dict_to_stats
    app, aria = _app()
    dlg = app.stats_dialog
    st = app.combat.get_agent_stats(app.bm, aria)
    dlg.open(app.screen, aria, "Aria", st, "Fighter", 5, app._on_stats_ok)
    dlg.steppers["attack_bonus"].value = 1
    dlg.steppers["spell_attack_bonus"].value = 2
    dlg.steppers["spell_dc_bonus"].value = 3
    dlg._confirm()
    s = app.combat.get_agent_stats(app.bm, aria)
    assert (s.attack_bonus, s.spell_attack_bonus, s.spell_dc_bonus) == (1, 2, 3)

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "agents.json")
        app._save_agents(path)
        data = json.load(open(path))
    rows = data if isinstance(data, list) else data.get("agents", [])
    row = next(r for r in rows if r.get("name") == "Aria")["stats"]
    back = dict_to_stats(row)
    assert (back.attack_bonus, back.spell_attack_bonus, back.spell_dc_bonus) == (1, 2, 3)
    assert dict_to_stats({}).spell_dc_bonus == 0
    print("✅ test_stats_dialog_and_save_load passed")


def test_weapon_dialog_bonus_fields():
    app, aria = _app()
    wd = app.weapon_dialog
    got = {}
    staff = rpg.Weapon()
    staff.name, staff.type, staff.proficient = "Quarterstaff", rpg.WeaponType.Melee, True
    wd.open(app.screen, aria, "Aria", [_weapon_to_dict(staff)],
            lambda idx, ws: got.setdefault("w", ws))
    wd.draw(app.screen)
    for key, digit, uni in (("bonus_hit", pygame.K_2, "2"),
                            ("ib_spell_attack", pygame.K_1, "1"),
                            ("ib_spell_dc", pygame.K_1, "1")):
        assert _click(wd, wd._rects[key], app.screen)
        assert wd._active_field == key, (key, wd._active_field)
        _key(wd, digit, app.screen, uni)
        _key(wd, pygame.K_RETURN, app.screen)
    wd._confirm()
    d = got["w"][0]
    assert d["bonus_hit"] == 2, d.get("bonus_hit")
    assert d["item_bonuses"] == {"spell_attack": 1, "spell_dc": 1}, d.get("item_bonuses")
    w = _dict_to_weapon(d)
    assert w.bonus_hit == 2 and w.item_spells.bonuses.spell_dc == 1
    print("✅ test_weapon_dialog_bonus_fields passed")


def test_items_dialog_bonus_editor():
    app, aria = _app()
    dlg = app.items_dialog
    ring = _dict_to_item({"name": "Plain Ring", "quantity": 1})
    done = {}
    dlg.open(app.screen, aria, "Aria", [ring], app.item_selection_dialog,
             lambda: done.setdefault("ok", True))
    dlg.draw(app.screen)
    assert _click(dlg, dlg._bonus_rect(0), app.screen)
    assert dlg._bonus_row == 0
    dlg.draw(app.screen)
    for _ in range(2):
        assert _click(dlg, dlg._bonus_steppers["spell_dc"].btn_inc, app.screen)
    assert _click(dlg, dlg._bonus_steppers["spell_attack"].btn_inc, app.screen)
    assert dlg.current_items[0]["item_bonuses"] == {"spell_dc": 2, "spell_attack": 1}
    dlg.draw(app.screen)
    assert dlg.rect.contains(dlg._editor_rect()), (dlg.rect, dlg._editor_rect())
    assert _click(dlg, dlg._editor_done_rect(), app.screen)
    assert dlg._bonus_row == -1

    app.combat.set_agent_items(app.bm, aria, [_dict_to_item(d) for d in dlg.current_items])
    b = app.combat.carried_item_bonuses(app.bm, aria)
    assert (b.spell_dc, b.spell_attack) == (2, 1), (b.spell_dc, b.spell_attack)

    # Back to zero drops the key, so the ring is ordinary again.
    dlg.open(app.screen, aria, "Aria", app.combat.get_agent_items(app.bm, aria),
             app.item_selection_dialog, None)
    dlg.draw(app.screen)
    _click(dlg, dlg._bonus_rect(0), app.screen)
    dlg._bonus_steppers["spell_dc"].value = 0
    dlg._bonus_steppers["spell_attack"].value = 0
    dlg._sync_bonuses()
    assert "item_bonuses" not in dlg.current_items[0]
    print("✅ test_items_dialog_bonus_editor passed")


def main():
    print("Running attack / spell bonus tests...\n")
    pygame.init()
    test_weapon_to_hit()
    test_spell_hit_chance_rises()
    test_stats_dialog_and_save_load()
    test_weapon_dialog_bonus_fields()
    test_items_dialog_bonus_editor()
    print("\nAll attack / spell bonus tests passed.")


if __name__ == "__main__":
    main()
