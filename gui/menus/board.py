"""The right-click menus on the board — what the DM gets by right-clicking the map.

Three builders, one per thing a right-click can land on:

  · **a placed agent, out of combat** — the DM menu: edit the token's name, sprite,
    stats, gear and spells, its teams and On Deck state, the Evoker and Fiend extras,
    and two submenus (NPC automation, and who controls the token).
  · **an On Deck reserve, in combat** — recall just that one mob.
  · **an empty cell, with fog on** — reveal all fog, or reset it.

A dropped item is the fourth target, and its menu is `dm.show_item_context_menu`.

All three end in `_ask_dm`, for the same reason `dm.py`'s builders do: the owner is
pinned to the DM, never derived from whoever holds the token, so seating a player on a
creature cannot hand them its authoring menu.

`App._handle_events` keeps the part that is about the event: which button, whether the
click is on the map, whether combat is running, and which cell it hit. What a menu offers
once that is settled lives here.
"""

import os

import rpg_battle_map as rpg

from helpers import _dict_to_armor, _dict_to_item, _dict_to_weapon
from net.roster import DM_PRINCIPAL_ID, Role


def show_agent_menu(app, hit, pos):
    """The DM menu for placed agent `hit`, anchored at the click `pos`. The event loop
    only opens it out of combat."""
    pt = app.bm.placed_agents[hit]
    # Capture hit by value for the lambdas.
    def _open_stats(h=hit):
        pt2   = app.bm.placed_agents[h]
        stats = app.combat.get_agent_stats(app.bm, h)
        class_name = stats.character_class.name
        char_level = stats.char_level
        is_npc = stats.is_npc
        npc_spell_groups = app._agent_meta.get(h, {}).get("npc_spell_groups", {})
        armor = app.combat.get_agent_armor(app.bm, h)
        # Get subclass name from stats based on class
        subclass_name = "NONE"
        if class_name == "Barbarian":
            subclass_name = stats.barbarian_subclass.name
        elif class_name == "Wizard":
            subclass_name = stats.wizard_subclass.name
        elif class_name == "Fighter":
            subclass_name = stats.fighter_subclass.name
        elif class_name == "Druid":
            subclass_name = stats.druid_circle.name
        elif class_name == "Monk":
            subclass_name = stats.monk_subclass.name
        elif class_name == "Paladin":
            subclass_name = stats.paladin_oath.name
        elif class_name == "Warlock":
            subclass_name = stats.warlock_subclass.name
        elif class_name == "Rogue":
            subclass_name = stats.rogue_subclass.name
        elif class_name == "Cleric":
            subclass_name = stats.cleric_subclass.name
        elif class_name == "Bard":
            subclass_name = stats.bard_subclass.name
        elif class_name == "Sorcerer":
            subclass_name = stats.sorcerer_subclass.name
        elif class_name == "Ranger":
            subclass_name = stats.ranger_subclass.name
        # Load the specialized sub-choices by class MEMBERSHIP (not just the
        # primary) so a multiclass build surfaces them for the focused class.
        blessed_strike_name = stats.blessed_strike.name if stats.has_class(rpg.CharacterClass.Cleric) else "NONE"
        is_hunter = (stats.has_class(rpg.CharacterClass.Ranger) and stats.ranger_subclass.name == "Hunter")
        hunter_prey_name = stats.hunter_prey.name if is_hunter else "NONE"
        defensive_tactics_name = stats.defensive_tactics.name if is_hunter else "NONE"
        app.stats_dialog.open(
            app.screen, h, pt2.name, stats,
            class_name, char_level,
            app._on_stats_ok,
            is_npc=is_npc,
            npc_spell_groups=npc_spell_groups,
            armor_list=armor,
            subclass_name=subclass_name,
            blessed_strike_name=blessed_strike_name,
            hunter_prey_name=hunter_prey_name,
            defensive_tactics_name=defensive_tactics_name)
    def _open_weapons(h=hit):
        pt2 = app.bm.placed_agents[h]
        weapon_array = app.combat.get_agent_weapons(app.bm, h)
        def _on_weapons_done():
            # Collect the variable-length "Attack N" list from the dialog and save
            # back to the combat engine (C++ pads to >=3). Trailing empty rows are
            # kept as blank weapons; interior empties preserve later indices.
            cpp_weapons = []
            for weapon_dict in app.weapons_dialog.current_weapons:
                if weapon_dict.get("name"):
                    cpp_weapons.append(_dict_to_weapon(weapon_dict))
                else:
                    cpp_weapons.append(rpg.Weapon())
            app.combat.set_agent_weapons(app.bm, h, cpp_weapons)
            # Keep has_offhand_attack in sync with the off-hand toggles.
            stats = app.combat.get_agent_stats(app.bm, h)
            stats.has_offhand_attack = any(
                d.get("off_hand", False) for d in app.weapons_dialog.current_weapons)
            app.combat.set_agent_stats(app.bm, h, stats)
        app.weapons_dialog.open(app.screen, h, pt2.name, weapon_array,
                                app.weapon_selection_dialog, _on_weapons_done,
                                app.combat, app.bm)
    def _open_spells(h=hit):
        pt2 = app.bm.placed_agents[h]
        spell_dicts = [app._spell_to_dict(h, j, s)
                       for j, s in enumerate(app.combat.get_agent_spells(app.bm, h))]
        def _open_spell_selector():
            app.spell_selection_dialog.show(app.spell_dialog._on_spell_selected)
        app.spell_dialog.open(
            app.screen, h, pt2.name,
            spell_dicts,
            app._on_spell_done,
            add_spell_callback=_open_spell_selector)
    def _open_armor(h=hit):
        pt2 = app.bm.placed_agents[h]
        armor_array = app.combat.get_agent_armor(app.bm, h)
        def _on_armor_done():
            # Collect armor from dialog and save back to combat engine
            cpp_armor = []
            for armor_dict in app.armor_dialog.current_armor:
                if armor_dict.get("name"):
                    cpp_armor.append(_dict_to_armor(armor_dict))
                else:
                    cpp_armor.append(rpg.Armor())
            app.combat.set_agent_armor(app.bm, h, cpp_armor)
        app.armor_dialog.open(app.screen, h, pt2.name, armor_array,
                              app.armor_selection_dialog, _on_armor_done)
    def _open_items(h=hit):
        pt2 = app.bm.placed_agents[h]
        item_array = app.combat.get_agent_items(app.bm, h)
        def _on_items_done():
            app.combat.set_agent_items(
                app.bm, h,
                [_dict_to_item(d) for d in app.items_dialog.current_items
                 if d.get("name")])
        app.items_dialog.open(app.screen, h, pt2.name, item_array,
                               app.item_selection_dialog, _on_items_done)
    def _edit_safe_targets(h=hit):
        app.safe_target_edit_idx = h
        app._combat_log_add(
            f"Editing safe targets for {app.bm.placed_agents[h].name}: "
            f"click allies to toggle them safe from this Evoker's AoEs "
            f"(Esc or click empty space to finish).")
    def _edit_name(h=hit):
        old = app.bm.placed_agents[h].name
        def _commit(new_name, hh=h, prev=old):
            app.bm.set_agent_name(hh, new_name)
            app._combat_log_add(f"Renamed '{prev}' → '{new_name}'.")
        app.name_prompt.show(old, _commit,
                              title=f"Rename '{old}'")
    def _edit_sprite(h=hit):
        def _commit(path, hh=h):
            app.bm.set_agent_sprite(hh, path)
            app._combat_log_add(
                f"{app.bm.placed_agents[hh].name}: sprite set to "
                f"{os.path.basename(path)}.")
        start = app.sprites_dir if os.path.isdir(app.sprites_dir) else "."
        app.file_browser.open(start, _commit,
                               title="Select Sprite")
    def _toggle_on_deck(h=hit):
        now_reserve = not app.bm.is_agent_on_deck(h)
        app.bm.set_agent_on_deck(h, now_reserve)
        nm = app.bm.placed_agents[h].name
        app._combat_log_add(
            f"{nm}: {'moved to On Deck (reserve)' if now_reserve else 'recalled to the battle'}.")
    _on_deck_label = ("Recall from On Deck" if app.bm.is_agent_on_deck(hit)
                      else "Send to On Deck")
    _menu_opts = [("Edit Name…",   _edit_name),
                  ("Edit Sprite…", _edit_sprite),
                  ("Edit Stats",   _open_stats),
                  ("Edit Weapons", _open_weapons),
                  ("Edit Armor",   _open_armor),
                  ("Edit Spells",  _open_spells),
                  ("Edit Items",   _open_items),
                  ("Set Teams…",   app._open_team_picker),
                  (_on_deck_label, _toggle_on_deck)]
    # Evoker Wizards only: manage the set of creatures safe from their AoEs.
    _hs = app.combat.get_agent_stats(app.bm, hit)
    if (_hs.character_class == rpg.CharacterClass.Wizard and
            _hs.wizard_subclass == rpg.WizardSubclass.Evoker):
        _menu_opts.append(("Edit Safe Targets", _edit_safe_targets))
        # Overchannel (L14): arm/disarm maximum-damage casting.
        if _hs.char_level >= 14:
            def _toggle_overchannel(h=hit):
                app.overchannel_armed = not app.overchannel_armed
                app._combat_log_add(
                    f"Overchannel {'ARMED' if app.overchannel_armed else 'disarmed'} — "
                    f"{app.bm.placed_agents[h].name}'s next damaging spell (level 1-5) "
                    f"{'deals maximum damage (first use free, then escalating Necrotic self-damage).' if app.overchannel_armed else 'rolls damage normally.'}")
            _menu_opts.append(
                ("Overchannel: " + ("Disarm" if app.overchannel_armed else "Arm"),
                 _toggle_overchannel))
    # Fiend Warlock L10+: choose the Fiendish Resilience damage resistance.
    if (_hs.character_class == rpg.CharacterClass.Warlock and
            _hs.warlock_subclass == rpg.WarlockSubclass.Fiend and
            _hs.char_level >= 10):
        def _choose_fiendish_resilience(h=hit, pos=pos):
            # Force (index 3) is excluded by the feature.
            _types = [("Acid", 0), ("Cold", 1), ("Fire", 2), ("Lightning", 4),
                      ("Necrotic", 5), ("Poison", 6), ("Psychic", 7),
                      ("Radiant", 8), ("Thunder", 9)]
            _opts = [(nm, (lambda hh=h, ii=ix: app._set_fiendish_resilience(hh, ii)))
                     for nm, ix in _types]
            # A genuine submenu: `answering` is the agent menu whose row
            # was just clicked, which is the parent D-M1-2 wants named.
            app._ask_dm("action",
                         f"{app._agent_name(h)}: Fiendish Resilience",
                         _opts, anchor=pos, actor_idx=h,
                         parent=app.prompts.answering)
        _menu_opts.append(("Fiendish Resilience", _choose_fiendish_resilience))
    # NPC automation: hand this agent's turn to the engine (NPC_AUTOMATION_PLAN Step 2).
    # Nested submenu, mirroring the Fiendish Resilience pattern above.
    def _npc_automation_menu(h=hit, pos=pos):
        nm = app.bm.placed_agents[h].name
        def _toggle_automated(hh=h):
            now_auto = not app.bm.is_agent_npc_automated(hh)
            app.bm.set_agent_npc_automated(hh, now_auto)
            app._combat_log_add(
                f"{app.bm.placed_agents[hh].name}: NPC automation "
                f"{'ENABLED' if now_auto else 'disabled'}.")
        def _difficulty_menu(hh=h, p=pos):
            def _set_diff(level, h2=hh):
                app.bm.set_agent_npc_automation_difficulty(h2, level)
                app._combat_log_add(
                    f"{app.bm.placed_agents[h2].name}: automation difficulty = "
                    f"{'manual' if level == 0 else level}.")
            _cur_d = app.bm.get_agent_npc_automation_difficulty(hh)
            _diff_opts = [
                (("✓ " if i == _cur_d else "") +
                 ("0 (manual)" if i == 0 else f"Level {i}"),
                 (lambda lv=i: _set_diff(lv)))
                for i in range(7)]
            app._ask_dm("action",
                         f"{app._agent_name(hh)}: automation difficulty",
                         _diff_opts, anchor=p, actor_idx=hh,
                         parent=app.prompts.answering)
        def _strategy_menu(hh=h, p=pos):
            _strats = [
                ("Simple",              rpg.NpcAutomationStrategy.Simple),
                ("Prefer Target Caster", rpg.NpcAutomationStrategy.PreferTargetCaster),
                ("Prefer AOE",          rpg.NpcAutomationStrategy.PreferAOE),
                ("Prefer Range",        rpg.NpcAutomationStrategy.PreferRange),
                ("Prefer Hide",         rpg.NpcAutomationStrategy.PreferHide),
                ("Prefer Control",      rpg.NpcAutomationStrategy.PreferControl),
                ("Prefer Heal",         rpg.NpcAutomationStrategy.PreferHeal),
                ("Prefer Support",      rpg.NpcAutomationStrategy.PreferSupport),
                ("No-op (Cower)",       rpg.NpcAutomationStrategy.NoOp)]
            def _set_strat(strat, h2=hh):
                app.bm.set_agent_npc_automation_strategy(h2, strat)
                app._combat_log_add(
                    f"{app.bm.placed_agents[h2].name}: automation strategy = {strat}.")
            _cur_s = app.bm.get_agent_npc_automation_strategy(hh)
            _strat_opts = [
                (("✓ " if s == _cur_s else "") + label,
                 (lambda st=s: _set_strat(st)))
                for label, s in _strats]
            app._ask_dm("action",
                         f"{app._agent_name(hh)}: automation strategy",
                         _strat_opts, anchor=p, actor_idx=hh,
                         parent=app.prompts.answering)
        _auto_label = ("Automated: ON" if app.bm.is_agent_npc_automated(h)
                       else "Automated: off")
        _sub_opts = [(_auto_label, _toggle_automated),
                     ("Difficulty ▸", _difficulty_menu),
                     ("Strategy ▸",   _strategy_menu)]
        app._ask_dm("action", f"{nm}: NPC automation", _sub_opts,
                     anchor=pos, actor_idx=h,
                     parent=app.prompts.answering)
    _menu_opts.append(("NPC Automation ▸", _npc_automation_menu))
    # Ownership (MULTIPLAYER_PLAN.md M0): hand this token to a player.
    # One submenu on the existing agent menu, never a new dialog — the
    # target user procedure pins that down. Reuses the name prompt for
    # seating someone new, exactly as Edit Name… does.
    def _controller_menu(h=hit, pos=pos):
        app._sync_roster_tokens()   # ✓ marks must reflect the live records
        _cur = app.roster.controller_of(h)

        def _assign(pid, hh=h):
            app.bm.set_agent_controller(hh, pid)
            app._sync_roster_tokens()
            app._save_session()
            app._combat_log_add(
                f"{app.bm.placed_agents[hh].name}: controlled by "
                f"{app.roster.display_name(pid)}.")

        def _seat_new(hh=h):
            def _commit(name, h2=hh):
                name = (name or "").strip()
                if not name:
                    return
                p = app.roster.add_principal(name, role=Role.PLAYER)
                _assign(p.id, h2)
            app.name_prompt.show("", _commit, title="Seat a new player")

        _opts = [(("✓ " if _cur == DM_PRINCIPAL_ID else "") + "DM",
                  (lambda: _assign(DM_PRINCIPAL_ID)))]
        for _p in app.roster.players():
            _opts.append((("✓ " if _cur == _p.id else "") + _p.display_name,
                          (lambda pid=_p.id: _assign(pid))))
        _opts.append(("Seat a new player…", _seat_new))
        app._ask_dm("action",
                     f"{app._agent_name(h)}: who controls this token?",
                     _opts, anchor=pos, actor_idx=h,
                     parent=app.prompts.answering)
    _menu_opts.append(("Controller ▸", _controller_menu))
    app._ask_dm("action", f"{app._agent_name(hit)} — DM menu",
                 _menu_opts, anchor=pos, actor_idx=hit)


def show_on_deck_recall_menu(app, hit, pos):
    """In combat, the per-mob counterpart to the On Deck section's group Deploy rows:
    recall reserve `hit` alone. Reserves sit outside initiative, so this never disturbs
    the current actor's turn."""
    nm = app.bm.placed_agents[hit].name
    def _recall_one(h=hit, label=nm):
        app._deploy_on_deck_idxs([h], label)
    app._ask_dm("action", f"{nm}: On Deck reserve",
                 [(f"Recall '{nm}' from On Deck", _recall_one)],
                 anchor=pos, actor_idx=hit)


def show_fog_menu(app, pos):
    """Manual overrides on the persistent explored mask: reveal everything, or reset
    back to fully fogged."""
    def _reveal_all_fog():
        app.bm.reveal_all_fog()
    def _reset_fog():
        app.bm.clear_fog()
        app._mark_fog_dirty()   # re-reveal whatever the party can currently see
    app._ask_dm("action", "Fog of war",
                 [("Reveal all fog", _reveal_all_fog),
                  ("Reset fog", _reset_fog)],
                 anchor=pos)
