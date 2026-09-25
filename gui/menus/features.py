"""The per-feature menus — one creature, one feature, one question.

Twenty-two builders that are neither post-hit riders nor authoring menus: the Portent die,
the Arcane Ward, Wild Shape, the unarmed strike's three modes, Use Item, the companion
and familiar commands, a legendary action, Mantle of Majesty, the Dispel target pick,
the friendly-fire confirmation, Animate Dead, the Wild Magic surge, the Bard's
beguiling/bewitching offers, and the six the combat panel's action buttons open: the
Elements monk's Attunement and Burst, Bend Luck, Boon of Fate, Bastion of Law and the
Transmuted Spell damage type.

What they share is the judgement `_ask_actor` makes by default and every one of them
accepts: the creature acting is the creature answering, so `owner` is its controller.
They differ in which widget draws them — the popup, the value picker (`render="picker"`)
and the spell grid (`render="grid"`) are all represented here — which is a renderer
choice the bus takes as a hint, not a second kind of prompt.
"""

import pygame

import rpg_battle_map as rpg

# Pact of the Chain (Warlock invocation 18) familiar forms → DND2024_MonsterStats.json keys.
# The 2024 PHB list; all six are already in the bestiary. Unlike RAW Find Familiar, the chain
# familiar can attack, so it spawns with its real statblock weapons (same path as _resolve_summon).
PACT_CHAIN_FAMILIARS = ["Imp", "Pseudodragon", "Quasit", "Sprite", "Skeleton", "Venomous Snake"]

# Command spell word choices (label, SpellAction.command_word int), reused via the ElementPickerDialog.
# 0=Drop, 1=Flee, 2=Grovel, 3=Halt, 4=Approach. The engine maps each to an existing mechanic on a
# failed save (applyCommandEffect): Drop=drop weapons+Disarmed, Flee/Approach=1-turn movement
# restriction toward/away from the bard, Grovel=Prone, Halt=Incapacitated for one turn.
# `main.py`'s own Command site reads it from here — the table came out with the menu that
# draws it, and `main` already imports this module, so the dependency only runs one way.
COMMAND_WORD_OPTIONS = [("Drop", 0), ("Flee", 1), ("Grovel", 2), ("Halt", 3), ("Approach", 4)]

# Transmuted Spell (Sorcerer Metamagic): the six elemental damage types a spell's damage may be
# rewritten to (label, MagicDamage_t int). Matches the engine's isElemental set (Acid/Cold/Fire/
# Lightning/Poison/Thunder). Reused via the ElementPickerDialog at arm-time.
METAMAGIC_TRANSMUTE_OPTIONS = [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4), ("Poison", 6), ("Thunder", 9)]

# Monk Warrior of the Elements — the five legal elements for Elemental Attunement / Elemental Burst,
# as (label, MagicDamage_t int). Reused via the ElementPickerDialog. (Acid=0, Cold=1, Fire=2,
# Lightning=4, Thunder=9 — Force/Poison/etc. are not valid Elemental choices.)
ELEMENTAL_MONK_OPTIONS = [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4), ("Thunder", 9)]

# MagicDamage_t index → human-readable name (Acid=0 … Thunder=9). `main.py`'s Draconic Resistance
# log line reads it from here too, the same way it reads COMMAND_WORD_OPTIONS.
_DAMAGE_TYPE_NAMES = {0: "Acid", 1: "Cold", 2: "Fire", 3: "Force", 4: "Lightning",
                      5: "Necrotic", 6: "Poison", 7: "Psychic", 8: "Radiant", 9: "Thunder"}


def show_portent_dice_menu(app):
    """Show available portent dice for selection."""
    idx = app._current_agent_idx()
    if idx < 0:
        return
    stats = app.combat.get_agent_stats(app.bm, idx)
    if (stats.character_class != rpg.CharacterClass.Wizard or
        stats.wizard_subclass != rpg.WizardSubclass.Diviner):
        app._combat_log_add("Not a Diviner Wizard!")
        return
    if len(stats.portent_dice) == 0:
        app._combat_log_add("No portent dice available!")
        return

    # Create menu items for each portent die
    items = []
    for die_idx, die_value in enumerate(stats.portent_dice):
        label = f"⚔️  Portent d20 → {die_value}"
        items.append((label, lambda idx=die_idx: app._use_portent_die_at_index(idx)))

    app._ask_actor(idx, "action", f"{app._agent_name(idx)}: spend a Portent die", items,
                    anchor=pygame.mouse.get_pos())


def show_arcane_ward_menu(app):
    """Show available spell slots for Arcane Ward charging."""
    idx = app._current_agent_idx()
    if idx < 0:
        return
    stats = app.combat.get_agent_stats(app.bm, idx)
    if (stats.character_class != rpg.CharacterClass.Wizard or
        stats.wizard_subclass != rpg.WizardSubclass.Abjurer or
        stats.char_level < 3 or stats.temp_hp <= 0):
        app._combat_log_add("Cannot charge Arcane Ward!")
        return

    # Create menu items for available spell slots
    items = []
    max_ward = 2 * stats.char_level + (stats.intel - 10) // 2
    for slot_level in range(1, 10):
        remaining = stats.spell_slots_remaining[slot_level - 1]
        if remaining > 0:
            ward_gain = 2 * slot_level
            label = f"Level {slot_level} Slot (+{ward_gain} HP)"
            items.append((label, lambda lvl=slot_level: app._expend_arcane_ward_slot(lvl)))

    if not items:
        app._combat_log_add("No spell slots available!")
        return

    app._ask_actor(idx, "action", f"{app._agent_name(idx)}: charge the Arcane Ward", items,
                    anchor=pygame.mouse.get_pos())


def show_wild_shape_menu(app):
    """Show Wild Shape form options or end Wild Shape if already active."""
    idx = app._current_agent_idx()
    if idx < 0:
        return
    stats = app.combat.get_agent_stats(app.bm, idx)
    if stats.character_class != rpg.CharacterClass.Druid or stats.char_level < 2:
        app._combat_log_add("Cannot use Wild Shape!")
        return

    if stats.wild_shape_active:
        app.combat.deactivate_wild_shape(app.bm, idx)
        app._combat_log_add(f"{app.bm.placed_agents[idx].name}: Exits Wild Shape")
        app.bonus_used = True
        return

    ws_resource = stats.get_resource("Wild Shape")
    if ws_resource is None or ws_resource.current <= 0:
        app._combat_log_add("No Wild Shape uses remaining!")
        return

    import json
    import os
    # `beast_forms.json` sits in gui/, which is one directory UP from this package —
    # `__file__` was main.py's when this code lived there.
    gui_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    beast_path = os.path.join(gui_dir, "beast_forms.json")

    try:
        with open(beast_path, 'r') as f:
            beasts = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        app._combat_log_add("Error loading beast forms!")
        return

    # Determine CR cap and fly restriction based on level and circle
    level = stats.char_level
    allow_fly = level >= 8

    if stats.druid_circle == rpg.DruidCircle.CircleOfMoon:
        cr_cap = level / 3
    else:
        if level < 4:
            cr_cap = 0.25
        elif level < 8:
            cr_cap = 0.5
        else:
            cr_cap = 1.0

    # Filter available beasts
    available = []
    for beast in beasts:
        if beast['cr'] <= cr_cap and (allow_fly or not beast['fly_speed']):
            available.append(beast)

    if not available:
        app._combat_log_add("No valid wild shapes available!")
        return

    # Create menu items
    items = []
    for beast in available:
        label = f"🐺 {beast['name']} (CR {beast['cr']})"
        items.append((label, lambda b=beast['name']: app._activate_wild_shape(idx, b)))

    app._ask_actor(idx, "action", f"{app._agent_name(idx)}: choose a Wild Shape form", items,
                    anchor=pygame.mouse.get_pos())


def show_unarmed_menu(app, mouse_pos):
    """Show the unarmed strike options menu at mouse position."""
    items = [
        ("💥 Damage (1 + STR)", lambda: app._start_unarmed_punch()),
        ("🤝 Grapple",          lambda: app._start_unarmed_grapple()),
        ("🤜 Shove (push 5 ft)", lambda: app._start_unarmed_push()),
    ]
    # Diagnostic: confirm the handler fired even if the popup somehow fails to render.
    app._combat_log_add("Unarmed Strike: choose Damage / Grapple / Shove from the popup.")
    # Anchor the menu over the map (left of the panel) so it can't render under the
    # right-side combat panel where the Unarmed button lives.
    px, py = mouse_pos
    panel_left = app._panel_x()
    if px >= panel_left:
        px = max(8, panel_left - app.context_menu.MIN_W - 8)
    idx = app._current_agent_idx()
    app._ask_actor(idx, "action", f"{app._agent_name(idx)}: Unarmed Strike", items,
                    anchor=(px, py))


def show_use_item_menu(app, pos):
    """Pop the current actor's inventory: pick which carried item to use, then click a target.
    Items the actor can no longer pay for this turn (the Bonus Action is gone, or there is no
    attack left for a thrown flask to replace) are left out of the menu."""
    idx = app._current_agent_idx()
    if not (0 <= idx < len(app.bm.placed_agents)):
        return
    items = app.combat.get_agent_items(app.bm, idx)
    if not items:
        app._combat_log_add(f"{app.bm.placed_agents[idx].name} is carrying no items.")
        return

    def _affordable(it) -> bool:
        if it.action_type == rpg.ItemAction.AttackReplacement:
            return app._can_replace_attack(idx)
        if it.action_type == rpg.ItemAction.BonusAction:
            return not app.bonus_used
        if it.action_type == rpg.ItemAction.Action:
            return not app.action_used
        return True

    def _arm(slot):
        app.pending_use_item = slot
        it = items[slot]
        if it.type == rpg.ItemType.Thrown:
            prompt = f"Click a creature within {it.range} ft to throw {it.name}"
        else:
            where = "yourself" if it.range <= 0 else f"yourself or a creature within {it.range} ft"
            prompt = f"Click {where} to use {it.name}"
        app._combat_log_add(prompt + ".")

    opts = []
    for slot, it in enumerate(items):
        if not _affordable(it):
            continue
        cost = " — replaces an attack" if it.action_type == rpg.ItemAction.AttackReplacement else ""
        opts.append((f"{it.name} (x{it.quantity}, {app._item_menu_dice(it)}){cost}",
                     (lambda s=slot: _arm(s))))
    if not opts:
        app._combat_log_add(
            f"{app.bm.placed_agents[idx].name} has nothing left to spend on an item this turn.")
        return
    app._ask_actor(idx, "action", f"{app._agent_name(idx)}: use a carried item", opts,
                    anchor=pos)


def show_companion_menu(app):
    """Beast Master L3+: summon a Beast of the Land/Sea/Sky, or dismiss the
    active companion. Mirrors the Wild Shape menu (context_menu)."""
    idx = app._current_agent_idx()
    if idx < 0:
        return
    stats = app.combat.get_agent_stats(app.bm, idx)
    if (stats.character_class != rpg.CharacterClass.Ranger or
            stats.ranger_subclass != rpg.RangerSubclass.BeastMaster or
            stats.char_level < 3):
        app._combat_log_add("Only a Beast Master Ranger (L3+) has a Primal Companion.")
        return
    existing = app._find_companion_idx(idx)
    if existing >= 0:
        app._dismiss_companion(idx, existing)
        return
    items = [(f"🐾 Beast of the {form}",
              lambda f=form: app._summon_companion(idx, f))
             for form in ("Land", "Sea", "Sky")]
    app._ask_actor(idx, "action", f"{app._agent_name(idx)}: summon a Primal Companion",
                    items, anchor=pygame.mouse.get_pos())


def show_familiar_menu(app):
    """Pact of the Chain (L1+): summon one of the six familiar forms, or dismiss the
    active familiar (the button label toggles). Mirrors the Primal Companion / Wild
    Shape menus (context_menu)."""
    idx = app._current_agent_idx()
    if idx < 0:
        return
    stats = app.combat.get_agent_stats(app.bm, idx)
    if (stats.character_class != rpg.CharacterClass.Warlock or
            not stats.has_invocation(18)):
        app._combat_log_add("Only a Warlock with Pact of the Chain can summon a familiar.")
        return
    existing = app._find_familiar_idx(idx)
    if existing >= 0:
        app._dismiss_familiar(idx, existing)
        return
    items = [(f"😈 {form}", lambda f=form: app._summon_familiar(idx, f))
             for form in PACT_CHAIN_FAMILIARS]
    app._ask_actor(idx, "action", f"{app._agent_name(idx)}: summon a Pact familiar",
                    items, anchor=pygame.mouse.get_pos())


def show_legendary_action_menu(app, idx: int, st):
    """Context menu for creature idx: one entry per available action name + Pass."""
    name = app.bm.placed_agents[idx].name
    remaining = st.legendary_actions_current
    app._combat_log_add(
        f"{name}: {remaining} legendary action(s) available — choose one or pass.")
    app._flush_combat_log()
    options = [(a, (lambda a=a: app._choose_legendary_action(a)))
               for a in app._legendary_action_names_for(idx, st)]
    options.append((f"Pass ({remaining} left)", app._pass_legendary))
    app._ask_actor(idx, "action", f"{name}: legendary action ({remaining} left)", options)


def start_mantle_majesty(app, bard_idx: int):
    """College of Glamour Mantle of Majesty (bonus action). The FIRST use spends the once/long-rest
    resource, opens the 1-minute Concentration window, and casts Command for free; while the window
    is already active, the button just re-casts Command for free (bonus action, no resource).

    Flow: pick the Command word (ElementPickerDialog), then — only on confirm, so an Esc wastes
    nothing — activate the window if needed and set up a free single-target Command cast."""
    if app.bonus_used:
        app._combat_log_add("Bonus action already used this turn.")
        app._flush_combat_log()
        return
    stats = app.combat.get_agent_stats(app.bm, bard_idx)
    if not (stats.bard_subclass == rpg.BardCollege.Glamour and stats.char_level >= 6):
        return
    window_active = stats.mantle_majesty_turns > 0
    maj = stats.get_resource("Mantle of Majesty")
    if not window_active and not (maj and maj.current > 0):
        app._combat_log_add(
            f"{app.bm.placed_agents[bard_idx].name}: no Mantle of Majesty use left.")
        app._flush_combat_log()
        return
    spells = app.combat.get_agent_spells(app.bm, bard_idx)
    command_idx = next((i for i, sp in enumerate(spells) if sp.name == "Command"), -1)
    if command_idx < 0:
        app._combat_log_add("Mantle of Majesty: Command spell not prepared.")
        app._flush_combat_log()
        return

    def _on_word(chosen, bard_idx=bard_idx, command_idx=command_idx, window_active=window_active):
        word = chosen[0] if chosen else 3   # default Halt
        if not window_active:
            if not app.combat.activate_mantle_of_majesty(app.bm, bard_idx):
                app._flush_combat_log()
                return
            app._flush_combat_log()
        # Free single-target Command cast (bonus action, no slot). The bonus action is charged in
        # _consume_cast_slot; the slot is skipped in C++ via SpellAction.free_cast.
        app.pending_spell_slot         = "bonus"
        app.pending_spell_idx          = command_idx
        app.pending_spell_slot_level   = 0
        app.pending_spell_is_aoe       = False
        app.pending_spell_targets      = []
        app.pending_spell_num_targets  = 0
        app.pending_spell_damage_type  = -1
        app.pending_spell_free_cast    = True
        app.pending_spell_command_word = word
        app.pending_spell_curse_choice = -1
        app.pending_chromatic_active   = False
        app.pending_chromatic_chain    = []
        word_name = next((lbl for lbl, val in COMMAND_WORD_OPTIONS if val == word), "?")
        app._combat_log_add(
            f"Mantle of Majesty: casting Command ({word_name}) — click a target within 60 ft.")
        app._flush_combat_log()

    app._ask_actor(bard_idx, "action", "Command: choose a word",
                    [(lbl, (lambda v=val: _on_word([v]))) for lbl, val in COMMAND_WORD_OPTIONS],
                    render="picker", on_cancel=lambda: _on_word([]))


def begin_dispel_pick(app, hit, cell, pos):
    """Dispel Magic click: enumerate the dispellable ongoing spells at the aimed creature and/or
    cell and open a picker so the DM ends exactly one — a buff on an ally, a debuff on an enemy,
    or one of several overlapping AoEs. Casting is deferred until an entry is chosen; an empty
    target just logs and leaves the spell pending so the caster can re-aim."""
    caster = app._current_agent_idx()
    if caster < 0:
        return

    cands, seen = [], set()

    def _add(c_list):
        for c in c_list:
            key = (tuple(c.condition_ids), tuple(c.spell_effect_ids), tuple(c.terrain_ids))
            if key in seen:
                continue
            seen.add(key)
            cands.append(c)

    if hit is not None and hit >= 0:
        # A creature: its own spell-applied effects, plus any area magic it stands in.
        _add(app.combat.dispel_candidates_on_agent(app.bm, caster, hit))
        oc = app.bm.placed_agents[hit].origin
        _add(app.combat.dispel_candidates_at_cell(app.bm, caster, oc.col, oc.row))
    elif cell is not None:
        _add(app.combat.dispel_candidates_at_cell(app.bm, caster, cell.col, cell.row))

    if not cands:
        app._combat_log_add("No magic to dispel there.")
        return

    agents = app.bm.placed_agents
    options = []
    for c in cands:
        owner = (agents[c.owner_idx].name
                 if 0 <= c.owner_idx < len(agents) else "?")
        side  = "ally" if c.owner_is_ally else "enemy"
        label = f"{c.label} — L{c.level}, {owner} ({side})"
        options.append((label, lambda cc=c, h=hit, cl=cell: app._cast_dispel_selection(cc, h, cl)))
    app._ask_actor(caster, "target",
                    f"{app._agent_name(caster)}: what should Dispel Magic end?",
                    options, anchor=pos)


def confirm_friendly_harm(app, target_idx: int, on_confirm) -> None:
    """Faction rule 4: if the acting agent and target_idx are on the same team,
    ask the player to confirm before a harmful action (e.g. accidentally clicking
    a teammate). Non-allies (or no current actor) run on_confirm() immediately."""
    actor = app._current_agent_idx()
    if actor < 0 or not app._are_allies(actor, target_idx):
        on_confirm()
        return
    tgt_name = app.bm.placed_agents[target_idx].name
    options = [
        (f"Harm ally {tgt_name}!", on_confirm),
        ("Cancel", lambda: None),
    ]
    app._ask_actor(actor, "confirm",
                    f"{app._agent_name(actor)} is about to harm an ally — {tgt_name}",
                    options, anchor=app._agent_screen_pos(target_idx))


def resolve_animate_dead(app, corpse_idx):
    """Animate Dead (Divine Intervention D3): raise an undead servant from the picked
    corpse. The corpse (conditions.dead) is consumed — tombstoned — and a Skeleton or
    Zombie is spawned in its place on the caster's team via spawn_agent (the summon path,
    not the destructive applyAgentConfigs). The choice of undead is prompted here; the
    actual spawn/slot/action-economy happen in _finish_animate_dead.

    No summoner_idx link is set: Animate Dead is not a Concentration spell (24-hour
    duration), and the summoner link would let a later dropConcentration wrongly tombstone
    the undead. Faction inheritance alone makes it a player-controlled ally."""
    caster_idx = app._current_agent_idx()
    if caster_idx < 0 or not app.pending_spell_slot:
        return
    if not (0 <= corpse_idx < len(app.bm.placed_agents)):
        return
    corpse = app.bm.placed_agents[corpse_idx]
    cell        = rpg.Cell(corpse.origin.col, corpse.origin.row)
    slot        = app.pending_spell_slot
    slot_level  = app.pending_spell_slot_level
    free_cast   = app.pending_spell_free_cast
    items = [
        ("💀 Skeleton", lambda: app._finish_animate_dead(
            caster_idx, corpse_idx, cell, "Skeleton", slot, slot_level, free_cast)),
        ("🧟 Zombie", lambda: app._finish_animate_dead(
            caster_idx, corpse_idx, cell, "Zombie", slot, slot_level, free_cast)),
    ]
    app._ask_actor(caster_idx, "action",
                    f"{app._agent_name(caster_idx)}: Animate Dead — raise which undead?",
                    items, anchor=pygame.mouse.get_pos())
    app._combat_log_add("Animate Dead — choose the undead to raise from the corpse.")


def maybe_wild_magic_surge(app, caster_idx: int):
    """Run the Wild Magic Surge trigger after a slot-fueled cast. The engine gates on
    class/subclass/level itself (no-op for non-Wild-Magic casters) and rolls the d20 trigger.
    For a plain L3-13 surge the single rolled band is applied immediately; with Controlled Chaos
    (L14: two rolled bands) or Tamed Surge (L18: any band) we present a choice menu first."""
    if not (0 <= caster_idx < len(app.bm.placed_agents)):
        return
    offer = app.combat.offer_wild_magic_surge(app.bm, caster_idx)
    app._flush_combat_log()
    if not offer.surged:
        return
    if offer.can_choose_any:
        bands = list(range(1, 11))                    # Tamed Surge (L18): pick any band
    else:
        # 1 band normally, or 2 with Controlled Chaos (L14); dedupe identical rolls.
        bands = list(dict.fromkeys(offer.options))
    if not bands:
        return
    if len(bands) == 1:
        app._resolve_wild_magic_surge(caster_idx, bands[0], offer.tides_expended)
        return
    # A choice is available — let the player pick which surge to apply.
    name = app.bm.placed_agents[caster_idx].name
    kind = "Tamed Surge" if offer.can_choose_any else "Controlled Chaos"
    app._combat_log_add(f"⚡ {name}: {kind} — choose a Wild Magic Surge.")
    app._flush_combat_log()
    options = []
    for b in bands:
        desc = app.combat.wild_magic_surge_description(b)
        options.append((f"{b}: {desc[:46]}",
                        lambda bb=b, te=offer.tides_expended:
                            app._resolve_wild_magic_surge(caster_idx, bb, te)))
    app._ask_actor(caster_idx, "action", f"{name}: {kind} — choose a surge", options)


def maybe_offer_beguiling_magic(app, caster_idx: int, spell_idx: int):
    """If a L3+ College of Glamour bard just cast an Enchantment or Illusion spell using a spell
    slot (not a cantrip / free cast) and still has a Beguiling Magic use, begin the target-pick
    flow: click a creature within 60 ft, then choose Charmed or Frightened."""
    if not (0 <= caster_idx < len(app.bm.placed_agents)):
        return
    stats = app.combat.get_agent_stats(app.bm, caster_idx)
    if (stats.character_class != rpg.CharacterClass.Bard or
            stats.bard_subclass != rpg.BardCollege.Glamour or stats.char_level < 3):
        return
    beg = stats.get_resource("Beguiling Magic")
    if not (beg and beg.current > 0):
        return
    spells = app.combat.get_agent_spells(app.bm, caster_idx)
    if not (0 <= spell_idx < len(spells)):
        return
    sp = spells[spell_idx]
    if sp.school not in (rpg.SpellSchool.Enchantment, rpg.SpellSchool.Illusion):
        return
    if sp.level < 1:   # cantrips don't use a slot
        return
    # Present the offer as a MODAL popup at the caster rather than a bare combat-log line. This
    # lands right after any OnDeclareCast reaction popup (e.g. Counterspell); a quiet log message
    # there is easy to miss and the DM ends up pressing End Turn, silently wasting the once/rest
    # use. The popup consumes clicks (blocking End Turn) until the DM picks Use or Decline.
    app._ask_actor(
        caster_idx, "confirm",
        f"{app._agent_name(caster_idx)}: Beguiling Magic after {sp.name}?",
        [(f"Use Beguiling Magic ({sp.name})",
          lambda i=caster_idx: app._arm_beguiling_target_pick(i)),
         ("Decline Beguiling Magic", app._decline_beguiling_offer)])


def maybe_offer_bewitching_magic(app, caster_idx: int, spell_idx: int):
    """Archfey Bewitching Magic (L14): if the caster is an Archfey L14+ warlock that just cast an
    Enchantment or Illusion spell with a slot, offer a free Misty Step (30 ft, no slot/use/action)
    as part of the same action. Presented as a modal popup at the caster (like Beguiling Magic)."""
    if not (0 <= caster_idx < len(app.bm.placed_agents)):
        return
    stats = app.combat.get_agent_stats(app.bm, caster_idx)
    if (stats.character_class != rpg.CharacterClass.Warlock or
            stats.warlock_subclass != rpg.WarlockSubclass.Archfey or stats.char_level < 14):
        return
    spells = app.combat.get_agent_spells(app.bm, caster_idx)
    if not (0 <= spell_idx < len(spells)):
        return
    sp = spells[spell_idx]
    if sp.school not in (rpg.SpellSchool.Enchantment, rpg.SpellSchool.Illusion):
        return
    if sp.level < 1:   # cantrips don't use a slot
        return
    app._ask_actor(
        caster_idx, "confirm",
        f"{app._agent_name(caster_idx)}: Bewitching Magic after {sp.name}?",
        [(f"Bewitching Magic: free Misty Step ({sp.name})",
          lambda i=caster_idx: app._arm_bewitching_misty(i)),
         ("Decline Bewitching Magic", app._decline_bewitching_offer)])


def beguiling_pick_target(app, hit: int):
    """A creature was clicked for Beguiling Magic: validate range, then open the Charmed/Frightened
    picker and resolve the WIS save through the engine on confirm."""
    bard_idx = app.pending_beguiling_bard
    agents = app.bm.placed_agents
    if not (0 <= hit < len(agents)) or not (0 <= bard_idx < len(agents)):
        return
    if hit == bard_idx:
        app._combat_log_add("Beguiling Magic affects another creature, not yourself.")
        app._flush_combat_log()
        return
    if app._footprint_dist_ft(bard_idx, hit) > 60:
        app._combat_log_add("Beguiling Magic: that creature is more than 60 ft away.")
        app._flush_combat_log()
        return

    def _on_choice(chosen, bard_idx=bard_idx, hit=hit):
        app.pending_beguiling      = False
        app.pending_beguiling_bard = -1
        if not chosen:   # Esc/no pick → decline without spending the use
            app._combat_log_add("Beguiling Magic declined.")
            app._flush_combat_log()
            app._update_attack_overlay()
            return
        use_frightened = (chosen[0] == 1)
        app.combat.bard_beguiling_magic(app.bm, bard_idx, hit, use_frightened)
        app._flush_combat_log()
        app._update_attack_overlay()

    app._ask_actor(bard_idx, "action", "Beguiling Magic",
                    [("Charmed", lambda: _on_choice([0])),
                     ("Frightened", lambda: _on_choice([1]))],
                    render="picker", on_cancel=lambda: _on_choice([]))


def show_elemental_attunement_menu(app, idx):
    """Monk Warrior of the Elements (L3): pick the element for Elemental Attunement."""
    def _on_attune_elem(chosen, idx=idx):
        element = chosen[0] if chosen else -1
        if element < 0:
            return
        if app.combat.activate_elemental_attunement(app.bm, idx, element):
            app.action_used = True
            app._flush_combat_log()
            app._update_attack_overlay()
        else:
            app._combat_log_add(
                "Elemental Attunement: requires the Elements subclass (L3) and 1 Focus Point.")
    app._ask_actor(
        idx, "action", "Elemental Attunement: element",
        [(lbl, (lambda v=val: _on_attune_elem([v])))
         for lbl, val in ELEMENTAL_MONK_OPTIONS],
        render="picker", on_cancel=lambda: _on_attune_elem([]))


def show_elemental_burst_menu(app, idx):
    """Monk Warrior of the Elements: pick Elemental Burst's element, then arm the center-cell click."""
    def _on_burst_elem(chosen, idx=idx):
        element = chosen[0] if chosen else -1
        if element < 0:
            return
        app.pending_elemental_burst = element
        type_name = next((lbl for lbl, val in ELEMENTAL_MONK_OPTIONS
                          if val == element), "?")
        app._combat_log_add(
            f"Elemental Burst ({type_name}): click a center cell (or click yourself to cancel).")
    app._ask_actor(
        idx, "action", "Elemental Burst: element",
        [(lbl, (lambda v=val: _on_burst_elem([v])))
         for lbl, val in ELEMENTAL_MONK_OPTIONS],
        render="picker", on_cancel=lambda: _on_burst_elem([]))


def show_bend_luck_menu(app, idx, pos):
    """Wild Magic Sorcerer: Bend Luck — boost or penalize the next D20 roll by 1d4 (1 SP)."""
    def _apply_bend_luck(boost, idx=idx):
        v = app.combat.sorcerer_bend_luck(app.bm, idx, boost)
        if v > 0:
            sign = "+" if boost else "-"
            app._combat_log_add(
                f"{app.bm.placed_agents[idx].name}: Bend Luck — {sign}{v} to next D20 roll (1 SP)")
            app._flush_combat_log()
        else:
            app._combat_log_add("Bend Luck: not eligible (wrong subclass/level/SP)")
    app._ask_actor(
        idx, "action", f"{app._agent_name(idx)}: Bend Luck",
        [("Boost (+1d4)", lambda: _apply_bend_luck(True)),
         ("Penalty (-1d4)", lambda: _apply_bend_luck(False))],
        anchor=pos)


def show_boon_of_fate_menu(app, idx, pos):
    """Boon of Fate (Epic Boon): boost or penalize the next D20 Test by 2d4."""
    def _apply_boon_of_fate(boost, idx=idx):
        v = app.combat.apply_boon_of_fate(app.bm, idx, boost)
        if v > 0:
            sign = "+" if boost else "-"
            app._combat_log_add(
                f"{app.bm.placed_agents[idx].name}: Boon of Fate — {sign}{v} "
                f"to the next D20 Test (attack roll or saving throw)")
            app._flush_combat_log()
        else:
            app._combat_log_add("Boon of Fate: not available (no feat / already used this rest)")
            app._flush_combat_log()
    app._ask_actor(
        idx, "action", f"{app._agent_name(idx)}: Boon of Fate",
        [("Boost (+2d4)", lambda: _apply_boon_of_fate(True)),
         ("Penalty (-2d4)", lambda: _apply_boon_of_fate(False))],
        anchor=pos)


def show_bastion_of_law_menu(app, idx, pos):
    """Clockwork Sorcerer: Bastion of Law — spend 1 to 5 Sorcery Points, then click the
    creature to ward. With no SP it opens nothing."""
    stats = app.combat.get_agent_stats(app.bm, idx)
    sp_res = stats.get_resource("Sorcery Points")
    avail = min(5, sp_res.current if sp_res else 0)
    if avail < 1:
        return
    def _arm_bastion(n):
        app.pending_bastion_sp = n
        app.pending_bastion_of_law = True
        app._combat_log_add(
            f"Bastion of Law: click the creature to ward ({n} SP, {n}d8) — self or within 30 ft")
        app._flush_combat_log()
    app._ask_actor(
        idx, "action",
        f"{app._agent_name(idx)}: Bastion of Law — how many SP?",
        [(f"{n} SP ({n}d8)", (lambda n=n: _arm_bastion(n)))
         for n in range(1, avail + 1)],
        anchor=pos)


def show_metamagic_transmute_menu(app):
    """Transmuted Spell needs its replacement damage type chosen at arm time; the arming
    itself stays in `_handle_events`, and a cancel leaves the type unset (-1)."""
    def _on_mm_transmute(chosen):
        app.pending_metamagic_transmute_type = chosen[0] if chosen else -1
        tname = _DAMAGE_TYPE_NAMES.get(app.pending_metamagic_transmute_type, "?")
        app._combat_log_add(f"Transmuted Spell → {tname} damage.")
        app._flush_combat_log()
    app._ask_actor(
        app._current_agent_idx(), "action",
        "Transmuted Spell — new damage type",
        [(lbl, (lambda v=val: _on_mm_transmute([v])))
         for lbl, val in METAMAGIC_TRANSMUTE_OPTIONS],
        render="picker", on_cancel=lambda: _on_mm_transmute([]))
