#!/usr/bin/env python3
"""The manual smoke pass's LOOKING half, as a rig (MULTIPLAYER_PLAN.md M2).

**Not part of `run_all_tests.py`** — it needs a display, it asserts almost nothing, and
its output is a directory of PNGs for a human to look at. `tests/test_gui_headless_smoke.py`
is the half that can be asserted; this is the half that cannot.

It runs the real `App` against a real X server — no `SDL_VIDEODRIVER=dummy` anywhere —
so pixels go through pygame → X11 → Xvfb and come back via `PIL.ImageGrab`. Scenarios are
built the way `tests/test_combat_panel.py` builds them, because driving character creation
through the UI would take an hour and prove nothing the panel does not already show.

Clicks are posted into the app's real event loop rather than synthesized with XTEST: the
image has no `python-xlib`, and the X input path is not what M2 changed. Say so in the
write-up rather than implying the pass covered it.

Run it inside the container, which already has Xvfb:

    docker run --rm -v "$HOME":/home/user -v /some/out/dir:/shots rpg_map -c \
      'Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset & sleep 2
        export DISPLAY=:99
        cd /home/user/Claude/DND && python3 tests/manual_smoke_xvfb.py /shots'

Then look at the PNGs. Every scenario is one panel, cropped out of the root window.
"""

import os, sys

os.environ.pop("SDL_VIDEODRIVER", None)
os.environ.pop("SDL_AUDIODRIVER", None)
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")     # no sound card in the container
os.environ["DISPLAY"] = ":99"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "gui"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import pygame
from PIL import ImageGrab
import rpg_battle_map as rpg

from constants import COL_BG, PANEL_W
from menus import panel
from actions import METAMAGIC_OPTIONS, METAMAGIC_ID_BY_VALUE
from test_combat_panel import (App, MAP_PATH, SEED, _build_scene, _goto, _idx,
                               _reclass, _set_conditions, _set_res, _spell,
                               _snapshot_baseline, _weapon)

OUT = sys.argv[1] if len(sys.argv) > 1 else "/shots"


def frame(app):
    app.screen.fill(COL_BG)
    app._draw_map()
    app._draw_agents()
    app._draw_panel()
    pygame.display.flip()
    pygame.event.pump()


_ORIGIN = []

def shot(app, name):
    frame(app)
    pygame.time.wait(150)
    img = ImageGrab.grab(xdisplay=":99").convert("RGB")
    if not _ORIGIN:
        bbox = img.getbbox()          # where the app window actually landed on the root
        print("  window bbox on root:", bbox)
        _ORIGIN.append((bbox[0], bbox[1]) if bbox else (0, 0))
        img.save(os.path.join(OUT, "00_full_root.png"))
    ox, oy = _ORIGIN[0]
    w, h = app.screen.get_size()
    px = ox + app._panel_x()
    img = img.crop((px, oy, min(px + PANEL_W, img.width), min(oy + h, img.height)))
    path = os.path.join(OUT, f"{name}.png")
    img.save(path)
    print(f"  saved {path}  ({img.width}x{img.height})")
    return path


def click(app, action_id):
    """A real click on the widget the panel last drew for `action_id`."""
    r = panel.cbt_btn(app, action_id).rect
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                         pos=r.center, button=1))
    alive = app._handle_events()
    assert alive is not False, "the app quit"


def main():
    #  sets SDL_VIDEODRIVER=dummy at import time (it is a headless
    # suite). This pass is the opposite of headless, so undo it before the App builds
    # its window — the whole point is that pixels land on a real X server.
    os.environ.pop("SDL_VIDEODRIVER", None)
    app = App(MAP_PATH, seed=SEED)
    print("SDL video driver:", pygame.display.get_driver())
    assert pygame.display.get_driver() != "dummy", "not on the real display"
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()
    _snapshot_baseline(app)
    print("window", app.screen.get_size(), "panel_x", app._panel_x())

    # ── 7b: the one-up, then the two-up with BOTH columns ──
    aria = _goto(app, "Aria")
    shot(app, "01_7b_oneup_fighter")
    app.combat.set_agent_spells(app.bm, aria, [_spell(app, "Fire Bolt")])
    shot(app, "02_7b_twoup_both_columns")
    _goto(app, "Aria")
    app.bonus_used = True
    app.attacks_remaining = 2
    app._attack_sequence_slot = "bonus"
    shot(app, "03_7b_twoup_mid_bonus_sequence")
    # F14, in the app: the header says how many swings are left and the click does
    # nothing, because both handlers sit inside the `not self.bonus_used` block.
    frame(app)
    before = (app.pending_attack_slot, app.pending_spell_slot)
    click(app, "atk_bonus")
    click(app, "spell_bonus")
    print("  F14 dead click: pending before", before,
          "after", (app.pending_attack_slot, app.pending_spell_slot))
    app.combat.set_agent_spells(app.bm, aria, [])

    # ── 7d: the nine toggles, armed, incarnate, and the caption alone ──
    cyra = _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 7)
    s = app.combat.get_agent_stats(app.bm, cyra)
    s.metamagic_options = [v for v, _n, _sp, _note in METAMAGIC_OPTIONS]
    app.combat.set_agent_stats(app.bm, cyra, s)
    shot(app, "04_7d_nine_metamagic_toggles")

    # a real click on one of them: the tick, the highlight, the log line
    frame(app)
    click(app, "metamagic_heightened")
    shot(app, "05_7d_armed_by_a_real_click")
    print("  armed_metamagic =", app.armed_metamagic)

    frame(app)
    click(app, "metamagic_seeking")
    shot(app, "06_7d_seeking_stacks_beside_it")
    print("  armed_seeking =", app.armed_seeking, " armed_metamagic =", app.armed_metamagic)

    s = app.combat.get_agent_stats(app.bm, cyra)
    s.innate_sorcery_turns = 10
    app.combat.set_agent_stats(app.bm, cyra, s)
    app.armed_metamagic2 = rpg.MetamagicOption.Twinned
    shot(app, "07_7d_sorcery_incarnate_caption")

    _set_res(app, cyra, "Sorcery Points", 0)
    shot(app, "08_7d_caption_over_nothing")
    app.armed_metamagic = rpg.MetamagicOption.NONE
    app.armed_metamagic2 = rpg.MetamagicOption.NONE
    app.armed_seeking = False

    # ── 7d: Haste's extra Action, with the Bonus Action already spent ──
    aria_h = _goto(app, "Aria")
    s = app.combat.get_agent_stats(app.bm, aria_h)
    s.haste_action_available = True
    app.combat.set_agent_stats(app.bm, aria_h, s)
    app.bonus_used = True
    shot(app, "09_7d_haste_survives_a_spent_bonus")
    s = app.combat.get_agent_stats(app.bm, aria_h)
    s.haste_action_available = False
    app.combat.set_agent_stats(app.bm, aria_h, s)

    # ── F10: two telekinetic options, two labels, two handlers ──
    cyra_f10 = _reclass(app, "Cyra", rpg.CharacterClass.Fighter, 3,
                        fighter_subclass=rpg.FighterSubclass.PsiWarrior)
    s = app.combat.get_agent_stats(app.bm, cyra_f10)
    s.add_feat("Telekinetic")
    app.combat.set_agent_stats(app.bm, cyra_f10, s)
    shot(app, "10_F10_two_widgets_two_labels")

    app.pending_shove_type = ""
    app.pending_telekinetic = False
    frame(app)
    click(app, "telekinetic_psi")
    print("  after clicking Movement: pending_telekinetic =", app.pending_telekinetic,
          " pending_shove_type =", repr(app.pending_shove_type))
    shot(app, "11_F10_psi_click_arms_only_psi")
    app.pending_telekinetic = False
    frame(app)
    click(app, "telekinetic_feat")
    print("  after clicking Shove:    pending_telekinetic =", app.pending_telekinetic,
          " pending_shove_type =", repr(app.pending_shove_type))
    shot(app, "12_F10_feat_click_arms_only_feat")
    app.pending_shove_type = ""
    app.pending_telekinetic = False
    s = app.combat.get_agent_stats(app.bm, cyra_f10)
    s.feats = []
    app.combat.set_agent_stats(app.bm, cyra_f10, s)

    # ── M2d's owed looking: the longest labels and the two rows ──
    _reclass(app, "Cyra", rpg.CharacterClass.Bard, 14,
             bard_subclass=rpg.BardCollege.Glamour)
    shot(app, "13_M2d_glamour_bard_longest_labels")
    _reclass(app, "Cyra", rpg.CharacterClass.Monk, 17,
             monk_subclass=rpg.MonkSubclass.WarriorOfShadow)
    shot(app, "14_M2d_shadow_monk_cluster")
    _reclass(app, "Cyra", rpg.CharacterClass.Rogue, 13,
             rogue_subclass=rpg.RogueSubclass.Soulknife)
    shot(app, "15_M2d_soulknife_and_cunning_row")
    _reclass(app, "Cyra", rpg.CharacterClass.Warlock, 6,
             warlock_subclass=rpg.WarlockSubclass.Archfey)
    shot(app, "16_M2d_archfey_rider")

    # bucket 7c: a grappler with an auto-bite weapon, then netted
    aria_g = _goto(app, "Aria")
    skarn = _idx(app, "Skarn")
    _set_conditions(app, skarn, grappled=True, grappler_idx=aria_g)
    bite = _weapon(app, "Longsword")
    bite.auto_use_when_grappling = True
    app.combat.set_agent_weapons(app.bm, aria_g,
                                 [bite, _weapon(app, "Shortsword", off_hand=True)])
    shot(app, "17_M2d_drop_grapple_and_bite")
    app.combat.set_agent_weapons(app.bm, aria_g,
                                 [_weapon(app, "Longsword"),
                                  _weapon(app, "Shortsword", off_hand=True)])
    _set_conditions(app, skarn, grappled=False, grappler_idx=-1)

    # ── F13: nobody on turn ──
    _goto(app, "Aria")
    app.initiative_order = []
    shot(app, "18_F13_nobody_on_turn")

    print("\nOK")


if __name__ == "__main__":
    try:
        main()
    finally:
        pygame.quit()
