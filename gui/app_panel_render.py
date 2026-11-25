"""The right-hand panel's drawing. The setup panel (`draw_panel`, with its widget
re-anchoring `reposition_panel` and the shared `panel_layout`), the combat panel
(`draw_combat_panel`: the initiative strip, the active combatant's block, the §4 / §7
action rows, item spells, then the log tail in `draw_combat_panel_log`), and the two
overlays drawn after it, the party-XP scoreboard and the debug cell readout.

Moved out of `App` in APP_REFACTOR_PLAN.md A6, the same way as `app_board_render.py`
(A1.2): module-level functions taking the app; widgets, fonts and scroll state stay on
`app` (D3). The §4 / §7 row tuples moved here with the draw code that reads them; `main`
re-imports them by name, so `vars(main)` (tests) and `App._BON_DRAW_RUNS` (`net/offer.py`)
still see them.

`App` keeps a one-line forwarder for `draw_panel`, `draw_combat_panel` and
`reposition_panel`, which are reached by name from tests, `gui_driver` and `playback.py`;
calls to those go through the forwarder so an instance patch still sees them. The rest are
called directly; `main.py` calls `panel_layout`, `draw_xp_total` and
`draw_cursor_cell_info` as `app_panel_render.*(self, ...)`.
"""

import os

import pygame

import rpg_battle_map as rpg

import app_dungeon_pages
import app_initiative
import lair
import pending
from actions import ActionMenu, fey_rider_index, METAMAGIC_OPTIONS, METAMAGIC_ID_BY_VALUE
from constants import *
from helpers import (hp_status, item_spells_summary, is_scroll, scroll_line, can_read_scroll,
                     attuned_count, attunement_warning)
from menus import panel
from xp import level_for_xp


# S3 (M2b): §4's three rows, as the only place row membership is written down. The
# ActionMenu builds the Action group in column order; these say where each row breaks.
# An arm that offers none of a tuple's ids draws no row and consumes no height.
_ACT_ROW_ATTACK = ("atk_action", "unarmed")
_ACT_ROW_BITE   = ("vampiric_bite",)
_ACT_ROW_MOVE   = ("dash", "dodge", "disengage", "hide", "standup", "prone")
_ACT_ROW_SPELL  = ("spell_action",)

# §7's runs: a maximal stretch of converted buttons with no still-fused button between
# them. Each member is drawn as its own full-width row, in the menu's build order, so
# these tuples say WHICH run a button belongs to and never what order it takes within
# one. Like the _ACT_ROW_* tuples above, this is the only place it is written down.
# §7's two ROWS. Like `_ACT_ROW_*` these are laid out side by side, not stacked: Jump
# alone at full width when nothing is adjacent and a three-up when something is, and
# Cunning Action's three.
_BON_ROW_SHOVE     = ("long_jump", "shove_push", "shove_prone")
_BON_ROW_CUNNING   = ("dash_bonus", "disengage_bonus", "hide_bonus")

# Escape and the Telekinetic feat's shove, between the two rows.
_BON_RUN_ESCAPE    = ("grapple_esc", "telekinetic_feat")

# The ones drawn OUTSIDE the band, in draw order. What they have in common is exactly
# their `economy`: none of them costs the Bonus Action, which is why spending it must
# not take them (`actions._BONUS_ECONOMY`).
_BON_RUN_UNBANDED  = ("grapple_drop", "use_item", "extinguish", "escape_net",
                      "haste_action", "horde_breaker", "sudden_strike", "beasts_strike",
                      "action_surge")

# The Archfey trio, named on its own only because the rider selector's label is the one
# thing in §7 the draw pass WRITES back to the app. See the draw site.
_BON_FEY_TRIO = ("fey_effect", "steps_of_fey", "misty_escape")

# Everything inside the band gate, in draw order — one run, because after M2e there is
# no still-fused button left to cut the column. M2c needed six of these tuples and M2d
# thirteen, for exactly that reason. The feature groups survive as the comments.
_BON_RUN_BAND      = (
    # Orc Adrenaline Rush (species)
    "adrenaline_rush",
    # Monk, Barbarian, Warlock — the class band
    "patient_defense", "step_of_wind", "hand_of_healing", "wholeness_of_body",
    "rage", "intimidating_presence", "zealous_presence",
    "clairvoyant_combatant", "magical_cunning", "healing_light",
    # Cleric: the Channel Divinity cluster, then Divine Intervention
    "turn_undead", "radiance", "preserve_life", "divine_intervention",
    # Trickery Cleric: the Invoke Duplicity cluster
    "invoke_duplicity", "move_duplicity", "swap_duplicity",
    # Grave Cleric: Path to the Grave
    "path_to_the_grave",
    # Sorcerer, with Boon of Fate, Steady Aim and War Priest inside the stretch
    "dragon_wings", "draconic_resistance", "bend_luck", "boon_of_fate",
    "tides_of_chaos", "innate_sorcery", "trance_of_order", "bastion_of_law",
    "clockwork_cavalcade", "revelation_in_flesh", "warping_implosion",
    "wild_magic_extra_action", "wild_magic_bonus_cast", "wild_magic_teleport",
    "steady_aim", "war_priest",
    # the Bite the engine pairs with the creature being held
    "bite_grappled",
    # Hew to Lay on Hands
    "gwm_hew", "blink_steps", "martial_arts", "flurry_of_blows", "second_wind",
    "bm_maneuver", "one_with_shadows", "merge_shadows",
    "lay_on_hands",
    # Bard: Grant Inspiration and the College of Glamour four
    "grant_inspiration", "mantle", "mantle_majesty", "unbreakable_majesty",
    "beguiling_restore",
    # Use Inspiration Die, the Paladin oaths, Corona of Light
    "use_inspiration", "sacred_weapon", "vow_of_enmity", "inspiring_smite",
    "avenging_angel", "elder_champion", "living_legend", "corona",
    # Psi Warrior: Telekinetic Movement (the feat's shove is in _BON_RUN_ESCAPE)
    "telekinetic_psi",
    # Ranger
    "tireless", "natures_veil", "fey_reinforcements", "misty_wanderer",
    # Hunter's Mark / Hex — move the mark off a creature at 0 HP
    "move_hunters_mark",
    # Soulknife Rogue
    "psychic_teleport", "psychic_veil",
    # Shadow Monk
    "shadow_step", "cloak_of_shadows", "shadow_arts_darkness",
    # Archfey Warlock — the rider selector is also §7's one WRITE, see `fey_rider_index`
    "fey_effect", "steps_of_fey", "misty_escape",
    # Elemental Monk
    "elemental_attunement", "elemental_burst",
    # the tail: detonate, and the two summons
    "quivering_palm", "companion", "command_companion", "familiar",
)
_BON_RUN_METAMAGIC = tuple(METAMAGIC_ID_BY_VALUE[int(_v)]
                           for _v, _n, _sp, _note in METAMAGIC_OPTIONS)

# The order `_draw_combat_panel` draws §7 in, run by run: the economy-band header row,
# Arcane Ward, Wild Shape, then the rows and runs above. The menu BUILDS §7 in another
# order, so the player's offer (`net/offer.py`, QOL Q4) sorts its bonus rows by this; within
# a run both keep the build order. Keep it in step with the draw code.
_BON_DRAW_RUNS = (("atk_bonus", "spell_bonus"), ("charge_arcane_ward",), ("wild_shape",),
                  _BON_ROW_SHOVE, _BON_RUN_ESCAPE, _BON_ROW_CUNNING, _BON_RUN_UNBANDED,
                  _BON_RUN_BAND, _BON_RUN_METAMAGIC)


def panel_layout(app):
    """Return (px, W, list-of-y-positions) for a fresh layout pass."""
    px = app._panel_x() + app._PANEL_PAD
    W  = PANEL_W - app._PANEL_PAD * 2

    # Row stride = label + gap + widget + row-gap
    RS = app._LABEL_H + app._LABEL_GAP + app._WIDGET_H + app._ROW_GAP

    # y of the INPUT/STEPPER for each row (label sits RS-_WIDGET_H-_ROW_GAP above it)
    title_y  = 10
    row0_y   = title_y + app._TITLE_H + 10           # Agents… menu button
    btn0_y   = row0_y  + app._WIDGET_H + app._ROW_GAP + 8   # Clear All
    btn1_y   = btn0_y  + app._BTN_H + app._BTN_GAP + 4  # Long/Short Rest (half-width)

    return px, W, title_y, row0_y, btn0_y, btn1_y


def reposition_panel(app):
    """Re-anchor all setup-panel widgets. Buttons flow top-down; every y is shifted
    by ``-app.panel_scroll`` so the panel scrolls when its content is taller than the
    window, and by ``+shift`` to make room for the Floor-nav block that docks at the
    top in dungeon mode. Combat-panel button y-positions are owned by
    _draw_combat_panel and are never scrolled (only their x is refreshed here)."""
    px, W, _, r0, b0, b1 = panel_layout(app)
    SW  = W // 2 - 2
    B, G = app._BTN_H, app._BTN_GAP

    # ── Base (top-anchored, scroll-independent) y for each row ──
    bc_y           = b1            + B + G + 8
    rs_y           = bc_y          + B + G
    rd_y           = rs_y          + B + G
    ls_y           = rd_y          + B + G
    ter_y          = ls_y          + B + G
    light_y        = ter_y         + B + G
    dung_y         = light_y       + B + G
    toggle_walls_y = dung_y        + B + G
    toggle_fog_y   = toggle_walls_y + B + G
    toggle_anim_y  = toggle_fog_y  + B + G
    set_grid_y     = toggle_anim_y + B + G
    quit_y         = set_grid_y    + B + G
    stats_y        = quit_y        + B + 14

    # ── Floor-nav block: docks in the first slot (dungeon mode), pushing the
    #    config rows down by its height. Cached for _draw_panel to render. ──
    app._panel_floor_nav_h = app_dungeon_pages.floor_nav_height(app) if app_dungeon_pages.panel_has_floor_nav(app) else 0
    shift = (app._panel_floor_nav_h + G) if app._panel_floor_nav_h else 0

    # ── Clamp scroll to the actual overflow (content vs. visible window) ──
    content_h = stats_y + shift + 54            # + 3-line grid-stats footer
    visible_h = app.screen.get_height() - 22   # minus the fixed cursor-info strip
    app._panel_max_scroll = max(0, content_h - visible_h)
    app.panel_scroll = min(max(0, app.panel_scroll), app._panel_max_scroll)

    off = shift - app.panel_scroll
    app._panel_floor_nav_top = (r0 - app.panel_scroll) if app._panel_floor_nav_h else None
    app._panel_stats_y = stats_y + off

    app.btn_agents.rect.update(px, r0 + off, W, app._WIDGET_H)
    app.btn_clear.rect.update(px, b0 + off, W, B)
    app.btn_long_rest.rect.update(px, b1 + off, SW, B)
    app.btn_short_rest.rect.update(px + SW + 4, b1 + off, SW, B)
    app.btn_begin_combat.rect.update(px, bc_y + off, W, B)
    app.btn_restore_autosave.rect.update(px, rs_y + off, SW, B)
    app.btn_table.rect.update(px + SW + 4, rs_y + off, SW, B)
    app.btn_reset_dungeon.rect.update(px, rd_y + off, SW, B)
    app.btn_undo_reset.rect.update(px + SW + 4, rd_y + off, SW, B)
    app.btn_load_save.rect.update(px, ls_y + off, W, B)
    app.btn_terrain.rect.update(px, ter_y + off, W, B)
    app.btn_lighting.rect.update(px, light_y + off, SW, B)
    app.btn_items.rect.update(px + SW + 4, light_y + off, SW, B)
    app.btn_dungeon.rect.update(px, dung_y + off, W, B)
    app.btn_toggle_walls.rect.update(px, toggle_walls_y + off, W, B)
    app.btn_fog.rect.update(px, toggle_fog_y + off, W, B)
    app.btn_toggle_animate.rect.update(px, toggle_anim_y + off, W, B)
    app.btn_set_grid.rect.update(px, set_grid_y + off, W, B)
    app.btn_quit.rect.update(px, quit_y + off, W, B)
    # Thirteen combat-panel buttons used to have their x refreshed here on a resize,
    # with a hand-copy of the three row widths `_draw_combat_panel` computes. Deleted
    # in M2e: every one of them is laid out from the menu on the frame it is drawn,
    # so the copy could only ever agree or be wrong, and a rect that is never read
    # between resize and repaint does not need keeping up to date.


def draw_item_spells_panel(app, agent_idx: int, lx: int, y: int, txt) -> int:
    """The side panel's 'Item spells' block (E4): one header per item, then its spell
    lines; an item still waiting on attunement says so instead. Returns the new y."""
    carried = app._carried_item_spells(agent_idx)
    if not carried:
        return y
    y += 4
    txt("Item spells:", lx, y, (120, 180, 200), app.font_sm)
    y += 14
    stats = app.combat.get_agent_stats(app.bm, agent_idx)
    for row, s in carried:
        name = row.name
        if is_scroll(row):
            # A spell scroll is one line (SS3); one its holder can't read says so (S5).
            readable = all(can_read_scroll(stats, n) for n in s.spell_names())
            txt(f"  {name} · {scroll_line(s)}" + ("" if readable else " (can't read)"),
                lx, y, (170, 200, 220) if readable else (130, 130, 150), app.font_sm)
            y += 14
            continue
        if not s.attuned_or_free():
            txt(f"  {name} (not attuned)", lx, y, (130, 130, 150), app.font_sm)
            y += 14
            continue
        txt(f"  {name}", lx, y, (170, 200, 220), app.font_sm)
        y += 14
        for line in item_spells_summary(s):
            txt(f"    {line}", lx, y, (200, 200, 220), app.font_sm)
            y += 14
    warn = attunement_warning(attuned_count(app.combat, app.bm, agent_idx))
    if warn:
        txt(warn, lx, y, (230, 170, 90), app.font_sm)
        y += 14
    return y


def draw_combat_panel(app):
    """Draw the right panel while combat is active.

    The stale-rect guard is gone (M2e). Every `btn_cbt_*` used to be parked at
    `x = -10000` at the top of this method, because a button was legal exactly when
    the branch that positioned it ran — so a button that stopped being offered kept
    its last rect and would capture the click meant for whatever now sits there.
    The guard had a hole of its own (Step 0.3's F4: it iterated `vars(app)` and
    filtered on `isinstance(_btn, Button)`, so the nine Metamagic toggles, which
    were a dict, escaped it entirely).

    What replaces it is not a better guard but the absence of the problem: every
    one of these buttons is dispatched by `_action_clicked`, which tests the click
    against `app._action_menu` — the offer this method last drew. A stale rect can
    still exist; nothing can fire through it.
    """
    sw, sh = app.screen.get_size()
    px = app._panel_x()
    lx = px + app._PANEL_PAD
    W  = PANEL_W - app._PANEL_PAD * 2
    HW = W // 2 - 2
    B  = app._BTN_H
    gap = 4
    section_gap = 8

    # Background + border
    pygame.draw.rect(app.screen, COL_PANEL_BG, pygame.Rect(px, 0, PANEL_W, sh))
    pygame.draw.line(app.screen, COL_PANEL_BORDER, (px, 0), (px, sh))

    def txt(s, x, y, col=COL_TEXT, fnt=None):
        surf = (fnt or app.font_sm).render(s, True, col)
        app.screen.blit(surf, (x, y))

    # ── Scroll viewport ────────────────────────────────────────────────
    # Everything below flows from a single `y` cursor, so the whole panel scrolls by
    # starting that cursor above the top. Button rects are (re)positioned from `y` as
    # they are drawn, so clicks follow the scrolled layout for free. Drawing is clipped
    # to the panel above the fixed cursor-info strip; the content height and the
    # scrollbar are computed at the bottom, once `y` has flowed to the end.
    app.screen.set_clip(pygame.Rect(px, 0, PANEL_W, sh - 22))

    # S3: the converted sections' offer for this frame, keyed by action id. Built
    # once here and consumed both below (layout) and by _handle_events (dispatch),
    # so a click is tested against exactly the offer that was drawn — the same
    # coupling the stale-rect guard fakes for the sections M2 has not reached yet.
    app._action_menu = {a.id: a for a in ActionMenu.build(app, app._current_agent_idx())}
    if app.tracker_mode:
        # The table rolls everything: only End Encounter and the Table menu are on
        # offer (no turns to pause, no reactions to time), so no action can be drawn
        # or dispatched.
        app._action_menu = {k: a for k, a in app._action_menu.items()
                             if k in ("end_combat", "table")}

    y = 10 - app.combat_panel_scroll

    # ── Title ──────────────────────────────────────────────────────────
    txt("⚔  Encounter" if app.tracker_mode else "⚔  Combat",
        lx, y, COL_INITIATIVE_CUR, app.font_lg)
    y += 28

    # ── Pause + reaction timer + End Combat row ────────────────────────
    y = panel.draw_action_row(app, panel.menu_group(app, "session"), lx, y, W, gap,
                              trail=8, font=app.font_sm)

    if app.tracker_mode:
        # The initiative sheet (T3) in place of the engine's order, then On Deck and
        # the log. No action rows.
        app.initiative_item_rects = []
        app.initiative_scroll_region = pygame.Rect(0, 0, 0, 0)
        y = panel.draw_tracker_section(app, lx, W, y)
        y = panel.draw_on_deck_section(app, lx, W, px, y)
        y += section_gap
        pygame.draw.line(app.screen, COL_PANEL_BORDER,
                         (px + 6, y), (px + PANEL_W - 6, y))
        y += section_gap
        draw_combat_panel_log(app, txt, lx, W, y, px, sh)
        return

    # ── Initiative list ────────────────────────────────────────────────
    txt("Initiative Order", lx, y, COL_LABEL)
    y += 16
    agents = app.bm.placed_agents
    app.initiative_item_rects = []  # Reset for this frame

    # Define scrollable region: max 8 entries visible
    init_list_start_y = y
    init_list_max_visible = 8
    init_list_height = init_list_max_visible * 16
    init_list_scroll_region = pygame.Rect(lx, init_list_start_y, W, init_list_height)
    app.initiative_scroll_region = init_list_scroll_region  # store for event handling

    # Auto-page: when the turn advances to a combatant outside the visible
    # window, jump to the page holding the current turn. Tracked per turn so
    # manual scrolling between turns is preserved (we only re-page on change).
    if app.turn_idx != app._initiative_autopaged_turn:
        app._initiative_autopaged_turn = app.turn_idx
        if not (app.initiative_scroll_offset <= app.turn_idx
                < app.initiative_scroll_offset + init_list_max_visible):
            page = app.turn_idx // init_list_max_visible
            app.initiative_scroll_offset = page * init_list_max_visible

    # Clamp scroll offset to valid range
    max_scroll = max(0, len(app.initiative_order) - init_list_max_visible)
    app.initiative_scroll_offset = min(app.initiative_scroll_offset, max_scroll)

    for i, entry in enumerate(app.initiative_order):
        # Skip entries before scroll offset
        if i < app.initiative_scroll_offset:
            continue
        # Stop after showing max visible entries
        if i >= app.initiative_scroll_offset + init_list_max_visible:
            break

        aidx   = entry.agent_idx
        is_cur = (i == app.turn_idx)
        col    = COL_INITIATIVE_CUR if is_cur else COL_TEXT
        if lair.is_lair_entry(entry):
            txt(f"{'▶ ' if is_cur else '  '}{entry.total:2d}  {lair.entry_label(app)}",
                lx, y, col if lair.owner(app) >= 0 else (90, 90, 90))
            y += 16
            continue
        name   = agents[aidx].name if aidx < len(agents) else "?"
        alive  = True
        dismissed = (aidx < len(agents) and agents[aidx].removed_from_play)
        hp_s = ""
        star = ""
        if aidx < len(agents):
            s = app.combat.get_agent_stats(app.bm, aidx)
            alive = s.hp_cur > 0
            hp_s = hp_status(s)
            star = " ★" if s.heroic_inspiration else ""   # Heroic Inspiration held (D11)
        if not alive or dismissed:
            col = (90, 90, 90)
        prefix = "▶ " if is_cur else "  "
        suffix = "  (dismissed)" if dismissed else ""
        row_s  = f"{prefix}{entry.total:2d}  {name}{star}{suffix}"
        txt(row_s, lx, y, col)
        if hp_s and not dismissed:
            hs = app.font_sm.render(hp_s, True, col)
            app.screen.blit(hs, (lx + W - hs.get_width(), y))
        # Track clickable area for this initiative item
        item_rect = pygame.Rect(lx, y, W, 16)
        app.initiative_item_rects.append((item_rect, aidx))
        y += 16

    # Show scroll indicator if there are more entries
    if len(app.initiative_order) > init_list_max_visible:
        scroll_info = f"↑↓ {app.initiative_scroll_offset + init_list_max_visible}/{len(app.initiative_order)}"
        txt(scroll_info, lx, y, COL_LABEL)
        y += 16

    # ── On Deck reinforcements (deploy reserves into the live order) ────
    y = panel.draw_on_deck_section(app, lx, W, px, y)

    y += section_gap

    # ── Separator ──────────────────────────────────────────────────────
    pygame.draw.line(app.screen, COL_PANEL_BORDER,
                     (px + 6, y), (px + PANEL_W - 6, y))
    y += section_gap

    # ── Current combatant info ─────────────────────────────────────────
    cur_idx = app._current_agent_idx()
    if 0 <= cur_idx < len(agents):
        pt    = agents[cur_idx]
        stats = app.combat.get_agent_stats(app.bm, cur_idx)
        frac  = stats.hp_cur / max(stats.hp_max, 1)
        hp_col = (COL_HP_HIGH if frac > 0.66 else
                  COL_HP_MID  if frac > 0.33 else
                  COL_HP_LOW)
        txt(f"Turn: {pt.name}", lx, y, COL_TEXT, app.font_md)
        y += 20

        # Draw HP bar with temp HP indicator
        total_bar_width = stats.hp_max + stats.temp_hp
        bar_width = W if total_bar_width == 0 else W * (stats.hp_max / max(total_bar_width, 1))
        temp_hp_width = W - bar_width

        pygame.draw.rect(app.screen, (50, 50, 50),
                         pygame.Rect(lx, y, W, 12), border_radius=3)
        # Draw regular HP in color
        pygame.draw.rect(app.screen, hp_col,
                         pygame.Rect(lx, y, int(bar_width), 12), border_radius=3)
        # Draw temp HP in blue
        if stats.temp_hp > 0:
            pygame.draw.rect(app.screen, (100, 150, 255),
                             pygame.Rect(lx + int(bar_width), y, int(temp_hp_width), 12), border_radius=3)

        # Display HP text with temp HP indicator (and any drained max-HP)
        drained = getattr(stats, "available_hit_points", 0)
        drain_sfx = f" [-{drained} max]" if drained > 0 else ""
        eff_max = stats.hp_max - drained
        if stats.temp_hp > 0:
            txt(f"HP {stats.hp_cur} (+{stats.temp_hp}){drain_sfx}", lx + W//2 - 40, y - 1)
        else:
            txt(f"HP {stats.hp_cur}/{eff_max}{drain_sfx}", lx + W//2 - 22, y - 1)
        y += 12

        # ── Focus Points display (Monk) ────────────────────────────────────
        if stats.character_class == rpg.CharacterClass.Monk:
            fp = stats.get_resource("Focus Points")
            if fp:
                # Draw Focus Points bar
                fp_bar_width = W * (fp.current / max(fp.max, 1)) if fp.max > 0 else 0
                pygame.draw.rect(app.screen, (50, 50, 50),
                                 pygame.Rect(lx, y, W, 12), border_radius=3)
                pygame.draw.rect(app.screen, (150, 180, 255),
                                 pygame.Rect(lx, y, int(fp_bar_width), 12), border_radius=3)
                txt(f"Focus Pts {fp.current}/{fp.max}", lx + W//2 - 45, y - 1)
                y += 12

        # ── Exhaustion display ─────────────────────────────────────────────
        cond = app.combat.get_agent_conditions(app.bm, cur_idx)
        if cond.exhaustion_level >= 1:
            exh_col = ((200, 100, 50) if cond.exhaustion_level < 6 else
                      (200, 50, 50))  # Red at level 6 (death)
            txt(f"🔗 Exhaustion L{cond.exhaustion_level}", lx, y, exh_col, app.font_sm)
            y += 16

        # ── Death saves display (if unconscious) ────────────────────────

        if cond.unconscious and stats.hp_cur <= 0:
            y += 8
            if cond.dead:
                txt("DEAD", lx, y, (200, 50, 50), app.font_md)
                y += 16
            elif cond.stabilized:
                txt("Stabilized", lx, y, (100, 200, 100), app.font_md)
                y += 16
            else:
                txt(f"Death Saves: {cond.death_save_successes}/3 {cond.death_save_failures}/3", lx, y, (200, 200, 150), app.font_sm)
                y += 14
                # Draw bubble visualization in panel
                bubble_radius = 2
                bubble_spacing = 1
                bubble_x_start = lx
                bubble_y = y

                # Green bubbles for successes
                txt("✓", bubble_x_start, bubble_y - 8, (100, 200, 100), app.font_sm)
                for i in range(3):
                    x = bubble_x_start + 16 + i * (bubble_radius * 2 + bubble_spacing)
                    if i < cond.death_save_successes:
                        pygame.draw.circle(app.screen, (100, 200, 100), (x, bubble_y), bubble_radius)
                    else:
                        pygame.draw.circle(app.screen, (50, 100, 50), (x, bubble_y), bubble_radius, 1)

                # Red bubbles for failures
                bubble_y_red = bubble_y + 10
                txt("✗", bubble_x_start, bubble_y_red - 8, (200, 100, 100), app.font_sm)
                for i in range(3):
                    x = bubble_x_start + 16 + i * (bubble_radius * 2 + bubble_spacing)
                    if i < cond.death_save_failures:
                        pygame.draw.circle(app.screen, (200, 100, 100), (x, bubble_y_red), bubble_radius)
                    else:
                        pygame.draw.circle(app.screen, (100, 50, 50), (x, bubble_y_red), bubble_radius, 1)

                y += 24

    y += section_gap

    # ── End Turn (prominent, before action choices) ────────────────────
    y = panel.draw_action_row(app, panel.menu_group(app, "turn"), lx, y, W, gap,
                              trail=section_gap)

    # ── Action section ─────────────────────────────────────────────────
    act_lbl = "Action" + (" ✓" if app.action_used else "")
    txt(act_lbl, lx, y, COL_LABEL)
    y += 16

    # Check if mid-sequence (attacks remaining, but action_used not yet set)
    mid_sequence_action = (app.attack_seq.remaining > 0 and app.attack_seq.slot == "action")

    # Check current conditions for the active combatant.
    cur_cond = app.combat.get_agent_conditions(app.bm, cur_idx) if 0 <= cur_idx < len(agents) else None
    _is_incapacitated = (cur_cond.incapacitated or cur_cond.unconscious) if cur_cond else False

    # The five-way branch survives here as five arms of TEXT and of ROW SHAPE;
    # WHICH buttons each arm has to place is `ActionMenu._action`'s answer now.
    # Three of the arms are a single full-width row and say so; the fourth is the
    # full band, whose three rows are named by the `_ACT_ROW_*` tuples below.
    if _is_incapacitated:
        reason = "Unconscious" if (cur_cond and cur_cond.unconscious) else "Incapacitated"
        txt(f"[Cannot act — {reason}]", lx, y, (120, 80, 80))
        y += B
    elif app.action_used and not mid_sequence_action:
        txt("[Action used]", lx, y, (100, 100, 120))
        y += B
        # Nick, if the menu offers it — the only button this arm can show.
        y = panel.draw_action_row(app, panel.menu_group(app, "action"), lx, y, W, gap)
    elif cur_cond and cur_cond.frightened:
        txt("Frightened — must Dash", lx, y, (180, 100, 200))  # Purple
        y += B
        y = panel.draw_action_row(app, panel.menu_group(app, "action"), lx, y, W, gap)
    else:
        y = panel.draw_action_row(app, panel.menu_group(app, "action", only=_ACT_ROW_ATTACK),
                                  lx, y, W, gap)
        y = panel.draw_action_row(app, panel.menu_group(app, "action", only=_ACT_ROW_BITE),
                                  lx, y, W, gap)
        y = panel.draw_action_row(app, panel.menu_group(app, "action", only=_ACT_ROW_MOVE),
                                  lx, y, W, gap, font=app.font_sm)
        y = panel.draw_action_row(app, panel.menu_group(app, "action", only=_ACT_ROW_SPELL),
                                  lx, y, W, gap)

    # ── Spell Slots / N/day display ────────────────────────────────────
    if 0 <= cur_idx < len(agents):
        stats = app.combat.get_agent_stats(app.bm, cur_idx)

        if stats.is_npc:
            # NPC N/day spell display
            spells = app.combat.get_agent_spells(app.bm, cur_idx)
            npc_spells = [sp for sp in spells if sp.uses_max > 0 or sp.recharge_min > 0]
            if npc_spells:
                y += 4
                txt("Spells (N/day):", lx, y, (160, 120, 200), app.font_sm)
                y += 14
                for spell in npc_spells:
                    rc = "  ⟳recharge" if spell.expended else (f"  ⟳{spell.recharge_min}+" if spell.recharge_min > 0 else "")
                    cap = spell.uses_max if spell.uses_max > 0 else 1
                    txt(f"{spell.name:20} {spell.uses_remaining}/{cap}{rc}", lx, y, (200, 200, 220), app.font_sm)
                    y += 14
            # NPC weapon N/day + recharge display
            npc_weapons = [w for w in app.combat.get_agent_weapons(app.bm, cur_idx)
                           if w.name and w.name != "Unnamed" and (w.uses_max > 0 or w.recharge_min > 0)]
            if npc_weapons:
                y += 4
                txt("Weapon uses:", lx, y, (200, 150, 120), app.font_sm)
                y += 14
                for w in npc_weapons:
                    rc = "  ⟳recharge" if w.expended else (f"  ⟳{w.recharge_min}+" if w.recharge_min > 0 else "")
                    cap = w.uses_max if w.uses_max > 0 else 1
                    txt(f"{w.name:20} {w.uses_remaining}/{cap}{rc}", lx, y, (220, 200, 190), app.font_sm)
                    y += 14
        else:
            # Player spell slot display (existing logic)
            slots_max = list(stats.spell_slots_max)
            if any(slots_max):
                y += 4
                slots_cur = list(stats.spell_slots_remaining)
                pip_chars = []
                for lvl in range(9):
                    if slots_max[lvl] > 0:
                        filled = min(slots_cur[lvl], slots_max[lvl])
                        empty = slots_max[lvl] - filled
                        lvl_label = {0:"C", 1:"1", 2:"2", 3:"3", 4:"4", 5:"5", 6:"6", 7:"7", 8:"8", 9:"9"}.get(lvl+1, "?")
                        pip_str = "●" * filled + "○" * empty
                        pip_chars.append(f"{lvl_label}:{pip_str}")
                if pip_chars:
                    # Wrap spell slot display to multiple lines if needed
                    lines = []
                    current_line = "Spells: "
                    for i, level_str in enumerate(pip_chars):
                        test_str = current_line + level_str + ("  " if i < len(pip_chars) - 1 else "")
                        test_surf = app.font_sm.render(test_str, True, (160, 120, 200))
                        if test_surf.get_width() > W and current_line != "Spells: ":
                            lines.append(current_line.rstrip())
                            current_line = "  " + level_str + ("  " if i < len(pip_chars) - 1 else "")
                        else:
                            current_line = test_str
                    if current_line.strip():
                        lines.append(current_line)
                    for line in lines:
                        txt(line, lx, y, (160, 120, 200), app.font_sm)
                        y += 14

        # Enspelled items (E4): what each carried item can still cast, PC or NPC alike.
        y = draw_item_spells_panel(app, cur_idx, lx, y, txt)

    y += section_gap

    # ── Portent Dice section (Diviner Wizards) ─────────────────────────
    # The whole section exists exactly when the button is on offer — Diviner, and
    # dice left — so the menu answers that too, and what stays here is the dice
    # readout's text.
    if "use_portent" in app._action_menu:
        txt("Portent Dice:", lx, y, (200, 180, 100), app.font_sm)
        y += 14
        dice_str = ", ".join(str(d) for d in
                             app.combat.get_agent_stats(app.bm, cur_idx).portent_dice)
        txt(f"  [{dice_str}]", lx, y, (220, 200, 120), app.font_sm)
        y += 14
        y = panel.draw_action_row(app, panel.menu_group(app, "portent"), lx, y, W, gap)
        y += section_gap

    # ── Bonus Action section ───────────────────────────────────────────
    bon_lbl = "Bonus Action" + (" ✓" if app.bonus_used else "")
    txt(bon_lbl, lx, y, COL_LABEL)
    y += 16

    # Check if mid-sequence for bonus action
    mid_sequence_bonus = (app.attack_seq.remaining > 0 and app.attack_seq.slot == "bonus")

    if _is_incapacitated:
        pass  # already shown "[Cannot act]" in the Action section; skip bonus section entirely
    elif app.bonus_used and not mid_sequence_bonus:
        txt("[Bonus used]", lx, y, (100, 100, 120))
        y += B
    else:
        # The economy-band header row: a fixed TWO-COLUMN band, not an n-up. The
        # menu says which of the two exist and what they read (bucket 7b); the
        # columns are this method's, and so is the rule that a band standing open
        # reserves its row even for a creature offered neither of them — which is
        # why this is not a `panel.draw_action_row` call. The left column stays empty
        # when only the right is offered; the width is the two-up's exactly when
        # the spell half is there to fill it.
        _bw = (W - gap) // 2 if "spell_bonus" in app._action_menu else HW
        for _i, _bid in enumerate(("atk_bonus", "spell_bonus")):
            _hdr = app._action_menu.get(_bid)
            if _hdr is None:
                continue
            _hbtn = panel.cbt_btn(app, _bid)
            _hbtn.text  = _hdr.label
            _hbtn.rect.x = lx + _i * (_bw + gap)
            _hbtn.rect.y = y
            _hbtn.rect.w = _bw
            _hbtn.draw(app.screen)
        y += B

    # Jump + Shove row — merged below into the adjacency block

    # Arcane Ward charging button (Abjurer L3+ with active ward)
    y = panel.draw_action_stack(app, panel.menu_group(app, "bonus", only=("charge_arcane_ward",)),
                                lx, y, W, gap)

    # Wild Shape button (Druid L2+). The label is the menu's; the form NAME above
    # it is display, so it stays here.
    _wild = panel.menu_group(app, "bonus", only=("wild_shape",))
    if _wild:
        _wstats = app.bm.placed_agents[cur_idx].stats
        if _wstats.wild_shape_active:
            txt(f"🐺 {_wstats.wild_shape_form_name}", lx, y, COL_LABEL)
            y += 12
        y = panel.draw_action_stack(app, _wild, lx, y, W, gap)

    # The Jump / Shove / Trip row, and the Escape under it. A three-up when
    # something is standing next to this creature and Jump alone at full width when
    # nothing is — which is the menu's answer now, not a branch here. The narrow
    # row is drawn in `font_sm`, as §4's five-up is.
    _jump = panel.menu_group(app, "bonus", only=_BON_ROW_SHOVE)
    if _jump:
        y += gap
        y = panel.draw_action_row(app, _jump, lx, y, W, gap,
                                  font=app.font_sm if len(_jump) > 1 else None)
    # Escape, then the Telekinetic feat's shove, then the Cunning Action three-up.
    # The Psi Warrior's Telekinetic Movement is a different option with its own
    # widget, drawn further down inside the band; see F10.
    y = panel.draw_action_stack(app, panel.menu_group(app, "bonus", only=_BON_RUN_ESCAPE),
                                lx, y, W, gap)
    _cunning = panel.menu_group(app, "bonus", only=_BON_ROW_CUNNING)
    if _cunning:
        y = panel.draw_action_row(app, _cunning, lx, y, W, gap)


    # The five the Bonus Action does not own, in draw order — Drop Grapple (free),
    # Use Item (per item: a potion is a Bonus Action, a thrown flask or a Net
    # replaces one attack of the Attack action), Extinguish and Free from Net (the
    # Action), and Haste's extra Action. They are drawn above the band gate below
    # precisely because spending the Bonus Action must not dead-key any of them,
    # and `actions._BONUS_ECONOMY` is where that is now said in words.
    y = panel.draw_action_stack(app, panel.menu_group(app, "bonus", only=_BON_RUN_UNBANDED),
                                lx, y, W, gap)

    if not _is_incapacitated and not app.bonus_used:
        # One run: after M2e nothing fused is left to cut the column, so the whole
        # band is a single stack drawn in the menu's build order. `_BON_RUN_BAND`
        # is that order written down, feature group by feature group.
        _band = panel.menu_group(app, "bonus", only=_BON_RUN_BAND)

        # §7's one WRITE during the draw pass, hoisted above the run so the run can
        # be one call. The Steps of the Fey rider cycle is five options at Warlock 6
        # and three below it, so a selection made at L6 is out of range at L3 and
        # the panel clamps it back to 0 on the spot. The menu's LABEL reads the
        # clamped value (`fey_rider_index`, a pure function); the write-through
        # stays here, because `actions.py` never mutates the app and both the click
        # handler and the engine call read the raw field.
        if any(a.id in _BON_FEY_TRIO for a in _band):
            app.steps_of_fey_effect = fey_rider_index(
                app, app.combat.get_agent_stats(app.bm, cur_idx))

        y = panel.draw_action_stack(app, _band, lx, y, W, gap)

    elif not _is_incapacitated:
        # F11: the band is shut, and exactly one option belongs on the other side of
        # it — Open Hand L11's Fleet Step, a free Step of the Wind that exists only
        # because the Bonus Action is already spent. The menu offers `step_of_wind`
        # in this state for nobody else, so this group is empty for everyone else
        # and an empty stack takes no vertical space.
        y = panel.draw_action_stack(app, panel.menu_group(app, "bonus", only=("step_of_wind",)),
                                    lx, y, W, gap)

    # Sorcerer Metamagic arm-toggles (Phase 2). WHICH options are offered — learned,
    # affordable, and Quickened only while the Bonus Action is unspent — and the tick
    # that marks the armed ones are `ActionMenu._metamagic`'s.
    #
    # Two things stay here. The CAPTION is the section's and not the buttons':
    # Sorcery Incarnate is a property of the creature and affordability a property of
    # each option, so an empty purse leaves the heading standing over nothing
    # (checkpoint 69). And the armed HIGHLIGHT is styling, which `Action` carries no
    # field for — it follows the tick in the label, so there is still one rule for
    # what "armed" means and it is the menu's.
    if not _is_incapacitated and 0 <= cur_idx < len(agents):
        _mm_stats = app.combat.get_agent_stats(app.bm, cur_idx)
        if (_mm_stats.character_class == rpg.CharacterClass.Sorcerer and
                _mm_stats.char_level >= 2 and len(_mm_stats.metamagic_options) > 0):
            if rpg.CombatEngine.sorcery_incarnate_active(_mm_stats):
                cap = app.font_sm.render(
                    "Sorcery Incarnate: 2 options per spell", True, (210, 190, 255))
                app.screen.blit(cap, (lx, y))
                y += cap.get_height() + 2
            for _mm_act in panel.menu_group(app, "bonus", only=_BON_RUN_METAMAGIC):
                _mm_btn = panel.cbt_btn(app, _mm_act.id)
                _mm_armed = _mm_act.label.startswith("✓")
                _mm_btn.color = (120, 95, 190) if _mm_armed else (80, 62, 135)
                y = panel.draw_action_row(app, [_mm_act], lx, y, W, gap)
                if _mm_armed:
                    pygame.draw.rect(app.screen, (210, 190, 255), _mm_btn.rect, 2,
                                     border_radius=4)

    y += section_gap

    # ── Movement type toggles ──────────────────────────────────────────
    txt("Movement", lx, y, COL_LABEL)
    y += 16

    # Show exhaustion speed reduction if active
    mv_stats = app.combat.get_agent_stats(app.bm, cur_idx) if 0 <= cur_idx < len(app.bm.placed_agents) else None
    cur_cond = app.combat.get_agent_conditions(app.bm, cur_idx) if 0 <= cur_idx < len(app.bm.placed_agents) else None
    if cur_cond and cur_cond.exhaustion_level >= 1:
        reduction = 5 * cur_cond.exhaustion_level
        exh_note = f"(−{reduction}ft exhaustion)" if reduction < 30 else "(exhaustion: 0ft movement)"
        txt(exh_note, lx, y, (200, 100, 50), app.font_sm)
        y += 14
    mv_entries = [
        (rpg.MovementType.Walk,   "Walk",   app.move_remaining(cur_idx, rpg.MovementType.Walk),
         mv_stats.speed_walk   if mv_stats else 0),
        (rpg.MovementType.Fly,    "Fly",    app.move_remaining(cur_idx, rpg.MovementType.Fly),
         mv_stats.speed_fly    if mv_stats else 0),
        (rpg.MovementType.Swim,   "Swim",   app.move_remaining(cur_idx, rpg.MovementType.Swim),
         mv_stats.speed_swim   if mv_stats else 0),
        (rpg.MovementType.Burrow, "Burrow", app.move_remaining(cur_idx, rpg.MovementType.Burrow),
         mv_stats.speed_burrow if mv_stats else 0),
    ]
    available_mv = [(mt, lbl, rem, spd) for mt, lbl, rem, spd in mv_entries if spd > 0]
    app._move_type_btns = {}
    HW = W // 2 - 2
    for i, (mt, lbl, rem, spd) in enumerate(available_mv):
        bx = lx + (i % 2) * (HW + gap)
        by = y + (i // 2) * (B + gap)
        r  = pygame.Rect(bx, by, HW, B)
        app._move_type_btns[mt] = r
        if rem == 0:
            bg = (40, 40, 55)
            fg = (80, 80, 95)
        elif mt == app.move_type:
            bg = COL_BTN_ENDTURN
            fg = (230, 230, 230)
        else:
            bg = COL_BTN_PASS
            fg = (190, 190, 210)
        pygame.draw.rect(app.screen, bg, r, border_radius=4)
        surf = app.font_sm.render(f"{lbl}  {rem}ft", True, fg)
        app.screen.blit(surf, (bx + 4, by + (B - surf.get_height()) // 2))
    rows_used = max(1, (len(available_mv) + 1) // 2)
    y += rows_used * (B + gap)

    # Pending action hints
    if app._armed_slot(pending.Attack):
        rem = app.attack_seq.remaining
        _atk_hint = "→ Click a target on the map" + (f" ({rem} left)" if rem > 1 else "")
        txt(_atk_hint, lx, y, COL_INITIATIVE_CUR)
        y += 14
    elif app._armed_slot(pending.Spell):
        if app._pending_spell_is_wall():
            hint = ("Click the wall's end (sets direction & length)"
                    if app.spell_anchor_cell is not None
                    else "Click the wall's start point")
        elif app.pending.is_aoe:
            hint = "Click a map location"
        else:
            hint = "Click a target"
        txt(f"→ {hint} to cast spell", lx, y, (190, 150, 255))
        y += 14
    elif app._armed(pending.Shove):
        txt("→ Click a target to shove", lx, y, (190, 190, 150))
        y += 14
    elif app._armed(pending.Unarmed):
        hint_text = {
            "grapple": "→ Click a target to grapple",
            "push": "→ Click a target to shove 5 ft",
        }.get(app.pending.type, "→ Click a target")
        txt(hint_text, lx, y, (190, 190, 150))
        y += 14

    y += section_gap

    # ── Visibility toggles + End Combat ───────────────────────────────
    HW = (W - 4) // 2
    app.btn_show_spell_effects.rect.x = lx
    app.btn_show_spell_effects.rect.y = y
    app.btn_show_spell_effects.rect.w = HW
    app.btn_show_spell_effects.draw(app.screen)

    app.btn_show_visible_targets.rect.x = lx + HW + 4
    app.btn_show_visible_targets.rect.y = y
    app.btn_show_visible_targets.rect.w = HW
    app.btn_show_visible_targets.draw(app.screen)
    y += B + gap

    # Show/Hide Terrain (in-combat toggle; pre-combat the same toggle lives in
    # the setup panel's Terrain… menu).
    app.btn_show_terrain.text = "Hide Terrain" if app.show_terrain else "Show Terrain"
    app.btn_show_terrain.rect.x = lx
    app.btn_show_terrain.rect.y = y
    app.btn_show_terrain.rect.w = HW
    app.btn_show_terrain.draw(app.screen)

    # Place Terrain shares this row with the Show/Hide toggle beside it, which is
    # not a `btn_cbt_*` and is not the menu's — so the row is half laid out here and
    # half by `panel.draw_action_row`, at the right column's own origin and width. Its
    # own `y` advance is discarded: the toggle owns the row's height, and it is
    # there whether or not Place Terrain is.
    panel.draw_action_row(app, panel.menu_group(app, "utility", only=("place_terrain",)),
                          lx + HW + 4, y, HW, gap)
    y += B + gap

    # Drop Concentration, then every droppable weapon slot on a single row.
    # Which of these exist is ActionMenu's call now (§9); this only lays them out.
    y = panel.draw_action_row(app, panel.menu_group(app, "utility", only=("drop_concentration",)),
                              lx, y, W, gap)
    y = panel.draw_action_row(app, panel.menu_group(app, "utility",
                                                     only=("use_luck", "regain_slot")),
                              lx, y, W, gap)
    y = panel.draw_action_row(app, panel.menu_group(app, "utility", skip=("place_terrain",
                                                                "drop_concentration",
                                                                "use_luck", "regain_slot")),
                              lx, y, W, gap)

    y += section_gap
    draw_combat_panel_log(app, txt, lx, W, y, px, sh)


def draw_combat_panel_log(app, txt, lx, W, y, px, sh):
    """The combat panel's tail: the log, then the scroll extent and scrollbar."""
    # ── Combat log ─────────────────────────────────────────────────────
    txt("Combat Log:", lx, y, COL_LABEL)
    y += 16

    max_log_w = W - 2

    def _wrap_draw(s, x, start_y, max_w, fnt, line_h=15):
        """Draw s word-wrapped within max_w pixels; return the new y after last line.

        Lines past the bottom of the window are still laid out (the clip rect drops
        them) — the panel scrolls, so they must count towards the content height or
        the user could never scroll down to them."""
        y_pos = start_y
        remaining = s
        while remaining:
            if fnt.size(remaining)[0] <= max_w:
                txt(remaining, x, y_pos)
                y_pos += line_h
                break
            lo, hi = 0, len(remaining)
            while lo < hi - 1:
                mid = (lo + hi) // 2
                if fnt.size(remaining[:mid])[0] <= max_w:
                    lo = mid
                else:
                    hi = mid
            cut = lo
            space = remaining.rfind(" ", 0, lo)
            if space > 0:
                cut = space
            txt(remaining[:cut], x, y_pos)
            y_pos += line_h
            remaining = remaining[cut:].lstrip(" ")
        return y_pos + 2

    for msg in app.combat_log[:5]:
        y = _wrap_draw(msg, lx, y, max_log_w, app.font_sm)

    # ── End scroll viewport; measure content and draw the scrollbar ─────
    # `y` is in scrolled coordinates, so add the offset back to get the true content
    # height. Clamping here (not just on the wheel event) keeps the panel from being
    # left scrolled past the end when the content shrinks — e.g. the turn passes to an
    # agent with far fewer action buttons.
    app.screen.set_clip(None)
    content_h = y + app.combat_panel_scroll + 10
    visible_h = sh - 22                      # minus the fixed cursor-info strip
    app._combat_panel_max_scroll = max(0, content_h - visible_h)
    app.combat_panel_scroll = min(max(0, app.combat_panel_scroll),
                                   app._combat_panel_max_scroll)
    if app._combat_panel_max_scroll > 0:
        track_h = visible_h - 4
        span    = visible_h + app._combat_panel_max_scroll
        thumb_h = max(28, int(track_h * visible_h / span))
        thumb_y = 2 + int((track_h - thumb_h)
                          * app.combat_panel_scroll / app._combat_panel_max_scroll)
        bar = pygame.Rect(px + PANEL_W - 6, thumb_y, 4, thumb_h)
        pygame.draw.rect(app.screen, (90, 92, 110), bar, border_radius=2)


def draw_panel(app):
    # Rebuilt every frame by the setup panel's Floor-nav block; cleared here so a
    # stale rect can't capture clicks when the block isn't drawn (e.g. in combat).
    app._dungeon_nav_rects = {}
    if app.combat_active:
        app._draw_combat_panel()
        return
    app._action_menu = {}   # no combat panel drawn ⇒ nothing is on offer

    # Setup panel has no Deploy rows; clear any stale combat-panel rects so they
    # can't capture clicks here. Reserves are managed pre-combat via right-click.
    app.on_deck_item_rects = []

    sw, sh = app.screen.get_size()
    px  = app._panel_x()
    lx  = px + app._PANEL_PAD          # left edge for text
    loff = app._LABEL_H + app._LABEL_GAP   # how far above a widget its label sits

    # Panel background + left border
    pygame.draw.rect(app.screen, COL_PANEL_BG,
                     pygame.Rect(px, 0, PANEL_W, sh))
    pygame.draw.line(app.screen, COL_PANEL_BORDER, (px, 0), (px, sh))

    # ── PC name input (after selecting PC class) ──────────────────────
    if app._pc_name_input:
        title = app.font_md.render("Enter character name:", True, COL_TEXT)
        app.screen.blit(title, (lx, 30))
        app._pc_name_input.draw(app.screen)
        hint = app.font_sm.render("Press Enter to continue", True, (150, 150, 150))
        app.screen.blit(hint, (lx, app._pc_name_input.rect.bottom + 8))
        return

    # ── Placement mode ─────────────────────────────────────────────────
    if app.placement_mode_active:
        title = app.font_lg.render("Click to place", True, (255, 200, 100))
        app.screen.blit(title, (lx, 20))
        status_col = (80, 220, 80) if app.placement_valid else (220, 60, 60)
        status_txt = "Valid placement" if app.placement_valid else "Invalid placement (ESC to cancel)"
        status = app.font_sm.render(status_txt, True, status_col)
        app.screen.blit(status, (lx, 50))
        return

    # ── Re-flow all widgets for the current scroll offset + Floor-nav block, then
    #    clip drawing to the scroll viewport (above the fixed cursor-info strip). ──
    app._reposition_panel()
    app.screen.set_clip(pygame.Rect(px, 0, PANEL_W, sh - 22))

    # ── Floor-nav block (docked at the top in dungeon mode) ────────────
    app._draw_panel_floor_nav(px, lx, W=PANEL_W - app._PANEL_PAD * 2)

    # ── Title ─────────────────────────────────────────────────────────
    _, _, title_y, *_ = panel_layout(app)
    title = app.font_lg.render("⚔  Agent Config", True, COL_TEXT)
    app.screen.blit(title, (lx, title_y - app.panel_scroll))

    # ── Field labels (sit loff px above their widget) ──────────────
    def label(text, x, widget_y):
        t = app.font_sm.render(text, True, COL_LABEL)
        app.screen.blit(t, (x, widget_y - loff))

    # ── Widgets ───────────────────────────────────────────────────────
    for w in [app.btn_agents, app.btn_clear]:
        w.draw(app.screen)

    # Current save-file hint (updates when user picks a different path)
    hint_txt = os.path.basename(app._save_path) if app._save_path else ""
    hint = app.font_sm.render(hint_txt, True, (100, 100, 130))
    app.screen.blit(hint, (lx, app.btn_begin_combat.rect.bottom + 4))

    # ── Long Rest / Short Rest buttons (only when agents are placed) ──
    if app.bm.placed_agents:
        app.btn_long_rest.draw(app.screen)
        app.btn_short_rest.draw(app.screen)

    # ── Begin Combat button (only when agents are placed) ─────────────
    if app.bm.placed_agents:
        app.btn_begin_combat.text = ("Begin Encounter" if app.tracker_mode
                                      else "Begin Combat")
        app.btn_begin_combat.draw(app.screen)

    # ── Restore Autosave… (always: after a crash the board may still be empty) ──
    # ── and Table…, the join code and the seats (D-M7-5) ──────────────────
    app.btn_restore_autosave.draw(app.screen)
    app.btn_table.draw(app.screen)
    app.btn_reset_dungeon.draw(app.screen)
    app.btn_undo_reset.draw(app.screen)
    app.btn_load_save.draw(app.screen)

    # ── Terrain… / Lighting… grouped menus ─────────────────────────────
    app.btn_terrain.draw(app.screen)
    app.btn_lighting.draw(app.screen)
    app.btn_items.draw(app.screen)

    # ── Dungeon… (New / Open / Floors… / Populate Floor… / save, releases) ──
    app.btn_dungeon.draw(app.screen)

    # ── Toggle Wall Auto-Detection button ──────────────────────────────
    app.btn_toggle_walls.draw(app.screen)

    # ── Fog of War button (menu) ───────────────────────────────────────
    app.btn_fog.draw(app.screen)

    # ── Toggle move animation (M4b B-7) ────────────────────────────────
    app.btn_toggle_animate.draw(app.screen)

    # ── Set Grid (sample a tile) button ────────────────────────────────
    app.btn_set_grid.draw(app.screen)

    # ── Quit button ────────────────────────────────────────────────────
    app.btn_quit.draw(app.screen)

    # ── Grid / map stats (flow with content, below Quit) ──────────────
    def text(txt, x, y, color=COL_LABEL):
        """Plain text blit with no offset (unlike label() which is for widgets)."""
        t = app.font_sm.render(txt, True, color)
        app.screen.blit(t, (x, y))

    info_y = app._panel_stats_y
    text(f"Grid: {app.bm.grid_cols}×{app.bm.grid_rows}  "
         f"cell={app.bm.cell_pixel_size}px  zoom={getattr(app, 'view_zoom', 1.0)*100:.0f}%",
         lx, info_y)
    text(f"Walls: {len(app.bm.walls) + len(app.bm.edge_walls)}   Blocked: {len(app.bm.disallowed_cells)}",
         lx, info_y + 18)
    text(f"Agents placed: {len(app.bm.placed_agents)}", lx, info_y + 36)

    # Transient confirmation (e.g. "Terrain saved: …")
    if app._status_msg and pygame.time.get_ticks() < app._status_msg_until:
        text(app._status_msg, lx, info_y - 20, (120, 220, 140))

    # ── End scroll viewport; draw the scrollbar over the (unclipped) panel ──
    app.screen.set_clip(None)
    if app._panel_max_scroll > 0:
        visible_h = sh - 22
        track_h   = visible_h - 4
        span      = visible_h + app._panel_max_scroll
        thumb_h   = max(28, int(track_h * visible_h / span))
        thumb_y   = 2 + int((track_h - thumb_h)
                            * app.panel_scroll / app._panel_max_scroll)
        bar = pygame.Rect(px + PANEL_W - 6, thumb_y, 4, thumb_h)
        pygame.draw.rect(app.screen, (90, 92, 110), bar, border_radius=2)


def draw_xp_total(app):
    """Persistent running-total party-XP scoreboard, pinned to the bottom-right
    of the config panel just above the cursor strip. Drawn unclipped every frame
    (in and out of combat) so the total accrued across finished combats — rolled
    up by _award_encounter_xp() — is always visible. See xp.py."""
    px = app._panel_x()
    sh = app.screen.get_height()
    total = app_initiative.party_xp_total(app)
    label = f"★ XP  {total:,} per PC  (Lv {level_for_xp(total)})"
    surf  = app.font_md.render(label, True, (245, 215, 90))   # gold
    pad   = 6
    w     = surf.get_width() + pad * 2
    h     = surf.get_height() + 4
    x     = px + PANEL_W - app._PANEL_PAD - w
    y     = sh - 22 - h - 4                                    # above the 22px cursor strip
    bg    = pygame.Rect(x, y, w, h)
    pygame.draw.rect(app.screen, (40, 40, 52), bg, border_radius=5)
    pygame.draw.rect(app.screen, (95, 82, 40), bg, width=1, border_radius=5)
    app.screen.blit(surf, (x + pad, y + 2))


def draw_cursor_cell_info(app):
    """Debug readout of the grid cell under the mouse, drawn at the bottom of the
    config panel. Shows col/row plus terrain type and whether the engine treats the
    cell as blocked — the info needed to debug terrain-vs-wall passability bugs.
    (The map is a 2D grid, so there is no true z; terrain/blocked stands in for it.)"""
    px = app._panel_x()
    mx, my = pygame.mouse.get_pos()
    lx = px + app._PANEL_PAD
    sh = app.screen.get_height()
    strip_h = 22
    strip_y = sh - strip_h
    # Opaque strip so the readout stays legible over any panel content.
    pygame.draw.rect(app.screen, (18, 18, 26),
                     pygame.Rect(px, strip_y, PANEL_W, strip_h))
    pygame.draw.line(app.screen, COL_PANEL_BORDER,
                     (px, strip_y), (px + PANEL_W, strip_y))

    # Only meaningful while the cursor is over the map, not the panel.
    if mx >= px:
        surf = app.font_sm.render("Cursor: (over panel)", True, (120, 120, 140))
        app.screen.blit(surf, (lx, strip_y + 3))
        return

    cell = app._screen_to_cell(mx, my)
    if cell is None:
        surf = app.font_sm.render("Cursor: (off-grid)", True, (120, 120, 140))
        app.screen.blit(surf, (lx, strip_y + 3))
        return

    tt = app.bm.get_terrain_type(cell)
    tt_name = {rpg.TerrainType.Standard: "Standard",
               rpg.TerrainType.Water:    "Water",
               rpg.TerrainType.Wall:     "Wall",
               rpg.TerrainType.Chasm:    "Chasm"}.get(tt, str(tt))
    blocked = app.bm.is_blocked(cell, 1, rpg.MovementType.Walk)
    col = (230, 110, 110) if blocked else (140, 220, 150)
    surf = app.font_sm.render(
        f"Cell ({cell.col}, {cell.row})  {tt_name}  "
        f"{'BLOCKED' if blocked else 'open'}", True, col)
    app.screen.blit(surf, (lx, strip_y + 3))
