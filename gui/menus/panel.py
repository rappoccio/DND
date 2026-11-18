"""The combat panel's rendering of the ActionMenu — S3 of M2.

`App._draw_combat_panel` builds `app._action_menu` once per frame and these helpers
turn it into pixels. Layout lives here and legality lives in `actions.py`; the split is
the whole point of the phase, so resist putting a rule back in here.

The click side stays on `App`: `App._action_clicked` is the gate every panel click
goes through, the way `_ask_actor` is for prompts, and it reaches the widget through
`cbt_btn` here. `App._BTN_H` stays on `App` too, because the pre-combat layout shares it.

The On Deck section is drawn here as well. It is the one part of the panel that is not an
action: each row deploys a group of reserves, and the click that does it is handled in
`App._handle_events` against the rects this leaves in `app.on_deck_item_rects`.
"""

import lair
import pygame

from actions import METAMAGIC_ID_BY_VALUE, METAMAGIC_OPTIONS
from constants import (COL_BTN_ATK, COL_BTN_ATK_HOV, COL_BTN_DANGER, COL_BTN_DASH,
                       COL_BTN_DASH_HOV, COL_BTN_DISENG, COL_BTN_DISENG_HOV, COL_BTN_DODGE,
                       COL_BTN_DODGE_HOV, COL_BTN_ENDTURN, COL_BTN_ENDTURN_HOV, COL_BTN_SPELL,
                       COL_BTN_SPELL_HOV, COL_INITIATIVE_CUR, COL_INPUT_ACTIVE, COL_INPUT_BG,
                       COL_LABEL, COL_PANEL_BORDER, COL_TEXT, PANEL_W)
from widgets import Button


def init_combat_panel(app):
    """Create the buttons shown exclusively in the combat panel."""
    px  = app._panel_x() + app._PANEL_PAD
    W   = PANEL_W - app._PANEL_PAD * 2
    HW  = W // 2 - 2
    B   = app._BTN_H

    # Dummy Y (will be set in _draw_combat_panel)
    dummy_y = 0

    app.btn_cbt_atk_action  = Button(pygame.Rect(px,       dummy_y, HW, B),
                                     "⚔ Attack",
                                     COL_BTN_ATK, COL_BTN_ATK_HOV, app.font_md)
    app.btn_cbt_unarmed     = Button(pygame.Rect(px,       dummy_y, HW, B),
                                     "👊 Unarmed",
                                     COL_BTN_ATK, COL_BTN_ATK_HOV, app.font_md)
    # Dhampir Vampiric Bite: opens the Drain / Strengthen pick, then a bite target.
    app.btn_cbt_vampiric_bite = Button(pygame.Rect(px,     dummy_y, W, B),
                                     "🧛 Vampiric Bite",
                                     (120, 30, 45), (160, 50, 65), app.font_md)
    app.btn_cbt_dash        = Button(pygame.Rect(px,               dummy_y, HW, B),
                                     "Dash",
                                     COL_BTN_DASH, COL_BTN_DASH_HOV, app.font_md)
    app.btn_cbt_dodge       = Button(pygame.Rect(px+HW+4,         dummy_y, HW, B),
                                     "Dodge",
                                     COL_BTN_DODGE, COL_BTN_DODGE_HOV, app.font_md)
    app.btn_cbt_disengage   = Button(pygame.Rect(px,     dummy_y, HW, B),
                                     "Disengage",
                                     COL_BTN_DISENG, COL_BTN_DISENG_HOV, app.font_md)
    app.btn_cbt_hide        = Button(pygame.Rect(px,       dummy_y, HW, B),
                                     "Hide",
                                     (150, 150, 150), (180, 180, 180), app.font_md)
    app.btn_cbt_hide_bonus  = Button(pygame.Rect(px,       dummy_y, HW, B),
                                     "Hide",
                                     (150, 150, 150), (180, 180, 180), app.font_md)
    app.btn_cbt_dash_bonus  = Button(pygame.Rect(px,       dummy_y, HW, B),
                                     "Dash",
                                     COL_BTN_DASH, COL_BTN_DASH_HOV, app.font_md)
    app.btn_cbt_disengage_bonus = Button(pygame.Rect(px,   dummy_y, HW, B),
                                     "Disengage",
                                     COL_BTN_DISENG, COL_BTN_DISENG_HOV, app.font_md)
    app.btn_cbt_patient_defense = Button(pygame.Rect(px,   dummy_y, HW, B),
                                     "Patient Defense",
                                     (180, 150, 200), (210, 180, 230), app.font_md)
    app.btn_cbt_step_of_wind = Button(pygame.Rect(px,   dummy_y, HW, B),
                                     "Step of the Wind",
                                     (160, 180, 200), (190, 210, 230), app.font_md)
    app.btn_cbt_hand_of_healing = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Hand of Healing",
                                     (150, 200, 160), (180, 230, 190), app.font_md)
    app.btn_cbt_wholeness_of_body = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Wholeness of Body",
                                     (150, 200, 160), (180, 230, 190), app.font_md)
    # Use Item: drink a carried potion / administer one to an adjacent creature (a Bonus
    # Action), or throw a flask or a Net (replacing one attack of the Attack action). Shown
    # whenever the actor has anything in its pack it can still pay for.
    app.btn_cbt_use_item    = Button(pygame.Rect(px, dummy_y, W, B),
                                     "🧪 Use Item",
                                     (110, 160, 130), (140, 190, 160), app.font_md)
    # Burning [Hazard] (Alchemist's Fire): an action to drop Prone and roll the flames out.
    app.btn_cbt_extinguish  = Button(pygame.Rect(px, dummy_y, W, B),
                                     "🔥 Extinguish (Prone)",
                                     (200, 130, 80), (230, 160, 110), app.font_md)
    # Net: an action to make a DC 10 STR check freeing yourself — or a creature within 5 ft.
    app.btn_cbt_escape_net  = Button(pygame.Rect(px, dummy_y, W, B),
                                     "🕸 Free from Net",
                                     (150, 160, 120), (180, 190, 150), app.font_md)
    app.btn_cbt_atk_bonus   = Button(pygame.Rect(px,       dummy_y, HW, B),
                                     "⚔ Bonus Atk",
                                     COL_BTN_ATK, COL_BTN_ATK_HOV, app.font_md)
    # Nick (weapon mastery): relocate the off-hand attack into the Attack action, freeing the
    # bonus action. Shown after the Attack action when the off-hand weapon has Nick + the agent
    # has Weapon Mastery + the off-hand attack hasn't been spent yet.
    app.btn_cbt_nick        = Button(pygame.Rect(px,       dummy_y, W, B),
                                     "🗡 Nick: Off-hand Atk",
                                     COL_BTN_ATK, COL_BTN_ATK_HOV, app.font_md)
    app.btn_cbt_shove_push  = Button(pygame.Rect(px,       dummy_y, HW, B),
                                     "🔨 Shove",
                                     (140, 100, 150), (160, 120, 170), app.font_md)
    app.btn_cbt_shove_prone = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                     "⬇ Trip",
                                     (140, 100, 150), (160, 120, 170), app.font_md)
    # Grapple is no longer a bonus action — it is an Unarmed Strike option (see
    # _show_unarmed_menu) that counts against the Attack action's attack budget. Only the
    # Escape-from-grapple bonus action survives here.
    app.btn_cbt_grapple_esc = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                     "💨 Escape",
                                     (150, 120, 80), (180, 150, 110), app.font_md)
    app.btn_cbt_grapple_drop = Button(pygame.Rect(px+HW+4,  dummy_y, HW, B),
                                     "🔓 Drop",
                                     (150, 120, 80), (180, 150, 110), app.font_md)
    # Telekinetic feat — Telekinetic Shove (bonus action, 30 ft, STR save or pushed 5 ft).
    # Until F10 was fixed this was called `btn_cbt_telekinetic` and the Psi Warrior's
    # constructor below REBOUND the same attribute, so this label had never been drawn.
    app.btn_cbt_telekinetic_feat = Button(pygame.Rect(px,  dummy_y, W, B),
                                     "🌀 Telekinetic Shove",
                                     (110, 90, 170), (140, 120, 200), app.font_md)
    app.btn_cbt_spell_action= Button(pygame.Rect(px, dummy_y, W, B),
                                     "✨ Cast Spell",
                                     COL_BTN_SPELL, COL_BTN_SPELL_HOV, app.font_md)
    app.btn_cbt_spell_bonus = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "✨ Spell",
                                     COL_BTN_SPELL, COL_BTN_SPELL_HOV, app.font_md)
    app.btn_cbt_charge_arcane_ward = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "🔮 Ward",
                                     (120, 100, 180), (150, 130, 210), app.font_md)
    app.btn_cbt_wild_shape = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "🐺 Wild",
                                     (100, 150, 100), (130, 180, 130), app.font_md)
    app.btn_cbt_long_jump   = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Jump",
                                     (100, 150, 200), (120, 170, 220), app.font_md)
    app.btn_cbt_prone       = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "Go Prone",
                                     (180, 100, 100), (220, 140, 140), app.font_md)
    app.btn_cbt_standup     = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "Stand Up",
                                     (150, 180, 100), (180, 220, 130), app.font_md)
    app.btn_cbt_pause_resume = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "⏸ Pause",
                                     (200, 150, 80), (230, 180, 110), app.font_md)
    app.btn_cbt_reaction_timer = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "React 60s",
                                     (120, 140, 170), (150, 170, 200), app.font_md)
    app.btn_cbt_table       = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "Table…",
                                     (95, 95, 75), (130, 130, 100), app.font_md)
    app.btn_cbt_end_turn    = Button(pygame.Rect(px, dummy_y, W, B),
                                     "End Turn",
                                     COL_BTN_ENDTURN, COL_BTN_ENDTURN_HOV, app.font_md)
    app.btn_cbt_place_terrain = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "🌍 Place Terrain",
                                     (150, 120, 80), (180, 150, 110), app.font_md)
    app.btn_cbt_end_combat  = Button(pygame.Rect(px, dummy_y, W, B),
                                     "End Combat",
                                     COL_BTN_DANGER, (180, 70, 70), app.font_md)
    app.btn_cbt_drop_concentration = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Drop Concentration",
                                     (150, 100, 100), (200, 130, 130), app.font_md)
    app.btn_cbt_drop_weapon_main = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Drop Main Hand",
                                     (130, 80, 60), (170, 110, 90), app.font_md)
    app.btn_cbt_drop_weapon_off  = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Drop Off Hand",
                                     (130, 80, 60), (170, 110, 90), app.font_md)
    app.btn_cbt_drop_weapon_rng  = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Drop Ranged",
                                     (130, 80, 60), (170, 110, 90), app.font_md)
    # Ravenloft items (M6 / M10): the label is the ActionMenu's ("Luck (n)").
    app.btn_cbt_use_luck = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Luck",
                                     (60, 120, 70), (90, 160, 100), app.font_md)
    app.btn_cbt_regain_slot = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Regain Slot (Rod)",
                                     (80, 70, 140), (110, 100, 180), app.font_md)
    app.btn_cbt_use_portent = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Use Portent Die",
                                     (200, 160, 100), (220, 180, 120), app.font_md)
    app.btn_cbt_rage = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Rage (Bonus)",
                                     (180, 80, 60), (220, 110, 90), app.font_md)
    app.btn_cbt_magical_cunning = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Magical Cunning",
                                     (120, 80, 180), (150, 110, 210), app.font_md)
    app.btn_cbt_healing_light = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Healing Light",
                                     (210, 180, 70), (240, 210, 100), app.font_md)
    app.btn_cbt_steady_aim = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Steady Aim",
                                     (90, 140, 190), (120, 170, 220), app.font_md)
    app.btn_cbt_turn_undead = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Turn Undead",
                                     (190, 190, 220), (220, 220, 250), app.font_md)
    app.btn_cbt_divine_intervention = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Divine Intervention",
                                     (235, 215, 130), (255, 235, 160), app.font_md)
    app.btn_cbt_radiance = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Radiance of the Dawn",
                                     (230, 200, 90), (255, 225, 120), app.font_md)
    app.btn_cbt_preserve_life = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Preserve Life",
                                     (120, 200, 130), (150, 230, 160), app.font_md)
    app.btn_cbt_invoke_duplicity = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Invoke Duplicity",
                                     (170, 130, 200), (200, 160, 230), app.font_md)
    app.btn_cbt_move_duplicity = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Move Duplicate",
                                     (170, 130, 200), (200, 160, 230), app.font_md)
    app.btn_cbt_swap_duplicity = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Swap w/ Duplicate",
                                     (150, 110, 185), (185, 145, 215), app.font_md)
    app.btn_cbt_path_to_the_grave = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Path to the Grave",
                                     (110, 110, 120), (150, 150, 165), app.font_md)
    app.btn_cbt_move_hunters_mark = Button(pygame.Rect(px, dummy_y, W, B),
                                     "🎯 Move Mark",
                                     (60, 130, 80), (90, 170, 110), app.font_md)
    app.btn_cbt_war_priest = Button(pygame.Rect(px, dummy_y, W, B),
                                     "War Priest (Bonus Attack)",
                                     (200, 120, 90), (235, 150, 115), app.font_md)
    # Auto-offer Bite vs a creature this attacker is Grappling (Vampire Bite). Highlighted red-violet.
    app.btn_cbt_bite_grappled = Button(pygame.Rect(px, dummy_y, W, B),
                                     "🧛 Bite (grappled)",
                                     (160, 40, 70), (200, 70, 100), app.font_md)
    app.btn_cbt_gwm_hew = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Hew (Bonus Attack)",
                                     (190, 100, 70), (225, 135, 100), app.font_md)
    app.btn_cbt_horde_breaker = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Horde Breaker (Extra Attack)",
                                     (190, 100, 70), (225, 135, 100), app.font_md)
    app.btn_cbt_sudden_strike = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Sudden Strike (Extra Attack)",
                                     (80, 90, 130), (110, 120, 170), app.font_md)
    # Boon of Dimensional Travel — Blink Steps: a ≤30-ft teleport armed right after the Attack/Magic
    # action; clicking enters a destination pick (see _resolve_blink_steps). Deep-violet like teleports.
    app.btn_cbt_blink_steps = Button(pygame.Rect(px, dummy_y, W, B),
                                     "✦ Blink Steps (30 ft)",
                                     (90, 60, 170), (125, 90, 210), app.font_md)
    app.btn_cbt_martial_arts = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Martial Arts (Bonus Attack)",
                                     (180, 110, 200), (210, 140, 230), app.font_md)
    app.btn_cbt_flurry_of_blows = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Flurry of Blows (2 Attacks)",
                                     (180, 110, 200), (210, 140, 230), app.font_md)
    app.btn_cbt_one_with_shadows = Button(pygame.Rect(px, dummy_y, W, B),
                                     "One with Shadows (Invisible)",
                                     (90, 80, 150), (120, 110, 190), app.font_md)
    # Boon of the Night Spirit — Merge with Shadows: BA Invisible while in Dim Light/Darkness.
    app.btn_cbt_merge_shadows = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Merge with Shadows (Invisible)",
                                     (70, 70, 130), (100, 100, 170), app.font_md)
    app.btn_cbt_second_wind = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Second Wind (Bonus Action)",
                                     (180, 150, 100), (220, 190, 130), app.font_md)
    app.btn_cbt_bm_maneuver = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Maneuver (Bonus Action)",
                                     (150, 120, 90), (190, 160, 120), app.font_md)
    app.btn_cbt_action_surge = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Action Surge",
                                     (220, 140, 90), (255, 170, 120), app.font_md)
    app.btn_cbt_lay_on_hands = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Lay on Hands",
                                     (180, 200, 150), (220, 240, 190), app.font_md)
    app.btn_cbt_grant_inspiration = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Grant Inspiration (Bonus Action)",
                                     (200, 160, 220), (230, 195, 250), app.font_md)
    app.btn_cbt_use_inspiration = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Use Inspiration Die",
                                     (180, 150, 220), (215, 185, 250), app.font_md)
    app.btn_cbt_mantle = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Mantle of Inspiration (Bonus Action)",
                                     (210, 150, 230), (240, 190, 255), app.font_md)
    app.btn_cbt_mantle_majesty = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Mantle of Majesty (Bonus Action)",
                                     (190, 120, 220), (225, 175, 250), app.font_md)
    app.btn_cbt_unbreakable_majesty = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Unbreakable Majesty (Bonus Action)",
                                     (190, 110, 210), (225, 165, 245), app.font_md)
    app.btn_cbt_beguiling_restore = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Restore Beguiling Magic (1 Inspiration)",
                                     (170, 130, 200), (205, 165, 235), app.font_md)
    app.btn_cbt_sacred_weapon = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Sacred Weapon (Bonus Action)",
                                     (200, 180, 110), (240, 220, 150), app.font_md)
    app.btn_cbt_corona = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Corona of Light (Action)",
                                     (235, 215, 120), (255, 240, 160), app.font_md)
    app.btn_cbt_vow_of_enmity = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Vow of Enmity (Channel Oath)",
                                     (170, 60, 70), (210, 90, 100), app.font_md)
    app.btn_cbt_avenging_angel = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Avenging Angel (Bonus Action)",
                                     (200, 70, 90), (240, 105, 125), app.font_md)
    app.btn_cbt_elder_champion = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Elder Champion (Bonus Action)",
                                     (70, 140, 90), (100, 180, 120), app.font_md)
    app.btn_cbt_inspiring_smite = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Inspiring Smite (Channel Oath)",
                                     (210, 180, 80), (245, 215, 115), app.font_md)
    app.btn_cbt_living_legend = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Living Legend (Bonus Action)",
                                     (215, 160, 60), (250, 195, 95), app.font_md)
    # Psi Warrior — Telekinetic Movement. A separate widget from the feat's above:
    # a Psi Warrior who has taken the feat is offered both, and one widget could
    # only ever be painted twice and clicked once (F10).
    app.btn_cbt_telekinetic_psi = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Telekinetic Movement",
                                     (140, 160, 210), (170, 190, 240), app.font_md)
    app.btn_cbt_intimidating_presence = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Intimidating Presence (Bonus Action)",
                                     (180, 80, 60), (220, 110, 90), app.font_md)
    app.btn_cbt_zealous_presence = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Zealous Presence (Bonus Action)",
                                     (140, 100, 180), (170, 130, 210), app.font_md)
    app.btn_cbt_clairvoyant_combatant = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Clairvoyant Combatant (Bonus Action)",
                                     (90, 70, 150), (120, 100, 190), app.font_md)
    app.btn_cbt_tireless = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Tireless (Magic Action)",
                                     (90, 150, 120), (120, 185, 155), app.font_md)
    app.btn_cbt_fey_reinforcements = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Fey Reinforcements (Magic Action)",
                                     (120, 90, 160), (150, 120, 195), app.font_md)
    app.btn_cbt_misty_wanderer = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Misty Wanderer (Bonus Action)",
                                     (100, 110, 170), (130, 140, 205), app.font_md)
    app.btn_cbt_natures_veil = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Nature's Veil (Bonus Action)",
                                     (70, 120, 90), (100, 155, 120), app.font_md)
    app.btn_cbt_psychic_veil = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Psychic Veil (Magic Action)",
                                     (110, 90, 150), (140, 120, 185), app.font_md)
    app.btn_cbt_psychic_teleport = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Psychic Teleportation (Bonus)",
                                     (110, 90, 150), (140, 120, 185), app.font_md)
    app.btn_cbt_shadow_step = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Shadow Step (Bonus)",
                                     (80, 60, 120), (110, 90, 150), app.font_md)
    app.btn_cbt_cloak_of_shadows = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Cloak of Shadows (Bonus)",
                                     (60, 40, 100), (90, 70, 130), app.font_md)
    # Archfey Warlock — Steps of the Fey (Bonus), the rider selector, and Misty Escape (Reaction).
    app.btn_cbt_fey_effect = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Fey Step: None",
                                     (70, 50, 110), (100, 80, 140), app.font_md)
    app.btn_cbt_steps_of_fey = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Steps of the Fey (Bonus)",
                                     (80, 60, 120), (110, 90, 150), app.font_md)
    app.btn_cbt_misty_escape = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Misty Escape (React)",
                                     (60, 40, 100), (90, 70, 130), app.font_md)
    app.btn_cbt_shadow_arts_darkness = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Shadow Arts: Darkness (1 Focus)",
                                     (50, 35, 85), (80, 60, 120), app.font_md)
    app.btn_cbt_elemental_attunement = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Elemental Attunement (1 Focus)",
                                     (120, 70, 40), (160, 100, 60), app.font_md)
    app.btn_cbt_elemental_burst = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Elemental Burst (2 Focus)",
                                     (140, 60, 40), (185, 90, 60), app.font_md)
    app.btn_cbt_quivering_palm = Button(pygame.Rect(px, dummy_y, W, B),
                                     "💥 Detonate Quivering Palm",
                                     (120, 40, 40), (165, 60, 60), app.font_md)
    app.btn_cbt_companion = Button(pygame.Rect(px, dummy_y, W, B),
                                     "🐾 Primal Companion",
                                     (90, 140, 90), (120, 175, 120), app.font_md)
    app.btn_cbt_command_companion = Button(pygame.Rect(px, dummy_y, W, B),
                                     "🐾 Command Companion",
                                     (90, 140, 90), (120, 175, 120), app.font_md)
    app.btn_cbt_beasts_strike = Button(pygame.Rect(px, dummy_y, W, B),
                                     "🐾 Beast's Strike",
                                     (90, 140, 90), (120, 175, 120), app.font_md)
    app.btn_cbt_familiar = Button(pygame.Rect(px, dummy_y, W, B),
                                     "😈 Pact Familiar",
                                     (110, 80, 140), (145, 110, 175), app.font_md)
    app.btn_cbt_dragon_wings = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Dragon Wings",
                                     (180, 100, 60), (220, 140, 90), app.font_md)
    app.btn_cbt_draconic_resistance = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Draconic Resistance (1 SP)",
                                     (60, 130, 80), (90, 160, 110), app.font_md)
    # Sorcerer Innate Sorcery (L1, Bonus Action): +1 spell save DC and advantage on spell
    # attacks for 1 minute. At L7 (Sorcery Incarnate) it also unlocks two-option Metamagic
    # casts, and can be paid for with 2 SP once its uses are gone.
    app.btn_cbt_innate_sorcery = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Innate Sorcery",
                                     (150, 60, 150), (185, 95, 185), app.font_md)
    # Sorcerer Metamagic arm-toggles (Phases 2–3): one button per working option,
    # including Twinned (Phase 3). Named by action id (`btn_cbt_metamagic_careful`,
    # …) rather than held in a dict keyed by int(MetamagicOption): Step 0.3's F4 was
    # that the dict slipped past the stale-rect guard below, and a dict cannot be
    # dispatched by id. Positioned and gated by the ActionMenu each draw.
    for _mm_val, _mm_name, _mm_sp, _mm_note in METAMAGIC_OPTIONS:
        setattr(app, "btn_cbt_" + METAMAGIC_ID_BY_VALUE[int(_mm_val)],
                Button(pygame.Rect(px, dummy_y, W, B), _mm_name,
                       (80, 62, 135), (120, 100, 185), app.font_md))
    app.btn_cbt_bend_luck = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Bend Luck (1 SP)",
                                     (100, 60, 180), (130, 90, 210), app.font_md)
    app.btn_cbt_tides_of_chaos = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Tides of Chaos",
                                     (120, 70, 200), (150, 100, 230), app.font_md)
    # Boon of Fate (epic boon): prime ±2d4 on the next D20 Test (1/rest).
    app.btn_cbt_boon_of_fate = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Boon of Fate (2d4)",
                                     (150, 120, 40), (190, 155, 60), app.font_md)
    app.btn_cbt_trance_of_order = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Trance of Order",
                                     (70, 110, 180), (100, 145, 215), app.font_md)
    app.btn_cbt_bastion_of_law = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Bastion of Law",
                                     (60, 120, 150), (90, 155, 185), app.font_md)
    app.btn_cbt_clockwork_cavalcade = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Clockwork Cavalcade",
                                     (60, 140, 130), (90, 175, 165), app.font_md)
    app.btn_cbt_revelation_in_flesh = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Revelation in Flesh (1 SP)",
                                     (140, 70, 150), (170, 100, 180), app.font_md)
    app.btn_cbt_warping_implosion = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Warping Implosion",
                                     (150, 60, 110), (185, 90, 140), app.font_md)
    app.btn_cbt_wild_magic_extra_action = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Wild Magic: Extra Action",
                                     (180, 80, 180), (210, 110, 210), app.font_md)
    app.btn_cbt_haste_action = Button(pygame.Rect(px, dummy_y, W, B),
                                     "⚡ Haste Action",
                                     (70, 130, 180), (100, 160, 210), app.font_md)
    app.btn_cbt_wild_magic_bonus_cast = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Wild Magic: Cast as Bonus",
                                     (160, 70, 170), (195, 105, 205), app.font_md)
    app.btn_cbt_wild_magic_teleport = Button(pygame.Rect(px, dummy_y, W, B),
                                     "Wild Magic: Teleport 20ft",
                                     (140, 60, 160), (175, 95, 190), app.font_md)
    app.btn_show_terrain = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "Show Terrain",
                                     (100, 150, 150), (130, 180, 200), app.font_md)
    dummy_y += B + 5
    app.btn_show_spell_effects = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "Show Spell Effects",
                                     (150, 120, 180), (180, 150, 210), app.font_md)
    dummy_y += B + 5
    app.btn_show_visible_targets = Button(pygame.Rect(px, dummy_y, HW, B),
                                     "Show Visible",
                                     (100, 180, 150), (130, 210, 180), app.font_md)



def cbt_btn(app, action_id: str):
    """The widget backing an action id. Ids match the `btn_cbt_` suffix by design.

    One id, one widget, with no exceptions since F10 was fixed — the alias table
    that pointed `telekinetic_feat` and `telekinetic_psi` at the same button is
    gone, and with it the pass that painted that button twice.
    """
    return getattr(app, "btn_cbt_" + action_id)


def menu_group(app, group: str, only=None, skip=()):
    """This frame's actions in `group`, in build order. `only`/`skip` split one
    group across several rows without teaching `actions.py` about rows."""
    return [a for a in app._action_menu.values()
            if a.group == group and a.id not in skip
            and (only is None or a.id in only)]


def draw_action_row(app, actions, lx, y, w, gap, trail=None, font=None):
    """Lay `actions` out as one equal-width row and draw them; return the new `y`.

    An empty row consumes no vertical space at all — that is how "the option is
    not on offer" reaches the layout now, in place of a positioning branch.

    `font` draws the row in something other than the panel default and restores
    `font_md` afterwards, which is what the narrow rows (§1's two, §4's five-up)
    have always done by hand.
    """
    if not actions:
        return y
    n = len(actions)
    tw = (w - (n - 1) * gap) // n
    row_font = font if font is not None else app.font_md
    widths = row_widths(app, [a.label for a in actions], tw, w, gap, row_font)
    x = lx
    for j, act in enumerate(actions):
        btn = cbt_btn(app, act.id)
        btn.text = act.label
        btn.rect.x = x
        btn.rect.y = y
        btn.rect.w = widths[j]
        x += widths[j] + gap
        if font is not None:
            btn.font = font
        btn.draw(app.screen)
        if font is not None:
            btn.font = app.font_md
    return y + app._BTN_H + (gap if trail is None else trail)


# A label needs this much more than its own glyphs before it stops looking clipped:
# two pixels of air on each side of the text `Button.draw` centres in the rect.
_ROW_LABEL_PAD = 4


def row_widths(app, labels, tw, w, gap, font):
    """Column widths for one `draw_action_row`: equal, unless equal would clip.

    F12: `Button.draw` centres its text and never clips, so a label wider than its
    column bleeds across the gap into its neighbour — which the structural golden
    cannot see, because every rect is exactly what the layout intended. The five-up
    posture row is where it bit: at `font_sm`, Disengage needs 76px, Go Prone 65 and
    Stand Up 64 in a 60px column.

    So the row sizes itself to its labels when it has to and can: each column takes
    the width its own text needs, and the slack left over is handed out evenly so the
    row still spans `w` exactly and its right edge still lines up with every other
    row. A row whose labels do NOT fit even at their natural widths keeps the equal
    split — a squashed-but-even row beats an arbitrary truncation, and the smoke
    test's overflow sweep is what reports it.

    Rows that already fit are untouched, which is why this moved only the posture
    row's rects in the golden.
    """
    need = [font.size(t)[0] + _ROW_LABEL_PAD for t in labels]
    span = w - (len(labels) - 1) * gap
    if max(need) <= tw or sum(need) > span:
        return [tw] * len(labels)
    widths = [x + (span - sum(need)) // len(need) for x in need]
    for j in range(span - sum(widths)):     # the division's remainder, leftmost first
        widths[j] += 1
    return widths


def draw_action_stack(app, actions, lx, y, w, gap):
    """Draw each action as its own full-width row; return the new `y`.

    §7 is a COLUMN of one-button rows, not a grid, so a run of converted buttons is
    n rows — not the n-up `draw_action_row` builds. The two shapes are one call
    apart and the mistake is silent: it turns a Monk's whole band into a three-up
    that still passes every availability test. An empty run consumes no space, same
    as an empty row.
    """
    for act in actions:
        y = draw_action_row(app, [act], lx, y, w, gap)
    return y


def draw_on_deck_section(app, lx, W, px, y):
    """Render the On Deck reserve list (grouped by name); each row deploys that group
    on click. Returns the new y. Resets on_deck_item_rects every call so a row that is
    no longer drawn can't capture clicks at a stale location."""
    app.on_deck_item_rects = []
    groups = app._on_deck_groups()
    if not groups:
        return y
    pygame.draw.line(app.screen, COL_PANEL_BORDER,
                     (px + 6, y), (px + PANEL_W - 6, y))
    y += 8
    app.screen.blit(app.font_sm.render("🎴 On Deck — click to deploy", True,
                                       (210, 180, 90)), (lx, y))
    y += 16
    for name, count in groups:
        label = f"  ⮕ {name}" + (f" ×{count}" if count > 1 else "")
        app.screen.blit(app.font_sm.render(label, True, COL_TEXT), (lx, y))
        app.on_deck_item_rects.append((pygame.Rect(lx, y, W, 16), name))
        y += 16
    return y


def draw_tracker_section(app, lx, W, y):
    """Tracker mode's initiative sheet (plans/INITIATIVE_TRACKER_PLAN.md T3), drawn in place
    of the engine's initiative list. Returns the new y.

    The DM view toggle (D1, T4b) heads it in either phase.
    Collecting: one number field per row (a mob group shares one), then Roll for monsters
    and Start. Running: the round, Prev / Next, and the order with ↑/↓ on each row; an
    entry that joins a later round is dimmed. A row shows its HP when D1 allows; a click
    on it moves the ▶ there and opens its HP box (T4), which sits under the sheet in
    either phase. Click targets
    go to `app._tracker_hits` as (rect, kind, arg), reset every call;
    `App._tracker_handle_event` acts on them."""
    app._tracker_hits = []
    t = app.tracker
    B = app._BTN_H
    font = app.font_sm
    agents = app.bm.placed_agents

    def text(s, x, yy, col=COL_TEXT):
        app.screen.blit(font.render(s, True, col), (x, yy))

    def button(label, rect, kind, arg=None):
        Button(rect, label, font=font).draw(app.screen)
        app._tracker_hits.append((rect, kind, arg))

    hw = (W - 4) // 2
    # D1: the table view by default; DM view lifts the fog and shows every number.
    button("DM view: ON" if app.dm_view else "DM view: OFF", pygame.Rect(lx, y, W, B),
           "dm_view")
    y += B + 6
    if t.phase == "collecting":
        text("Initiative: click a row, type its total", lx, y, COL_LABEL)
        y += 18
        fw = 44
        for label, idxs, _pc in app._tracker_rows():
            key = tuple(idxs)
            editing = app._tracker_edit == key
            total = t.entry(idxs[0]).total
            val = app._tracker_edit_text if editing else ("" if total is None else str(total))
            field = pygame.Rect(lx, y, fw, 18)
            pygame.draw.rect(app.screen, COL_INPUT_ACTIVE if editing else COL_INPUT_BG,
                             field, border_radius=3)
            pygame.draw.rect(app.screen, COL_PANEL_BORDER, field, 1, border_radius=3)
            s = font.render(val or "—", True, COL_TEXT if val else COL_LABEL)
            app.screen.blit(s, (field.x + 6, field.centery - s.get_height() // 2))
            text(label, lx + fw + 8, y + 2)
            app._tracker_hits.append((pygame.Rect(lx, y, W, 18), "field", key))
            y += 20
        y += 4
        button("Roll for monsters", pygame.Rect(lx, y, hw, B), "roll")
        button("Start", pygame.Rect(lx + hw + 4, y, W - hw - 4, B), "start")
        return _draw_hp_box(app, lx, W, y + B + 6, text, button)

    if t.phase == "running":
        text(f"Round {t.round}", lx, y, COL_INITIATIVE_CUR)
        y += 18
        button("◀ Prev", pygame.Rect(lx, y, hw, B), "prev")
        button("Next ▶", pygame.Rect(lx + hw + 4, y, W - hw - 4, B), "next")
        y += B + 6
        aw = 22
        for i, e in enumerate(t.entries):
            if e.removed:
                continue
            cur = i == t.turn
            waiting = e.joins_round > t.round
            col = COL_INITIATIVE_CUR if cur else ((120, 120, 120) if waiting else COL_TEXT)
            tot = " —" if e.total is None else f"{e.total:2d}"
            name = lair.tracker_name(app, e.agent_idx)
            text(f"{'▶ ' if cur else '  '}{tot}  {name}{'  (next round)' if waiting else ''}",
                 lx, y + 2, col)
            hp = _hp_label(app, e.agent_idx) if e.agent_idx >= 0 else ""
            if hp:
                s = font.render(hp, True, col)
                app.screen.blit(s, (lx + W - 2 * aw - 8 - s.get_width(), y + 2))
            button("↑", pygame.Rect(lx + W - 2 * aw - 2, y, aw, 18), "up", e.agent_idx)
            button("↓", pygame.Rect(lx + W - aw, y, aw, 18), "down", e.agent_idx)
            app._tracker_hits.append((pygame.Rect(lx, y, W - 2 * aw - 4, 18),
                                      "row", e.agent_idx))
            y += 20
        y = _draw_hp_box(app, lx, W, y + 4, text, button)
    return y


def _hp_label(app, idx) -> str:
    """ "12/30" (+ "+5" temp). The tracker sits on the DM's console, so it shows every
    token's HP whatever D1's view; D1 still governs the map's HP bars and the log. """
    s = app.combat.get_agent_stats(app.bm, idx)
    return f"{s.hp_cur}/{s.hp_max}" + (f" +{s.temp_hp}" if s.temp_hp else "")


def _draw_hp_box(app, lx, W, y, text, button):
    """The HP box (T4) on `app._tracker_hp`: its HP, the amount typed so
    far, and −N / +N / Temp / Max. Closed if its token has left the board."""
    idx = app._tracker_hp
    agents = app.bm.placed_agents
    if not (0 <= idx < len(agents)) or agents[idx].removed_from_play:
        app._tracker_hp = -1
        return y
    B = app._BTN_H
    hp = _hp_label(app, idx)
    text(f"{agents[idx].name}: {hp}", lx, y, COL_INITIATIVE_CUR)
    y += 18
    field = pygame.Rect(lx, y, W - 30, 20)
    pygame.draw.rect(app.screen, COL_INPUT_ACTIVE, field, border_radius=3)
    pygame.draw.rect(app.screen, COL_PANEL_BORDER, field, 1, border_radius=3)
    val = app._tracker_hp_text
    text(val or "type an amount", field.x + 6, field.y + 3, COL_TEXT if val else COL_LABEL)
    button("×", pygame.Rect(lx + W - 26, y, 26, 20), "hp_close")
    y += 24
    qw = (W - 12) // 4
    for k, (label, op) in enumerate((("−N", "dmg"), ("+N", "heal"),
                                     ("Temp", "temp"), ("Max", "max"))):
        button(label, pygame.Rect(lx + k * (qw + 4), y, qw, B), "hp", op)
    return y + B + 6
