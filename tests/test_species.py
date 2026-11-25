"""SRD species framework (SPECIES_PLAN.md SP1: D1 table + D2 sub-choices).

Covered: the nine SRD species are in the table after Dhampir, with their option lists
(dragon colour, lineage, Giant ancestry, Fiendish legacy), size options and the
spell-ability flag; set_species fills the defaults, keeps a valid option on a re-send,
replaces an invalid one, and clears them for "no species"; the size and spell-ability
setters refuse what the species doesn't allow; the choices survive the agent-JSON save
and load, and an older save with none gets the defaults; the Stats dialog shows the
pickers only for species that have them, cycles them, and hands the picks to OK.
The traits of the nine species (Speed, Darkvision, resistances) are SP2.
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg

INT, WIS, CHA = 3, 4, 5
SRD = ["Dragonborn", "Dwarf", "Elf", "Gnome", "Goliath", "Halfling", "Human", "Orc", "Tiefling"]


def test_table_lists_the_srd_species():
    assert list(rpg.species_names()) == ["Dhampir"] + SRD
    expect = {
        "Dragonborn": ("Ancestry", ["Black", "Blue", "Brass", "Bronze", "Copper", "Gold", "Green",
                                    "Red", "Silver", "White"]),
        "Elf":        ("Lineage", ["Drow", "High Elf", "Wood Elf"]),
        "Gnome":      ("Lineage", ["Forest Gnome", "Rock Gnome"]),
        "Goliath":    ("Ancestry", ["Cloud", "Fire", "Frost", "Hill", "Stone", "Storm"]),
        "Tiefling":   ("Legacy", ["Abyssal", "Chthonic", "Infernal"]),
    }
    for name in ["Dhampir"] + SRD:
        label, opts = expect.get(name, ("", []))
        assert rpg.species_option_label(name) == label, name
        assert list(rpg.species_options(name)) == opts, name
    sizes = {"Gnome": ["Small"], "Halfling": ["Small"], "Human": ["Small", "Medium"],
             "Tiefling": ["Small", "Medium"], "Dhampir": ["Small", "Medium"]}
    for name in ["Dhampir"] + SRD:
        assert list(rpg.species_sizes(name)) == sizes.get(name, ["Medium"]), name
    assert {n for n in ["Dhampir"] + SRD if rpg.species_has_spell_ability(n)} == {"Elf", "Gnome", "Tiefling"}
    assert rpg.species_options("") == [] and rpg.species_sizes("Nope") == []
    print("✅ test_table_lists_the_srd_species passed")


def test_set_species_defaults_and_keeps_choices():
    s = rpg.Stats()
    s.set_species("Tiefling")
    assert (s.species_option, s.species_size, s.species_spell_ability) == ("Abyssal", "Medium", INT)
    s.set_species("Tiefling", "Infernal")
    assert s.species_option == "Infernal"
    s.set_species("Tiefling")                     # re-send with no option: keeps Infernal
    assert s.species_option == "Infernal"
    s.set_species("Tiefling", "Bogus")            # unknown option: the default
    assert s.species_option == "Abyssal"
    assert s.set_species_size("Small") and s.species_size == "Small"
    assert not s.set_species_size("Large") and s.species_size == "Small"
    assert s.set_species_spell_ability(CHA) and s.species_spell_ability == CHA
    assert not s.set_species_spell_ability(1) and s.species_spell_ability == CHA

    s.set_species("Gnome")                        # Small only; Lineage resets to Forest
    assert (s.species_option, s.species_size) == ("Forest Gnome", "Small")
    s.set_species("Dwarf")                        # no option, Medium only, no ability pick
    assert (s.species_option, s.species_size) == ("", "Medium")
    assert not s.set_species_spell_ability(WIS)
    assert not s.set_species_size("Small")
    s.set_species("")
    assert (s.species, s.species_option, s.species_size) == ("", "", "")
    assert not s.set_species_size("Medium")
    print("✅ test_set_species_defaults_and_keeps_choices passed")


def test_option_swap_keeps_dhampir_strip_intact():
    """An option change re-applies the species; with no option-driven traits yet the
    stat block is unchanged, and the Dhampir strip still restores what it set."""
    s = rpg.Stats()
    s.speed_walk = 30
    s.set_species("Dragonborn", "Red")
    s.set_species("Dragonborn", "Blue")
    assert s.species_option == "Blue" and s.speed_walk == 30
    s.set_species("Dhampir")
    assert s.speed_walk == 35 and s.species_option == ""
    s.set_species("Elf", "Drow")
    assert s.speed_walk == 30 and s.species_option == "Drow"
    print("✅ test_option_swap_keeps_dhampir_strip_intact passed")


def test_loader_round_trip_and_legacy_defaults():
    from agent_loader import dict_to_stats
    s = dict_to_stats({"species": "Tiefling", "species_option": "Chthonic",
                       "species_size": "Small", "species_spell_ability": WIS})
    assert (s.species_option, s.species_size, s.species_spell_ability) == ("Chthonic", "Small", WIS)
    s = dict_to_stats({"species": "Elf"})          # saved before SP1: defaults
    assert (s.species_option, s.species_size, s.species_spell_ability) == ("Drow", "Medium", INT)
    s = dict_to_stats({"species": "Dwarf", "species_option": "Red", "species_size": "Small"})
    assert (s.species_option, s.species_size) == ("", "Medium"), "invalid picks normalized"
    s = dict_to_stats({})
    assert (s.species, s.species_option, s.species_size) == ("", "", "")
    print("✅ test_loader_round_trip_and_legacy_defaults passed")


def _app():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    from main import App
    from test_combat_panel import MAP_PATH, SEED, _build_scene, _idx
    app = App(MAP_PATH, seed=SEED)
    app.autosave_enabled = False
    _build_scene(app)
    return app, _idx(app, "Aria")


def test_app_save_round_trip():
    app, aria = _app()
    s = app.combat.get_agent_stats(app.bm, aria)
    s.set_species("Goliath", "Storm")
    app.combat.set_agent_stats(app.bm, aria, s)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "agents.json")
        app._save_agents(path)
        data = json.load(open(path))
    rows = data if isinstance(data, list) else data.get("agents", [])
    row = next(r for r in rows if r.get("name") == "Aria")["stats"]
    assert (row["species"], row["species_option"], row["species_size"]) == ("Goliath", "Storm", "Medium")
    assert row["species_spell_ability"] == INT
    print("✅ test_app_save_round_trip passed")


def _click(dlg, rect, screen):
    import pygame
    s, dest = dlg._placement(screen)
    pos = (dest.x + int(rect.centerx * s), dest.y + int(rect.centery * s))
    return dlg.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos), screen)


def test_dialog_pickers_and_ok():
    import pygame
    app, aria = _app()
    dlg = app.stats_dialog
    st = app.combat.get_agent_stats(app.bm, aria)
    st.set_species("")
    app.combat.set_agent_stats(app.bm, aria, st)
    dlg.open(app.screen, aria, "Aria", st, "Fighter", 5, app._on_stats_ok)
    surf = pygame.Surface((dlg.DLG_W, dlg.DLG_H), pygame.SRCALPHA)

    dlg._draw_body(surf)
    assert dlg._species_sub_rects == {}, "no species, no sub-choice pickers"
    while dlg._species != "Tiefling":
        _click(dlg, dlg._species_rects["right"], app.screen)
        dlg._draw_body(surf)
        if dlg._species == "Dwarf":
            assert set(dlg._species_sub_rects) == set(), "Dwarf has no choices"
        if dlg._species == "Halfling":
            assert set(dlg._species_sub_rects) == set(), "Halfling is Small only"
        if dlg._species == "Elf":
            assert set(dlg._species_sub_rects) == {"_species_option", "_species_ability"}
    assert set(dlg._species_sub_rects) == {"_species_option", "_species_size", "_species_ability"}
    assert (dlg._species_option, dlg._species_size, dlg._species_ability) == ("Abyssal", "Medium", INT)
    # The three pickers sit on two rows inside the dialog, clear of each other.
    rr = dlg._species_sub_rects
    rects = [rr[a][k] for a in rr for k in ("left", "right")]
    for i, a in enumerate(rects):
        assert surf.get_rect().contains(a)
        for b in rects[i + 1:]:
            assert not a.colliderect(b), (a, b)

    _click(dlg, rr["_species_option"]["left"], app.screen)     # Abyssal -> Infernal
    _click(dlg, rr["_species_size"]["right"], app.screen)      # Medium -> Small
    _click(dlg, rr["_species_ability"]["right"], app.screen)   # INT -> WIS
    _click(dlg, rr["_species_ability"]["right"], app.screen)   # WIS -> CHA
    assert (dlg._species_option, dlg._species_size, dlg._species_ability) == ("Infernal", "Small", CHA)
    dlg._confirm()
    s = app.combat.get_agent_stats(app.bm, aria)
    assert (s.species, s.species_option, s.species_size, s.species_spell_ability) == \
        ("Tiefling", "Infernal", "Small", CHA)

    # Re-opening shows the saved picks; changing species resets the option to the default.
    dlg.open(app.screen, aria, "Aria", s, "Fighter", 5, app._on_stats_ok)
    assert (dlg._species, dlg._species_option, dlg._species_size) == ("Tiefling", "Infernal", "Small")
    dlg._draw_body(surf)
    _click(dlg, dlg._species_rects["left"], app.screen)        # Tiefling -> Orc
    assert (dlg._species, dlg._species_option, dlg._species_size) == ("Orc", "", "Medium")
    print("✅ test_dialog_pickers_and_ok passed")


def main():
    test_table_lists_the_srd_species()
    test_set_species_defaults_and_keeps_choices()
    test_option_swap_keeps_dhampir_strip_intact()
    test_loader_round_trip_and_legacy_defaults()
    test_app_save_round_trip()
    test_dialog_pickers_and_ok()
    print("All species tests passed.")


if __name__ == "__main__":
    main()
