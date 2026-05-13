#!/usr/bin/env python3
"""
RPG Battle Map Viewer
─────────────────────
Usage:  python main.py <map_image.png>

Left panel  – the battle map with grid / wall / agent overlays
Right panel – agent configuration GUI (add / remove / place agents)
"""

import sys
import os
import json

os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
import pygame.gfxdraw

import textwrap
import copy
import read_stats_from_csv

# ── Import the C++ analysis core ──────────────────────────────────────────────
try:
    import rpg_battle_map as rpg
except ModuleNotFoundError:
    sys.exit(
        "ERROR: rpg_battle_map module not found.\n"
        "Build it first:  cmake --build build && cmake --install build"
    )

# ─────────────────────────────────────────────────────────────────────────────
#  Colour palette
# ─────────────────────────────────────────────────────────────────────────────

# ── Extracted modules ──────────────────────────────────────────────────────
from constants import *
from widgets import Button, TextInput, IntStepper
from helpers import (
    _dnd_mod, _mod_str,
    _parse_physical_damage, _parse_magic_damage,
    _DEFAULT_WEAPON, _weapon_to_dict, _dict_to_weapon,
    _DEFAULT_ARMOR, _armor_to_dict, _dict_to_armor,
    _ABILITY_TO_INT, _INT_TO_ABILITY, _DEFAULT_SPELL,
    _spell_to_dict, _dict_to_spell,
)
from dialogs import FileBrowser, StatsDialog, MobSelectionDialog, ContextMenu, SpellSelectionDialog, ArmorSelectionDialog, WeaponSelectionDialog, ArmorDialog, WeaponsDialog
from weapon_dialog import WeaponDialog
from spell_dialog import SpellDialog
from terrain_dialogs import TemporaryTerrainPlacementDialog, TerrainEditorDialog
from lighting_dialogs import LightingEditorDialog

class App:
    def __init__(self, map_path: str):
        pygame.init()
        pygame.display.set_caption("RPG Battle Map")

        # ── Load json file containing all available mobs from a huge spreadsheet
        script_dir = os.path.dirname(os.path.abspath(__file__))
        map_dir = os.path.dirname(os.path.abspath(map_path))
        # Try multiple possible locations for the CSV file
        possible_paths = [
            os.path.join(script_dir, "sprites", "DND2024_MonsterStats.csv"),
            os.path.join(script_dir, "..", "sprites", "DND2024_MonsterStats.csv"),
            os.path.join(map_dir, "..", "sprites", "DND2024_MonsterStats.csv"),
            "sprites/DND2024_MonsterStats.csv",
        ]
        csv_path = None
        for path in possible_paths:
            if os.path.exists(path):
                csv_path = path
                break
        if not csv_path:
            sys.exit(f"ERROR: Could not find DND2024_MonsterStats.csv. Checked: {possible_paths}")

        # Create or load JSON file with mob stats
        json_path = os.path.splitext(csv_path)[0] + '.json'
        if not os.path.exists(json_path):
            json_path = read_stats_from_csv.save_stats_as_json(csv_path, json_path)
        self.mob_stats_json = read_stats_from_csv.load_stats_from_json(json_path)
        self.all_mobs = self.mob_stats_json
        self.sprites_dir = os.path.dirname(csv_path)  # Store for later use

        # ── Load spells from spells.json ──────────────────────────────────
        self.all_spells = []  # list of spell dicts from spells.json
        possible_spell_paths = [
            os.path.join(script_dir, "spells.json"),
            os.path.join(script_dir, "..", "spells.json"),
            os.path.join(map_dir, "spells.json"),
            "spells.json",
        ]
        spells_loaded_from = None
        for spells_path in possible_spell_paths:
            if os.path.exists(spells_path):
                try:
                    with open(spells_path) as f:
                        self.all_spells = json.load(f)
                    spells_loaded_from = spells_path
                    break
                except (json.JSONDecodeError, IOError):
                    continue

        if self.all_spells:
            print(f"✓ Loaded {len(self.all_spells)} spells from {spells_loaded_from}")
        else:
            print("⚠ WARNING: No spells loaded. Agents with spells will not function.")

        # Create spell lookup: spell_name -> index
        self.spell_name_to_idx = {s.get("name"): i for i, s in enumerate(self.all_spells)}

        # ── Load weapons from weapons.json ──────────────────────────────────
        self.all_weapons = []  # list of weapon dicts from weapons.json
        possible_weapon_paths = [
            os.path.join(script_dir, "weapons.json"),
            os.path.join(script_dir, "..", "weapons.json"),
            os.path.join(map_dir, "weapons.json"),
            "weapons.json",
        ]
        weapons_loaded_from = None
        for weapons_path in possible_weapon_paths:
            if os.path.exists(weapons_path):
                try:
                    with open(weapons_path) as f:
                        self.all_weapons = json.load(f)
                    weapons_loaded_from = weapons_path
                    break
                except (json.JSONDecodeError, IOError):
                    continue

        if self.all_weapons:
            print(f"✓ Loaded {len(self.all_weapons)} weapons from {weapons_loaded_from}")
        else:
            print("⚠ WARNING: No weapons loaded. Agents with weapons will not function.")

        # Create weapon lookup: weapon_name -> weapon_dict
        self.weapon_name_to_dict = {w.get("name"): w for w in self.all_weapons}

        # ── Load armor from armor.json ──────────────────────────────────────
        self.all_armor = []  # list of armor dicts from armor.json
        possible_armor_paths = [
            os.path.join(script_dir, "armor.json"),
            os.path.join(script_dir, "..", "armor.json"),
            os.path.join(map_dir, "armor.json"),
            "armor.json",
        ]
        armor_loaded_from = None
        for armor_path in possible_armor_paths:
            if os.path.exists(armor_path):
                try:
                    with open(armor_path) as f:
                        self.all_armor = json.load(f)
                    armor_loaded_from = armor_path
                    break
                except (json.JSONDecodeError, IOError):
                    continue

        if self.all_armor:
            print(f"✓ Loaded {len(self.all_armor)} armor pieces from {armor_loaded_from}")
        else:
            print("⚠ WARNING: No armor loaded.")

        # Create armor lookup: armor_name -> armor_dict
        self.armor_name_to_dict = {a.get("name"): a for a in self.all_armor}

        # Selected mob's stats (loaded when a mob is selected from dropdown)
        self.selected_mob_stats = None
        self.current_mob_grid_size = 1  # Grid size for current mob (1-4)

        # Pending PC creation (used when placing a new PC)
        self._pending_pc_class = None
        self._pending_pc_stats = None

        # ── Load C++ battle map ───────────────────────────────────────────
        self.bm = rpg.BattleMap(map_path)
        self.bm.analyze_grid()
        self.bm.detect_walls()

        # ── Load image to get size BEFORE creating the display ────────────
        # convert_alpha() requires a display surface to exist first, so we
        # load raw here, create the window, then convert/scale below.
        raw_map = pygame.image.load(map_path)
        mw, mh  = raw_map.get_size()

        # ── Auto-scale map to fit within a reasonable display area ────────
        # Leave room for the right-side config panel and keep some margin.
        MAX_MAP_W = 1860 - PANEL_W   # fits comfortably on a 1920-wide display
        MAX_MAP_H = 1040             # fits comfortably on a 1080-tall display
        scale = min(MAX_MAP_W / mw, MAX_MAP_H / mh, 1.0)  # never upscale
        disp_mw = int(mw * scale)
        disp_mh = int(mh * scale)
        self.map_scale = scale       # used to convert C++ pixel coords → screen

        # ── Window sizing ─────────────────────────────────────────────────
        win_w = disp_mw + PANEL_W
        win_h = max(disp_mh, 600)
        self.screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)

        # ── Now safe to convert (display surface exists) ──────────────────
        converted = raw_map.convert_alpha()
        if scale < 1.0:
            self.map_surf = pygame.transform.smoothscale(converted, (disp_mw, disp_mh))
        else:
            self.map_surf = converted
        self.map_rect = pygame.Rect(0, 0, disp_mw, disp_mh)

        # ── Fonts ─────────────────────────────────────────────────────────
        self.font_sm = pygame.font.SysFont("sans", FONT_SM)
        self.font_md = pygame.font.SysFont("sans", FONT_MD)
        self.font_lg = pygame.font.SysFont("sans", FONT_LG, bold=True)

        # ── Overlay surfaces (alpha) – matches the displayed (scaled) size ──
        self.overlay = pygame.Surface((disp_mw, disp_mh), pygame.SRCALPHA)
        self._build_overlay()

        # ── Sprite cache  {sprite_path: pygame.Surface} ───────────────────
        self.sprites: dict[str, pygame.Surface] = {}

        # ── File browser (shared modal) ───────────────────────────────────
        self.file_browser   = FileBrowser(self.font_sm, self.font_md, self.font_lg)
        self.stats_dialog   = StatsDialog(self.font_sm, self.font_md, self.font_lg, spells=self.all_spells)
        self.weapon_dialog  = WeaponDialog(self.font_sm, self.font_md, self.font_lg)
        self.spell_dialog   = SpellDialog(self.font_sm, self.font_md, self.font_lg)
        self.spell_selection_dialog = SpellSelectionDialog(self.all_spells, self.font_sm, self.font_md)
        self.armor_selection_dialog = ArmorSelectionDialog(list(self.armor_name_to_dict.values()), self.font_sm, self.font_md)
        self.weapon_selection_dialog = WeaponSelectionDialog(list(self.weapon_name_to_dict.values()), self.font_sm, self.font_md)
        self.armor_dialog = ArmorDialog(self.font_sm, self.font_md)
        self.weapons_dialog = WeaponsDialog(self.font_sm, self.font_md)
        mob_names = sorted(self.all_mobs.keys())
        self.mob_dialog = MobSelectionDialog(mob_names, self.font_sm, self.font_md)
        self.terrain_editor = TerrainEditorDialog(self.font_sm, self.font_md)
        self.terrain_placement_dialog = TemporaryTerrainPlacementDialog(self.font_sm, self.font_md)
        self.lighting_editor = LightingEditorDialog(self.font_sm, self.font_md)
        self.context_menu   = ContextMenu()

        # ── NPC spell mechanics ──────────────────────────────────────────────
        self._agent_meta: dict[int, dict] = {}  # {agent_idx: {"npc_spell_groups": {...}}} — for stats dialog

        self._map_dir  = os.path.dirname(os.path.abspath(map_path)) or "/"
        self._save_path = os.path.join(
            self._map_dir,
            os.path.splitext(os.path.basename(map_path))[0] + "_agents.json"
        )
        self._terrain_path = os.path.join(
            self._map_dir,
            os.path.splitext(os.path.basename(map_path))[0] + "_terrain.json"
        )
        self._terrain_regions = []  # List of {type, x, y, width, height, multiplier}

        self._effects_path = os.path.join(
            self._map_dir,
            os.path.splitext(os.path.basename(map_path))[0] + "_effects.json"
        )

        self._lighting_path = os.path.join(
            self._map_dir,
            os.path.splitext(os.path.basename(map_path))[0] + "_lighting.json"
        )

        # Load terrain, spell effects, and lighting data if they exist
        self._load_terrain()
        self._load_spell_effects()
        self._load_lighting()

        # ── Drag-and-drop state ───────────────────────────────────────────
        self.drag_idx     = -1         # index of agent being dragged
        self.drag_origin  = None       # Cell: original position (for cancel)
        self.drag_offset  = (0, 0)     # (dcol, drow) within agent where click landed
        self.drag_cell    = None       # Cell: current snapped target
        self.drag_valid   = False      # is current drag_cell a legal drop?

        # ── Placement mode state (for floating agent placement) ────────────
        self.placement_mode_active = False  # True when placing new agent
        self.placement_config: rpg.AgentConfig | None = None  # Config for agent being placed
        self.placement_cell: rpg.Cell | None = None  # Current cell under mouse
        self.placement_valid = False  # Is current placement location valid?

        # ── Selection state ───────────────────────────────────────────────
        self.selected_idx  = -1        # index of selected agent (-1 = none)
        self._reach_walk: list = []    # Cell list for walk range overlay
        self._reach_fly:  list = []    # Cell list for fly range overlay
        self._reach_set:  set  = set() # union of walk+fly as (col,row) tuples for O(1) lookup

        # ── Visualization toggles ─────────────────────────────────────────
        self.show_lighting_overlay = False  # Toggle for lighting visualization

        # ── Combat engine (C++ — seeded PRNG, RL-ready) ──────────────────
        self.combat = rpg.CombatEngine()
        self.logger = rpg.MessageLogger()
        self.combat.set_logger(self.logger)

        # ── Attack-range overlay ──────────────────────────────────────────
        self._attack_cells_melee:  list = []   # cells attackable by active melee weapon
        self._attack_cells_rnorm:  list = []   # cells in ranged normal range
        self._attack_cells_rlong:  list = []   # cells only in ranged long range

        # ── Combat widget state ───────────────────────────────────────────
        self.combat_active        = False
        self.initiative_order     = []    # list[rpg.InitiativeEntry], high→low
        self.turn_idx             = 0     # index into initiative_order
        self.action_used          = False
        self.bonus_used           = False
        self.pending_attack_slot      = ""    # "" | "action" | "bonus"
        self.pending_weapon_idx       = 0
        self.attacks_remaining        = 0     # attacks left in current pending slot
        self._attack_sequence_slot    = ""    # "action" | "bonus" | "" — which slot the sequence belongs to
        self.pending_spell_slot        = ""    # "" | "action" | "bonus"
        self.pending_spell_idx         = 0
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0     # For Multiple geometry: number of targets to select
        self.pending_spell_targets     = []    # For Multiple geometry: collected targets
        self._opportunity_queue   = []    # list[tuple(attacker_idx, target_idx)]
        self.pending_move_idx     = -1    # agent trying to move away from threat (-1 = none)
        self.pending_move_cell    = None  # destination cell
        self.pending_move_type    = None  # rpg.MovementType
        self.spell_hover_cell     = None  # cell under mouse during AoE targeting
        self.combat_log           = []    # list[str], newest first
        self.move_remaining_walk   = 0     # feet remaining this turn (walk)
        self.move_remaining_fly    = 0     # feet remaining this turn (fly)
        self.move_remaining_swim   = 0     # feet remaining this turn (swim)
        self.move_remaining_burrow = 0     # feet remaining this turn (burrow)
        self.move_type             = rpg.MovementType.Walk  # selected movement type
        self._move_type_btns: dict = {}    # MovementType -> pygame.Rect (built each draw)
        self.last_movement_dist    = 0     # distance of most recent movement (for running jump)
        self.jump_overlay_active   = False # whether jump overlay is showing
        self.jump_reachable_cells  = []    # cells reachable by jump

        # ── Temporary terrain effects (spells, items, etc. with duration) ───
        self.round_num              = 0     # current round number (incremented when turn_idx wraps)
        self._effect_meta: dict     = {}    # {effect_id: {"name": str, "color": tuple, "cells": [(col,row)]}}
        self.show_terrain            = False # toggle for showing all terrain regions
        self.show_spell_effects      = True  # toggle for showing persistent spell effect overlays
        self._spell_metadata: dict = {} # {(agent_idx, spell_idx): {"terrain_effect": dict, "hatch_pattern": str, "level", "upcast_dice_bonus"}}

        # ── Spell slot economy (class-based caster tracking) ────────────────
        self.pending_spell_slot_level: int = 0          # slot level chosen for current spell cast

        # ── Agent config GUI state ────────────────────────────────────────
        self._init_config_panel()
        self._init_combat_panel()
        self.scroll_y = 0         # scroll offset for agent list

        self.clock = pygame.time.Clock()

    # ─────────────────────────────────────────────────────────────────────
    #  Build the static grid / wall / blocked overlay (drawn once)
    # ─────────────────────────────────────────────────────────────────────
    def _build_overlay(self):
        self.overlay.fill((0, 0, 0, 0))
        bm  = self.bm
        s   = self.map_scale          # C++ coords → screen coords
        cpx = int(bm.cell_pixel_size * s)

        # Scale all C++ pixel positions to match the displayed map size.
        raw_h = bm.h_line_positions
        raw_v = bm.v_line_positions
        if not raw_h or not raw_v:
            return
        hlines = [int(y * s) for y in raw_h]
        vlines = [int(x * s) for x in raw_v]

        ox = vlines[0]
        oy = hlines[0]

        # Blocked / wall cells – exact per-cell boundaries from the grid lines.
        for cell in bm.disallowed_cells:
            c, rw = cell.col, cell.row
            if c + 1 >= len(vlines) or rw + 1 >= len(hlines):
                continue
            rx  = vlines[c]
            ry  = hlines[rw]
            rw_ = vlines[c + 1] - rx
            rh_ = hlines[rw + 1] - ry
            pygame.draw.rect(self.overlay, COL_BLOCKED,
                             pygame.Rect(rx, ry, rw_, rh_))

        # Grid lines
        grid_color = (255, 255, 255, 55)
        span_x = vlines[-1] - vlines[0]
        span_y = hlines[-1] - hlines[0]
        for y in hlines:
            pygame.draw.line(self.overlay, grid_color, (ox, y), (ox + span_x, y))
        for x in vlines:
            pygame.draw.line(self.overlay, grid_color, (x, oy), (x, oy + span_y))

        # Edge-based walls (thick red lines between cells) – only when enabled.
        wall_color = (200, 60, 60, 220)
        for w in bm.walls:
            ax = ox + w.a.col * cpx
            ay = oy + w.a.row * cpx
            bx = ox + w.b.col * cpx
            by = oy + w.b.row * cpx
            if w.a.row != w.b.row:                   # horizontal wall (between rows)
                wy = max(ay, by)
                pygame.draw.line(self.overlay, wall_color,
                                 (ax, wy), (ax + cpx, wy), 4)
            else:                                    # vertical wall (between cols)
                wx = max(ax, bx)
                pygame.draw.line(self.overlay, wall_color,
                                 (wx, ay), (wx, ay + cpx), 4)

    # ─────────────────────────────────────────────────────────────────────
    #  Config panel widgets
    # ─────────────────────────────────────────────────────────────────────
    def _panel_x(self):
        return self.screen.get_width() - PANEL_W

    # Layout constants used by both init and reposition
    _PANEL_PAD    = 12   # left/right inset inside panel
    _LABEL_H      = 15   # height reserved for a label line
    _WIDGET_H     = 28   # height of inputs / steppers
    _LABEL_GAP    =  4   # gap between label and its widget
    _ROW_GAP      = 12   # gap between one row's widget and the next row's label
    _BTN_H        = 30   # button height
    _BTN_GAP      =  8   # gap between buttons
    _TITLE_H      = 26   # height of the bold title
    _BROWSE_W     = 34   # width of the "…" browse button

    def _panel_layout(self):
        """Return (px, W, list-of-y-positions) for a fresh layout pass."""
        px = self._panel_x() + self._PANEL_PAD
        W  = PANEL_W - self._PANEL_PAD * 2

        # Row stride = label + gap + widget + row-gap
        RS = self._LABEL_H + self._LABEL_GAP + self._WIDGET_H + self._ROW_GAP

        # y of the INPUT/STEPPER for each row (label sits RS-_WIDGET_H-_ROW_GAP above it)
        title_y  = 10
        row0_y   = title_y + self._TITLE_H + 10           # Mob dropdown
        btn0_y   = row0_y  + self._WIDGET_H + self._ROW_GAP + 8   # Clear All
        btn1_y   = btn0_y  + self._BTN_H + self._BTN_GAP + 4  # Save (half-width)
        # btn2 (Load) is at same y as btn1, right half

        return px, W, title_y, row0_y, btn0_y, btn1_y

    def _init_config_panel(self):
        """Initialize config panel using layout from _panel_layout()."""
        px, W, title_y, r0, b0, b1 = self._panel_layout()
        H   = self._WIDGET_H
        HW  = W // 2 - 2
        B   = self._BTN_H

        self.btn_select_mob = Button(pygame.Rect(px, r0, HW, B), "Select Mob", font=self.font_md)
        self.btn_select_pc = Button(pygame.Rect(px + HW + 4, r0, HW, B), "Select PC",
                                   (80, 100, 140), (110, 130, 170), font=self.font_md)
        self.btn_clear = Button(pygame.Rect(px, b0, W, B), "Clear All",
                               COL_BTN_DANGER, (180, 70, 70), font=self.font_md)
        SW = HW
        self.btn_save = Button(pygame.Rect(px,        b1, SW, B), "Save",
                              (50, 100, 60), (70, 130, 80), font=self.font_md)
        self.btn_load = Button(pygame.Rect(px + SW+4, b1, SW, B), "Load",
                              (50, 75, 120), (70, 100, 155), font=self.font_md)
        lr_y = b1 + B + self._BTN_GAP
        self.btn_long_rest = Button(pygame.Rect(px, lr_y, W, B), "Long Rest",
                                    (60, 100, 60), (80, 130, 80), font=self.font_md)
        bc_y = lr_y + B + self._BTN_GAP + 8
        self.btn_begin_combat = Button(pygame.Rect(px, bc_y, W, B),
                                      "Begin Combat",
                                      COL_BTN_COMBAT, COL_BTN_COMBAT_HOV, font=self.font_md)
        ter_y = bc_y + B + self._BTN_GAP
        self.btn_edit_terrain = Button(pygame.Rect(px, ter_y, W, B),
                                       "Edit Terrain",
                                       (80, 100, 120), (110, 130, 160), font=self.font_md)
        light_y = ter_y + B + self._BTN_GAP
        self.btn_edit_lighting = Button(pygame.Rect(px, light_y, W, B),
                                        "Edit Lighting",
                                        (120, 100, 80), (160, 130, 110), font=self.font_md)
        toggle_light_y = light_y + B + self._BTN_GAP
        self.btn_toggle_lighting = Button(pygame.Rect(px, toggle_light_y, W, B),
                                          "Lighting: OFF",
                                          (80, 80, 120), (110, 110, 160), font=self.font_md)
        quit_y = toggle_light_y + B + self._BTN_GAP
        self.btn_quit = Button(pygame.Rect(px, quit_y, W, B),
                              "Quit",
                              COL_BTN_DANGER, (180, 70, 70), font=self.font_md)

        self.pending_configs: list[rpg.AgentConfig] = []
        self.pending_mob_stats: list[dict | None] = []  # Parallel list of mob stats for each config

    def _reposition_panel(self):
        """Re-anchor all widgets after a window resize."""
        px, W, _, r0, b0, b1 = self._panel_layout()
        SW  = W // 2 - 2

        self.btn_select_mob.rect.update(px, r0, SW, self._WIDGET_H)
        self.btn_select_pc.rect.update(px + SW + 4, r0, SW, self._WIDGET_H)
        self.btn_clear.rect.update(px, b0, W, self._BTN_H)
        self.btn_save.rect.update(px,        b1, SW, self._BTN_H)
        self.btn_load.rect.update(px + SW+4, b1, SW, self._BTN_H)
        lr_y = b1 + self._BTN_H + self._BTN_GAP
        self.btn_long_rest.rect.update(px, lr_y, W, self._BTN_H)
        bc_y = lr_y + self._BTN_H + self._BTN_GAP + 8
        self.btn_begin_combat.rect.update(px, bc_y, W, self._BTN_H)
        ter_y = bc_y + self._BTN_H + self._BTN_GAP
        self.btn_edit_terrain.rect.update(px, ter_y, W, self._BTN_H)
        light_y = ter_y + self._BTN_H + self._BTN_GAP
        self.btn_edit_lighting.rect.update(px, light_y, W, self._BTN_H)
        toggle_light_y = light_y + self._BTN_H + self._BTN_GAP
        self.btn_toggle_lighting.rect.update(px, toggle_light_y, W, self._BTN_H)
        quit_y = toggle_light_y + self._BTN_H + self._BTN_GAP
        self.btn_quit.rect.update(px, quit_y, W, self._BTN_H)
        # Update combat panel button x-positions (y is fixed by _draw_combat_panel)
        HW2 = W // 2 - 2
        TW3 = (W - 8) // 3
        self.btn_cbt_atk_action.rect.update( px,           self.btn_cbt_atk_action.rect.y,  HW2, self._BTN_H)
        self.btn_cbt_pass_action.rect.update(px+HW2+4,     self.btn_cbt_pass_action.rect.y, HW2, self._BTN_H)
        self.btn_cbt_dash.rect.update(       px,           self.btn_cbt_dash.rect.y,       TW3, self._BTN_H)
        self.btn_cbt_dodge.rect.update(      px+TW3+4,     self.btn_cbt_dodge.rect.y,      TW3, self._BTN_H)
        self.btn_cbt_disengage.rect.update(  px+2*(TW3+4), self.btn_cbt_disengage.rect.y,  TW3, self._BTN_H)
        self.btn_cbt_atk_bonus.rect.update(   px,           self.btn_cbt_atk_bonus.rect.y,   TW3, self._BTN_H)
        self.btn_cbt_spell_bonus.rect.update( px+TW3+4,    self.btn_cbt_spell_bonus.rect.y,  TW3, self._BTN_H)
        self.btn_cbt_pass_bonus.rect.update(  px+2*(TW3+4),self.btn_cbt_pass_bonus.rect.y,   TW3, self._BTN_H)
        self.btn_cbt_spell_action.rect.update(px,          self.btn_cbt_spell_action.rect.y,  W,  self._BTN_H)
        self.btn_cbt_end_turn.rect.update(    px,          self.btn_cbt_end_turn.rect.y,       W,  self._BTN_H)
        self.btn_cbt_end_combat.rect.update(  px,          self.btn_cbt_end_combat.rect.y,     W,  self._BTN_H)

    def _init_combat_panel(self):
        """Create the buttons shown exclusively in the combat panel."""
        px  = self._panel_x() + self._PANEL_PAD
        W   = PANEL_W - self._PANEL_PAD * 2
        HW  = W // 2 - 2
        B   = self._BTN_H

        # Dummy Y (will be set in _draw_combat_panel)
        dummy_y = 0

        self.btn_cbt_atk_action  = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "⚔ Attack",
                                          COL_BTN_ATK, COL_BTN_ATK_HOV, self.font_md)
        self.btn_cbt_pass_action = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                          "Pass",
                                          COL_BTN_PASS, COL_BTN_PASS_HOV, self.font_md)
        self.btn_cbt_dash        = Button(pygame.Rect(px,               dummy_y, HW, B),
                                          "Dash",
                                          COL_BTN_DASH, COL_BTN_DASH_HOV, self.font_md)
        self.btn_cbt_dodge       = Button(pygame.Rect(px+HW+4,         dummy_y, HW, B),
                                          "Dodge",
                                          COL_BTN_DODGE, COL_BTN_DODGE_HOV, self.font_md)
        self.btn_cbt_disengage   = Button(pygame.Rect(px,     dummy_y, HW, B),
                                          "Disengage",
                                          COL_BTN_DISENG, COL_BTN_DISENG_HOV, self.font_md)
        self.btn_cbt_atk_bonus   = Button(pygame.Rect(px,       dummy_y, HW, B),
                                          "⚔ Bonus Atk",
                                          COL_BTN_ATK, COL_BTN_ATK_HOV, self.font_md)
        self.btn_cbt_pass_bonus  = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                          "Pass",
                                          COL_BTN_PASS, COL_BTN_PASS_HOV, self.font_md)
        self.btn_cbt_spell_action= Button(pygame.Rect(px, dummy_y, W, B),
                                          "✨ Cast Spell",
                                          COL_BTN_SPELL, COL_BTN_SPELL_HOV, self.font_md)
        self.btn_cbt_spell_bonus = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "✨ Spell",
                                          COL_BTN_SPELL, COL_BTN_SPELL_HOV, self.font_md)
        self.btn_cbt_long_jump   = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Long Jump",
                                          (100, 150, 200), (120, 170, 220), self.font_md)
        self.btn_cbt_end_turn    = Button(pygame.Rect(px, dummy_y, W, B),
                                          "End Turn",
                                          COL_BTN_ENDTURN, COL_BTN_ENDTURN_HOV, self.font_md)
        self.btn_cbt_place_terrain = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "🌍 Place Terrain",
                                          (150, 120, 80), (180, 150, 110), self.font_md)
        self.btn_cbt_end_combat  = Button(pygame.Rect(px, dummy_y, W, B),
                                          "End Combat",
                                          COL_BTN_DANGER, (180, 70, 70), self.font_md)
        self.btn_cbt_drop_concentration = Button(pygame.Rect(px, dummy_y, W, B),
                                          "Drop Concentration",
                                          (150, 100, 100), (200, 130, 130), self.font_md)
        self.btn_show_terrain = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "Show Terrain",
                                          (100, 150, 150), (130, 180, 200), self.font_md)
        dummy_y += B + 5
        self.btn_show_spell_effects = Button(pygame.Rect(px, dummy_y, HW, B),
                                          "Show Spell Effects",
                                          (150, 120, 180), (180, 150, 210), self.font_md)

    # ─────────────────────────────────────────────────────────────────────
    #  Sprite loading (cached)
    # ─────────────────────────────────────────────────────────────────────
    def _get_sprite(self, path: str, size_px: int) -> pygame.Surface | None:
        key = (path, size_px)
        if key not in self.sprites:
            if path and os.path.exists(path):
                try:
                    raw = pygame.image.load(path).convert_alpha()
                    self.sprites[key] = pygame.transform.scale(
                        raw, (size_px, size_px))
                except Exception:
                    self.sprites[key] = None
            else:
                self.sprites[key] = None
        return self.sprites[key]

    def _get_mob_sprite_path(self, mob_name: str) -> str:
        """Determine sprite path for a mob: use specific sprite if it exists, otherwise use first letter."""
        specific_path = os.path.join(self.sprites_dir, f"{mob_name}.png")
        if os.path.exists(specific_path):
            return specific_path
        return os.path.join(self.sprites_dir, f"{mob_name[0].upper()}.png")

    def _avg_damage_to_dice(self, avg: int) -> tuple[int, int]:
        total = avg * 2
        for die in (6, 8, 10):
            if total % die == 0:
                return total // die, die
        return max(1, total // 6), 6

    def _parse_atk_range(self, range_str: str, atk_type: str) -> tuple[int, int, int]:
        s = range_str.strip()
        if not s:
            return 5, 80, 320
        if "/" in s:
            parts = s.split("/")
            normal, long_ = int(parts[0]), int(parts[1])
            return 5, normal, long_
        val = int(s)
        if atk_type == "Melee":
            return val, 80, 320
        return 5, val, val * 4

    def _parse_damage_types(self, dtype_str: str):
        physical, magic = [], []
        for part in dtype_str.split(","):
            t = part.strip()
            try:
                physical.append(getattr(rpg.PhysicalDamage, t))
                continue
            except AttributeError:
                pass
            try:
                magic.append(getattr(rpg.MagicDamage, t))
            except AttributeError:
                pass
        return physical, magic

    def _auto_weapons_from_mob_stats(self, mob_stats: dict) -> list:
        weapons = []
        for i in range(1, 5):  # slots Atk 1–4; iterate all, skip empties
            atk_type  = mob_stats.get(f"Atk {i} Type", "").strip()
            dam_str   = mob_stats.get(f"Atk {i} Dam.", "").strip()
            dtype_str = mob_stats.get(f"Atk {i} Damage Type", "").strip()
            range_str = mob_stats.get(f"Atk {i} Range", "").strip()
            if not atk_type or not dam_str:
                continue
            try:
                avg_dam = int(dam_str)
            except ValueError:
                avg_dam = 6
            num_dice, die_size = self._avg_damage_to_dice(avg_dam)
            physical, magic    = self._parse_damage_types(dtype_str)
            reach_ft, normal_ft, long_ft = self._parse_atk_range(range_str, atk_type)
            w = rpg.Weapon()
            w.name             = f"Atk {i} ({atk_type})"
            w.type             = rpg.WeaponType.Melee if atk_type == "Melee" else rpg.WeaponType.Ranged
            w.reach_ft         = reach_ft
            w.normal_range_ft  = normal_ft
            w.long_range_ft    = long_ft
            w.proficient       = True
            # Create damage roll objects for each damage type
            w.physical_damage_types = []
            for phys_type in physical:
                roll = rpg.PhysicalDamageRoll()
                roll.type = phys_type
                roll.num_dice = num_dice
                roll.die_size = die_size
                roll.bonus = 0
                w.physical_damage_types.append(roll)
            w.magic_damage_types = []
            for mag_type in magic:
                roll = rpg.MagicDamageRoll()
                roll.type = mag_type
                roll.num_dice = num_dice
                roll.die_size = die_size
                roll.bonus = 0
                w.magic_damage_types.append(roll)
            weapons.append(w)
        return weapons

    def _size_category_to_grid_size(self, size_category: str) -> int:
        """Convert D&D size category to grid size (cells)."""
        size_map = {
            "Small": 1,
            "Tiny": 1,
            "Medium": 1,
            "Large": 2,
            "Huge": 3,
            "Gargantuan": 4,
        }
        return size_map.get(size_category, 1)

    def _on_mob_selected(self, mob_name: str):
        """Callback when a mob is selected from the dialog."""
        # Load stats from JSON
        if mob_name in self.mob_stats_json:
            self.selected_mob_stats = self.mob_stats_json[mob_name]
            # Set size based on mob size category
            size_category = self.selected_mob_stats.get("Size", "Medium")
            self.current_mob_grid_size = self._size_category_to_grid_size(size_category)
        else:
            self.selected_mob_stats = None
            self.current_mob_grid_size = 1

        # Enter placement mode immediately
        cfg = rpg.AgentConfig()
        cfg.name        = mob_name
        cfg.sprite_path = self._get_mob_sprite_path(mob_name)
        cfg.size        = self.current_mob_grid_size
        cfg.start_col   = 0
        cfg.start_row   = 0
        self.placement_mode_active = True
        self.placement_config = cfg
        self.placement_cell = None
        self.placement_valid = False

    def _on_pc_class_selected(self, class_name: str):
        """Callback when a PC class is selected."""
        self.selected_mob_stats = None  # No mob stats for PCs
        self.current_mob_grid_size = 1

        # Enter placement mode with new PC
        cfg = rpg.AgentConfig()
        cfg.name        = f"{class_name} 1"
        cfg.sprite_path = ""  # PCs don't have sprites initially
        cfg.size        = 1
        cfg.start_col   = 0
        cfg.start_row   = 0

        # Create default PC stats (standard array: 15, 14, 13, 12, 10, 8)
        stats = rpg.Stats()
        stats.str        = 15
        stats.dex        = 14
        stats.con        = 13
        stats.intel      = 12
        stats.wis        = 10
        stats.cha        = 8
        stats.hp_max     = 8  # Will be updated based on class
        stats.hp_cur     = 8
        stats.base_ac    = 10
        stats.speed_walk = 30
        stats.prof_bonus = 2
        stats.num_attacks = 1
        # Set class and level (this also sets can_cast_spell and spell slots)
        stats.set_class_level(getattr(rpg.CharacterClass, class_name), 1)

        # Store for use in placement handler
        self._pending_pc_class = class_name
        self._pending_pc_stats = stats

        self.placement_mode_active = True
        self.placement_config = cfg
        self.placement_cell = None
        self.placement_valid = False

    def _mob_stats_to_d_d_stats(self, mob_data: dict):
        """Convert CSV mob stats to D&D 5e agent stats."""
        # Convert ability modifiers to ability scores: score = (mod * 2) + 10
        def mod_to_score(mod_str):
            try:
                mod = int(mod_str) if mod_str else 0
                return (mod * 2) + 10
            except (ValueError, TypeError):
                return 10

        def safe_int(val, default=10):
            try:
                return int(val) if val else default
            except (ValueError, TypeError):
                return default

        # Create Stats object directly
        stats = rpg.Stats()
        stats.str = mod_to_score(mob_data.get('STR Mod'))
        stats.dex = mod_to_score(mob_data.get('DEX Mod'))
        stats.con = mod_to_score(mob_data.get('CON Mod'))
        stats.intel = mod_to_score(mob_data.get('INT Mod'))
        stats.wis = mod_to_score(mob_data.get('WIS Mod'))
        stats.cha = mod_to_score(mob_data.get('CHA Mod'))
        stats.hp_max = safe_int(mob_data.get('HP', '10'), 10)
        stats.hp_cur = stats.hp_max
        stats.base_ac = safe_int(mob_data.get('AC', '10'), 10)
        stats.speed_walk   = safe_int(mob_data.get('Walk',   '30'), 30)
        stats.speed_fly    = safe_int(mob_data.get('Fly',    '0'),   0)
        stats.speed_swim   = safe_int(mob_data.get('Swim',   '0'),   0)
        stats.speed_burrow = safe_int(mob_data.get('Burrow', '0'),   0)
        stats.prof_bonus   = safe_int(mob_data.get('PB',     '2'),   2)
        stats.num_attacks  = safe_int(mob_data.get('# of Atk', '1'), 1)

        # Saving throw proficiencies from "Saving Throw" field (comma-separated ability names)
        save_str = mob_data.get('Saving Throw', '') or ''
        saves = {s.strip().lower() for s in save_str.split(',')}
        stats.save_prof_str   = 'strength'     in saves
        stats.save_prof_dex   = 'dexterity'    in saves
        stats.save_prof_con   = 'constitution' in saves
        stats.save_prof_intel = 'intelligence' in saves
        stats.save_prof_wis   = 'wisdom'       in saves
        stats.save_prof_cha   = 'charisma'     in saves
        return stats

    # ─────────────────────────────────────────────────────────────────────
    #  Grid coordinate helpers
    # ─────────────────────────────────────────────────────────────────────
    def _screen_to_cell(self, sx, sy):
        """Convert a screen pixel position to a grid Cell, or None if outside."""
        s     = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        if not raw_v or not raw_h:
            return None
        # Unscale back to original image space
        ix = sx / s
        iy = sy / s
        # Binary-search which column/row we're in
        import bisect
        c = bisect.bisect_right(raw_v, ix) - 1
        r = bisect.bisect_right(raw_h, iy) - 1
        if 0 <= c < self.bm.grid_cols and 0 <= r < self.bm.grid_rows:
            return rpg.Cell(c, r)
        return None

    def _cell_to_screen(self, col, row):
        """Return top-left screen pixel of a grid cell."""
        s     = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        return int(raw_v[col] * s), int(raw_h[row] * s)

    def _agent_at(self, cell):
        """Return index of the placed agent whose footprint contains cell, or -1."""
        for i, pt in enumerate(self.bm.placed_agents):
            oc, or_ = pt.origin.col, pt.origin.row
            if oc <= cell.col < oc + pt.size and or_ <= cell.row < or_ + pt.size:
                return i
        return -1

    def _can_place(self, cell, size, exclude_idx=-1):
        """Return True if a size×size agent can be placed with top-left at cell."""
        cols, rows = self.bm.grid_cols, self.bm.grid_rows
        if cell.col < 0 or cell.row < 0:
            return False
        if cell.col + size > cols or cell.row + size > rows:
            return False
        if self.bm.is_blocked(cell, size):
            return False
        # Check overlap with other agents
        for i, pt in enumerate(self.bm.placed_agents):
            if i == exclude_idx:
                continue
            if (cell.col < pt.origin.col + pt.size and
                    cell.col + size > pt.origin.col and
                    cell.row < pt.origin.row + pt.size and
                    cell.row + size > pt.origin.row):
                return False
        return True

    # ─────────────────────────────────────────────────────────────────────
    #  Save / Load
    # ─────────────────────────────────────────────────────────────────────
    # ── Save / load callbacks called by the file browser ─────────────────────
    def _on_save_path_chosen(self, path: str):
        self._save_path = path
        self._save_agents(path)

    def _on_load_path_chosen(self, path: str):
        self._save_path = path
        self._load_agents(path)

    def _update_reach(self):
        """Recompute walk/fly reachable-cell overlays for the selected agent.

        In combat mode the budget comes from CombatEngine so it shrinks as the
        agent moves.  Outside combat the full stat speed is used.
        """
        self._reach_walk   = []
        self._reach_fly    = []
        self._reach_swim   = []
        self._reach_burrow = []
        self._reach_set    = set()
        idx = self.selected_idx
        if idx < 0 or idx >= len(self.bm.placed_agents):
            return
        pt    = self.bm.placed_agents[idx]
        stats = self.combat.get_agent_stats(self.bm, idx)

        if self.combat_active:
            walk_ft   = self.move_remaining_walk
            fly_ft    = self.move_remaining_fly
            swim_ft   = self.move_remaining_swim
            burrow_ft = self.move_remaining_burrow
        else:
            walk_ft   = stats.speed_walk
            fly_ft    = stats.speed_fly
            swim_ft   = stats.speed_swim
            burrow_ft = stats.speed_burrow

        if walk_ft > 0:
            self._reach_walk = self.bm.reachable_cells(
                pt.origin, pt.size, walk_ft, rpg.MovementType.Walk)
        if fly_ft > 0:
            self._reach_fly = self.bm.reachable_cells(
                pt.origin, pt.size, fly_ft, rpg.MovementType.Fly)
        if swim_ft > 0:
            self._reach_swim = self.bm.reachable_cells(
                pt.origin, pt.size, swim_ft, rpg.MovementType.Swim)
        if burrow_ft > 0:
            self._reach_burrow = self.bm.reachable_cells(
                pt.origin, pt.size, burrow_ft, rpg.MovementType.Burrow)

        # Drag validity uses only the selected movement type's reach.
        _reach_by_type = {
            rpg.MovementType.Walk:   self._reach_walk,
            rpg.MovementType.Fly:    self._reach_fly,
            rpg.MovementType.Swim:   self._reach_swim,
            rpg.MovementType.Burrow: self._reach_burrow,
        }
        self._reach_set = {(c.col, c.row)
                           for c in _reach_by_type.get(self.move_type, [])}

    def _on_stats_ok(self, agent_idx: int, steppers: dict, prof_flags: dict, class_name: str = "None", char_level: int = 1, npc_data: dict = None):
        """Called by StatsDialog when the user clicks OK."""
        # Start from current stats so flags not shown in the dialog are preserved.
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        stats.str        = steppers["str"].value
        stats.dex        = steppers["dex"].value
        stats.con        = steppers["con"].value
        stats.intel      = steppers["intel"].value
        stats.wis        = steppers["wis"].value
        stats.cha        = steppers["cha"].value
        stats.hp_cur     = steppers["hp_cur"].value
        stats.hp_max     = steppers["hp_max"].value
        stats.base_ac    = steppers["base_ac"].value
        stats.speed_walk   = steppers["speed_walk"].value
        stats.speed_swim   = steppers["speed_swim"].value
        stats.speed_fly    = steppers["speed_fly"].value
        stats.speed_burrow = steppers["speed_burrow"].value
        stats.prof_bonus   = steppers["prof_bonus"].value
        stats.num_attacks  = steppers["num_attacks"].value
        # Saving throw proficiency per ability
        stats.save_prof_str   = prof_flags.get("save_prof_str",   False)
        stats.save_prof_dex   = prof_flags.get("save_prof_dex",   False)
        stats.save_prof_con   = prof_flags.get("save_prof_con",   False)
        stats.save_prof_intel = prof_flags.get("save_prof_intel", False)
        stats.save_prof_wis   = prof_flags.get("save_prof_wis",   False)
        stats.save_prof_cha   = prof_flags.get("save_prof_cha",   False)

        # Set class and level; this updates spell_slots_max and can_cast_spell automatically
        stats.set_class_level(getattr(rpg.CharacterClass, class_name), char_level)
        # Restore remaining slots to max (they're newly set)
        stats.spell_slots_remaining = list(stats.spell_slots_max)

        self.combat.set_agent_stats(self.bm, agent_idx, stats)

        # Store NPC metadata if provided, and initialize spell uses via C++
        if npc_data:
            self._agent_meta[agent_idx] = npc_data
            # Initialize spell uses_max/uses_remaining in C++ from npc_spell_groups
            npc_spell_groups = npc_data.get("npc_spell_groups", {})
            if npc_spell_groups:
                groups_dict = {int(k): v for k, v in npc_spell_groups.items()}
                self.combat.init_npc_spell_groups(self.bm, agent_idx, groups_dict)
        elif agent_idx in self._agent_meta:
            del self._agent_meta[agent_idx]

        if agent_idx == self.selected_idx:
            self._update_reach()

    # ── Weapon callbacks & overlays ───────────────────────────────────────────

    def _on_weapon_done(self, agent_idx: int, weapons: list[dict]):
        """Called by WeaponDialog when the user clicks Done.

        `weapons` is a list of plain dicts (the WeaponDialog's internal format).
        Convert each to an rpg.Weapon and push the list into the C++ layer.
        """
        cpp_weapons = [_dict_to_weapon(d) for d in weapons]
        self.combat.set_agent_weapons(self.bm, agent_idx, cpp_weapons)
        # Update has_offhand_attack based on whether any weapon is off-hand
        stats = self.combat.get_agent_stats(self.bm, agent_idx)
        stats.has_offhand_attack = any(d.get("off_hand", False) for d in weapons)
        self.combat.set_agent_stats(self.bm, agent_idx, stats)
        # Refresh attack overlay if this is the currently selected agent.
        if agent_idx == self.selected_idx:
            self._update_attack_overlay()

    def _update_attack_overlay(self):
        """Recompute attack-range overlays for the selected agent's weapons."""
        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []
        idx = self.selected_idx
        if idx < 0 or idx >= len(self.bm.placed_agents):
            return
        weapons = self.combat.get_agent_weapons(self.bm, idx)   # list[rpg.Weapon] from C++
        if not weapons:
            return
        pt = self.bm.placed_agents[idx]
        melee_cells:  set[tuple[int, int]] = set()
        rnorm_cells:  set[tuple[int, int]] = set()
        rlongx_cells: set[tuple[int, int]] = set()  # long-range-only

        for w in weapons:
            if w.type == rpg.WeaponType.Melee:
                for c in self.bm.attack_target_cells(
                        pt.origin, pt.size, w.reach_ft):
                    melee_cells.add((c.col, c.row))
            else:  # Ranged
                for c in self.bm.attack_target_cells(
                        pt.origin, pt.size, w.normal_range_ft):
                    rnorm_cells.add((c.col, c.row))
                for c in self.bm.attack_target_cells(
                        pt.origin, pt.size, w.long_range_ft):
                    if (c.col, c.row) not in rnorm_cells:
                        rlongx_cells.add((c.col, c.row))

        # Convert back to Cell-like objects (just store as (col,row) dicts
        # to avoid depending on rpg.Cell construction in a hot path).
        def _as_cells(s):
            return [rpg.Cell(c, r) for c, r in s]

        self._attack_cells_melee = _as_cells(melee_cells)
        self._attack_cells_rnorm = _as_cells(rnorm_cells)
        self._attack_cells_rlong = _as_cells(rlongx_cells)

    # ─────────────────────────────────────────────────────────────────────
    #  Combat widget helpers
    # ─────────────────────────────────────────────────────────────────────

    def _current_agent_idx(self) -> int:
        """Return the BattleMap index of the currently acting combatant, or -1."""
        if not self.combat_active or not self.initiative_order:
            return -1
        return self.initiative_order[self.turn_idx].agent_idx

    def _reset_movement(self, agent_idx: int):
        """Seed this turn's movement budgets from the agent's stats."""
        if 0 <= agent_idx < len(self.bm.placed_agents):
            stats  = self.combat.get_agent_stats(self.bm, agent_idx)
            agent  = self.bm.placed_agents[agent_idx]
            walk   = stats.speed_walk
            fly    = stats.speed_fly
            swim   = stats.speed_swim
            burrow = stats.speed_burrow
            self.move_remaining_walk   = walk
            self.move_remaining_fly    = fly
            self.move_remaining_swim   = swim
            self.move_remaining_burrow = burrow
            agent.init_movement(walk, fly, swim, burrow)
        else:
            self.move_remaining_walk   = 0
            self.move_remaining_fly    = 0
            self.move_remaining_swim   = 0
            self.move_remaining_burrow = 0
        # Default to Walk; fall back to first available type if walk speed is 0.
        if self.move_remaining_walk > 0:
            self.move_type = rpg.MovementType.Walk
        elif self.move_remaining_fly > 0:
            self.move_type = rpg.MovementType.Fly
        elif self.move_remaining_swim > 0:
            self.move_type = rpg.MovementType.Swim
        else:
            self.move_type = rpg.MovementType.Burrow
        self.last_movement_dist = 0
        self.jump_overlay_active = False
        self.jump_reachable_cells = set()

    def _toggle_jump_overlay(self):
        """Toggle the jump overlay visibility and recalculate if needed."""
        if self.jump_overlay_active:
            self.jump_overlay_active = False
            self.jump_reachable_cells = []
        else:
            self._update_jump_reachable()
            self.jump_overlay_active = True

    def _update_jump_reachable(self):
        """Calculate cells reachable by long jump from current agent."""
        self.jump_reachable_cells = []
        idx = self._current_agent_idx()
        if not (0 <= idx < len(self.bm.placed_agents)):
            return

        agent = self.bm.placed_agents[idx]
        stats = self.combat.get_agent_stats(self.bm, idx)
        strength = stats.str

        if strength <= 0:
            return

        # Determine if running or standing jump (based on most recent movement)
        is_running_jump = self.last_movement_dist >= 10
        max_jump_dist = strength if is_running_jump else (strength // 2)

        # Calculate reachable cells (Manhattan distance from current position, ignoring walls)
        origin = agent.origin
        for dr in range(-max_jump_dist, max_jump_dist + 1):
            for dc in range(-max_jump_dist, max_jump_dist + 1):
                manhattan_dist = abs(dc) + abs(dr)
                if manhattan_dist == 0:
                    continue  # Can't jump to current cell
                if manhattan_dist > max_jump_dist:
                    continue

                target_cell = rpg.Cell(origin.col + dc, origin.row + dr)
                # Add cells within Manhattan distance (visualization will skip invalid ones)
                self.jump_reachable_cells.append(target_cell)

    def _execute_jump(self, agent_idx: int, target_cell):
        """Execute a jump to the target cell, deducting movement."""
        if not (0 <= agent_idx < len(self.bm.placed_agents)):
            return

        # Refresh agent reference to ensure we have current position
        agent = self.bm.placed_agents[agent_idx]
        stats = self.combat.get_agent_stats(self.bm, agent_idx)

        # Calculate jump distance for logging (from current position to target)
        jump_dist = (abs(target_cell.col - agent.origin.col) +
                     abs(target_cell.row - agent.origin.row)) * 5

        # Determine if running or standing jump based on most recent movement
        is_running = self.last_movement_dist >= 10

        # Execute jump (C++ handles all budget deductions)
        if self.combat.jump_agent(self.bm, agent_idx, target_cell, is_running):
            self._flush_combat_log()  # Flush any spell effect damage messages
            # Update remaining movement values
            ag = self.bm.placed_agents[agent_idx]
            self.move_remaining_walk = ag.walk_remaining
            self.move_remaining_fly = ag.fly_remaining
            self.move_remaining_swim = ag.swim_remaining
            self.move_remaining_burrow = ag.burrow_remaining
            self.last_movement_dist = 0  # Reset run-up after jump
            jump_type = "running" if is_running else "standing"
            self._combat_log_add(f"{agent.name}: {jump_type.capitalize()} long jump (+{jump_dist}ft)")
            self._update_reach()
            self._update_jump_reachable()
        else:
            # Jump failed - out of range or insufficient movement
            strength = stats.str
            max_dist = strength if is_running else (strength // 2)
            self._combat_log_add(f"{agent.name}: Jump out of range ({jump_dist}ft > {max_dist}ft)")

    def _start_combat(self):
        """Roll initiative and enter combat mode."""
        if not self.bm.placed_agents:
            return
        order = list(self.combat.roll_initiative(self.bm))
        if not order:
            return
        self.initiative_order    = order
        self.combat_active       = True
        self.turn_idx            = 0
        self.round_num           = 0
        self.action_used          = False
        self.bonus_used           = False
        self.pending_attack_slot       = ""
        self.attacks_remaining         = 0
        self.pending_spell_slot        = ""
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0
        self.pending_spell_targets     = []
        self.combat_log                = []
        # Initialize combat log file
        self._combat_log_file = "combat_log.txt"
        with open(self._combat_log_file, "w") as f:
            f.write("=== COMBAT LOG ===\n")
        self._effect_meta         = {}
        self.bm.clear_terrain_effects()
        # Apply armor multipliers for all agents at combat start
        for i in range(len(self.bm.placed_agents)):
            self.combat.apply_armor_multipliers(self.bm, i)
        first = self._current_agent_idx()
        self.selected_idx = first
        self._reset_movement(first)
        self._update_reach()
        self._update_attack_overlay()
        print(f"[COMBAT START] Initiative order: {[(e.total, self.bm.placed_agents[e.agent_idx].name) for e in order]}")
        print(f"[COMBAT START] First turn: agent_idx={first}, name={self.bm.placed_agents[first].name if 0 <= first < len(self.bm.placed_agents) else '?'}")

    def _end_combat(self):
        """Leave combat mode and clear all combat state."""
        self.move_remaining_walk   = 0
        self.move_remaining_fly    = 0
        self.move_remaining_swim   = 0
        self.move_remaining_burrow = 0
        self.move_type             = rpg.MovementType.Walk
        self.combat_active         = False
        self.initiative_order    = []
        self.turn_idx            = 0
        self.round_num           = 0
        self.action_used          = False
        self.bonus_used           = False
        self.pending_attack_slot       = ""
        self.attacks_remaining         = 0
        self.pending_spell_slot        = ""
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0
        self.pending_spell_targets     = []
        self.selected_idx              = -1
        self._reach_walk         = []
        self._reach_fly          = []
        self._reach_set          = set()
        self._effect_meta         = {}
        self._concentration_state = {}
        self._spell_metadata      = {}
        self.bm.clear_terrain_effects()
        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []

    def _advance_turn(self):
        """Advance to the next living combatant in initiative order."""
        if not self.initiative_order:
            return
        n = len(self.initiative_order)
        prev_turn_idx = self.turn_idx
        prev_idx = self._current_agent_idx()

        # Find next living agent (skip dead)
        for _ in range(n):
            self.turn_idx = (self.turn_idx + 1) % n
            idx = self._current_agent_idx()
            if 0 <= idx < len(self.bm.placed_agents):
                stats = self.combat.get_agent_stats(self.bm, idx)
                if stats.hp_cur > 0:
                    break
                else:
                    # Agent is dead, drop concentration if any
                    self._drop_concentration_for_agent(idx)

        # Round advancement: when turn_idx wraps to 0
        if self.turn_idx < prev_turn_idx:
            self.round_num += 1
            # Tick concentration terrain duration
            self._tick_concentration_terrain()
            # Tick DM-placed effects at round boundary
            expired_dm = self.bm.tick_dm_terrain_effects()
            for effect_id in expired_dm:
                if effect_id in self._effect_meta:
                    effect_name = self._effect_meta[effect_id].get("name", "Effect")
                    self._combat_log_add(f"{effect_name} fades.")
                    del self._effect_meta[effect_id]

        # End previous agent's turn
        if prev_idx >= 0:
            self.combat.end_turn(self.bm, prev_idx)

        # Reset action economy and per-turn conditions for the new combatant.
        self.action_used           = False
        self.bonus_used            = False
        self.pending_attack_slot       = ""
        self.attacks_remaining         = 0
        self._attack_sequence_slot     = ""
        self.pending_spell_slot        = ""
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0
        self.pending_spell_targets     = []
        self._opportunity_queue.clear()

        # Begin new agent's turn (conditions reset + movement seed now happen in C++)
        new_idx = self._current_agent_idx()
        self.selected_idx = new_idx
        if new_idx >= 0:
            self.combat.begin_turn(self.bm, new_idx)
            # Initialize Python-side movement tracking (C++ also seeds in beginTurn)
            self._reset_movement(new_idx)

        # Tick terrain effects (stays in Python for now — terrain is BattleMap concern)
        if new_idx >= 0:
            expired = self.bm.tick_terrain_effects(new_idx)
            for effect_id in expired:
                if effect_id in self._effect_meta:
                    effect_name = self._effect_meta[effect_id].get("name", "Effect")
                    self._combat_log_add(f"{effect_name} fades.")
                    del self._effect_meta[effect_id]

        self._update_reach()
        self._update_attack_overlay()

    def _drop_concentration(self):
        """Drop concentration for current agent and remove associated terrain."""
        cur_idx = self._current_agent_idx()
        self._drop_concentration_for_agent(cur_idx)

    def _drop_concentration_for_agent(self, agent_idx: int):
        """Drop concentration for specified agent and remove associated terrain."""
        if agent_idx < 0 or agent_idx >= len(self.bm.placed_agents):
            return
        agent = self.bm.placed_agents[agent_idx]
        if not agent.conditions.concentrating:
            return
        spell_name = agent.conditions.concentrating_on
        agent_name = agent.name
        # Remove terrain regions from this agent's concentration spell
        self._terrain_regions = [r for r in self._terrain_regions
                                  if not (r.get("source", {}).get("agent") == agent_name and
                                          r.get("source", {}).get("spell") == spell_name)]
        # Remove spell effects from this agent's concentration spell
        effects_to_remove = []
        for effect in self.bm.active_spell_effects:
            if effect.caster_idx == agent_idx and effect.spell.name == spell_name:
                effects_to_remove.append(effect.effect_id)
        for effect_id in effects_to_remove:
            self.bm.remove_spell_effect(effect_id)
        # Clear C++ concentration state
        cond = agent.conditions
        cond.concentrating = False
        cond.concentrating_on = ""
        self.combat.set_agent_conditions(self.bm, agent_idx, cond)
        self._apply_terrain_to_battle_map()
        self._combat_log_add(f"{agent_name} drops concentration on {spell_name or 'spell'}.")
        self._save_terrain()

    def _tick_concentration_terrain(self):
        """Decrement duration on concentration terrain and remove expired effects."""
        expired_spells = []
        for region in self._terrain_regions:
            if region.get("source", {}).get("requires_concentration"):
                duration = region["source"].get("duration_remaining", 0)
                if duration > 0:
                    region["source"]["duration_remaining"] = duration - 1
                    if duration - 1 == 0:
                        expired_spells.append((region.get("source", {}).get("agent"), region.get("source", {}).get("spell")))
        # Remove expired terrain
        self._terrain_regions = [r for r in self._terrain_regions
                                  if not (r.get("source", {}).get("requires_concentration") and
                                          r.get("source", {}).get("duration_remaining", 0) <= 0)]
        # Clear concentration for agents with expired effects (C++ side)
        for agent_name, spell_name in expired_spells:
            for i, agent in enumerate(self.bm.placed_agents):
                if agent.name == agent_name:
                    if agent.conditions.concentrating and agent.conditions.concentrating_on == spell_name:
                        cond = agent.conditions
                        cond.concentrating = False
                        cond.concentrating_on = ""
                        self.combat.set_agent_conditions(self.bm, i, cond)
                        self._combat_log_add(f"{spell_name} effect on {agent_name} has expired.")
                    break
        self._apply_terrain_to_battle_map()
        self._save_terrain()

    def _combat_log_add(self, msg: str):
        self.combat_log.insert(0, msg)
        if len(self.combat_log) > 10:
            self.combat_log.pop()
        # Print to console
        print(msg)
        # Write to combat log file
        try:
            if not hasattr(self, '_combat_log_file'):
                self._combat_log_file = "combat_log.txt"
            with open(self._combat_log_file, "a") as f:
                f.write(msg + "\n")
        except Exception:
            pass  # Silently fail on file write errors

    def _flush_combat_log(self):
        """Flush messages from the combat engine logger into the combat log."""
        for msg in self.logger.flush():
            self._combat_log_add(msg)

    def _start_attack(self, slot: str):
        """Begin target-selection for an attack in the given slot."""
        idx = self._current_agent_idx()
        if idx < 0:
            return
        weapons = self.combat.get_agent_weapons(self.bm, idx)
        if not weapons:
            self._combat_log_add("No weapons equipped!")
            if slot == "action":
                self.action_used = True
            else:
                self.bonus_used = True
            return

        stats = self.combat.get_agent_stats(self.bm, idx)
        # Only seed attacks_remaining when starting a fresh sequence (== 0).
        # If mid-sequence and same slot, don't reset. If mid-sequence and different slot, reject.
        if self.attacks_remaining == 0:
            # Fresh start
            self.attacks_remaining = stats.num_attacks if slot == "action" else 1
            self._attack_sequence_slot = slot
        elif slot != self._attack_sequence_slot:
            # Can't start a different slot while attacks are pending
            return
        # print(f"[DEBUG _start_attack] idx={idx} slot={slot} stats.num_attacks={stats.num_attacks} n_atk={n_atk} attacks_remaining={self.attacks_remaining}")

        def _activate(s, wi_):
            self.pending_attack_slot = s
            self.pending_weapon_idx  = wi_
            rem = self.attacks_remaining
            # print(f"[DEBUG _activate] slot={s} weapon_idx={wi_} attacks_remaining={rem}")
            suffix = f" ({rem} attack{'s' if rem != 1 else ''} remaining)"
            self._combat_log_add(f"Click a target on the map.{suffix}")

        # Filter weapons for bonus attacks: only show off-hand weapons
        weapons_to_use = weapons
        if slot == "bonus":
            offhand_weapons = [w for w in weapons if w.off_hand]
            if offhand_weapons:
                weapons_to_use = offhand_weapons

        if len(weapons_to_use) == 1:
            # Auto-select if only one weapon (or one off-hand weapon for bonus)
            wi = next((i for i, w in enumerate(weapons) if w == weapons_to_use[0]), 0)
            _activate(slot, wi)
        else:
            options = []
            for w in weapons_to_use:
                wi = next((i for i, weapon in enumerate(weapons) if weapon == w), 0)
                def _pick(s=slot, wi_=wi):
                    _activate(s, wi_)
                options.append((w.name, _pick))
            px_popup = self._panel_x() + self._PANEL_PAD
            self.context_menu.show(
                (px_popup, 290),
                options,
                self.screen.get_size()
            )

    def _resolve_combat_attack(self, target_idx: int):
        """Resolve the pending attack against target_idx."""
        atk_idx = self._current_agent_idx()
        slot    = self.pending_attack_slot
        # print(f"[DEBUG _resolve_combat_attack ENTER] atk_idx={atk_idx} target_idx={target_idx} slot={slot} pending_weapon_idx={self.pending_weapon_idx} attacks_remaining={self.attacks_remaining}")
        if atk_idx < 0 or not slot:
            # print(f"[DEBUG _resolve_combat_attack] early return (atk_idx<0 or no slot)")
            return
        action = rpg.Attack(atk_idx, target_idx, self.pending_weapon_idx)
        action.is_offhand = (slot == "bonus")
        result = self.combat.execute_action(self.bm, action)
        # print(f"[DEBUG _resolve_combat_attack] result.valid={result.valid} result.hit={getattr(result,'hit',None)} total_damage={getattr(result,'total_damage',None)} target_down={getattr(result,'target_down',None)}")

        self._flush_combat_log()

        agents   = self.bm.placed_agents
        atk_name = agents[atk_idx].name if atk_idx < len(agents) else "?"
        tgt_name = agents[target_idx].name if target_idx < len(agents) else "?"

        if not result.valid:
            self._combat_log_add(f"{atk_name}: out of range")
            self.pending_attack_slot = ""
            self.attacks_remaining   = 0
            return

        if result.hit:
            dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            msg = (f"{atk_name}→{tgt_name}: "
                   f"HIT {result.total_damage} {dmg_type_str}"
                   f"{' CRIT!' if result.critical else ''}"
                   f"{' — DOWN' if result.target_down else ''}")
        else:
            msg = (f"{atk_name}→{tgt_name}: "
                   f"miss (roll {result.total_roll} vs AC {result.target_ac})")
        self._combat_log_add(msg)

        # Check concentration save if damage was dealt
        if result.hit and result.total_damage > 0:
            csave = self.combat.concentration_save(self.bm, target_idx, result.total_damage)
            self._flush_combat_log()
            if csave.checked:
                result_str = "HELD" if csave.passed else "BROKEN"
                self._combat_log_add(
                    f"{tgt_name}: CON concentration save — "
                    f"rolled {csave.save_d20} + {csave.con_mod} = {csave.save_d20 + csave.con_mod} "
                    f"vs DC {csave.save_dc} — {result_str}"
                )
                if csave.concentration_lost:
                    spell_name = csave.spell_name or "spell"
                    agent_name = tgt_name
                    # Remove terrain for the dropped spell
                    self._terrain_regions = [r for r in self._terrain_regions
                                              if not (r.get("source", {}).get("agent") == agent_name and
                                                      r.get("source", {}).get("spell") == spell_name)]
                    self._apply_terrain_to_battle_map()
                    self._combat_log_add(f"{agent_name} drops concentration on {spell_name}.")

        # If target is down, drop their concentration
        if result.target_down:
            self._drop_concentration_for_agent(target_idx)

        self.attacks_remaining -= 1
        if self.attacks_remaining > 0:
            # More attacks left — clear pending slot so user can move or pick another weapon
            self.pending_attack_slot = ""
            rem = self.attacks_remaining
            self._combat_log_add(
                f"{atk_name}: {rem} attack{'s' if rem != 1 else ''} remaining — move or click Attack to continue.")
        else:
            # Attacks exhausted — mark action used and clear sequence state
            self.pending_attack_slot = ""
            self._attack_sequence_slot = ""
            if slot == "action":
                self.action_used = True
            else:
                self.bonus_used = True
        # Refresh attack overlay (HP may have changed).
        self._update_attack_overlay()

    def _on_spell_done(self, agent_idx: int, spells: list[dict]):
        cpp_spells = []
        for j, d in enumerate(spells):
            cpp_spells.append(self._dict_to_spell(agent_idx, d))
            # Store all metadata for this spell (terrain, level, upcast)
            meta = {
                "terrain_effect": d.get("terrain_effect"),
                "hatch_pattern": d.get("hatch_pattern"),
                "terrain_color": d.get("terrain_color"),
                "level": d.get("level", 0),
                "upcast_dice_bonus": d.get("upcast_dice_bonus", 0),
            }
            self._spell_metadata[(agent_idx, j)] = meta
        self.combat.set_agent_spells(self.bm, agent_idx, cpp_spells)

    def _start_cast_spell(self, slot: str):
        self.jump_overlay_active = False  # Close jump overlay when casting spell
        self.jump_reachable_cells = []
        idx = self._current_agent_idx()
        if idx < 0:
            return

        # Get castable spells from C++ layer (respects both NPC and player rules)
        available_indices = self.combat.available_castable_spells(self.bm, idx)
        if not available_indices:
            self._combat_log_add("No available spells!")
            if slot == "action":
                self.action_used = True
            else:
                self.bonus_used = True
            return

        spells = self.combat.get_agent_spells(self.bm, idx)
        stats = self.combat.get_agent_stats(self.bm, idx)

        def _activate(s, si_, slot_level_=0):
            sp_ = spells[si_]
            if sp_.geometry == rpg.SpellGeometry.Single:
                self.pending_spell_is_aoe = False
                self.pending_spell_targets = []
                hint = "click a target"
            elif sp_.geometry == rpg.SpellGeometry.Multiple:
                # Multiple geometry: collect N independent targets
                num_targets = sp_.num_targets + max(0, (slot_level_ - sp_.level)) * sp_.targets_per_upcast_level
                self.pending_spell_is_aoe = False
                self.pending_spell_targets = []  # Will collect targets sequentially
                self.pending_spell_num_targets = num_targets
                hint = f"click {num_targets} target{'s' if num_targets != 1 else ''} ({0}/{num_targets})"
            else:
                # AoE (Line, Cone, Sphere, Square, Rectangle)
                self.pending_spell_is_aoe = True
                hint = "click a map location"

            self.pending_spell_slot       = s
            self.pending_spell_idx        = si_
            self.pending_spell_slot_level = slot_level_
            self._combat_log_add(f"Casting {sp_.name} — {hint}.")

        def _ordinal(n):
            return {1:"1st",2:"2nd",3:"3rd"}.get(n, f"{n}th")

        # Build spell menu from available spells
        options = []
        for si in available_indices:
            sp = spells[si]
            sp_level = sp.level

            if sp_level == 0:
                # Cantrip - always available
                def _pick_cantrip(s=slot, si_=si):
                    _activate(s, si_, 0)
                options.append((f"{sp.name} ∞", _pick_cantrip))
            else:
                # Leveled spell - check available slots for players
                if not stats.is_npc:
                    available_levels = []
                    for lvl in range(sp_level, 10):
                        if stats.spell_slots_remaining[lvl - 1] > 0:
                            available_levels.append((lvl, stats.spell_slots_remaining[lvl - 1]))

                    if not available_levels:
                        continue

                    # Add submenu for each available slot level
                    for slot_lvl, remaining in available_levels:
                        label = f"{sp.name} @ {_ordinal(slot_lvl)} ({remaining})"
                        def _pick_slot(s=slot, si_=si, sl=slot_lvl):
                            _activate(s, si_, sl)
                        options.append((label, _pick_slot))
                else:
                    # NPC: just add the spell (availability already checked by available_castable_spells)
                    def _pick_npc(s=slot, si_=si):
                        _activate(s, si_, 0)
                    options.append((sp.name, _pick_npc))

        if not options:
            self._combat_log_add("No available spells!")
            if slot == "action":
                self.action_used = True
            else:
                self.bonus_used = True
            return

        if len(options) == 1:
            options[0][1]()  # Call the action directly
        else:
            px_popup = self._panel_x() + self._PANEL_PAD
            self.context_menu.show(
                (px_popup, 290),
                options,
                self.screen.get_size()
            )

    def _get_damage_type_names(self, magic_damage_types, physical_damage_types):
        """Convert damage type enums to their string names."""
        magic_damage_names = {
            rpg.MagicDamage.Acid: "Acid",
            rpg.MagicDamage.Cold: "Cold",
            rpg.MagicDamage.Fire: "Fire",
            rpg.MagicDamage.Force: "Force",
            rpg.MagicDamage.Lightning: "Lightning",
            rpg.MagicDamage.Necrotic: "Necrotic",
            rpg.MagicDamage.Poison: "Poison",
            rpg.MagicDamage.Psychic: "Psychic",
            rpg.MagicDamage.Radiant: "Radiant",
            rpg.MagicDamage.Thunder: "Thunder",
        }

        physical_damage_names = {
            rpg.PhysicalDamage.Bludgeoning: "Bludgeoning",
            rpg.PhysicalDamage.Piercing: "Piercing",
            rpg.PhysicalDamage.Slashing: "Slashing",
        }

        names = []
        for dmg_type in physical_damage_types:
            names.append(physical_damage_names.get(dmg_type, "Unknown"))
        for dmg_type in magic_damage_types:
            names.append(magic_damage_names.get(dmg_type, "Unknown"))

        return names

    def _get_damage_modifier_names(self, spell, tgt_agent):
        """Extract damage type names from spell and target multipliers. Returns dict with modifier info."""
        # Magic damage type names
        magic_damage_names = {
            rpg.MagicDamage.Acid: "Acid",
            rpg.MagicDamage.Cold: "Cold",
            rpg.MagicDamage.Fire: "Fire",
            rpg.MagicDamage.Force: "Force",
            rpg.MagicDamage.Lightning: "Lightning",
            rpg.MagicDamage.Necrotic: "Necrotic",
            rpg.MagicDamage.Poison: "Poison",
            rpg.MagicDamage.Psychic: "Psychic",
            rpg.MagicDamage.Radiant: "Radiant",
            rpg.MagicDamage.Thunder: "Thunder",
        }

        # Physical damage type names
        physical_damage_names = {
            rpg.PhysicalDamage.Bludgeoning: "Bludgeoning",
            rpg.PhysicalDamage.Piercing: "Piercing",
            rpg.PhysicalDamage.Slashing: "Slashing",
        }

        result = {
            "immune": [],
            "vulnerable": [],
            "resistant": [],
            "damage_types": []
        }

        if not spell or not tgt_agent:
            return result

        # Collect damage types from spell with their multipliers
        for dmg_roll in spell.magic_damage_rolls:
            dmg_type_name = magic_damage_names.get(dmg_roll.type, "Unknown")
            mult = tgt_agent.stats.get_magic_damage_multiplier(int(dmg_roll.type))

            result["damage_types"].append((dmg_type_name, mult))
            if mult == 0.0:
                result["immune"].append(dmg_type_name)
            elif mult == 2.0:
                result["vulnerable"].append(dmg_type_name)
            elif mult == 0.5:
                result["resistant"].append(dmg_type_name)

        for dmg_roll in spell.physical_damage_rolls:
            dmg_type_name = physical_damage_names.get(dmg_roll.type, "Unknown")
            mult = tgt_agent.stats.get_physical_damage_multiplier(int(dmg_roll.type))

            result["damage_types"].append((dmg_type_name, mult))
            if mult == 0.0:
                result["immune"].append(dmg_type_name)
            elif mult == 2.0:
                result["vulnerable"].append(dmg_type_name)
            elif mult == 0.5:
                result["resistant"].append(dmg_type_name)

        return result

    def _get_immunity_message(self, spell, tgt_agent, tr) -> str:
        """Check if target is immune to spell damage and return immunity message, or empty string."""
        if tr.total_damage > 0 or not spell or not tgt_agent:
            return ""

        mods = self._get_damage_modifier_names(spell, tgt_agent)
        if not mods["damage_types"]:
            return ""

        # Check if target is immune to all damage types
        all_immune = len(mods["immune"]) == len(mods["damage_types"])
        if all_immune and mods["immune"]:
            immune_str = ", ".join(mods["immune"])
            return f"Immune to {immune_str}"

        return ""

    def _get_vulnerability_message(self, spell, tgt_agent, tr) -> str:
        """Check if target is vulnerable to spell damage and return message with vulnerability indicator."""
        if not spell or not tgt_agent or tr.total_damage == 0:
            return ""

        mods = self._get_damage_modifier_names(spell, tgt_agent)
        if not mods["vulnerable"]:
            return ""

        # Check if all damage types are vulnerable
        if len(mods["vulnerable"]) == len(mods["damage_types"]):
            vuln_str = ", ".join(mods["vulnerable"])
            return f"{tr.total_damage} dmg (Vulnerable to {vuln_str})"

        return ""

    def _get_resistance_message(self, spell, tgt_agent, tr) -> str:
        """Check if target is resistant to spell damage and return message with resistance indicator."""
        if not spell or not tgt_agent or tr.total_damage == 0:
            return ""

        mods = self._get_damage_modifier_names(spell, tgt_agent)
        if not mods["resistant"]:
            return ""

        # Check if all damage types are resistant
        if len(mods["resistant"]) == len(mods["damage_types"]):
            resist_str = ", ".join(mods["resistant"])
            return f"{tr.total_damage} dmg (Resistant to {resist_str})"

        return ""

    def _log_spell_results(self, result, cast_name: str, caster_idx: int = -1, spell_idx: int = -1):
        agents = self.bm.placed_agents
        spell = None
        if caster_idx >= 0 and spell_idx >= 0 and caster_idx < len(agents) and spell_idx < len(agents[caster_idx].spells):
            spell = agents[caster_idx].spells[spell_idx]

        for tr in result.target_results:
            tgt_name = agents[tr.target_idx].name if 0 <= tr.target_idx < len(agents) else "?"
            tgt_agent = agents[tr.target_idx] if 0 <= tr.target_idx < len(agents) else None

            if result.attack_type == rpg.SpellAttack.AttackRoll:
                # Check for damage modifiers in AttackRoll spells
                immunity_msg = self._get_immunity_message(spell, tgt_agent, tr)
                vuln_msg = self._get_vulnerability_message(spell, tgt_agent, tr)
                resist_msg = self._get_resistance_message(spell, tgt_agent, tr)

                modifier_suffix = ""
                if immunity_msg:
                    modifier_suffix = f" ({immunity_msg})"
                elif vuln_msg:
                    modifier_suffix = f" (Vulnerable to {', '.join(self._get_damage_modifier_names(spell, tgt_agent)['vulnerable'])})"
                elif resist_msg:
                    modifier_suffix = f" (Resistant to {', '.join(self._get_damage_modifier_names(spell, tgt_agent)['resistant'])})"

                msg = f"{cast_name}→{tgt_name}: {result.spell_name} {tr.log_message}{modifier_suffix}"
            elif result.attack_type == rpg.SpellAttack.Save:
                if spell and tgt_agent:
                    save_ability_map = {
                        rpg.SaveAbility.SaveStr: "STR",
                        rpg.SaveAbility.SaveDex: "DEX",
                        rpg.SaveAbility.SaveCon: "CON",
                        rpg.SaveAbility.SaveInt: "INT",
                        rpg.SaveAbility.SaveWis: "WIS",
                        rpg.SaveAbility.SaveCha: "CHA",
                    }
                    ability_str = save_ability_map.get(spell.save_ability, "???")
                    ability_score_map = {
                        rpg.SaveAbility.SaveStr: tgt_agent.stats.str,
                        rpg.SaveAbility.SaveDex: tgt_agent.stats.dex,
                        rpg.SaveAbility.SaveCon: tgt_agent.stats.con,
                        rpg.SaveAbility.SaveInt: tgt_agent.stats.intel,
                        rpg.SaveAbility.SaveWis: tgt_agent.stats.wis,
                        rpg.SaveAbility.SaveCha: tgt_agent.stats.cha,
                    }
                    ability_score = ability_score_map.get(spell.save_ability, 10)
                    save_prof_map = {
                        rpg.SaveAbility.SaveStr: tgt_agent.stats.save_prof_str,
                        rpg.SaveAbility.SaveDex: tgt_agent.stats.save_prof_dex,
                        rpg.SaveAbility.SaveCon: tgt_agent.stats.save_prof_con,
                        rpg.SaveAbility.SaveInt: tgt_agent.stats.save_prof_intel,
                        rpg.SaveAbility.SaveWis: tgt_agent.stats.save_prof_wis,
                        rpg.SaveAbility.SaveCha: tgt_agent.stats.save_prof_cha,
                    }
                    has_prof = save_prof_map.get(spell.save_ability, False)

                    ability_mod = (ability_score - 10) // 2
                    if ability_score < 10 and (ability_score - 10) % 2 != 0:
                        ability_mod -= 1
                    save_mod = ability_mod + (tgt_agent.stats.prof_bonus if has_prof else 0)
                    save_total = tr.save_d20 + save_mod

                    result_str = "SAVED" if tr.saved else "FAILED"
                    dmg_str = f"{tr.total_healing} heal" if tr.total_healing else f"{tr.total_damage} dmg"
                    if tr.saved and tr.total_damage > 0:
                        dmg_str = f"{tr.total_damage // 2} dmg (half)"

                    # Check for damage modifiers (immunity > vulnerability > resistance > normal)
                    immunity_msg = self._get_immunity_message(spell, tgt_agent, tr)
                    if immunity_msg:
                        dmg_str = immunity_msg
                    else:
                        vuln_msg = self._get_vulnerability_message(spell, tgt_agent, tr)
                        if vuln_msg:
                            dmg_str = vuln_msg
                        else:
                            resist_msg = self._get_resistance_message(spell, tgt_agent, tr)
                            if resist_msg:
                                dmg_str = resist_msg

                    msg = (f"{cast_name}→{tgt_name}: {ability_str} save — "
                           f"rolled {tr.save_d20} + {save_mod} = {save_total} vs DC {tr.save_dc} — "
                           f"{result_str} — {dmg_str}"
                           f"{' — DOWN' if tr.target_down else ''}")
                else:
                    saved_str = " (saved — half)" if tr.saved else ""
                    if tr.total_healing:
                        msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                               f"HEAL {tr.total_healing}{saved_str}")
                    else:
                        # Check for damage modifiers (immunity > vulnerability > resistance > normal)
                        immunity_msg = self._get_immunity_message(spell, tgt_agent, tr)
                        if immunity_msg:
                            dmg_text = immunity_msg
                        else:
                            vuln_msg = self._get_vulnerability_message(spell, tgt_agent, tr)
                            if vuln_msg:
                                dmg_text = f"{vuln_msg}{saved_str}"
                            else:
                                resist_msg = self._get_resistance_message(spell, tgt_agent, tr)
                                if resist_msg:
                                    dmg_text = f"{resist_msg}{saved_str}"
                                else:
                                    dmg_text = f"{tr.total_damage} dmg{saved_str}"
                        msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                               f"{dmg_text}"
                               f"{' — DOWN' if tr.target_down else ''}")
            else:  # Automatic
                if tr.total_healing:
                    msg = f"{cast_name}→{tgt_name}: {result.spell_name} HEAL {tr.total_healing}"
                else:
                    # Check for damage modifiers (immunity > vulnerability > resistance > normal)
                    immunity_msg = self._get_immunity_message(spell, tgt_agent, tr)
                    if immunity_msg:
                        dmg_text = immunity_msg
                    else:
                        vuln_msg = self._get_vulnerability_message(spell, tgt_agent, tr)
                        if vuln_msg:
                            dmg_text = vuln_msg
                        else:
                            resist_msg = self._get_resistance_message(spell, tgt_agent, tr)
                            if resist_msg:
                                dmg_text = resist_msg
                            else:
                                dmg_text = f"{tr.total_damage} dmg"
                    msg = (f"{cast_name}→{tgt_name}: {result.spell_name} "
                           f"{dmg_text}"
                           f"{' — DOWN' if tr.target_down else ''}")
            self._combat_log_add(msg)

    def _on_long_rest(self):
        """Reset all spell slots and NPC spell uses to their maximum values."""
        agents = self.bm.placed_agents
        for idx in range(len(agents)):
            stats = self.combat.get_agent_stats(self.bm, idx)
            stats.restore_spell_slots()
            self.combat.set_agent_stats(self.bm, idx, stats)
            # Reset NPC spell uses: copy uses_max back to uses_remaining
            if idx in self._agent_meta:
                spells = self.combat.get_agent_spells(self.bm, idx)
                for spell in spells:
                    if spell.uses_max > 0:
                        spell.uses_remaining = spell.uses_max
        if self.combat_active:
            self._combat_log_add("Long rest — all spell slots and daily spells restored.")

    def _process_opportunity_queue(self):
        """Process one opportunity attack from the queue, then chain to the next."""
        if not self._opportunity_queue:
            # Queue is empty - if there's a pending move, complete it now
            if self.pending_move_idx >= 0:
                self._complete_pending_move()
            return
        attacker_idx, target_idx = self._opportunity_queue[0]
        agents = self.bm.placed_agents
        if attacker_idx >= len(agents) or target_idx >= len(agents):
            self._opportunity_queue.pop(0)
            self._process_opportunity_queue()
            return
        atk_name = agents[attacker_idx].name
        tgt_name = agents[target_idx].name
        self._combat_log_add(f"{atk_name} gets opportunity attack vs {tgt_name}!")

        options = []
        # Weapon options - melee only
        for wi, w in enumerate(agents[attacker_idx].weapons):
            if w.type != rpg.WeaponType.Melee:
                continue
            def _atk(ai=attacker_idx, ti=target_idx, widx=wi):
                action = rpg.Attack(ai, ti, widx)
                result = self.combat.execute_action(self.bm, action)
                self._flush_combat_log()
                self.bm.placed_agents[ai].conditions.reaction_used = True
                self._log_opportunity_result(ai, ti, result)
                self._check_concentration_after_oa(ti, result)
                self._update_attack_overlay()
                self._opportunity_queue.pop(0)
                self._process_opportunity_queue()
            options.append((f"[Weapon] {w.name}", _atk))

        # Spell options - single-target only
        for si, sp in enumerate(agents[attacker_idx].spells):
            # Only offer single-target spells
            if sp.geometry != rpg.SpellGeometry.Single:
                continue
            def _spl(ai=attacker_idx, ti=target_idx, sidx=si):
                action = rpg.SpellAction()
                action.caster_idx = ai
                action.spell_idx = sidx
                action.target_indices = [ti]
                result = self.combat.execute_spell(self.bm, action)
                self._flush_combat_log()
                self.bm.placed_agents[ai].conditions.reaction_used = True
                cast_name = self.bm.placed_agents[ai].name
                self._log_spell_results(result, cast_name, ai, sidx)
                self._update_attack_overlay()
                self._opportunity_queue.pop(0)
                self._process_opportunity_queue()
            options.append((f"[Spell] {sp.name}", _spl))

        # Skip option
        def _skip():
            self._opportunity_queue.pop(0)
            self._process_opportunity_queue()
        options.append(("Skip", _skip))

        px, py = self._agent_screen_pos(attacker_idx)
        self.context_menu.show((px, py), options, self.screen.get_size())

    def _log_opportunity_result(self, atk_idx: int, tgt_idx: int, result):
        """Log weapon-based opportunity attack result."""
        agents = self.bm.placed_agents
        atk_name = agents[atk_idx].name if atk_idx < len(agents) else "?"
        tgt_name = agents[tgt_idx].name if tgt_idx < len(agents) else "?"
        if not result.valid:
            self._combat_log_add(f"{atk_name}: OA — out of range")
            return
        if result.hit:
            dmg_parts = self._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            self._combat_log_add(
                f"{atk_name}→{tgt_name}: OA HIT {result.total_damage} {dmg_type_str}"
                f"{' CRIT!' if result.critical else ''}"
                f"{' — DOWN' if result.target_down else ''}")
        else:
            self._combat_log_add(
                f"{atk_name}→{tgt_name}: OA miss (roll {result.total_roll} vs AC {result.target_ac})")

    def _check_concentration_after_oa(self, tgt_idx: int, result):
        """Check concentration save after OA damage (weapon only)."""
        if result.hit and result.total_damage > 0:
            agents = self.bm.placed_agents
            tgt_name = agents[tgt_idx].name if tgt_idx < len(agents) else "?"
            csave = self.combat.concentration_save(self.bm, tgt_idx, result.total_damage)
            self._flush_combat_log()
            if csave.checked:
                result_str = "HELD" if csave.passed else "BROKEN"
                self._combat_log_add(
                    f"{tgt_name}: CON concentration save — "
                    f"rolled {csave.save_d20} + {csave.con_mod} = {csave.save_d20 + csave.con_mod} "
                    f"vs DC {csave.save_dc} — {result_str}")
                if csave.concentration_lost:
                    spell_name = csave.spell_name or "spell"
                    self._terrain_regions = [r for r in self._terrain_regions
                                             if not (r.get("source", {}).get("agent") == tgt_name and
                                                     r.get("source", {}).get("spell") == spell_name)]
                    self._apply_terrain_to_battle_map()
                    self._combat_log_add(f"{tgt_name} drops concentration on {spell_name}.")

    def _sync_spell_effect_cache(self):
        """Remove cache entries for spell effects that have been removed in C++."""
        active_effect_ids = {effect.effect_id for effect in self.bm.active_spell_effects}
        to_remove = [eid for eid in self._effect_meta if eid not in active_effect_ids]
        for eid in to_remove:
            del self._effect_meta[eid]

    def _agent_screen_pos(self, agent_idx: int) -> tuple:
        """Get screen position of agent for context menu anchor."""
        agents = self.bm.placed_agents
        if agent_idx >= len(agents):
            return (100, 100)
        ag = agents[agent_idx]
        cpx = int(self.bm.cell_pixel_size)
        x = ag.origin.col * cpx + cpx // 2
        y = ag.origin.row * cpx + cpx // 2
        return (x, y)

    def _complete_pending_move(self):
        """Complete a move that was pending while OA resolved."""
        if self.pending_move_idx < 0:
            return
        move_idx = self.pending_move_idx
        move_cell = self.pending_move_cell
        move_type = self.pending_move_type
        self.pending_move_idx = -1
        self.pending_move_cell = None
        self.pending_move_type = None

        agents = self.bm.placed_agents
        move_success = self.combat.move_agent(self.bm, move_idx, move_cell, move_type)
        self._flush_combat_log()  # Flush any spell effect damage messages
        if move_success:
            ag = agents[move_idx]
            self.move_remaining_walk = ag.walk_remaining
            self.move_remaining_fly = ag.fly_remaining
            self.move_remaining_swim = ag.swim_remaining
            self.move_remaining_burrow = ag.burrow_remaining
            self._combat_log_add(f"{ag.name} completes movement to ({ag.origin.col},{ag.origin.row}).")
            self._update_reach()
            self._update_attack_overlay()
        else:
            self._combat_log_add(f"{agents[move_idx].name if move_idx < len(agents) else '?'}: movement blocked")

    def _resolve_spell_cast(self, target_idx: int):
        caster_idx = self._current_agent_idx()
        slot       = self.pending_spell_slot
        if caster_idx < 0 or not slot:
            return

        spells_orig = self.combat.get_agent_spells(self.bm, caster_idx)
        sp = spells_orig[self.pending_spell_idx]

        # For Multiple geometry spells, collect targets until we have enough
        if sp.geometry == rpg.SpellGeometry.Multiple:
            self.pending_spell_targets.append(target_idx)

            targets_collected = len(self.pending_spell_targets)
            targets_needed = self.pending_spell_num_targets

            if targets_collected < targets_needed:
                # Still collecting targets
                self._combat_log_add(f"Target selected ({targets_collected}/{targets_needed})")
                return
            # else: we have all targets, fall through to execute

        action = rpg.SpellAction()
        action.caster_idx     = caster_idx
        action.spell_idx      = self.pending_spell_idx
        action.slot_level     = self.pending_spell_slot_level
        action.target_indices = self.pending_spell_targets if sp.geometry == rpg.SpellGeometry.Multiple else [target_idx]
        result = self.combat.execute_spell(self.bm, action)

        self._flush_combat_log()

        self.pending_spell_slot        = ""
        self.pending_spell_is_aoe      = False
        self.pending_spell_num_targets = 0
        self.pending_spell_targets     = []
        self.pending_spell_targets     = []
        self.spell_hover_cell          = None

        agents    = self.bm.placed_agents
        cast_name = agents[caster_idx].name if caster_idx < len(agents) else "?"
        if not result.valid:
            self._combat_log_add(f"{cast_name}: spell failed (invalid)")
            return
        self._log_spell_results(result, cast_name, caster_idx, self.pending_spell_idx)
        # Clear spell effect cache entries for any removed effects (e.g., from concentration loss)
        self._sync_spell_effect_cache()
        if slot == "action":
            self.action_used = True
        else:
            self.bonus_used = True

    def _resolve_spell_cast_aoe(self, cell):
        caster_idx = self._current_agent_idx()
        slot       = self.pending_spell_slot
        if caster_idx < 0 or not slot:
            return

        spells_orig = self.combat.get_agent_spells(self.bm, caster_idx)
        sp = spells_orig[self.pending_spell_idx]

        action = rpg.SpellAction()
        action.caster_idx     = caster_idx
        action.spell_idx      = self.pending_spell_idx
        action.slot_level     = self.pending_spell_slot_level
        action.target_indices = []
        action.aoe_col        = cell.col
        action.aoe_row        = cell.row
        result = self.combat.execute_spell(self.bm, action)

        self._flush_combat_log()

        self.pending_spell_slot       = ""
        self.pending_spell_is_aoe     = False
        self.pending_spell_num_targets = 0
        self.spell_hover_cell         = None

        agents    = self.bm.placed_agents
        cast_name = agents[caster_idx].name if caster_idx < len(agents) else "?"
        if not result.valid:
            self._combat_log_add(f"{cast_name}: spell failed (invalid)")
            return
        if not result.target_results:
            self._combat_log_add(f"{cast_name}: {result.spell_name} — no targets in area")
        else:
            self._log_spell_results(result, cast_name, caster_idx, self.pending_spell_idx)
            # Clear spell effect cache entries for any removed effects (e.g., from concentration loss)
            self._sync_spell_effect_cache()

        # Auto-place terrain effect if spell has one
        if 0 <= caster_idx < len(agents) and 0 <= self.pending_spell_idx < len(agents[caster_idx].spells):
            spell = agents[caster_idx].spells[self.pending_spell_idx]
            # Get terrain_effect and hatch_pattern from metadata
            spell_meta = self._spell_metadata.get((caster_idx, self.pending_spell_idx), {})
            terrain_effect = spell_meta.get("terrain_effect")
            hatch_pattern = spell_meta.get("hatch_pattern")
            if terrain_effect:
                aoe_cells_raw = self._aoe_cells(cell, spell)
                aoe_cells = self._filter_spell_cells_by_range_and_los(aoe_cells_raw, caster_idx, spell, center_cell=cell)
                if aoe_cells:
                    terrain_region = self._cells_to_terrain_region(aoe_cells, terrain_effect, spell.name, caster_idx, hatch_pattern, self.pending_spell_idx)
                    if terrain_region:
                        # Handle concentration replacement: remove old spell's terrain if one was dropped
                        if result.concentration_replaced and result.prev_concentration_spell:
                            agent_name = cast_name
                            self._terrain_regions = [r for r in self._terrain_regions
                                                      if not (r.get("source", {}).get("agent") == agent_name and
                                                              r.get("source", {}).get("spell") == result.prev_concentration_spell)]
                            self._combat_log_add(f"{cast_name} drops concentration on {result.prev_concentration_spell}.")

                        self._terrain_regions.append(terrain_region)
                        self._apply_terrain_to_battle_map()
                        if spell.requires_concentration:
                            self._combat_log_add(f"{spell.name}: {cast_name} is concentrating.")
            elif spell.terrain_difficulty != rpg.TerrainDifficulty.Normal:
                aoe_cells = self._aoe_cells(cell, spell)
                if aoe_cells:
                    effect_id = self.bm.place_terrain_effect(
                        spell.name,
                        aoe_cells,
                        spell.terrain_difficulty,
                        spell.duration,
                        caster_idx
                    )
                    if effect_id >= 0:
                        # Store metadata for rendering
                        if spell.terrain_difficulty == rpg.TerrainDifficulty.Halved:
                            color = (80, 200, 80, 80)  # Green
                        elif spell.terrain_difficulty == rpg.TerrainDifficulty.Quartered:
                            color = (200, 60, 60, 80)  # Red
                        else:
                            color = (100, 180, 220, 80)  # Cyan
                        self._effect_meta[effect_id] = {
                            "name": spell.name,
                            "color": color,
                            "cells": [(c.col, c.row) for c in aoe_cells]
                        }
                        self._combat_log_add(f"{spell.name} terrain effect placed.")

        if slot == "action":
            self.action_used = True
        else:
            self.bonus_used = True

    def _aoe_cells(self, center_cell, spell) -> list:
        """Return list of rpg.Cell objects covered by the spell AoE (1 cell = 5 ft)."""
        import math
        geo   = spell.geometry
        cols  = self.bm.grid_cols
        rows  = self.bm.grid_rows
        cells = []
        ax = float(center_cell.col)
        ay = float(center_cell.row)

        if geo == rpg.SpellGeometry.Sphere:
            r_cells = spell.radius / 5.0
            for c in range(cols):
                for r in range(rows):
                    dx, dy = c - ax, r - ay
                    if math.sqrt(dx*dx + dy*dy) <= r_cells:
                        cells.append(rpg.Cell(c, r))

        elif geo == rpg.SpellGeometry.Cone:
            caster_idx = self._current_agent_idx()
            if caster_idx < 0:
                return cells
            cp = self.bm.placed_agents[caster_idx].origin
            cx, cy = float(cp.col), float(cp.row)
            dx, dy = ax - cx, ay - cy
            ln = math.sqrt(dx*dx + dy*dy)
            if ln < 0.001:
                return cells
            ux, uy = dx/ln, dy/ln
            r_cells = spell.radius / 5.0
            for c in range(cols):
                for r in range(rows):
                    px, py = c - cx, r - cy
                    plen = math.sqrt(px*px + py*py)
                    if plen < 0.001:
                        continue
                    dot = px*ux + py*uy
                    if dot > 0 and plen <= r_cells and (dot/plen) >= 0.866:
                        cells.append(rpg.Cell(c, r))

        elif geo == rpg.SpellGeometry.Line:
            caster_idx = self._current_agent_idx()
            if caster_idx < 0:
                return cells
            cp = self.bm.placed_agents[caster_idx].origin
            cx, cy = float(cp.col), float(cp.row)
            dx, dy = ax - cx, ay - cy
            ln = math.sqrt(dx*dx + dy*dy)
            if ln < 0.001:
                return cells
            ux, uy = dx/ln, dy/ln
            l_cells = spell.length / 5.0
            w_cells = spell.width  / 5.0
            for c in range(cols):
                for r in range(rows):
                    px, py = c - cx, r - cy
                    along = px*ux + py*uy
                    perp  = abs(-py*ux + px*uy)
                    if 0.0 <= along <= l_cells and perp <= w_cells / 2.0:
                        cells.append(rpg.Cell(c, r))

        elif geo == rpg.SpellGeometry.Square or geo == rpg.SpellGeometry.Rectangle:
            w_cells = spell.width  / 5.0
            l_cells = spell.length / 5.0
            for c in range(cols):
                for r in range(rows):
                    dx, dy = abs(c - ax), abs(r - ay)
                    if dx <= w_cells / 2.0 and dy <= l_cells / 2.0:
                        cells.append(rpg.Cell(c, r))

        return cells

    def _filter_spell_cells_by_range_and_los(self, cells: list, caster_idx: int, spell, center_cell=None) -> list:
        """Filter cells using C++ method that respects spell's requires_los and check_los_on_center flags."""
        if caster_idx < 0 or caster_idx >= len(self.bm.placed_agents):
            return cells
        if not center_cell:
            return cells

        caster = self.bm.placed_agents[caster_idx]
        return self.bm.filter_spell_cells(cells, caster.origin, caster.size, spell, center_cell)

    def _cells_to_terrain_region(self, cells: list, terrain_effect: dict, spell_name: str, caster_idx: int, hatch_pattern: str = None, spell_idx: int = -1) -> dict:
        """Convert list of cells to a terrain region with source metadata."""
        if not cells:
            return None
        caster_name = self.bm.placed_agents[caster_idx].name if caster_idx < len(self.bm.placed_agents) else "Unknown"
        return {
            "type": terrain_effect.get("type", "Difficult Terrain"),
            "cells": [(c.col, c.row) for c in cells],  # Store actual affected cells
            "multiplier": terrain_effect.get("multiplier", 0.5),
            "source": {
                "agent": caster_name,
                "caster": caster_idx,
                "spell": spell_name,
                "spell_idx": spell_idx,
                "requires_concentration": True,
                "duration_remaining": terrain_effect.get("duration", 10),
            },
            "hatch_pattern": hatch_pattern
        }

    def _draw_spell_aoe_preview(self, cpx: int):
        """Translucent AoE highlight while the player is aiming a non-Single spell."""
        if not self.pending_spell_is_aoe or self.spell_hover_cell is None:
            return
        caster_idx = self._current_agent_idx()
        if caster_idx < 0:
            return
        spells = self.combat.get_agent_spells(self.bm, caster_idx)
        if not (0 <= self.pending_spell_idx < len(spells)):
            return
        sp    = spells[self.pending_spell_idx]
        aoe_cells = self._aoe_cells(self.spell_hover_cell, sp)
        # Filter by spell range and line of sight
        cells = self._filter_spell_cells_by_range_and_los(aoe_cells, caster_idx, sp, center_cell=self.spell_hover_cell)

        fill_s   = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        fill_s.fill((160, 80, 220, 60))
        border_s = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
        pygame.draw.rect(border_s, (200, 130, 255, 160), border_s.get_rect(), 1)

        # Only render cells that fall within the map viewport
        map_w, map_h = self.map_rect.width, self.map_rect.height
        cell_set = {(c.col, c.row) for c in cells}
        for c in cells:
            sx, sy = self._cell_to_screen(c.col, c.row)
            # Skip cells whose rendered area extends beyond the map
            if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                continue
            self.screen.blit(fill_s,   (sx, sy))
            self.screen.blit(border_s, (sx, sy))

        # Orange ring around each agent caught in the blast
        for pt in self.bm.placed_agents:
            if (pt.origin.col, pt.origin.row) in cell_set:
                size_px = cpx * pt.size
                sx, sy  = self._cell_to_screen(pt.origin.col, pt.origin.row)
                pygame.draw.rect(self.screen, (255, 140, 0),
                                 pygame.Rect(sx, sy, size_px, size_px), 3,
                                 border_radius=3)

        # Bright white outline on the aimed cell
        ax, ay = self._cell_to_screen(self.spell_hover_cell.col,
                                      self.spell_hover_cell.row)
        pygame.draw.rect(self.screen, (255, 255, 255),
                         pygame.Rect(ax, ay, cpx, cpx), 2)

        # Draw spell range circle (thin line showing max range from caster)
        caster = self.bm.placed_agents[caster_idx]
        range_cells = sp.range / 5
        range_px = range_cells * cpx
        caster_sx, caster_sy = self._cell_to_screen(caster.origin.col, caster.origin.row)
        caster_center_x = caster_sx + (caster.size * cpx) / 2
        caster_center_y = caster_sy + (caster.size * cpx) / 2
        pygame.draw.circle(self.screen, (100, 150, 255, 100),
                          (int(caster_center_x), int(caster_center_y)),
                          int(range_px), 1)

    def _draw_attack_overlays(self, cpx: int):
        """Draw melee / ranged-normal / ranged-long attack-range overlays."""
        map_w, map_h = self.map_rect.width, self.map_rect.height
        def _draw_zone(cells, fill_rgba, border_rgba):
            if not cells:
                return
            fill_s   = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fill_s.fill(fill_rgba)
            border_s = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_s, border_rgba, border_s.get_rect(), 1)
            for cell in cells:
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                # Skip cells whose rendered area extends beyond the map
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(fill_s,   (sx, sy))
                self.screen.blit(border_s, (sx, sy))

        # Melee: warm red
        _draw_zone(self._attack_cells_melee, (200, 55, 55, 70), (255, 100, 100, 150))
        # Ranged normal: orange
        _draw_zone(self._attack_cells_rnorm, (200, 120, 40, 55), (255, 165, 60, 130))
        # Ranged long (disadvantage): dull yellow
        _draw_zone(self._attack_cells_rlong, (180, 165, 40, 35), (220, 200, 60, 90))

    def _spell_to_dict(self, agent_idx: int, spell_idx: int, s) -> dict:
        """Convert C++ Spell object to dict, including metadata."""
        geo = s.geometry.name
        uses_radius = geo in ("Sphere", "Cone")
        uses_line   = geo == "Line"
        metadata = self._spell_metadata.get((agent_idx, spell_idx), {})

        # Convert magic_damage_rolls to dict format
        magic_dmg = []
        for roll in s.magic_damage_rolls:
            magic_dmg.append({
                "type": roll.type.name,
                "num_dice": roll.num_dice,
                "die_size": roll.die_size
            })

        # Convert physical_damage_rolls to dict format
        phys_dmg = []
        for roll in s.physical_damage_rolls:
            phys_dmg.append({
                "type": roll.type.name,
                "num_dice": roll.num_dice,
                "die_size": roll.die_size
            })

        return {
            "name":                  s.name,
            "type":                  s.type.name,
            "geometry":              geo,
            "attack_type":           s.attack_type.name,
            "save_ability":          s.save_ability.name if s.attack_type == rpg.SpellAttack.Save else None,
            "range":                 s.range,
            "radius":                s.radius if uses_radius else None,
            "width":                 s.width  if uses_line   else None,
            "length":                s.length if uses_line   else None,
            "duration":              s.duration,
            "magic_damage_types":    magic_dmg,
            "physical_damage_types": phys_dmg,
            "terrain_effect":        metadata.get("terrain_effect"),
            "hatch_pattern":         metadata.get("hatch_pattern"),
            "terrain_color":         metadata.get("terrain_color"),
            "level":                 s.level,
            "upcast_dice_bonus":     s.upcast_dice_bonus,
            "requires_concentration": s.requires_concentration,
        }

    def _dict_to_spell(self, agent_idx: int, d: dict):
        """Convert dict to C++ Spell, storing metadata separately."""
        s = rpg.Spell()
        s.name         = d.get("name",         "Unnamed Spell")
        s.type         = getattr(rpg.SpellType,     d.get("type",         "Harm"),     rpg.SpellType.Harm)
        s.geometry     = getattr(rpg.SpellGeometry, d.get("geometry",     "Single"),   rpg.SpellGeometry.Single)
        s.attack_type  = getattr(rpg.SpellAttack,   d.get("attack_type",  "AttackRoll"), rpg.SpellAttack.AttackRoll)
        s.save_ability = getattr(rpg.SaveAbility,   d.get("save_ability") or "SaveDex", rpg.SaveAbility.SaveDex)
        s.range        = int(d.get("range")  or 30)
        s.radius       = int(d.get("radius") or 10)
        s.width        = int(d.get("width")  or  5)
        s.length       = int(d.get("length") or 30)
        s.duration     = int(d.get("duration",   1))

        # Parse magic damage types - handle both new (object) and old (string) formats
        magic_dmg_raw = d.get("magic_damage_types", [])
        magic_rolls = []
        for dmg in magic_dmg_raw:
            if isinstance(dmg, dict):
                # New format: {"type": "Fire", "num_dice": 2, "die_size": 6, "bonus": 1}
                dmg_type = _parse_magic_damage(dmg.get("type", "Fire"))
                roll = rpg.MagicDamageRoll()
                roll.type = dmg_type
                roll.num_dice = int(dmg.get("num_dice", 1))
                roll.die_size = int(dmg.get("die_size", 6))
                roll.bonus = int(dmg.get("bonus", 0))
                magic_rolls.append(roll)
            else:
                # Old format: just the string "Fire"
                dmg_type = _parse_magic_damage(dmg)
                roll = rpg.MagicDamageRoll()
                roll.type = dmg_type
                roll.num_dice = int(d.get("num_dice", 1))
                roll.die_size = int(d.get("die_size", 6))
                roll.bonus = int(d.get("bonus", 0))
                magic_rolls.append(roll)
        s.magic_damage_rolls = magic_rolls

        # Parse physical damage types - handle both new (object) and old (string) formats
        phys_dmg_raw = d.get("physical_damage_types", [])
        phys_rolls = []
        for dmg in phys_dmg_raw:
            if isinstance(dmg, dict):
                # New format: {"type": "Slashing", "num_dice": 1, "die_size": 8, "bonus": 0}
                dmg_type = _parse_physical_damage(dmg.get("type", "Bludgeoning"))
                roll = rpg.PhysicalDamageRoll()
                roll.type = dmg_type
                roll.num_dice = int(dmg.get("num_dice", 1))
                roll.die_size = int(dmg.get("die_size", 6))
                roll.bonus = int(dmg.get("bonus", 0))
                phys_rolls.append(roll)
            else:
                # Old format: just the string "Slashing"
                dmg_type = _parse_physical_damage(dmg)
                roll = rpg.PhysicalDamageRoll()
                roll.type = dmg_type
                roll.num_dice = int(d.get("num_dice", 1))
                roll.die_size = int(d.get("die_size", 6))
                roll.bonus = int(d.get("bonus", 0))
                phys_rolls.append(roll)
        s.physical_damage_rolls = phys_rolls

        s.requires_concentration = d.get("requires_concentration", False)
        s.requires_los = d.get("requires_los", False)
        s.check_los_on_center = d.get("check_los_on_center", True)
        s.level = int(d.get("level", 0))
        s.upcast_dice_bonus = int(d.get("upcast_dice_bonus", 0))
        s.num_targets = int(d.get("num_targets", 1))
        s.targets_per_upcast_level = int(d.get("targets_per_upcast_level", 0))
        s.effects_on_begin_turn = d.get("effects_on_begin_turn", True)
        s.effects_on_end_turn = d.get("effects_on_end_turn", False)
        return s

    def _save_agents(self, path: str | None = None):
        path = path or self._save_path
        data = []
        for i, pt in enumerate(self.bm.placed_agents):
            s = self.combat.get_agent_stats(self.bm, i)
            # Save only the filename, not the full path, for portability
            sprite_filename = os.path.basename(pt.sprite_path) if pt.sprite_path else ""
            data.append({
                "name":        pt.name,
                "sprite_path": sprite_filename,
                "size":        pt.size,
                "col":         pt.origin.col,
                "row":         pt.origin.row,
                "stats": {
                    "str": s.str, "dex": s.dex, "con": s.con,
                    "intel": s.intel, "wis": s.wis, "cha": s.cha,
                    "hp_max": s.hp_max, "hp_cur": s.hp_cur,
                    "ac": s.base_ac,
                    "speed_walk": s.speed_walk, "speed_swim": s.speed_swim,
                    "speed_fly":  s.speed_fly,  "speed_burrow": s.speed_burrow,
                    "prof_bonus": s.prof_bonus,
                    "save_prof_str":   s.save_prof_str,
                    "save_prof_dex":   s.save_prof_dex,
                    "save_prof_con":   s.save_prof_con,
                    "save_prof_intel": s.save_prof_intel,
                    "save_prof_wis":   s.save_prof_wis,
                    "save_prof_cha":      s.save_prof_cha,
                    "num_attacks":        s.num_attacks,
                    "has_cunning_action": s.has_cunning_action,
                    "has_offhand_attack": s.has_offhand_attack,
                    "spellcasting_ability": _INT_TO_ABILITY.get(s.spellcasting_ability, "cha"),
                },
                "weapons": {
                    "main_hand": self.combat.get_agent_weapons(self.bm, i)[0].name or "",
                    "off_hand": self.combat.get_agent_weapons(self.bm, i)[1].name or "",
                    "ranged": self.combat.get_agent_weapons(self.bm, i)[2].name or "",
                },
                "armor": {
                    "helmet": self.combat.get_agent_armor(self.bm, i)[0].name or "",
                    "chest": self.combat.get_agent_armor(self.bm, i)[1].name or "",
                    "leggings": self.combat.get_agent_armor(self.bm, i)[2].name or "",
                    "boots": self.combat.get_agent_armor(self.bm, i)[3].name or "",
                    "gloves": self.combat.get_agent_armor(self.bm, i)[4].name or "",
                    "cloak": self.combat.get_agent_armor(self.bm, i)[5].name or "",
                },
                "spell_indices": [s.name
                                  for s in self.combat.get_agent_spells(self.bm, i)],
                "agent_class":      s.character_class.name,
                "agent_char_level": s.char_level,
                "spell_slots_max":  list(s.spell_slots_max),
                "spell_slots_cur":  list(s.spell_slots_remaining),
            })
            # Add NPC data if this agent is an NPC
            if i in self._agent_meta:
                meta = self._agent_meta[i]
                data[-1]["is_npc"] = meta.get("is_npc", False)
                data[-1]["npc_spell_groups"] = meta.get("npc_spell_groups", {})
                # Save current uses_remaining from each spell
                npc_uses = {}
                spells = self.combat.get_agent_spells(self.bm, i)
                for spell in spells:
                    if spell.uses_max > 0:  # Only save if this is an N/day spell
                        npc_uses[spell.name] = spell.uses_remaining
                data[-1]["npc_spell_uses_cur"] = npc_uses
        with open(path, "w") as f:
            json.dump({"agents": data}, f, indent=2)

    def _load_agents(self, path: str | None = None):
        path = path or self._save_path
        if not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"\n{'='*60}")
            print(f"ERROR: Agents file corrupted: {path}")
            print(f"Details: {e}")
            print(f"\nFix: Delete the corrupted file and start fresh:")
            print(f"  rm \"{path}\"")
            print(f"Then reload the map.")
            print(f"{'='*60}\n")
            return
        self.bm.clear_agents()
        self.pending_configs.clear()
        self.selected_idx = -1
        self.drag_idx     = -1
        self._spell_metadata.clear()
        agent_data = data.get("agents", [])
        for t in agent_data:
            cfg = rpg.AgentConfig()
            cfg.name        = t["name"]
            # Resolve sprite path relative to sprites directory
            sprite_filename = t.get("sprite_path", "")
            cfg.sprite_path = os.path.join(self.sprites_dir, sprite_filename) if sprite_filename else ""
            cfg.size        = t["size"]
            cfg.start_col   = t["col"]
            cfg.start_row   = t["row"]
            self.combat.add_agent_config(self.bm, cfg)
            self.pending_configs.append(cfg)
        self.combat.apply_agent_configs(self.bm)
        self.sprites.clear()
        # Restore stats for each placed agent
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            sd = t.get("stats")
            if not sd:
                continue
            s = rpg.Stats()
            s.str = int(sd.get("str", 10))
            s.dex = int(sd.get("dex", 10))
            s.con = int(sd.get("con", 10))
            s.intel = int(sd.get("intel", 10))
            s.wis = int(sd.get("wis", 10))
            s.cha = int(sd.get("cha", 10))
            s.hp_max = int(sd.get("hp_max", 10))
            s.hp_cur = int(sd.get("hp_cur", s.hp_max))
            s.base_ac = int(sd.get("ac", 10))
            s.speed_walk = int(sd.get("speed_walk", 30))
            s.speed_fly = int(sd.get("speed_fly", 0))
            s.speed_swim = int(sd.get("speed_swim", 0))
            s.speed_burrow = int(sd.get("speed_burrow", 0))
            s.prof_bonus = int(sd.get("prof_bonus", 2))
            s.num_attacks = int(sd.get("num_attacks", 1))
            s.save_prof_str = bool(sd.get("save_prof_str", False))
            s.save_prof_dex = bool(sd.get("save_prof_dex", False))
            s.save_prof_con = bool(sd.get("save_prof_con", False))
            s.save_prof_intel = bool(sd.get("save_prof_intel", False))
            s.save_prof_wis = bool(sd.get("save_prof_wis", False))
            s.save_prof_cha = bool(sd.get("save_prof_cha", False))
            if "spellcasting_ability" in sd:
                ability_val = sd["spellcasting_ability"]
                if isinstance(ability_val, str):
                    ability_map = {"str": 0, "dex": 1, "con": 2, "intel": 3, "wis": 4, "cha": 5}
                    s.spellcasting_ability = ability_map.get(ability_val, 5)
                else:
                    s.spellcasting_ability = int(ability_val) if ability_val else 5

            # Load temporary HP and damage multipliers
            s.temp_hp = int(sd.get("temp_hp", 0))

            # Load magic damage multipliers (resistances/immunities/vulnerabilities)
            magic_damage_names = ["Acid", "Cold", "Fire", "Force", "Lightning", "Necrotic", "Poison", "Psychic", "Radiant", "Thunder"]
            for idx in range(len(magic_damage_names)):
                s.set_magic_damage_multiplier(idx, 1.0)  # default: normal damage

            for res in sd.get("magic_resistances", []):
                if res in magic_damage_names:
                    idx = magic_damage_names.index(res)
                    s.set_magic_damage_multiplier(idx, 0.5)
            for imm in sd.get("magic_immunities", []):
                if imm in magic_damage_names:
                    idx = magic_damage_names.index(imm)
                    s.set_magic_damage_multiplier(idx, 0.0)
            for vuln in sd.get("magic_vulnerabilities", []):
                if vuln in magic_damage_names:
                    idx = magic_damage_names.index(vuln)
                    s.set_magic_damage_multiplier(idx, 2.0)

            # Load physical damage multipliers
            physical_damage_names = ["Bludgeoning", "Piercing", "Slashing"]
            for idx in range(len(physical_damage_names)):
                s.set_physical_damage_multiplier(idx, 1.0)  # default: normal damage

            for res in sd.get("physical_resistances", []):
                if res in physical_damage_names:
                    idx = physical_damage_names.index(res)
                    s.set_physical_damage_multiplier(idx, 0.5)
            for imm in sd.get("physical_immunities", []):
                if imm in physical_damage_names:
                    idx = physical_damage_names.index(imm)
                    s.set_physical_damage_multiplier(idx, 0.0)
            for vuln in sd.get("physical_vulnerabilities", []):
                if vuln in physical_damage_names:
                    idx = physical_damage_names.index(vuln)
                    s.set_physical_damage_multiplier(idx, 2.0)

            self.combat.set_agent_stats(self.bm, i, s)

        # Restore weapons — load from weapons dict (slot format) or legacy formats
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            cpp_weapons = [rpg.Weapon(), rpg.Weapon(), rpg.Weapon()]  # 3 slots: main, off, ranged

            # Try new weapons dict format first (slot names -> weapon names)
            weapons_dict = t.get("weapons", {})
            if weapons_dict and isinstance(weapons_dict, dict):
                slot_names = ["main_hand", "off_hand", "ranged"]
                for slot_idx, slot_name in enumerate(slot_names):
                    weapon_name = weapons_dict.get(slot_name, "")
                    if weapon_name and weapon_name in self.weapon_name_to_dict:
                        weapon_dict = self.weapon_name_to_dict[weapon_name]
                        cpp_weapons[slot_idx] = _dict_to_weapon(weapon_dict)
            else:
                # Fallback to legacy weapon_indices format (list of weapon names)
                weapon_names = t.get("weapon_indices", [])
                if weapon_names:
                    for slot_idx, weapon_name in enumerate(weapon_names):
                        if slot_idx >= 3:
                            break
                        if weapon_name and weapon_name in self.weapon_name_to_dict:
                            weapon_dict = self.weapon_name_to_dict[weapon_name]
                            cpp_weapons[slot_idx] = _dict_to_weapon(weapon_dict)
                else:
                    # Fallback to legacy "weapons" field with full weapon dicts
                    legacy_weapons = t.get("weapons_legacy", [])
                    if legacy_weapons:
                        for slot_idx, w_dict in enumerate(legacy_weapons):
                            if slot_idx >= 3:
                                break
                            cpp_weapons[slot_idx] = _dict_to_weapon(w_dict)

            self.combat.set_agent_weapons(self.bm, i, cpp_weapons)

        # Restore spells — load from spell_indices or legacy "spells" field
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            cpp_spells = []

            # Try new spell_indices format first (spell names as strings)
            spell_names = t.get("spell_indices", [])
            if spell_names:
                for j, spell_name in enumerate(spell_names):
                    if spell_name in self.spell_name_to_idx:
                        idx = self.spell_name_to_idx[spell_name]
                        spell_dict = self.all_spells[idx]
                        cpp_spell = self._dict_to_spell(i, spell_dict)
                        cpp_spells.append(cpp_spell)
                        # Store metadata (terrain, hatch, color)
                        meta = {
                            "terrain_effect": spell_dict.get("terrain_effect"),
                            "hatch_pattern": spell_dict.get("hatch_pattern"),
                            "terrain_color": spell_dict.get("terrain_color"),
                        }
                        self._spell_metadata[(i, j)] = meta
                    else:
                        available = ", ".join(sorted(list(self.spell_name_to_idx.keys())[:5])) + "..."
                        print(f"WARNING: Spell '{spell_name}' not found for agent {t.get('name', i)}")
                        print(f"         Available spells: {available}")
            else:
                # Fallback to legacy "spells" format for backward compatibility
                spell_data = t.get("spells", [])
                for j, item in enumerate(spell_data):
                    # Handle both old formats: spell dicts or spell names (strings)
                    if isinstance(item, dict):
                        cpp_spells.append(self._dict_to_spell(i, item))
                        # Store metadata from dict
                        meta = {
                            "terrain_effect": item.get("terrain_effect"),
                            "hatch_pattern": item.get("hatch_pattern"),
                            "terrain_color": item.get("terrain_color"),
                        }
                        self._spell_metadata[(i, j)] = meta
                    elif isinstance(item, str):
                        # Legacy format: spell stored as name string
                        # Look up in all_spells by name
                        if item in self.spell_name_to_idx:
                            idx = self.spell_name_to_idx[item]
                            spell_dict = self.all_spells[idx]
                            cpp_spells.append(self._dict_to_spell(i, spell_dict))
                            # Store metadata
                            meta = {
                                "terrain_effect": spell_dict.get("terrain_effect"),
                                "hatch_pattern": spell_dict.get("hatch_pattern"),
                                "terrain_color": spell_dict.get("terrain_color"),
                            }
                            self._spell_metadata[(i, j)] = meta

            self.combat.set_agent_spells(self.bm, i, cpp_spells)

        # Restore armor — load from armor dict (new format) or legacy armor_indices (old format)
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            cpp_armor = [rpg.Armor() for _ in range(6)]  # 6 slots: [helmet, chest, leggings, boots, gloves, cloak]

            # Slot order: helmet, chest, leggings, boots, gloves, cloak
            SLOT_NAMES = ["helmet", "chest", "leggings", "boots", "gloves", "cloak"]

            # Try new armor dict format first (slot name -> armor name)
            armor_dict_new = t.get("armor", {})
            if armor_dict_new and isinstance(armor_dict_new, dict):
                for slot_idx, slot_name in enumerate(SLOT_NAMES):
                    armor_name = armor_dict_new.get(slot_name, "")
                    if armor_name and armor_name in self.armor_name_to_dict:
                        armor_def = self.armor_name_to_dict[armor_name]
                        cpp_armor[slot_idx] = _dict_to_armor(armor_def)
            else:
                # Fallback to legacy armor_indices format (list of names)
                armor_names = t.get("armor_indices", [])
                if armor_names:
                    for slot_idx, armor_name in enumerate(armor_names):
                        if slot_idx >= 6:
                            break
                        if armor_name and armor_name in self.armor_name_to_dict:
                            armor_dict = self.armor_name_to_dict[armor_name]
                            cpp_armor[slot_idx] = _dict_to_armor(armor_dict)

            # Store armor in the C++ layer (as array of 6 pieces)
            self.combat.set_agent_armor(self.bm, i, cpp_armor)

            # Check STR requirements and warn if insufficient
            agent_stats = self.combat.get_agent_stats(self.bm, i)
            for piece in cpp_armor:
                if piece.name and not self.combat.can_equip_armor(self.bm, i, piece):
                    print(f"⚠ {self.bm.placed_agents[i].name} wearing {piece.name} (requires STR {piece.str_requirement}, has {agent_stats.str})")

        # Restore character class, level, and spell slots to C++ Stats objects
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            stats = self.combat.get_agent_stats(self.bm, i)
            class_name = t.get("agent_class", "None")
            char_level = int(t.get("agent_char_level", 1))
            stats.set_class_level(getattr(rpg.CharacterClass, class_name), char_level)
            # Restore remaining spell slots if they were saved
            slots_cur = t.get("spell_slots_cur")
            if slots_cur:
                stats.spell_slots_remaining = list(slots_cur)
            self.combat.set_agent_stats(self.bm, i, stats)

        # Restore NPC spell mechanics if present
        for i, t in enumerate(agent_data):
            if i >= len(self.bm.placed_agents):
                break
            is_npc = t.get("is_npc", False)
            if is_npc:
                npc_spell_groups = t.get("npc_spell_groups", {})
                # Initialize NPC spell groups in C++ (converts string keys to ints)
                if npc_spell_groups:
                    groups_dict = {int(k): v for k, v in npc_spell_groups.items()}
                    self.combat.init_npc_spell_groups(self.bm, i, groups_dict)
                # Keep in _agent_meta for stats dialog to access
                self._agent_meta[i] = {"npc_spell_groups": npc_spell_groups}

        self._attack_cells_melee = []
        self._attack_cells_rnorm = []
        self._attack_cells_rlong = []

    def _load_terrain(self):
        """Load terrain data from JSON file if it exists.

        If the file doesn't exist on first load, terrain starts empty.
        User can manually label terrain using the terrain editor,
        or choose to auto-detect walls as a fallback.
        """
        if os.path.exists(self._terrain_path):
            try:
                with open(self._terrain_path, 'r') as f:
                    data = json.load(f)
                self._terrain_regions = data.get("regions", [])
                self._apply_terrain_to_battle_map()
            except Exception:
                self._terrain_regions = []
        else:
            # First load: start with empty terrain, user can manually label or auto-detect later
            self._terrain_regions = []

    def _save_terrain(self):
        """Save terrain data to JSON file."""
        data = {"regions": self._terrain_regions}
        with open(self._terrain_path, 'w') as f:
            json.dump(data, f, indent=2)

    def _load_spell_effects(self):
        """Load spell effect data from JSON file if it exists."""
        if os.path.exists(self._effects_path):
            try:
                rpg.apply_spell_effect_configuration(self.bm, self._effects_path)
                self._build_spell_effect_metadata()
            except Exception as e:
                print(f"Warning: Failed to load spell effects: {e}")

    def _build_spell_effect_metadata(self):
        """Build metadata for spell effects to use in rendering."""
        for effect in self.bm.active_spell_effects:
            # Find the spell in all_spells to get its visual properties
            spell_color = None
            for spell_dict in self.all_spells:
                if spell_dict.get("name") == effect.spell.name:
                    # Look for terrain_color property (RGB array)
                    if "terrain_color" in spell_dict:
                        rgb = spell_dict["terrain_color"]
                        # Add alpha for semi-transparency
                        spell_color = tuple(rgb + [120])
                    break

            # Default color if not found
            if not spell_color:
                spell_color = (100, 180, 220, 120)  # Cyan

            self._effect_meta[effect.effect_id] = {
                "name": effect.spell.name,
                "color": spell_color,
                "cells": [(c.col, c.row) for c in effect.cells]
            }

    def _load_lighting(self):
        """Load lighting data from JSON file if it exists."""
        if os.path.exists(self._lighting_path):
            try:
                with open(self._lighting_path, 'r') as f:
                    data = json.load(f)
                default_str = data.get("default_light", "BrightLight")
                default_lvl = self._parse_light_level(default_str)
                sources = []
                for src in data.get("light_sources", []):
                    lvl = self._parse_light_level(src.get("light_level", "BrightLight"))
                    sources.append((int(src["x"]), int(src["y"]),
                                   int(src.get("bright_radius", 20)),
                                   int(src.get("dim_radius", 40))))
                self.bm.apply_base_lighting(default_lvl, sources)
            except Exception as e:
                print(f"[App] Error loading lighting: {e}")

    def _save_lighting(self, light_sources, default_light):
        """Save lighting data to JSON file."""
        # Convert enum to string
        light_str_map = {
            rpg.LightLevel.BrightLight: "BrightLight",
            rpg.LightLevel.DimLight: "DimLight",
            rpg.LightLevel.Darkness: "Darkness",
            rpg.LightLevel.MagicalDarkness: "MagicalDarkness",
        }
        default_str = light_str_map.get(default_light, "Darkness")

        data = {
            "default_light": default_str,
            "light_sources": light_sources
        }
        with open(self._lighting_path, 'w') as f:
            json.dump(data, f, indent=2)

        # Reload lighting into battle map
        self._load_lighting()

    @staticmethod
    def _parse_light_level(s: str) -> 'rpg.LightLevel':
        """Convert string to LightLevel enum."""
        mapping = {
            "BrightLight": rpg.LightLevel.BrightLight,
            "DimLight": rpg.LightLevel.DimLight,
            "Darkness": rpg.LightLevel.Darkness,
            "MagicalDarkness": rpg.LightLevel.MagicalDarkness,
        }
        return mapping.get(s, rpg.LightLevel.BrightLight)

    def _clear_temporary_terrain(self):
        """Remove spell-created temporary terrain (regions with 'source' field)."""
        self._terrain_regions = [r for r in self._terrain_regions if "source" not in r]

    def _apply_terrain_to_battle_map(self):
        """Apply terrain regions to the C++ battle map multiplier system."""
        self.bm.reset_terrain_multipliers()
        for region in self._terrain_regions:
            terrain_type = region.get("type", "Difficult Terrain")
            if terrain_type == "Difficult Terrain":
                mult = region.get("multiplier", 0.5)
                px = region.get("x", 0)
                py = region.get("y", 0)
                pw = region.get("width", 0)
                ph = region.get("height", 0)
                if pw > 0 and ph > 0:
                    self._apply_pixel_terrain(px, py, pw, ph, mult)

    def _apply_pixel_terrain(self, px, py, pw, ph, mult):
        """Convert pixel coordinates to grid and apply multiplier."""
        import bisect
        s = self.map_scale
        raw_v = self.bm.v_line_positions
        raw_h = self.bm.h_line_positions
        if not raw_v or not raw_h:
            return

        # Convert pixel coords (scaled) to original image coords
        ix, iy = px / s, py / s
        iw, ih = pw / s, ph / s

        # Find grid cell range using binary search
        c_start = max(0, bisect.bisect_right(raw_v, ix) - 1)
        r_start = max(0, bisect.bisect_right(raw_h, iy) - 1)
        c_end = min(self.bm.grid_cols - 1, bisect.bisect_right(raw_v, ix + iw) - 1)
        r_end = min(self.bm.grid_rows - 1, bisect.bisect_right(raw_h, iy + ih) - 1)

        width = max(1, c_end - c_start + 1)
        height = max(1, r_end - r_start + 1)

        self.bm.set_terrain_multiplier_rect(rpg.Cell(c_start, r_start), width, height, mult)

    # ─────────────────────────────────────────────────────────────────────
    #  Drawing
    # ─────────────────────────────────────────────────────────────────────
    def _draw_map(self):
        self.screen.blit(self.map_surf, self.map_rect)
        # Draw regular overlay unless lighting editor is active
        if not self.lighting_editor.active:
            self.screen.blit(self.overlay, self.map_rect)
            # Draw lighting overlay if persistent toggle is on
            if self.show_lighting_overlay:
                self._draw_lighting_overlay()
        elif self.lighting_editor.show_overlay:
            # Draw lighting overlay if editor dialog toggle is on
            self._draw_lighting_overlay()

    def _draw_lighting_overlay(self):
        """Draw the lighting visualization overlay on the map."""
        if not self.bm or not self.map_rect:
            return

        cpx = self.bm.cell_pixel_size
        cols = self.bm.grid_cols
        rows = self.bm.grid_rows
        h_lines = self.bm.h_line_positions
        v_lines = self.bm.v_line_positions

        # Create a surface for the lighting overlay
        lighting_surf = pygame.Surface((self.map_rect.width, self.map_rect.height), pygame.SRCALPHA)

        # Draw each cell with its light level
        for r in range(rows):
            for c in range(cols):
                if c >= len(v_lines) - 1 or r >= len(h_lines) - 1:
                    continue

                # Get the light level at this cell
                light_level = self.bm.get_light_level(rpg.Cell(c, r))

                # Calculate opacity based on light level
                # BrightLight: 0% opacity (transparent)
                # DimLight: 50% opacity
                # Darkness: 90% opacity
                # MagicalDarkness: 100% opacity
                opacity = {
                    rpg.LightLevel.BrightLight: 0,
                    rpg.LightLevel.DimLight: 128,      # 50% of 255
                    rpg.LightLevel.Darkness: 230,      # 90% of 255
                    rpg.LightLevel.MagicalDarkness: 255,
                }.get(light_level, 0)

                if opacity > 0:
                    # Draw semi-transparent overlay for this cell
                    cell_x = v_lines[c]
                    cell_y = h_lines[r]
                    cell_w = v_lines[c + 1] - v_lines[c]
                    cell_h = h_lines[r + 1] - h_lines[r]

                    # Color depends on light level
                    if light_level == rpg.LightLevel.MagicalDarkness:
                        color = (0, 0, 0, opacity)  # Black for magical darkness
                    else:
                        color = (50, 50, 50, opacity)  # Dark grey for other darkness

                    pygame.draw.rect(lighting_surf, color, (cell_x, cell_y, cell_w, cell_h))

        # Blit the lighting overlay onto the screen
        self.screen.blit(lighting_surf, self.map_rect)

        # Draw markers for light sources (golden circles)
        h_lines = self.bm.h_line_positions
        v_lines = self.bm.v_line_positions

        for light_src in self.lighting_editor.light_sources:
            px = light_src["x"]
            py = light_src["y"]

            # Find grid cell containing this pixel
            grid_c = -1
            grid_r = -1
            for c in range(len(v_lines) - 1):
                if px >= v_lines[c] and px < v_lines[c + 1]:
                    grid_c = c
                    break
            for r in range(len(h_lines) - 1):
                if py >= h_lines[r] and py < h_lines[r + 1]:
                    grid_r = r
                    break

            if grid_c >= 0 and grid_r >= 0:
                # Draw a circle marker at the light source center
                cell_x = v_lines[grid_c]
                cell_y = h_lines[grid_r]
                cell_w = v_lines[grid_c + 1] - v_lines[grid_c]
                cell_h = h_lines[grid_r + 1] - h_lines[grid_r]
                center_x = cell_x + cell_w // 2
                center_y = cell_y + cell_h // 2
                radius = max(6, cell_w // 6)

                # Draw outer circle (golden yellow)
                pygame.draw.circle(self.screen, (255, 200, 0), (center_x, center_y), radius, 3)
                # Draw inner circle (bright yellow)
                pygame.draw.circle(self.screen, (255, 255, 100), (center_x, center_y), radius - 2, 1)

    def _draw_one_agent(self, pt, screen_x, screen_y, cpx, alpha=255, tint=None):
        """Draw a single agent (sprite or placeholder) at the given screen coords."""
        size_px = cpx * pt.size
        sprite  = self._get_sprite(pt.sprite_path, size_px)
        if sprite:
            if alpha < 255 or tint:
                surf = sprite.copy()
                if tint:
                    surf.fill(tint, special_flags=pygame.BLEND_RGBA_MULT)
                surf.set_alpha(alpha)
                self.screen.blit(surf, (screen_x, screen_y))
            else:
                self.screen.blit(sprite, (screen_x, screen_y))
        else:
            r = pygame.Rect(screen_x+2, screen_y+2, size_px-4, size_px-4)
            placeholder = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
            fill_col    = tint if tint else COL_AGENT_FILL
            placeholder.fill((*fill_col[:3], alpha))
            self.screen.blit(placeholder, r)
            pygame.draw.rect(self.screen, COL_AGENT_BORDER, r, 2, border_radius=3)
        # Down hatching (diagonal lines when HP <= 0)
        if pt.stats.hp_cur <= 0:
            hatch = pygame.Surface((size_px, size_px), pygame.SRCALPHA)
            hatch.fill((0, 0, 0, 0))
            step = max(4, size_px // 8)
            col  = (180, 0, 0, 200)
            for offset in range(-size_px, size_px * 2, step):
                pygame.draw.line(hatch, col, (offset, 0), (offset + size_px, size_px), 2)
                pygame.draw.line(hatch, col, (offset + size_px, 0), (offset, size_px), 2)
            self.screen.blit(hatch, (screen_x, screen_y))

        # Name label
        lbl = self.font_sm.render(pt.name, True, (255, 255, 255))
        self.screen.blit(lbl, (screen_x + 3, screen_y + 3))

        # Concentration indicator (circle around agent if concentrating)
        if pt.conditions.concentrating:
            center_x = int(screen_x + size_px / 2)
            center_y = int(screen_y + size_px / 2)
            radius = int(size_px / 2 + 6)
            pygame.draw.circle(self.screen, (255, 200, 100), (center_x, center_y), radius, 2)
            spell_name = pt.conditions.concentrating_on or 'Spell'
            spell_lbl = self.font_sm.render(spell_name, True, (255, 200, 100))
            self.screen.blit(spell_lbl, (screen_x + size_px + 5, screen_y))

    def _draw_reach_overlays(self, cpx: int, raw_h=None, raw_v=None):
        """Draw walk (blue) and fly (gold) reachable-cell overlays."""
        # Get map dimensions if not provided
        if raw_h is None:
            raw_h = self.bm.h_line_positions
        if raw_v is None:
            raw_v = self.bm.v_line_positions

        # Walk range: semi-transparent cornflower blue
        if self._reach_walk:
            walk_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            walk_surf.fill((60, 120, 220, 55))
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, (80, 150, 255, 120),
                             border_surf.get_rect(), 1)
            map_w, map_h = self.map_rect.width, self.map_rect.height
            for cell in self._reach_walk:
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(walk_surf,   (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

        # Fly range: semi-transparent gold — drawn on top so overlapping
        # cells show both colours (fly usually extends beyond walk).
        if self._reach_fly:
            fly_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fly_surf.fill((220, 180, 0, 45))
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, (255, 210, 0, 110),
                             border_surf.get_rect(), 1)
            map_w, map_h = self.map_rect.width, self.map_rect.height
            for cell in self._reach_fly:
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(fly_surf,    (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

        # Jump range: semi-transparent cyan (when overlay is active)
        if self.jump_overlay_active and self.jump_reachable_cells:
            jump_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            jump_surf.fill((100, 200, 255, 70))
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, (150, 230, 255, 150),
                             border_surf.get_rect(), 2)
            for cell in self.jump_reachable_cells:
                # Skip cells outside map bounds
                if (cell.col < 0 or cell.row < 0 or
                    cell.col >= len(raw_v) or cell.row >= len(raw_h)):
                    continue
                sx, sy = self._cell_to_screen(cell.col, cell.row)
                self.screen.blit(jump_surf,   (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

    def _draw_temp_terrain_overlays(self, cpx: int):
        """Draw temporary terrain effect overlays."""
        if not self.bm.has_active_terrain_effects():
            return

        s = self.map_scale
        raw_h = self.bm.h_line_positions
        raw_v = self.bm.v_line_positions

        for effect in self.bm.active_terrain_effects:
            # Get color from metadata, or use a default based on difficulty
            if effect.id in self._effect_meta:
                color = self._effect_meta[effect.id].get("color", (100, 180, 220, 80))
            else:
                # Default colors by difficulty
                if effect.difficulty == rpg.TerrainDifficulty.Halved:
                    color = (80, 200, 80, 80)  # Green
                elif effect.difficulty == rpg.TerrainDifficulty.Quartered:
                    color = (200, 60, 60, 80)  # Red
                else:
                    color = (100, 180, 220, 80)  # Cyan

            # Create surfaces for fill and border
            fill_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fill_surf.fill(color)
            border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, border_color, border_surf.get_rect(), 1)

            # Render each cell of the effect
            map_w, map_h = self.map_rect.width, self.map_rect.height
            for cell_idx in effect.cell_indices:
                # Convert flat index back to (col, row)
                col = cell_idx % self.bm.grid_cols
                row = cell_idx // self.bm.grid_cols
                if col < 0 or row < 0 or col >= len(raw_v) or row >= len(raw_h):
                    continue
                sx, sy = self._cell_to_screen(col, row)
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(fill_surf, (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

            # Draw turns_remaining as a small label in the first cell
            if effect.cell_indices and effect.turns_remaining >= 0:
                first_idx = effect.cell_indices[0]
                col = first_idx % self.bm.grid_cols
                row = first_idx // self.bm.grid_cols
                if col >= 0 and row >= 0 and col < len(raw_v) and row < len(raw_h):
                    sx, sy = self._cell_to_screen(col, row)
                    # Draw a small number in the top-left corner
                    txt = self.font_sm.render(str(effect.turns_remaining), True, (255, 255, 255))
                    self.screen.blit(txt, (sx + 2, sy + 2))

    def _draw_spell_effects(self, cpx: int):
        """Draw persistent spell effect overlays."""
        if not self.show_spell_effects:
            return

        active_effects = self.bm.active_spell_effects
        if not active_effects:
            return

        s = self.map_scale
        raw_h = self.bm.h_line_positions
        raw_v = self.bm.v_line_positions
        if not raw_h or not raw_v:
            return

        for effect in active_effects:
            # Build metadata for this effect if not already present
            if effect.effect_id not in self._effect_meta:
                spell_color = None
                for spell_dict in self.all_spells:
                    if spell_dict.get("name") == effect.spell.name:
                        if "terrain_color" in spell_dict:
                            rgb = spell_dict["terrain_color"]
                            spell_color = tuple(rgb + [120])
                        break
                if not spell_color:
                    spell_color = (100, 180, 220, 120)  # Cyan default
                self._effect_meta[effect.effect_id] = {
                    "name": effect.spell.name,
                    "color": spell_color,
                    "cells": [(c.col, c.row) for c in effect.cells]
                }

            # Get color from metadata
            if effect.effect_id in self._effect_meta:
                color = self._effect_meta[effect.effect_id].get("color", (100, 180, 220, 120))
            else:
                color = (100, 180, 220, 120)  # Cyan default

            # Create surfaces for fill and border
            fill_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fill_surf.fill(color)
            border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, border_color, border_surf.get_rect(), 1)

            # Render each cell of the effect
            map_w, map_h = self.map_rect.width, self.map_rect.height
            for cell in effect.cells:
                col = cell.col
                row = cell.row
                if col < 0 or row < 0 or col >= len(raw_v) or row >= len(raw_h):
                    continue
                sx, sy = self._cell_to_screen(col, row)
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(fill_surf, (sx, sy))
                self.screen.blit(border_surf, (sx, sy))

            # Draw turns_remaining as a small label in the first cell
            if effect.cells and effect.turns_remaining >= 0:
                first_cell = effect.cells[0]
                sx, sy = self._cell_to_screen(first_cell.col, first_cell.row)
                txt = self.font_sm.render(str(effect.turns_remaining), True, (255, 255, 255))
                self.screen.blit(txt, (sx + 2, sy + 2))

    def _draw_concentration_terrain(self, cpx: int):
        """Draw all terrain: permanent features and concentration-based effects."""
        if not self.show_terrain:
            return

        # Draw permanent terrain (walls, chasms, difficult terrain)
        for region in self._terrain_regions:
            # Skip concentration-based terrain for now (draw separately below)
            if "cells" in region or region.get("source", {}).get("requires_concentration"):
                continue

            # Permanent terrain from JSON
            if "x" not in region or "y" not in region:
                continue

            x = int(region.get("x", 0))
            y = int(region.get("y", 0))
            w = int(region.get("width", 0))
            h = int(region.get("height", 0))
            terrain_type = region.get("type", "Difficult Terrain")

            if terrain_type == "Wall":
                color = (50, 50, 50, 150)
            elif terrain_type == "Chasm":
                color = (140, 140, 140, 150)
            else:  # Difficult Terrain
                color = (139, 90, 43, 150)  # Brown

            # Draw filled rectangle
            fill_surf = pygame.Surface((w, h), pygame.SRCALPHA)
            fill_surf.fill(color)
            self.screen.blit(fill_surf, (x + self.map_rect.x, y + self.map_rect.y))

            # Draw border
            border_rect = pygame.Rect(x + self.map_rect.x, y + self.map_rect.y, w, h)
            border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
            pygame.draw.rect(self.screen, border_color, border_rect, 2)

        # Draw concentration-based terrain with hatching patterns, cell-by-cell
        hatch_patterns = ['//', '\\\\', '||', '--', '++', 'xx', 'oo', 'OO', '..', '**']
        for i, region in enumerate(self._terrain_regions):
            if not region.get("source", {}).get("requires_concentration"):
                continue

            cells = region.get("cells", [])
            if not cells:
                continue

            hatch = region.get("hatch_pattern") or hatch_patterns[i % len(hatch_patterns)]
            multiplier = region.get("multiplier", 0.5)
            duration = region.get("source", {}).get("duration_remaining", 0)
            spell_name = region.get("source", {}).get("spell", "Effect")
            caster_idx = region.get("source", {}).get("caster", -1)
            spell_idx = region.get("source", {}).get("spell_idx", -1)

            # Get color from spell metadata if available, otherwise use brown default
            spell_meta = self._spell_metadata.get((caster_idx, spell_idx), {})
            if "terrain_color" in spell_meta and spell_meta["terrain_color"]:
                rgb = spell_meta["terrain_color"]
                color = (rgb[0], rgb[1], rgb[2], 100)
            else:
                # Default brown color for difficult terrain
                color = (139, 90, 43, 100)

            # Create fill and border surfaces for one cell
            fill_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            fill_surf.fill(color)
            border_color = tuple(min(c + 40, 255) for c in color[:3]) + (color[3],)
            border_surf = pygame.Surface((cpx, cpx), pygame.SRCALPHA)
            pygame.draw.rect(border_surf, border_color, border_surf.get_rect(), 1)

            # Draw each cell
            map_w, map_h = self.map_rect.width, self.map_rect.height
            for col, row in cells:
                sx, sy = self._cell_to_screen(col, row)
                if sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h:
                    continue
                self.screen.blit(fill_surf, (sx, sy))
                self.screen.blit(border_surf, (sx, sy))
                # Draw hatching for this cell
                self._draw_cell_hatching(hatch, sx, sy, cpx, color)

            # Draw duration label on first cell
            if cells:
                first_col, first_row = cells[0]
                sx, sy = self._cell_to_screen(first_col, first_row)
                if not (sx + cpx <= 0 or sx >= map_w or sy + cpx <= 0 or sy >= map_h):
                    spell = region.get("source", {}).get("spell", "Effect")
                    duration_txt = self.font_sm.render(f"{spell}({duration})", True, (255, 255, 255))
                    self.screen.blit(duration_txt, (sx + 3, sy + 3))

    def _draw_cell_hatching(self, pattern: str, sx: int, sy: int, cpx: int, color: tuple):
        """Draw hatching pattern for a single cell."""
        hatch_color = tuple(min(c + 100, 255) for c in color[:3]) + (120,)
        spacing = 4

        # Clip to cell bounds
        clip_rect = pygame.Rect(sx, sy, cpx, cpx)
        old_clip = self.screen.get_clip()
        self.screen.set_clip(clip_rect)

        try:
            if pattern == '//' or pattern == 'xx':
                # Forward diagonal lines
                for i in range(-cpx, cpx * 2, spacing):
                    pygame.draw.line(self.screen, hatch_color, (sx + i, sy), (sx + i + cpx, sy + cpx), 1)
            if pattern == '\\\\' or pattern == 'xx':
                # Backward diagonal lines
                for i in range(-cpx, cpx * 2, spacing):
                    pygame.draw.line(self.screen, hatch_color, (sx + i + cpx, sy), (sx + i, sy + cpx), 1)
            if pattern == '||' or pattern == '++':
                # Vertical lines
                for i in range(0, cpx, spacing):
                    pygame.draw.line(self.screen, hatch_color, (sx + i, sy), (sx + i, sy + cpx), 1)
            if pattern == '--' or pattern == '++':
                # Horizontal lines
                for i in range(0, cpx, spacing):
                    pygame.draw.line(self.screen, hatch_color, (sx, sy + i), (sx + cpx, sy + i), 1)
        finally:
            self.screen.set_clip(old_clip)

    def _draw_hatching(self, pattern: str, x: float, y: float, w: float, h: float, color: tuple):
        """Draw a hatching pattern on the screen within bounds."""
        screen_x = int(x + self.map_rect.x)
        screen_y = int(y + self.map_rect.y)
        screen_w = int(w)
        screen_h = int(h)
        hatch_color = tuple(min(c + 100, 255) for c in color[:3]) + (120,)

        # Create a clipping rectangle for the hatching
        clip_rect = pygame.Rect(screen_x, screen_y, screen_w, screen_h)
        old_clip = self.screen.get_clip()
        self.screen.set_clip(clip_rect)

        if pattern == '//':
            for i in range(-screen_h, screen_w + screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i + screen_h, screen_y + screen_h), 1)
        elif pattern == '\\\\':
            for i in range(-screen_h, screen_w + screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i - screen_h, screen_y + screen_h), 1)
        elif pattern == '||':
            for i in range(0, screen_w, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i, screen_y + screen_h), 1)
        elif pattern == '--':
            for i in range(0, screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x, screen_y + i), (screen_x + screen_w, screen_y + i), 1)
        elif pattern == '++':
            for i in range(0, screen_w, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i, screen_y + screen_h), 1)
            for i in range(0, screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x, screen_y + i), (screen_x + screen_w, screen_y + i), 1)
        elif pattern == 'xx':
            for i in range(-screen_h, screen_w + screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i + screen_h, screen_y + screen_h), 1)
            for i in range(-screen_h, screen_w + screen_h, 8):
                pygame.draw.line(self.screen, hatch_color, (screen_x + i, screen_y), (screen_x + i - screen_h, screen_y + screen_h), 1)

        # Restore the clip rect
        self.screen.set_clip(old_clip)

    def _draw_agents(self):
        bm    = self.bm
        s     = self.map_scale
        cpx   = int(bm.cell_pixel_size * s)
        raw_h = bm.h_line_positions
        raw_v = bm.v_line_positions
        if not raw_h or not raw_v:
            return

        agents = bm.placed_agents

        # ── Movement reach overlays (beneath all agents) ──────────────────
        self._draw_reach_overlays(cpx, raw_h, raw_v)

        # ── Attack range overlays (beneath all agents) ────────────────────
        self._draw_attack_overlays(cpx)

        # ── Temporary terrain effects overlays (beneath all agents) ────────
        self._draw_temp_terrain_overlays(cpx)

        # ── Spell effect overlays (beneath all agents) ─────────────────────
        self._draw_spell_effects(cpx)

        # ── Concentration-based terrain overlays (beneath all agents) ──────
        self._draw_concentration_terrain(cpx)

        # ── Draw all settled agents ───────────────────────────────────────
        for i, pt in enumerate(agents):
            if i == self.drag_idx:
                continue    # skip the one being dragged (draw as ghost below)
            sx, sy = self._cell_to_screen(pt.origin.col, pt.origin.row)
            self._draw_one_agent(pt, sx, sy, cpx)

            # Selection highlight (yellow border)
            if i == self.selected_idx:
                size_px = cpx * pt.size
                pygame.draw.rect(self.screen, (255, 215, 0),
                                 pygame.Rect(sx, sy, size_px, size_px), 3,
                                 border_radius=3)

        # ── Spell AoE preview (above agents, below drag ghost) ───────────
        self._draw_spell_aoe_preview(cpx)

        # ── Draw drag ghost ───────────────────────────────────────────────
        if self.drag_idx >= 0 and self.drag_cell is not None:
            pt  = agents[self.drag_idx]
            sx, sy = self._cell_to_screen(self.drag_cell.col, self.drag_cell.row)
            tint = (100, 255, 100) if self.drag_valid else (255, 80, 80)
            self._draw_one_agent(pt, sx, sy, cpx, alpha=180, tint=tint)
            # Outline
            size_px = cpx * pt.size
            border_col = (80, 220, 80) if self.drag_valid else (220, 60, 60)
            pygame.draw.rect(self.screen, border_col,
                             pygame.Rect(sx, sy, size_px, size_px), 3,
                             border_radius=3)

        # ── Draw placement mode ghost ──────────────────────────────────────
        if self.placement_mode_active and self.placement_cell is not None:
            sx, sy = self._cell_to_screen(self.placement_cell.col, self.placement_cell.row)
            size_px = cpx * self.placement_config.size
            # Draw sprite if it exists
            sprite = self._get_sprite(self.placement_config.sprite_path, size_px)
            if sprite:
                surf = sprite.copy()
                surf.set_alpha(200)
                self.screen.blit(surf, (sx, sy))
            else:
                # Draw placeholder
                r = pygame.Rect(sx + 2, sy + 2, size_px - 4, size_px - 4)
                placeholder = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                placeholder.fill((150, 150, 200, 200))
                self.screen.blit(placeholder, r)
            # Red outline if invalid, green if valid
            border_col = (220, 60, 60) if not self.placement_valid else (80, 220, 80)
            pygame.draw.rect(self.screen, border_col,
                             pygame.Rect(sx, sy, size_px, size_px), 3,
                             border_radius=3)

    def _draw_combat_panel(self):
        """Draw the right panel while combat is active."""
        sw, sh = self.screen.get_size()
        px = self._panel_x()
        lx = px + self._PANEL_PAD
        W  = PANEL_W - self._PANEL_PAD * 2
        HW = W // 2 - 2
        B  = self._BTN_H
        gap = 4
        section_gap = 8

        # Background + border
        pygame.draw.rect(self.screen, COL_PANEL_BG, pygame.Rect(px, 0, PANEL_W, sh))
        pygame.draw.line(self.screen, COL_PANEL_BORDER, (px, 0), (px, sh))

        def txt(s, x, y, col=COL_TEXT, fnt=None):
            surf = (fnt or self.font_sm).render(s, True, col)
            self.screen.blit(surf, (x, y))

        y = 10

        # ── Title ──────────────────────────────────────────────────────────
        txt("⚔  Combat", lx, y, COL_INITIATIVE_CUR, self.font_lg)
        y += 28

        # ── Initiative list ────────────────────────────────────────────────
        txt("Initiative Order", lx, y, COL_LABEL)
        y += 16
        agents = self.bm.placed_agents
        for i, entry in enumerate(self.initiative_order[:8]):
            aidx   = entry.agent_idx
            is_cur = (i == self.turn_idx)
            col    = COL_INITIATIVE_CUR if is_cur else COL_TEXT
            name   = agents[aidx].name if aidx < len(agents) else "?"
            alive  = True
            if aidx < len(agents):
                s = self.combat.get_agent_stats(self.bm, aidx)
                alive = s.hp_cur > 0
            if not alive:
                col = (90, 90, 90)
            prefix = "▶ " if is_cur else "  "
            row_s  = f"{prefix}{entry.total:2d}  {name}"
            txt(row_s, lx, y, col)
            y += 16
        if len(self.initiative_order) > 8:
            txt(f"  …+{len(self.initiative_order)-8} more", lx, y, COL_LABEL)
            y += 16

        y += section_gap

        # ── Separator ──────────────────────────────────────────────────────
        pygame.draw.line(self.screen, COL_PANEL_BORDER,
                         (px + 6, y), (px + PANEL_W - 6, y))
        y += section_gap

        # ── Current combatant info ─────────────────────────────────────────
        cur_idx = self._current_agent_idx()
        if 0 <= cur_idx < len(agents):
            pt    = agents[cur_idx]
            stats = self.combat.get_agent_stats(self.bm, cur_idx)
            frac  = stats.hp_cur / max(stats.hp_max, 1)
            hp_col = (COL_HP_HIGH if frac > 0.66 else
                      COL_HP_MID  if frac > 0.33 else
                      COL_HP_LOW)
            txt(f"Turn: {pt.name}", lx, y, COL_TEXT, self.font_md)
            y += 20
            pygame.draw.rect(self.screen, (50, 50, 50),
                             pygame.Rect(lx, y, W, 12), border_radius=3)
            pygame.draw.rect(self.screen, hp_col,
                             pygame.Rect(lx, y, int(W * frac), 12), border_radius=3)
            txt(f"HP {stats.hp_cur}/{stats.hp_max}", lx + W//2 - 22, y - 1)
            y += 12

        y += section_gap

        # ── Action section ─────────────────────────────────────────────────
        act_lbl = "Action" + (" ✓" if self.action_used else "")
        txt(act_lbl, lx, y, COL_LABEL)
        y += 16

        # Check weapon/spell capability for current agent.
        _cur_has_weapons = False
        _cur_has_offhand = False
        _cur_can_spell   = False
        _cur_has_spells  = False
        if 0 <= cur_idx < len(agents):
            _cur_has_weapons = len(self.combat.get_agent_weapons(self.bm, cur_idx)) > 0
            _cur_has_offhand = any(w.off_hand for w in self.combat.get_agent_weapons(self.bm, cur_idx))
            _cur_has_spells  = len(self.combat.get_agent_spells(self.bm, cur_idx)) > 0
            _cur_can_spell   = _cur_has_spells  # can cast if has spells

        # Check if mid-sequence (attacks remaining, but action_used not yet set)
        mid_sequence_action = (self.attacks_remaining > 0 and self._attack_sequence_slot == "action")

        if self.action_used and not mid_sequence_action:
            txt("[Action used]", lx, y, (100, 100, 120))
            y += B
        else:
            # Attack and Pass buttons
            # Update Attack button label with attack count if mid-sequence
            if mid_sequence_action:
                self.btn_cbt_atk_action.text = f"⚔ Attack ({self.attacks_remaining})"
            else:
                self.btn_cbt_atk_action.text = "⚔ Attack"

            self.btn_cbt_atk_action.rect.x  = lx
            self.btn_cbt_atk_action.rect.y  = y
            self.btn_cbt_atk_action.rect.w  = HW
            self.btn_cbt_pass_action.rect.x = lx + HW + gap
            self.btn_cbt_pass_action.rect.y = y
            self.btn_cbt_pass_action.rect.w = HW
            if _cur_has_weapons:
                self.btn_cbt_atk_action.draw(self.screen)
            self.btn_cbt_pass_action.draw(self.screen)
            y += B + gap

            # Dash, Dodge, Disengage buttons
            TW3 = (W - 8) // 3
            self.btn_cbt_dash.rect.x       = lx
            self.btn_cbt_dash.rect.y       = y
            self.btn_cbt_dash.rect.w       = TW3
            self.btn_cbt_dodge.rect.x      = lx + TW3 + gap
            self.btn_cbt_dodge.rect.y      = y
            self.btn_cbt_dodge.rect.w      = TW3
            self.btn_cbt_disengage.rect.x  = lx + 2 * (TW3 + gap)
            self.btn_cbt_disengage.rect.y  = y
            self.btn_cbt_disengage.rect.w  = TW3
            self.btn_cbt_dash.draw(self.screen)
            self.btn_cbt_dodge.draw(self.screen)
            self.btn_cbt_disengage.draw(self.screen)
            y += B + gap

            # Long Jump button
            self.btn_cbt_long_jump.rect.x = lx
            self.btn_cbt_long_jump.rect.y = y
            self.btn_cbt_long_jump.rect.w = W
            self.btn_cbt_long_jump.draw(self.screen)
            y += B + gap

            # Cast Spell button (if available)
            if _cur_can_spell and _cur_has_spells:
                self.btn_cbt_spell_action.rect.x = lx
                self.btn_cbt_spell_action.rect.y = y
                self.btn_cbt_spell_action.rect.w = W
                self.btn_cbt_spell_action.draw(self.screen)
                y += B + gap

        # ── Spell Slots / N/day display ────────────────────────────────────
        if 0 <= cur_idx < len(agents):
            stats = self.combat.get_agent_stats(self.bm, cur_idx)

            if stats.is_npc:
                # NPC N/day spell display
                spells = self.combat.get_agent_spells(self.bm, cur_idx)
                npc_spells = [sp for sp in spells if sp.uses_max > 0]
                if npc_spells:
                    y += 4
                    txt("Spells (N/day):", lx, y, (160, 120, 200), self.font_sm)
                    y += 14
                    for spell in npc_spells:
                        txt(f"{spell.name:20} {spell.uses_remaining}/{spell.uses_max}", lx, y, (200, 200, 220), self.font_sm)
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
                            test_surf = self.font_sm.render(test_str, True, (160, 120, 200))
                            if test_surf.get_width() > W and current_line != "Spells: ":
                                lines.append(current_line.rstrip())
                                current_line = "  " + level_str + ("  " if i < len(pip_chars) - 1 else "")
                            else:
                                current_line = test_str
                        if current_line.strip():
                            lines.append(current_line)
                        for line in lines:
                            txt(line, lx, y, (160, 120, 200), self.font_sm)
                            y += 14

        y += section_gap

        # ── Bonus Action section ───────────────────────────────────────────
        bon_lbl = "Bonus Action" + (" ✓" if self.bonus_used else "")
        txt(bon_lbl, lx, y, COL_LABEL)
        y += 16

        # Check if mid-sequence for bonus action
        mid_sequence_bonus = (self.attacks_remaining > 0 and self._attack_sequence_slot == "bonus")

        if self.bonus_used and not mid_sequence_bonus:
            txt("[Bonus used]", lx, y, (100, 100, 120))
            y += B
        else:
            # Update bonus button label with attack count if mid-sequence
            if mid_sequence_bonus:
                self.btn_cbt_atk_bonus.text = f"⚔ Bonus ({self.attacks_remaining})"
            else:
                self.btn_cbt_atk_bonus.text = "⚔ Bonus Atk"

            # Layout depends on whether spells are available
            if _cur_can_spell and _cur_has_spells:
                TW3_bonus = (W - 8) // 3
                self.btn_cbt_atk_bonus.rect.x   = lx
                self.btn_cbt_atk_bonus.rect.y   = y
                self.btn_cbt_atk_bonus.rect.w   = TW3_bonus
                self.btn_cbt_spell_bonus.rect.x = lx + TW3_bonus + gap
                self.btn_cbt_spell_bonus.rect.y = y
                self.btn_cbt_spell_bonus.rect.w = TW3_bonus
                self.btn_cbt_pass_bonus.rect.x  = lx + 2 * (TW3_bonus + gap)
                self.btn_cbt_pass_bonus.rect.y  = y
                self.btn_cbt_pass_bonus.rect.w  = TW3_bonus
                if _cur_has_offhand or mid_sequence_bonus:
                    self.btn_cbt_atk_bonus.draw(self.screen)
                self.btn_cbt_spell_bonus.draw(self.screen)
                self.btn_cbt_pass_bonus.draw(self.screen)
            else:
                self.btn_cbt_atk_bonus.rect.x  = lx
                self.btn_cbt_atk_bonus.rect.y  = y
                self.btn_cbt_atk_bonus.rect.w  = HW
                self.btn_cbt_pass_bonus.rect.x = lx + HW + gap
                self.btn_cbt_pass_bonus.rect.y = y
                self.btn_cbt_pass_bonus.rect.w = HW
                if _cur_has_offhand or mid_sequence_bonus:
                    self.btn_cbt_atk_bonus.draw(self.screen)
                self.btn_cbt_pass_bonus.draw(self.screen)
            y += B

        y += section_gap

        # ── Movement type toggles ──────────────────────────────────────────
        txt("Movement", lx, y, COL_LABEL)
        y += 16

        mv_stats = self.combat.get_agent_stats(self.bm, cur_idx) if 0 <= cur_idx < len(self.bm.placed_agents) else None
        mv_entries = [
            (rpg.MovementType.Walk,   "Walk",   self.move_remaining_walk,
             mv_stats.speed_walk   if mv_stats else 0),
            (rpg.MovementType.Fly,    "Fly",    self.move_remaining_fly,
             mv_stats.speed_fly    if mv_stats else 0),
            (rpg.MovementType.Swim,   "Swim",   self.move_remaining_swim,
             mv_stats.speed_swim   if mv_stats else 0),
            (rpg.MovementType.Burrow, "Burrow", self.move_remaining_burrow,
             mv_stats.speed_burrow if mv_stats else 0),
        ]
        available_mv = [(mt, lbl, rem, spd) for mt, lbl, rem, spd in mv_entries if spd > 0]
        self._move_type_btns = {}
        HW = W // 2 - 2
        for i, (mt, lbl, rem, spd) in enumerate(available_mv):
            bx = lx + (i % 2) * (HW + gap)
            by = y + (i // 2) * (B + gap)
            r  = pygame.Rect(bx, by, HW, B)
            self._move_type_btns[mt] = r
            if rem == 0:
                bg = (40, 40, 55)
                fg = (80, 80, 95)
            elif mt == self.move_type:
                bg = COL_BTN_ENDTURN
                fg = (230, 230, 230)
            else:
                bg = COL_BTN_PASS
                fg = (190, 190, 210)
            pygame.draw.rect(self.screen, bg, r, border_radius=4)
            surf = self.font_sm.render(f"{lbl}  {rem}ft", True, fg)
            self.screen.blit(surf, (bx + 4, by + (B - surf.get_height()) // 2))
        rows_used = max(1, (len(available_mv) + 1) // 2)
        y += rows_used * (B + gap)

        # Pending action hints
        if self.pending_attack_slot:
            rem = self.attacks_remaining
            _atk_hint = "→ Click a target on the map" + (f" ({rem} left)" if rem > 1 else "")
            txt(_atk_hint, lx, y, COL_INITIATIVE_CUR)
            y += 14
        elif self.pending_spell_slot:
            hint = "Click a map location" if self.pending_spell_is_aoe else "Click a target"
            txt(f"→ {hint} to cast spell", lx, y, (190, 150, 255))
            y += 14

        y += section_gap

        # ── Place Terrain / End Turn ───────────────────────────────────────
        HW = (W - 4) // 2
        self.btn_cbt_place_terrain.rect.x = lx
        self.btn_cbt_place_terrain.rect.y = y
        self.btn_cbt_place_terrain.rect.w = HW
        self.btn_cbt_place_terrain.draw(self.screen)

        self.btn_cbt_end_turn.rect.x  = lx + HW + 4
        self.btn_cbt_end_turn.rect.y  = y
        self.btn_cbt_end_turn.rect.w  = HW
        self.btn_cbt_end_turn.draw(self.screen)
        y += B + gap

        self.btn_show_terrain.rect.x = lx
        self.btn_show_terrain.rect.y = y
        self.btn_show_terrain.rect.w = HW
        self.btn_show_terrain.draw(self.screen)
        y += B + gap

        self.btn_show_spell_effects.rect.x = lx
        self.btn_show_spell_effects.rect.y = y
        self.btn_show_spell_effects.rect.w = HW
        self.btn_show_spell_effects.draw(self.screen)

        self.btn_cbt_end_combat.rect.x = lx + HW + 4
        self.btn_cbt_end_combat.rect.y = y
        self.btn_cbt_end_combat.rect.w = HW
        self.btn_cbt_end_combat.draw(self.screen)
        y += B + gap

        # Drop Concentration button (if current agent is concentrating)
        cur_idx = self._current_agent_idx()
        is_concentrating = (0 <= cur_idx < len(self.bm.placed_agents) and
                           self.bm.placed_agents[cur_idx].conditions.concentrating)
        if is_concentrating:
            self.btn_cbt_drop_concentration.rect.x = lx
            self.btn_cbt_drop_concentration.rect.y = y
            self.btn_cbt_drop_concentration.rect.w = W
            self.btn_cbt_drop_concentration.draw(self.screen)
        y += B + section_gap

        # ── Combat log ─────────────────────────────────────────────────────
        txt("Combat Log:", lx, y, COL_LABEL)
        y += 16

        max_log_w = W - 2

        def _wrap_draw(s, x, start_y, max_w, fnt, line_h=15):
            """Draw s word-wrapped within max_w pixels; return the new y after last line."""
            y_pos = start_y
            remaining = s
            while remaining:
                if y_pos + line_h > sh:
                    break
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

        for msg in self.combat_log[:5]:
            y = _wrap_draw(msg, lx, y, max_log_w, self.font_sm)


    def _draw_panel(self):
        if self.combat_active:
            self._draw_combat_panel()
            return

        sw, sh = self.screen.get_size()
        px  = self._panel_x()
        lx  = px + self._PANEL_PAD          # left edge for text
        loff = self._LABEL_H + self._LABEL_GAP   # how far above a widget its label sits

        # Panel background + left border
        pygame.draw.rect(self.screen, COL_PANEL_BG,
                         pygame.Rect(px, 0, PANEL_W, sh))
        pygame.draw.line(self.screen, COL_PANEL_BORDER, (px, 0), (px, sh))

        # ── Placement mode ─────────────────────────────────────────────────
        if self.placement_mode_active:
            title = self.font_lg.render("Click to place", True, (255, 200, 100))
            self.screen.blit(title, (lx, 20))
            status_col = (80, 220, 80) if self.placement_valid else (220, 60, 60)
            status_txt = "Valid placement" if self.placement_valid else "Invalid placement (ESC to cancel)"
            status = self.font_sm.render(status_txt, True, status_col)
            self.screen.blit(status, (lx, 50))
            return

        # ── Title ─────────────────────────────────────────────────────────
        _, _, title_y, *_ = self._panel_layout()
        title = self.font_lg.render("⚔  Agent Config", True, COL_TEXT)
        self.screen.blit(title, (lx, title_y))

        # ── Field labels (sit loff px above their widget) ──────────────
        def label(text, x, widget_y):
            t = self.font_sm.render(text, True, COL_LABEL)
            self.screen.blit(t, (x, widget_y - loff))

        # ── Widgets ───────────────────────────────────────────────────────
        for w in [self.btn_select_mob, self.btn_select_pc, self.btn_clear, self.btn_save, self.btn_load]:
            w.draw(self.screen)

        # Current save-file hint (updates when user picks a different path)
        hint_txt = os.path.basename(self._save_path) if self._save_path else ""
        hint = self.font_sm.render(hint_txt, True, (100, 100, 130))
        self.screen.blit(hint, (lx, self.btn_begin_combat.rect.bottom + 4))

        # ── Long Rest button (only when agents are placed) ────────────────
        if self.bm.placed_agents:
            self.btn_long_rest.draw(self.screen)

        # ── Begin Combat button (only when agents are placed) ─────────────
        if self.bm.placed_agents:
            self.btn_begin_combat.draw(self.screen)

        # ── Edit Terrain button ────────────────────────────────────────────
        self.btn_edit_terrain.draw(self.screen)

        # ── Edit Lighting button ───────────────────────────────────────────
        self.btn_edit_lighting.draw(self.screen)

        # ── Toggle Lighting Overlay button ─────────────────────────────────
        self.btn_toggle_lighting.draw(self.screen)

        # ── Quit button ────────────────────────────────────────────────────
        self.btn_quit.draw(self.screen)

        # ── Grid / map stats (bottom of panel) ───────────────────────────
        def text(txt, x, y, color=COL_LABEL):
            """Plain text blit with no offset (unlike label() which is for widgets)."""
            t = self.font_sm.render(txt, True, color)
            self.screen.blit(t, (x, y))

        info_y = sh - 72
        text(f"Grid: {self.bm.grid_cols}×{self.bm.grid_rows}  "
             f"cell={self.bm.cell_pixel_size}px  scale={self.map_scale:.2f}",
             lx, info_y)
        text(f"Walls: {len(self.bm.walls)}   Blocked: {len(self.bm.disallowed_cells)}",
             lx, info_y + 18)
        text(f"Agents placed: {len(self.bm.placed_agents)}", lx, info_y + 36)

    # ─────────────────────────────────────────────────────────────────────
    #  Event handling
    # ─────────────────────────────────────────────────────────────────────
    def _panel_rect(self):
        return pygame.Rect(self._panel_x(), 0, PANEL_W, self.screen.get_height())

    def _handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            # ── Terrain editor gets first pick when open ──────────────────
            if self.terrain_editor.active:
                self.terrain_editor.handle(event)
                # Handle close/save for terrain editor
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self._terrain_regions = self.terrain_editor.terrain_regions
                    self._save_terrain()
                    self._apply_terrain_to_battle_map()
                    self.terrain_editor.close()
                    # Recalculate reach and attack overlays if an agent is selected
                    if self.selected_idx >= 0:
                        self._update_reach()
                        self._update_attack_overlay()
                continue

            # ── Lighting editor gets priority when open ──────────────────
            if self.lighting_editor.active:
                self.lighting_editor.handle(event)
                continue

            # ── Terrain placement dialog gets priority when open ────────────
            if self.terrain_placement_dialog.active:
                self.terrain_placement_dialog.handle(event)
                continue

            # ── Modals get first pick when open ───────────────────────────
            if self.file_browser.active:
                self.file_browser.handle(event, self.screen)
                continue
            if self.stats_dialog.active:
                self.stats_dialog.handle(event, self.screen)
                continue
            # Selection dialogs get priority (handle before parent dialogs)
            if self.weapon_selection_dialog.visible:
                if self.weapon_selection_dialog.handle(event):
                    continue
            if self.armor_selection_dialog.visible:
                if self.armor_selection_dialog.handle(event):
                    continue
            if self.spell_selection_dialog.visible:
                if self.spell_selection_dialog.handle(event):
                    continue

            # Parent dialogs
            if self.weapon_dialog.active:
                self.weapon_dialog.handle(event, self.screen)
                continue
            if self.armor_dialog.active:
                self.armor_dialog.handle(event, self.screen)
                continue
            if self.weapons_dialog.active:
                self.weapons_dialog.handle(event, self.screen)
                continue
            if self.spell_dialog.active:
                self.spell_dialog.handle(event, self.screen)
                continue
            # ── Placement mode (floating agent) ───────────────────────────────
            if self.placement_mode_active:
                if event.type == pygame.MOUSEMOTION:
                    mx, my = event.pos
                    # Check if mouse is on the map
                    if self.map_rect.collidepoint(mx, my):
                        self.placement_cell = self._screen_to_cell(mx, my)
                        if self.placement_cell:
                            self.placement_valid = self._can_place(self.placement_cell, self.placement_config.size)
                        else:
                            self.placement_valid = False
                    else:
                        self.placement_cell = None
                        self.placement_valid = False
                    continue
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    # Place the agent immediately on the map
                    if self.placement_cell and self.placement_valid:
                        cfg = self.placement_config
                        cfg.start_col = self.placement_cell.col
                        cfg.start_row = self.placement_cell.row
                        # Save stats + weapons for all existing agents before
                        # apply_agent_configs() recreates them from scratch
                        existing = self.bm.placed_agents
                        saved = [(self.combat.get_agent_stats(self.bm, i),
                                  self.combat.get_agent_weapons(self.bm, i))
                                 for i in range(len(existing))]
                        self.combat.add_agent_config(self.bm, cfg)
                        self.combat.apply_agent_configs(self.bm)
                        # Restore previously saved stats + weapons (spell slots are in stats)
                        for i, (st, wps) in enumerate(saved):
                            self.combat.set_agent_stats(self.bm, i, st)
                            self.combat.set_agent_weapons(self.bm, i, wps)
                        # Apply mob stats and auto-weapons to the newly placed agent
                        idx = len(self.bm.placed_agents) - 1
                        if self.selected_mob_stats:
                            d_d_stats = self._mob_stats_to_d_d_stats(self.selected_mob_stats)
                            self.combat.set_agent_stats(self.bm, idx, d_d_stats)
                            # For auto-weapons, we need to update the weapons array
                            current_weapons = list(self.combat.get_agent_weapons(self.bm, idx))
                            # Check if all weapons are empty
                            has_weapons = any(w.name for w in current_weapons)
                            if not has_weapons:
                                # Fill empty weapon slots with auto-weapons
                                auto_weapons = self._auto_weapons_from_mob_stats(self.selected_mob_stats)
                                for i, auto_w in enumerate(auto_weapons):
                                    if i < 3:
                                        current_weapons[i] = auto_w
                                self.combat.set_agent_weapons(self.bm, idx, current_weapons)
                        elif self._pending_pc_class:
                            # Apply PC stats (class/level and spell slots already set)
                            self.combat.set_agent_stats(self.bm, idx, self._pending_pc_stats)
                            self._pending_pc_class = None
                            self._pending_pc_stats = None
                        self.sprites.clear()
                        self.placement_mode_active = False
                        self.placement_config = None
                        self.placement_cell = None
                    continue
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    # Cancel placement
                    self.placement_mode_active = False
                    self.placement_config = None
                    self.placement_cell = None
                    continue

            # Context menu sits above normal map events but below modals.
            if self.context_menu.visible:
                if self.context_menu.handle(event):
                    continue

            # ── Keyboard shortcuts ────────────────────────────────────────
            if event.type == pygame.KEYDOWN:
                # Delete / Backspace removes the selected placed agent,
                # but ONLY when not in combat.
                if event.key in (pygame.K_DELETE, pygame.K_BACKSPACE) \
                        and not self.combat_active:
                    if self.selected_idx >= 0:
                        idx = self.selected_idx
                        self.bm.remove_agent(idx)
                        # Weapon data lives in C++ and is removed with the agent.
                        self.selected_idx        = -1
                        self.drag_idx            = -1
                        self._reach_walk         = []
                        self._reach_fly          = []
                        self._reach_set          = set()
                        self._attack_cells_melee = []
                        self._attack_cells_rnorm = []
                        self._attack_cells_rlong = []

            if event.type == pygame.VIDEORESIZE:
                self._reposition_panel()

            # ── Map area: drag-and-drop ───────────────────────────────────
            on_map = not self._panel_rect().collidepoint(
                *getattr(event, 'pos', (-1, -1)))

            # Right-click on a placed agent → context menu (disabled during combat)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3 and on_map \
                    and not self.combat_active:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    if hit >= 0:
                        pt = self.bm.placed_agents[hit]
                        # Capture hit by value for the lambdas.
                        def _open_stats(h=hit):
                            pt2   = self.bm.placed_agents[h]
                            stats = self.combat.get_agent_stats(self.bm, h)
                            class_name = stats.character_class.name
                            char_level = stats.char_level
                            is_npc = stats.is_npc
                            npc_spell_groups = self._agent_meta.get(h, {}).get("npc_spell_groups", {})
                            armor = self.combat.get_agent_armor(self.bm, h)
                            self.stats_dialog.open(
                                self.screen, h, pt2.name, stats,
                                class_name, char_level,
                                self._on_stats_ok,
                                is_npc=is_npc,
                                npc_spell_groups=npc_spell_groups,
                                armor_list=armor)
                        def _open_weapons(h=hit):
                            pt2 = self.bm.placed_agents[h]
                            weapon_array = self.combat.get_agent_weapons(self.bm, h)
                            def _on_weapons_done():
                                # Collect weapons from dialog and save back to combat engine
                                cpp_weapons = []
                                for weapon_dict in self.weapons_dialog.current_weapons:
                                    if weapon_dict.get("name"):
                                        cpp_weapons.append(_dict_to_weapon(weapon_dict))
                                    else:
                                        cpp_weapons.append(rpg.Weapon())
                                self.combat.set_agent_weapons(self.bm, h, cpp_weapons)
                            self.weapons_dialog.open(self.screen, h, pt2.name, weapon_array,
                                                    self.weapon_selection_dialog, _on_weapons_done,
                                                    self.combat, self.bm)
                        def _open_spells(h=hit):
                            pt2 = self.bm.placed_agents[h]
                            spell_dicts = [self._spell_to_dict(h, j, s)
                                           for j, s in enumerate(self.combat.get_agent_spells(self.bm, h))]
                            def _open_spell_selector():
                                self.spell_selection_dialog.show(self.spell_dialog._on_spell_selected)
                            self.spell_dialog.open(
                                self.screen, h, pt2.name,
                                spell_dicts,
                                self._on_spell_done,
                                add_spell_callback=_open_spell_selector)
                        def _open_armor(h=hit):
                            pt2 = self.bm.placed_agents[h]
                            armor_array = self.combat.get_agent_armor(self.bm, h)
                            def _on_armor_done():
                                # Collect armor from dialog and save back to combat engine
                                cpp_armor = []
                                for armor_dict in self.armor_dialog.current_armor:
                                    if armor_dict.get("name"):
                                        cpp_armor.append(_dict_to_armor(armor_dict))
                                    else:
                                        cpp_armor.append(rpg.Armor())
                                self.combat.set_agent_armor(self.bm, h, cpp_armor)
                            self.armor_dialog.open(self.screen, h, pt2.name, armor_array,
                                                  self.armor_selection_dialog, _on_armor_done)
                        self.context_menu.show(
                            event.pos,
                            [("Edit Stats",   _open_stats),
                             ("Edit Weapons", _open_weapons),
                             ("Edit Armor",   _open_armor),
                             ("Edit Spells",  _open_spells)],
                            self.screen.get_size()
                        )

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and on_map:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    hit = self._agent_at(cell)
                    if self.combat_active:
                        # Pending attack: resolve against the clicked agent.
                        if self.pending_attack_slot and hit >= 0:
                            self._resolve_combat_attack(hit)
                        elif self.pending_spell_slot:
                            if self.pending_spell_is_aoe:
                                self._resolve_spell_cast_aoe(cell)
                            elif hit >= 0:
                                # Check line of sight for single-target spells
                                caster_idx = self._current_agent_idx()
                                if caster_idx >= 0 and caster_idx < len(self.bm.placed_agents):
                                    caster = self.bm.placed_agents[caster_idx]
                                    target = self.bm.placed_agents[hit]
                                    if self.bm.has_line_of_sight(caster.origin, caster.size, target.origin, target.size):
                                        self._resolve_spell_cast(hit)
                                    else:
                                        self._combat_log_add("No line of sight to target!")
                                else:
                                    self._resolve_spell_cast(hit)
                        else:
                            # Only allow dragging the current combatant.
                            cur = self._current_agent_idx()
                            if hit == cur and hit >= 0:
                                pt = self.bm.placed_agents[hit]
                                self.drag_idx    = hit
                                self.drag_origin = rpg.Cell(pt.origin.col, pt.origin.row)
                                self.drag_offset = (cell.col - pt.origin.col,
                                                    cell.row - pt.origin.row)
                                self.drag_cell   = rpg.Cell(pt.origin.col, pt.origin.row)
                                self.drag_valid  = True
                                # Keep selected_idx on the current combatant.
                    else:
                        # Normal mode: drag any agent or deselect.
                        # But disable dragging if jump overlay is active (use jump instead)
                        if hit >= 0 and not self.jump_overlay_active:
                            pt = self.bm.placed_agents[hit]
                            self.drag_idx    = hit
                            self.drag_origin = rpg.Cell(pt.origin.col, pt.origin.row)
                            self.drag_offset = (cell.col - pt.origin.col,
                                                cell.row - pt.origin.row)
                            self.drag_cell   = rpg.Cell(pt.origin.col, pt.origin.row)
                            self.drag_valid  = True
                            self.selected_idx = hit
                            self._update_reach()
                            self._update_attack_overlay()
                        else:
                            self.selected_idx        = -1
                            self._reach_walk         = []
                            self._reach_fly          = []
                            self._reach_set          = set()
                            self._attack_cells_melee = []
                            self._attack_cells_rnorm = []
                            self._attack_cells_rlong = []

            if event.type == pygame.MOUSEMOTION and self.pending_spell_is_aoe:
                if on_map:
                    self.spell_hover_cell = self._screen_to_cell(*event.pos)
                else:
                    self.spell_hover_cell = None

            if event.type == pygame.MOUSEMOTION and self.drag_idx >= 0:
                cell = self._screen_to_cell(*event.pos)
                if cell is not None:
                    pt   = self.bm.placed_agents[self.drag_idx]
                    tcol = cell.col - self.drag_offset[0]
                    trow = cell.row - self.drag_offset[1]
                    self.drag_cell  = rpg.Cell(tcol, trow)
                    self.drag_valid = self._can_place(
                        self.drag_cell, pt.size, exclude_idx=self.drag_idx)
                    # Restrict to the computed reach (walk ∪ fly).
                    # Outside combat an empty reach means no speed → allow
                    # free repositioning.  Inside combat an empty reach means
                    # movement is exhausted → block the drag entirely.
                    if self.drag_valid:
                        if self._reach_set:
                            self.drag_valid = (
                                self.drag_cell.col, self.drag_cell.row
                            ) in self._reach_set
                        elif self.combat_active:
                            self.drag_valid = False   # no movement remaining

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if self.drag_idx >= 0:
                    if self.drag_valid and self.drag_cell is not None:
                        # Calculate Manhattan distance moved (for running jump qualification)
                        ag_old = self.bm.placed_agents[self.drag_idx]
                        dist_moved = abs(self.drag_cell.col - ag_old.origin.col) + abs(self.drag_cell.row - ag_old.origin.row)
                        dist_moved *= 5  # Each cell = 5 feet

                        # Compute Chebyshev distance (D&D 5e diagonal = 5 ft).
                        print(f"[Movement] Attempting to move agent {self.drag_idx} to ({self.drag_cell.col},{self.drag_cell.row}) using {self.move_type}")
                        # Debug: check terrain types along the path
                        print(f"[Movement] Terrain at dest: {self.bm.get_terrain_type(self.drag_cell)}")

                        # Opportunity attack: check if agent is moving away from adjacent threats
                        agents = self.bm.placed_agents
                        moving_agent = agents[self.drag_idx]
                        pre_adjacent = set(self.combat.threatening_agents(self.bm, self.drag_idx)) if self.combat_active else set()

                        # Check if destination would leave all threat zones
                        move_leaves_all_threats = False
                        if self.combat_active and pre_adjacent and not moving_agent.conditions.disengaging:
                            move_leaves_all_threats = True
                            for threat_idx in pre_adjacent:
                                if threat_idx >= len(agents):
                                    continue
                                threat_agent = agents[threat_idx]
                                # Calculate Chebyshev distance from threat to destination
                                dc = max(threat_agent.origin.col - self.drag_cell.col,
                                        self.drag_cell.col - (threat_agent.origin.col + threat_agent.size - 1),
                                        0)
                                dr = max(threat_agent.origin.row - self.drag_cell.row,
                                        self.drag_cell.row - (threat_agent.origin.row + threat_agent.size - 1),
                                        0)
                                dist = max(dc, dr)
                                if dist <= 1:  # Still within reach of this threat
                                    move_leaves_all_threats = False
                                    break

                        # If move would leave all threats, trigger OA first
                        if move_leaves_all_threats:
                            self.pending_move_idx = self.drag_idx
                            self.pending_move_cell = self.drag_cell
                            self.pending_move_type = self.move_type
                            for threat_idx in sorted(pre_adjacent):
                                if threat_idx >= len(agents): continue
                                t = agents[threat_idx]
                                if (not t.conditions.reaction_used
                                        and not t.conditions.incapacitated
                                        and t.stats.hp_cur > 0):
                                    self._opportunity_queue.append((threat_idx, self.drag_idx))
                            self._combat_log_add(f"{moving_agent.name} is threatened! Opportunity attacks triggered.")
                            self._process_opportunity_queue()
                        else:
                            # Normal move - no threat violation
                            move_success = self.combat.move_agent(self.bm, self.drag_idx, self.drag_cell, self.move_type)
                            print(f"[Movement] Move result: {move_success}")
                            self._flush_combat_log()  # Flush any spell effect damage messages
                            if move_success:
                                # Read back the shared-pool budgets from C++.
                                ag = self.bm.placed_agents[self.drag_idx]
                                self.move_remaining_walk   = ag.walk_remaining
                                self.move_remaining_fly    = ag.fly_remaining
                                self.move_remaining_swim   = ag.swim_remaining
                                self.move_remaining_burrow = ag.burrow_remaining
                                self.last_movement_dist = dist_moved  # Track most recent movement for running jump
                                print(f"[Movement] Agent successfully moved to ({ag.origin.col},{ag.origin.row})")
                            else:
                                print(f"[Movement] Move failed - likely blocked by terrain")
                        self.selected_idx = self.drag_idx
                        self._update_reach()
                        self._update_attack_overlay()
                    # else: agent stays at original position (C++ not updated)
                    self.drag_idx = -1
                    self.drag_cell = None

            # ── Handle jump clicks ────────────────────────────────────────────
            if self.jump_overlay_active and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                if on_map:
                    cell = self._screen_to_cell(*event.pos)
                    # Check if clicked cell is in jump range (compare by coordinates)
                    is_jump_cell = any(c.col == cell.col and c.row == cell.row for c in self.jump_reachable_cells)
                    if is_jump_cell:
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self._execute_jump(idx, cell)

            # ── Mob selection dialog ──────────────────────────────────────
            if not self.combat_active:
                if self.mob_dialog.handle(event):
                    pass  # Event was consumed by dialog

                # ── Panel widgets ─────────────────────────────────────────────
                # Select Mob button
                if self.btn_select_mob.clicked(event):
                    self.mob_dialog.show(lambda mob: self._on_mob_selected(mob))

                # Select PC
                if self.btn_select_pc.clicked(event):
                    pc_classes = ["Barbarian", "Bard", "Cleric", "Druid", "Fighter", "Monk", "Paladin", "Ranger", "Rogue", "Sorcerer", "Warlock", "Wizard"]
                    options = [(cls, lambda c=cls: self._on_pc_class_selected(c)) for cls in pc_classes]
                    px_popup = self._panel_x() + self._PANEL_PAD
                    self.context_menu.show((px_popup, 100), options, self.screen.get_size())

                # Clear All
                if self.btn_clear.clicked(event):
                    self.bm.clear_agents()
                    self.bm.clear_terrain_effects()
                    self.selected_idx        = -1
                    self.drag_idx            = -1
                    self._attack_cells_melee = []
                    self._attack_cells_rnorm = []
                    self._attack_cells_rlong = []

                # Save — open browser in save mode
                if self.btn_save.clicked(event):
                    start = os.path.dirname(self._save_path) or self._map_dir
                    self.file_browser.open(
                        start, self._on_save_path_chosen,
                        save_mode=True,
                        extensions=JSON_EXTS,
                        default_filename=os.path.basename(self._save_path)
                    )

                # Load — open browser in load mode
                if self.btn_load.clicked(event):
                    start = os.path.dirname(self._save_path) or self._map_dir
                    self.file_browser.open(
                        start, self._on_load_path_chosen,
                        save_mode=False,
                        extensions=JSON_EXTS
                    )

                # Long Rest — reset all spell slots
                if self.btn_long_rest.clicked(event):
                    self._on_long_rest()

                # Remove pending agent by clicking ✕
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    list_y = self.btn_clear.rect.bottom + 20 + 18
                    px_rm = self._panel_x()
                    for i in range(len(self.pending_configs)):
                        rx = px_rm + PANEL_W - 22
                        rb = pygame.Rect(rx, list_y + i*18 - 1, 16, 16)
                        if rb.collidepoint(event.pos):
                            self.pending_configs.pop(i)
                            break

                # Begin Combat
                if self.btn_begin_combat.clicked(event):
                    self._start_combat()

                # Edit Terrain
                if self.btn_edit_terrain.clicked(event):
                    self.terrain_editor.open(self.map_surf, self._terrain_regions, self.bm)

                # Edit Lighting
                if self.btn_edit_lighting.clicked(event):
                    light_sources = []
                    if os.path.exists(self._lighting_path):
                        try:
                            with open(self._lighting_path, 'r') as f:
                                data = json.load(f)
                                light_sources = data.get("light_sources", [])
                        except:
                            light_sources = []
                    self.lighting_editor.open(self.map_surf, self.bm, self, light_sources)

                # Toggle Lighting Overlay
                if self.btn_toggle_lighting.clicked(event):
                    self.show_lighting_overlay = not self.show_lighting_overlay
                    self.btn_toggle_lighting.text = "Lighting: ON" if self.show_lighting_overlay else "Lighting: OFF"

                # Quit
                if self.btn_quit.clicked(event):
                    return False

            else:
                # ── Combat panel buttons ───────────────────────────────────
                _ev_idx = self._current_agent_idx()
                _has_wpn = (0 <= _ev_idx < len(self.bm.placed_agents) and
                            len(self.combat.get_agent_weapons(self.bm, _ev_idx)) > 0)
                _has_offhand = (0 <= _ev_idx < len(self.bm.placed_agents) and
                                any(w.off_hand for w in self.combat.get_agent_weapons(self.bm, _ev_idx)))
                if not self.action_used:
                    if _has_wpn and self.btn_cbt_atk_action.clicked(event):
                        self._start_attack("action")
                    if self.btn_cbt_pass_action.clicked(event):
                        self.action_used = True
                    if self.btn_cbt_dash.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            agent = self.bm.placed_agents[idx]
                            self.bm.apply_dash(idx)
                            self.move_remaining_walk   = agent.walk_remaining
                            self.move_remaining_fly    = agent.fly_remaining
                            self.move_remaining_swim   = agent.swim_remaining
                            self.move_remaining_burrow = agent.burrow_remaining
                            self._combat_log_add(f"{agent.name}: Dashing (+{self.combat.get_agent_stats(self.bm, idx).speed_walk}ft)")
                            self._update_reach()
                        self.action_used = True
                    if self.btn_cbt_dodge.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self.bm.placed_agents[idx].dodge()
                            self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Dodging")
                        self.action_used = True
                    if self.btn_cbt_disengage.clicked(event):
                        idx = self._current_agent_idx()
                        if 0 <= idx < len(self.bm.placed_agents):
                            self.bm.placed_agents[idx].disengage()
                            self._combat_log_add(f"{self.bm.placed_agents[idx].name}: Disengaging")
                        self.action_used = True
                    if self.btn_cbt_long_jump.clicked(event):
                        if not self.pending_spell_slot:  # Don't allow jump while casting spell
                            self._toggle_jump_overlay()
                    if self.btn_cbt_spell_action.clicked(event):
                        self._start_cast_spell("action")
                if not self.bonus_used:
                    if _has_offhand and self.btn_cbt_atk_bonus.clicked(event):
                        self._start_attack("bonus")
                    if self.btn_cbt_spell_bonus.clicked(event):
                        self._start_cast_spell("bonus")
                    if self.btn_cbt_pass_bonus.clicked(event):
                        self.bonus_used = True
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for mv_mt, mv_rect in self._move_type_btns.items():
                        if mv_rect.collidepoint(event.pos):
                            self.move_type = mv_mt
                            self._update_reach()
                            break
                if self.btn_cbt_place_terrain.clicked(event):
                    self.terrain_placement_dialog.open(self.map_surf, self.bm, self)
                if self.btn_show_terrain.clicked(event):
                    self.show_terrain = not self.show_terrain
                if self.btn_show_spell_effects.clicked(event):
                    self.show_spell_effects = not self.show_spell_effects
                if self.btn_cbt_end_turn.clicked(event):
                    self._advance_turn()
                    self._flush_combat_log()
                if self.btn_cbt_end_combat.clicked(event):
                    self._end_combat()
                if self.btn_cbt_drop_concentration.clicked(event):
                    self._drop_concentration()

        return True

    # ─────────────────────────────────────────────────────────────────────
    #  Main loop
    # ─────────────────────────────────────────────────────────────────────
    def run(self):
        running = True
        while running:
            running = self._handle_events()
            self.screen.fill(COL_BG)
            self._draw_map()
            self._draw_agents()
            self._draw_panel()
            self.terrain_editor.draw(self.screen)          # modal — always on top
            self.lighting_editor.draw(self.screen)         # modal — always on top
            self.terrain_placement_dialog.draw(self.screen)  # modal — always on top
            self.file_browser.draw(self.screen)     # modal — always on top
            self.stats_dialog.draw(self.screen)    # modal — always on top
            self.weapon_dialog.draw(self.screen)   # modal — always on top
            self.armor_dialog.draw(self.screen)    # modal — always on top
            self.weapons_dialog.draw(self.screen)  # modal — always on top
            self.spell_dialog.draw(self.screen)    # modal — always on top
            self.spell_selection_dialog.draw(self.screen)  # modal — always on top
            self.armor_selection_dialog.draw(self.screen)  # modal — always on top
            self.weapon_selection_dialog.draw(self.screen)  # modal — always on top
            self.mob_dialog.draw(self.screen)      # modal — always on top
            self.context_menu.draw(self.screen)    # popup — topmost
            pygame.display.flip()
            self.clock.tick(60)
        # Clean up temporary terrain effects before quitting
        self.bm.clear_terrain_effects()
        self._clear_temporary_terrain()
        self._save_terrain()
        pygame.quit()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python main.py <map_image.png>")
    App(sys.argv[1]).run()
