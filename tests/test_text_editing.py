#!/usr/bin/env python3
"""Single-line text editing in every typed field (widgets.edit_line).

Fields used to append at the end and erase from the end only. They now carry a caret:
← / → move it, Home / End jump, Backspace / Delete erase around it, typing inserts at
it, and Ctrl/Cmd+C copies the field, Ctrl/Cmd+X cuts it, Ctrl/Cmd+V pastes at the caret.

  · edit_line itself: caret moves, mid-string insert/erase, clipboard, accept veto;
  · TextInput, IntStepper (digits only), NamePromptDialog, a picker's search box,
    and the weapon editor's per-type dice fields all route through it;
  · the PC-name field's arrows move its caret instead of panning the map.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame

pygame.init()
pygame.display.set_mode((1400, 900))
FONT = pygame.font.Font(None, 20)

from widgets import edit_line, TextInput, IntStepper, clipboard_put

CMD = pygame.KMOD_CTRL


def _key(k, ch="", mod=0):
    return pygame.event.Event(pygame.KEYDOWN, key=k, mod=mod, unicode=ch, scancode=0)


def _type(text):
    return [_key(pygame.key.key_code(c) if c.isalnum() else pygame.K_SPACE, c) for c in text]


def _run(text, caret, events, accept=None):
    for e in events:
        text, caret, _ = edit_line(text, caret, e, accept)
    return text, caret


def test_caret_moves_and_edits_mid_string():
    t, c = _run("helo", None, [_key(pygame.K_LEFT), _key(pygame.K_l, "l")])
    assert (t, c) == ("hello", 4), (t, c)
    t, c = _run(t, c, [_key(pygame.K_HOME), _key(pygame.K_DELETE), _key(pygame.K_h, "H")])
    assert (t, c) == ("Hello", 1), (t, c)
    t, c = _run(t, c, [_key(pygame.K_RIGHT), _key(pygame.K_BACKSPACE)])
    assert (t, c) == ("Hllo", 1), (t, c)
    t, c = _run(t, c, [_key(pygame.K_LEFT)] * 5 + [_key(pygame.K_BACKSPACE)])
    assert (t, c) == ("Hllo", 0), "erasing at the start does nothing"
    t, c = _run(t, c, [_key(pygame.K_END), _key(pygame.K_RIGHT), _key(pygame.K_DELETE)])
    assert (t, c) == ("Hllo", 4), "moving or deleting past the end does nothing"
    print("✅ test_caret_moves_and_edits_mid_string passed")


def test_cut_copy_paste():
    clipboard_put("")
    t, c = _run("abc", 1, [_key(pygame.K_c, "\x03", CMD)])
    assert (t, c) == ("abc", 1), "copy leaves the field alone"
    t, c = _run("XY", 1, [_key(pygame.K_v, "\x16", CMD)])
    assert (t, c) == ("XabcY", 4), (t, c)
    t, c = _run(t, c, [_key(pygame.K_x, "\x18", pygame.KMOD_META)])
    assert (t, c) == ("", 0), "Cmd+X cuts the field"
    t, c = _run(t, c, [_key(pygame.K_v, "\x16", pygame.KMOD_META)])
    assert (t, c) == ("XabcY", 5), "the cut text pastes back"
    clipboard_put("line one\nline\ttwo")
    t, _ = _run("", None, [_key(pygame.K_v, "\x16", CMD)])
    assert t == "line one line two", f"a multi-line paste folds onto one line: {t!r}"
    print("✅ test_cut_copy_paste passed")


def test_accept_vetoes_edits():
    import re
    digits = re.compile(r"\d*").fullmatch
    t, c = _run("12", None, [_key(pygame.K_a, "a"), _key(pygame.K_LEFT), _key(pygame.K_5, "5")],
                digits)
    assert (t, c) == ("152", 2), (t, c)
    clipboard_put("9x")
    t, _ = _run(t, c, [_key(pygame.K_v, "\x16", CMD)], digits)
    assert t == "152", "a paste the field can't hold is refused"
    clipboard_put("34")
    t, _ = _run(t, c, [_key(pygame.K_v, "\x16", CMD)], digits)
    assert t == "15342", t
    print("✅ test_accept_vetoes_edits passed")


def test_text_input_and_int_stepper():
    ti = TextInput(pygame.Rect(0, 0, 200, 30), font=FONT)
    ti.text, ti.active = "seed", True
    for e in [_key(pygame.K_LEFT), _key(pygame.K_LEFT), _key(pygame.K_x, "x")]:
        ti.handle(e)
    assert ti.text == "sexed", ti.text
    ti.draw(pygame.display.get_surface())

    st = IntStepper(pygame.Rect(0, 100, 150, 30), 7, -99, 99, font=FONT)
    st.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=st.field.center))
    for e in _type("15") + [_key(pygame.K_HOME), _key(pygame.K_MINUS, "-"),
                            _key(pygame.K_MINUS, "-"), _key(pygame.K_RETURN)]:
        st.handle(e)
    assert st.value == -15, st.value
    st.draw(pygame.display.get_surface())
    print("✅ test_text_input_and_int_stepper passed")


def test_name_prompt_and_search_box():
    from dialogs import NamePromptDialog, MobSelectionDialog
    got = []
    np_ = NamePromptDialog(FONT, FONT)
    np_.show("Gobin", got.append)
    for e in [_key(pygame.K_LEFT), _key(pygame.K_LEFT), _key(pygame.K_l, "l"),
              _key(pygame.K_RETURN)]:
        np_.handle(e)
    assert got == ["Goblin"], got

    md = MobSelectionDialog(["Goblin", "Orc", "Ogre"], FONT, FONT)
    md.show(lambda m: None)
    for e in _type("Ore") + [_key(pygame.K_LEFT), _key(pygame.K_LEFT), _key(pygame.K_g, "g")]:
        md.handle(e)
    assert md.search_text == "Ogre" and md.filtered_mobs == ["Ogre"], \
        (md.search_text, md.filtered_mobs)
    md.draw(pygame.display.get_surface())
    print("✅ test_name_prompt_and_search_box passed")


def test_weapon_dice_fields_edit_their_roll():
    from weapon_dialog import WeaponDialog
    from helpers import _DEFAULT_WEAPON
    screen = pygame.display.get_surface()
    wd = WeaponDialog(FONT, FONT, FONT)
    wd.open(screen, 0, "Fighter", [dict(_DEFAULT_WEAPON)], lambda *a: None)
    wd._sel = 0
    wd._load_form()
    wd.draw(screen)
    key = "phys_die_size_Slashing"
    assert key in wd._rects, sorted(k for k in wd._rects if k.startswith("phys"))
    wd.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                 pos=wd._rects[key].center), screen)
    assert wd._active_field == key, wd._active_field
    for e in [_key(pygame.K_BACKSPACE), _key(pygame.K_1, "1"), _key(pygame.K_0, "0")]:
        wd.handle(e, screen)
    roll = wd._f["physical_damage_types"][0]
    assert roll["die_size"] == 10, roll
    wd.draw(screen)
    print("✅ test_weapon_dice_fields_edit_their_roll passed")


def test_pc_name_arrows_do_not_pan_the_map():
    from main import App
    app = App(os.path.join(_ROOT, "maps", "TestGrid12x12.png"), seed=1)
    app._pc_name_input = TextInput(pygame.Rect(0, 0, 200, 30), font=FONT)
    app._pc_name_input.text, app._pc_name_input.active = "Bran", True
    pan = []
    app._pan_by = lambda dx, dy: pan.append((dx, dy))
    for e in [_key(pygame.K_LEFT), _key(pygame.K_d, "d")]:
        pygame.event.post(e)
    app._handle_events()
    assert not pan, f"arrow keys panned the map while typing: {pan}"
    assert app._pc_name_input.text == "Bradn", app._pc_name_input.text
    print("✅ test_pc_name_arrows_do_not_pan_the_map passed")


def main():
    tests = [test_caret_moves_and_edits_mid_string,
             test_cut_copy_paste,
             test_accept_vetoes_edits,
             test_text_input_and_int_stepper,
             test_name_prompt_and_search_box,
             test_weapon_dice_fields_edit_their_roll,
             test_pc_name_arrows_do_not_pan_the_map]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_text_editing: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_text_editing: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
