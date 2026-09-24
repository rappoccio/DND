"""The post-hit attack riders — the choice a hit hands back to the attacker.

Twenty-five builders, all reached from `main.py`'s one post-hit dispatcher, and all the
same shape: the attack has already resolved in the engine, the rider is an OPTIONAL
extra the attacker may now spend something on, and the two callbacks are "apply it" and
"skip it". Both ends run `_continue_attack_sequence_after_rider`, because an Extra
Attack sequence must go on whichever way the DM answers.

`owner` is the attacker's controller at every site here (M1 Step 0.2's G2): the rider is
the attacker's own choice, even though the thing it does lands on the defender. The
defender's own reactions are the opposite judgement and live in `reactions.py`.
"""

import rpg_battle_map as rpg

from constants import FLASH_BAD, FLASH_CRIT, FLASH_GOOD


def offer_brutal_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=None):
    """Show Brutal Strike effect menu after a hit. Logs the attack after effect is chosen. When
    on_done is set (a pending weapon-Mastery rider), it is invoked instead of refreshing the
    overlay, chaining the Mastery prompt after this one."""
    atk_stats = app.combat.get_agent_stats(app.bm, atk_idx)
    level = atk_stats.char_level
    dice_str = "2d10" if level >= 17 else "1d10"

    # FLAG: Move to C++
    def _apply(effects):
        if effects:
            # Apply Brutal Strike effect and modify result
            app.combat.apply_brutal_strike_effect(app.bm, atk_idx, target_idx, effects, result)
            # Re-format attack message with updated damage breakdown
            dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            updated_msg = (f"{atk_name}→{tgt_name}: "
                           f"HIT {result.total_damage}{app._damage_breakdown_str(result)} {dmg_type_str}"
                           f"{' CRIT!' if result.critical else ''}"
                           f"{' — DOWN' if result.target_down else ''}")
            app._combat_log_add(updated_msg)
        else:
            # Skip chosen - log original attack
            app._combat_log_add(atk_msg)
        app._flush_combat_log()
        if on_done:
            on_done()
        else:
            app._update_attack_overlay()

    options = [
        (f"Forceful Blow ({dice_str} + push 15ft)", lambda: _apply([0])),
        (f"Hamstring Blow ({dice_str} + speed −15ft)", lambda: _apply([1])),
    ]
    if level >= 13:
        options += [
            (f"Staggering Blow ({dice_str} + disadv next save)", lambda: _apply([2])),
            (f"Sundering Blow ({dice_str} + +5 next atk vs target)", lambda: _apply([3])),
        ]
    options.append(("Skip Brutal Strike", lambda: _apply([])))

    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Brutal Strike", options)


def offer_push(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, chained=False):
    """Push weapon mastery: optionally shove the target 10 ft straight away (Large or smaller).
    The shove itself is applied in C++ via apply_push, which clears the availability flag. When
    chained=True it is presented after a preceding on-hit rider that already logged the HIT line,
    so the duplicate attack-message log is suppressed."""
    def _apply(do):
        if not chained:
            app._combat_log_add(atk_msg)
        if do:
            feet = app.combat.apply_push(app.bm, atk_idx, target_idx)
            if feet > 0:
                app._combat_log_add(f"{atk_name} pushes {tgt_name} {feet} ft (Push).")
            else:
                app._combat_log_add(f"{atk_name}: Push had no effect.")
        else:
            # Skip push: clear the availability flag so it won't be offered again this turn.
            # (push_used_this_turn was already set in C++ on the qualifying hit and is not
            # bound to Python; the overlay gates on push_available.)
            c = app.combat.get_agent_conditions(app.bm, atk_idx)
            c.push_available = False
            app.combat.set_agent_conditions(app.bm, atk_idx, c)
        app._flush_combat_log()
        app._update_attack_overlay()
    options = [
        ("Push 10 ft (away)", lambda: _apply(True)),
        ("Skip Push", lambda: _apply(False)),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Push (Mastery)", options)


def offer_topple(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, weapon_idx, chained=False):
    """Topple weapon mastery: optionally force a CON save or knock the target Prone.
    The save + prone are resolved in C++ via apply_topple, which clears the flag. When chained=True
    it is presented after a preceding on-hit rider that already logged the HIT line, so the
    duplicate attack-message log is suppressed."""
    def _apply(do):
        if not chained:
            app._combat_log_add(atk_msg)
        if do:
            res = app.combat.apply_topple(app.bm, atk_idx, target_idx, weapon_idx)
            if res.toppled:
                app._combat_log_add(
                    f"{tgt_name} is knocked Prone (Topple — save {res.save_roll} vs DC {res.save_dc}).")
                app._spawn_flash(target_idx, "Failed", FLASH_BAD)
            else:
                app._combat_log_add(
                    f"{tgt_name} resists Topple (save {res.save_roll} vs DC {res.save_dc}).")
                app._spawn_flash(target_idx, "Saved", FLASH_GOOD)
        else:
            # Skip topple: clear the availability flag so it won't be offered again this turn.
            # (topple_used_this_turn is not bound to Python; the overlay gates on topple_available.)
            c = app.combat.get_agent_conditions(app.bm, atk_idx)
            c.topple_available = False
            app.combat.set_agent_conditions(app.bm, atk_idx, c)
        app._flush_combat_log()
        app._update_attack_overlay()
    options = [
        ("Topple (CON save or Prone)", lambda: _apply(True)),
        ("Skip Topple", lambda: _apply(False)),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Topple (Mastery)", options)


def offer_cleave(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, weapon_idx, chained=False):
    """Cleave weapon mastery: optionally make one extra attack vs a 2nd creature within 5 ft of
    the first target AND within reach, with no ability modifier on damage (once per turn). Cleave
    is part of the Attack action, so it is resolved out-of-band (see _resolve_cleave) — it does
    not consume the bonus action or a sequence attack. On accept, the legal second targets are
    highlighted on the map (green rings) and the player clicks one (Esc cancels). When chained=True
    it is presented after a preceding on-hit rider that already logged the HIT line, so the
    duplicate attack-message log is suppressed."""
    def _apply(do):
        if not chained:
            app._combat_log_add(atk_msg)
        app._flush_combat_log()
        if do:
            valid = app._cleave_valid_targets(atk_idx, target_idx, weapon_idx)
            if not valid:
                app._combat_log_add(
                    f"Cleave: no eligible creature within 5 ft of {tgt_name} and within reach.")
                app._flush_combat_log()
            else:
                # Mark Cleave spent for the turn so the engine won't re-offer it (and a chained
                # Cleave hit can't recurse). Then await the 2nd-target click.
                c = app.combat.get_agent_conditions(app.bm, atk_idx)
                c.cleave_used_this_turn = True
                c.cleave_available = False
                app.combat.set_agent_conditions(app.bm, atk_idx, c)
                app.pending_cleave = {"attacker": atk_idx, "first": target_idx,
                                       "weapon": weapon_idx, "valid": valid}
                app._combat_log_add(
                    f"Cleave — click a highlighted creature within 5 ft of {tgt_name} "
                    f"(Esc to cancel).")
                app._flush_combat_log()
        app._update_attack_overlay()
    options = [
        ("Cleave: extra attack (no ability mod)", lambda: _apply(True)),
        ("Skip Cleave", lambda: _apply(False)),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Cleave (Mastery)", options)


def offer_sudden_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, weapon_idx):
    """Stalker's Flurry — Sudden Strike (Gloom Stalker L11): immediately after a Dreadful Strike
    hit, optionally make one FREE additional attack with the same weapon against a creature within
    5 ft of the target. Routes through the shared extra-attack flow with slot="action" so it does
    NOT consume the bonus action (it's a free attack granted by the feature). Clearing
    sudden_strike_available stops a re-offer.

    v1 sequencing: like GWM Hew, accepting forgoes any remaining Attack-action attacks (the extra
    attack takes over the pending sequence). The "within 5 ft of the target" constraint is left to
    the player's target click (noted in the prompt). Mass Fear (the alternative L11 effect) is
    deferred — see known_limitations.md."""
    def _apply(do):
        app._combat_log_add(atk_msg)
        c = app.combat.get_agent_conditions(app.bm, atk_idx)
        c.sudden_strike_available = False
        app.combat.set_agent_conditions(app.bm, atk_idx, c)
        app._flush_combat_log()
        if do:
            # Forgo any leftover action attacks so the free Sudden Strike sets up cleanly.
            app.attacks_remaining = 0
            app._attack_sequence_slot = ""
            app.pending_attack_slot = ""
            app._start_extra_attack(weapon_idx=weapon_idx, offhand=False, slot="action",
                                     label="Stalker's Flurry: Sudden Strike (target within 5 ft)")
        app._update_attack_overlay()
    options = [
        ("Sudden Strike: free extra attack", lambda: _apply(True)),
        ("Skip Sudden Strike", lambda: _apply(False)),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Sudden Strike", options)


def offer_divine_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=None):
    """After a qualifying weapon hit, offer Cleric Divine Strike (Radiant or Necrotic).
    Mirrors _offer_brutal_strike; the extra die is applied in C++ via apply_divine_strike_effect.
    When on_done is set (a pending weapon-Mastery rider), it is invoked instead of refreshing the
    overlay, chaining the Mastery prompt after this one."""
    def _apply(radiant):
        if radiant is not None:
            app.combat.apply_divine_strike_effect(app.bm, atk_idx, target_idx, radiant, result)
            dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{atk_name}→{tgt_name}: HIT {result.total_damage}{app._damage_breakdown_str(result)} "
                f"{dmg_type_str}{' CRIT!' if result.critical else ''}{' — DOWN' if result.target_down else ''}")
        else:
            app._combat_log_add(atk_msg)
        app._flush_combat_log()
        if on_done:
            on_done()
        else:
            app._update_attack_overlay()
    options = [
        ("Divine Strike: Radiant", lambda: _apply(True)),
        ("Divine Strike: Necrotic", lambda: _apply(False)),
        ("Skip Divine Strike", lambda: _apply(None)),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Divine Strike", options)


def offer_psionic_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=None):
    """After a qualifying hit, offer Psi Warrior Psionic Strike (spend 1 Psionic Energy die → Force).
    Mirrors _offer_divine_strike; the extra die is applied in C++ via apply_psionic_strike_effect.
    When on_done is set (a pending weapon-Mastery rider), it is invoked instead of refreshing the
    overlay, chaining the Mastery prompt after this one."""
    def _apply(use_it):
        if use_it:
            app.combat.apply_psionic_strike_effect(app.bm, atk_idx, target_idx, result)
            dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{atk_name}→{tgt_name}: HIT {result.total_damage}{app._damage_breakdown_str(result)} "
                f"{dmg_type_str}{' CRIT!' if result.critical else ''}{' — DOWN' if result.target_down else ''}")
        else:
            app._combat_log_add(atk_msg)
        app._flush_combat_log()
        if on_done:
            on_done()
        else:
            app._update_attack_overlay()
    options = [
        ("Psionic Strike (1 die → Force)", lambda: _apply(True)),
        ("Skip Psionic Strike", lambda: _apply(False)),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Psionic Strike", options)


def offer_hand_of_harm(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """After a qualifying unarmed hit, offer Monk Warrior of Mercy Hand of Harm (extra Necrotic,
    MA die + WIS). At L6 (Physician's Touch) the target is also Poisoned; at L11 it's free. The extra
    damage is applied in C++ via apply_hand_of_harm_effect. Mirrors _offer_psionic_strike."""
    atk_stats = app.combat.get_agent_stats(app.bm, atk_idx)
    free = atk_stats.char_level >= 11
    fp = atk_stats.get_resource("Focus Points")
    if not free and (not fp or fp.current <= 0):
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)
        return

    def _apply(use_it):
        if use_it:
            app.combat.apply_hand_of_harm_effect(app.bm, atk_idx, target_idx, result)
            dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{atk_name}→{tgt_name}: HIT {result.total_damage}{app._damage_breakdown_str(result)} "
                f"{dmg_type_str}{' CRIT!' if result.critical else ''}{' — DOWN' if result.target_down else ''}")
            if result.target_down:
                app._drop_concentration_for_agent(target_idx)
        else:
            app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._continue_attack_sequence_after_rider(atk_idx)
        app._update_attack_overlay()

    label = "Hand of Harm (free → Necrotic)" if free else "Hand of Harm (1 FP → Necrotic)"
    if atk_stats.char_level >= 6:
        label = label[:-1] + ", Poisoned)"
    options = [
        (label, lambda: _apply(True)),
        ("Skip Hand of Harm", lambda: _apply(False)),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Hand of Harm", options)


def offer_punch_and_grab(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """After an Unarmed-Strike hit in the Attack action, offer the Grappler feat's Punch-and-Grab:
    ALSO attempt a Grapple this attack (normally damage OR grapple), once per turn. The contested
    grapple runs in C++ via apply_punch_and_grab → resolveGrapple. Mirrors _offer_psionic_strike."""
    def _apply(use_it):
        app._combat_log_add(atk_msg)   # the unarmed-strike damage still landed
        if use_it:
            grab = app.combat.apply_punch_and_grab(app.bm, atk_idx, target_idx)
            if grab.valid and grab.success:
                app._combat_log_add(
                    f"{atk_name}→{tgt_name}: Punch-and-Grab — grappled (escape DC {grab.escape_dc})")
            elif grab.valid:
                app._combat_log_add(
                    f"{atk_name}→{tgt_name}: Punch-and-Grab — grapple failed "
                    f"(atk {grab.attacker_roll} vs def {grab.defender_roll})")
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()
    options = [
        ("Punch-and-Grab (also attempt a Grapple)", lambda: _apply(True)),
        ("Skip Grapple", lambda: _apply(False)),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Punch-and-Grab", options)


def offer_elemental_move(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """After an unarmed hit while Elemental Attunement is active (Warrior of the Elements L3), offer
    to push the target 10 ft away or pull it 10 ft toward the Monk (no save). Mirrors
    _offer_punch_and_grab. The forced move runs in C++ via elemental_attunement_move."""
    def _apply(mode):
        app._combat_log_add(atk_msg)   # the unarmed-strike damage still landed
        if mode is not None:
            ft = app.combat.elemental_attunement_move(app.bm, atk_idx, target_idx, mode)
            verb = "pulls" if mode else "pushes"
            if ft > 0:
                app._combat_log_add(f"{atk_name}→{tgt_name}: Elemental Attunement {verb} {ft} ft")
            else:
                app._combat_log_add(f"{atk_name}→{tgt_name}: Elemental Attunement could not move the target (blocked)")
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()
    options = [
        ("Push 10 ft (away)", lambda: _apply(False)),
        ("Pull 10 ft (toward)", lambda: _apply(True)),
        ("Skip", lambda: _apply(None)),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Elemental Attunement", options)


def offer_divine_smite(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=None):
    """After a melee/unarmed hit, offer Paladin Divine Smite with one entry per available
    spell-slot level (1st→2d8 … 5th→6d8, +1d8 vs Undead/Fiend). The Radiant damage and the
    slot + bonus-action spend happen in C++ via apply_divine_smite_effect. Mirrors
    _offer_divine_strike. When on_done is set (a pending weapon-Mastery rider), it is invoked
    instead of refreshing the overlay, chaining the Mastery prompt after this one."""
    def _apply(slot_level):
        if slot_level is not None:
            app.combat.apply_divine_smite_effect(app.bm, atk_idx, target_idx, slot_level, result)
            dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{atk_name}→{tgt_name}: HIT {result.total_damage}{app._damage_breakdown_str(result)} "
                f"{dmg_type_str}{' CRIT!' if result.critical else ''}{' — DOWN' if result.target_down else ''}")
        else:
            app._combat_log_add(atk_msg)
        app._flush_combat_log()
        if on_done:
            on_done()
        else:
            app._update_attack_overlay()

    def _ordinal(n):
        return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")

    stats = app.combat.get_agent_stats(app.bm, atk_idx)
    tgt_stats = app.combat.get_agent_stats(app.bm, target_idx)
    bonus = 1 if (tgt_stats.is_undead or tgt_stats.is_fiend) else 0
    options = []
    for lvl in range(1, 10):
        if stats.spell_slots_remaining[lvl - 1] > 0:
            dice = 1 + min(lvl, 5) + bonus
            options.append((f"Divine Smite ({_ordinal(lvl)} slot → {dice}d8 Radiant)",
                            lambda l=lvl: _apply(l)))
    options.append(("Skip Divine Smite", lambda: _apply(None)))
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Divine Smite", options)


def offer_eldritch_smite(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=None):
    """After a pact-weapon hit, offer Warlock Eldritch Smite. Pact Magic slots are all one level
    (pact_slot_level), so there's a single option: expend the pact slot → (lvl+1)d8 Force + knock
    Prone. The damage, slot + bonus-action spend, and Prone happen in C++ via
    apply_eldritch_smite_effect. Mirrors _offer_divine_smite. When on_done is set (a pending
    weapon-Mastery rider), it is invoked instead of refreshing the overlay, chaining the Mastery
    prompt after this one."""
    def _apply(slot_level):
        if slot_level is not None:
            app.combat.apply_eldritch_smite_effect(app.bm, atk_idx, target_idx, slot_level, result)
            dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{atk_name}→{tgt_name}: HIT {result.total_damage}{app._damage_breakdown_str(result)} "
                f"{dmg_type_str}{' CRIT!' if result.critical else ''}{' — DOWN' if result.target_down else ''}")
        else:
            app._combat_log_add(atk_msg)
        app._flush_combat_log()
        if on_done:
            on_done()
        else:
            app._update_attack_overlay()

    stats = app.combat.get_agent_stats(app.bm, atk_idx)
    psl = stats.pact_slot_level()
    options = []
    if psl >= 1 and stats.spell_slots_remaining[psl - 1] > 0:
        dice = psl + 1
        options.append((f"Eldritch Smite (pact slot L{psl} → {dice}d8 Force + Prone)",
                        lambda l=psl: _apply(l)))
    options.append(("Skip Eldritch Smite", lambda: _apply(None)))
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Eldritch Smite", options)


def offer_guided_strike(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """After a miss, offer War Domain Guided Strike (+10) via an eligible War Cleric. The +10 and
    any resulting hit/damage are applied in C++ via apply_guided_strike_effect."""
    agents = app.bm.placed_agents
    eligible = app._eligible_guided_clerics(atk_idx)

    def _apply(cleric_idx):
        if cleric_idx is not None:
            app.combat.apply_guided_strike_effect(app.bm, action, cleric_idx, result)
            if result.hit:
                dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                app._combat_log_add(
                    f"{atk_name}→{tgt_name}: Guided Strike → HIT {result.total_damage}"
                    f"{app._damage_breakdown_str(result)} {dmg_type_str}{' — DOWN' if result.target_down else ''}")
            else:
                app._combat_log_add(
                    f"{atk_name}→{tgt_name}: Guided Strike +10 → still misses "
                    f"(roll {result.total_roll} vs AC {result.target_ac})")
        else:
            app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._update_attack_overlay()

    options = []
    for ci in eligible:
        label = "Guided Strike (+10)" if ci == atk_idx else f"Guided Strike: {agents[ci].name} reacts (+10)"
        options.append((label, (lambda c=ci: _apply(c))))
    options.append(("Skip Guided Strike", lambda: _apply(None)))
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Guided Strike", options)


def offer_peerless_aim(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """After a miss, offer Boon of Combat Prowess — Peerless Aim (turn the miss into a hit, once per
    turn). apply_peerless_aim_effect re-validates in C++ and rolls/applies weapon damage on accept."""
    def _apply(use_it):
        if use_it:
            app.combat.apply_peerless_aim_effect(app.bm, action, result)
            if result.hit:
                dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                app._combat_log_add(
                    f"{atk_name}→{tgt_name}: Peerless Aim → HIT {result.total_damage}"
                    f"{app._damage_breakdown_str(result)} {dmg_type_str}{' — DOWN' if result.target_down else ''}")
            else:
                app._combat_log_add(atk_msg)
        else:
            app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        ("Peerless Aim (turn miss into a hit)", lambda: _apply(True)),
        ("Skip Peerless Aim", lambda: _apply(False)),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Peerless Aim", options)


def offer_cunning_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Show the Sneak Attack / Cunning Strike menu after a qualifying hit.

    Mirrors _offer_brutal_strike: the attack already resolved, so the chosen riders (and the
    Sneak Attack dice) are applied out of band via apply_cunning_strike_effect. "Sneak Attack
    only" spends no dice on a rider. Logs the final attack message after the choice.
    """
    atk_stats = app.combat.get_agent_stats(app.bm, atk_idx)
    level = atk_stats.char_level

    def _apply(effects):
        # round_num drives the Assassin's round-1 features (Assassinate +level damage, Envenom
        # free Poison rider, Death Strike CON-save double). round_num == 0 is the first round.
        app.combat.apply_cunning_strike_effect(
            app.bm, atk_idx, target_idx, effects, result, app.round_num)
        dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
        dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
        updated_msg = (f"{atk_name}→{tgt_name}: "
                       f"HIT {result.total_damage}{app._damage_breakdown_str(result)} {dmg_type_str}"
                       f"{' CRIT!' if result.critical else ''}"
                       f"{' — DOWN' if result.target_down else ''}")
        app._combat_log_add(updated_msg)
        app._flush_combat_log()
        # Sneak Attack damage can drop the target after the base attack already settled.
        if result.target_down:
            app._drop_concentration_for_agent(target_idx)
        app._update_attack_overlay()
        # Rend Mind (Soulknife L17): a Psychic-Blade Sneak Attack can Stun the target.
        if (not result.target_down and app._has_psychic_blade(atk_idx)
                and app.combat.can_rend_mind(app.bm, atk_idx)):
            offer_rend_mind(app, atk_idx, target_idx, tgt_name)

    options = []
    if level >= 5:
        options += [
            ("Poison (1 die)", lambda: _apply([0])),
            ("Trip (1 die)", lambda: _apply([1])),
            ("Withdraw (1 die)", lambda: _apply([2])),
        ]
    if level >= 11:
        options.append(("Poison + Trip (2 dice)", lambda: _apply([0, 1])))
    if level >= 14:
        options += [
            ("Knock Out (6 dice)", lambda: _apply([4])),
            ("Obscure (3 dice)", lambda: _apply([5])),
        ]
    # Supreme Sneak (Thief L9+): Stealth Attack — spend 1 die to stay hidden after the strike.
    # Only meaningful if this attack came from stealth (it just ended the Hide/Invisible condition).
    atk_cond = app.combat.get_agent_conditions(app.bm, atk_idx)
    if (level >= 9 and atk_stats.rogue_subclass == rpg.RogueSubclass.Thief
            and atk_cond.attacked_while_invisible):
        options.append(("Stealth Attack (1 die) — stay hidden", lambda: _apply([6])))
    options.append(("Sneak Attack only", lambda: _apply([])))

    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Cunning Strike", options)


def offer_quivering_palm(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Standalone Quivering Palm plant menu (Open Hand L17): after an unarmed hit, spend 4 Focus
    Points to plant lethal vibrations the monk can later detonate (💥 button → 10d12 Force)."""
    def _continue():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)
    opt = app._quivering_palm_option(atk_idx, target_idx, tgt_name, _continue)
    if opt is None:
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        return

    def _skip():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [opt, ("Don't use", _skip)]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Quivering Palm", options)


def offer_stunning_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Show Stunning Strike menu after a qualifying unarmed hit.
    Monk can spend 1 Focus Point to force a CON save or the target is Stunned.
    """
    atk_stats = app.combat.get_agent_stats(app.bm, atk_idx)
    tgt_stats = app.combat.get_agent_stats(app.bm, target_idx)
    fp = atk_stats.get_resource("Focus Points")

    # Can't use Stunning Strike if no Focus Points
    if not fp or fp.current <= 0:
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        return

    def _apply_stunning_strike():
        # Apply Stunning Strike in C++ (spends resource, rolls save, applies condition)
        res = app.combat.apply_stunning_strike(app.bm, atk_idx, target_idx)

        if res.valid:
            if res.stunned:
                app._combat_log_add(
                    f"  → CON save DC {res.save_dc}: rolled {res.save_roll} vs DC {res.save_dc} — Stunned!")
                app._spawn_flash(target_idx, "Failed", FLASH_BAD)
            else:
                app._combat_log_add(
                    f"  → CON save DC {res.save_dc}: rolled {res.save_roll} vs DC {res.save_dc} — Resisted")
                app._spawn_flash(target_idx, "Saved", FLASH_GOOD)

        # Log original attack
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._update_attack_overlay()

    def _skip_stunning_strike():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()

    def _qp_continue():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._update_attack_overlay()

    options = [(f"Stunning Strike (1 FP)", _apply_stunning_strike)]
    # Quivering Palm (L17) is an alternate use of the same unarmed hit — offer it alongside.
    qp = app._quivering_palm_option(atk_idx, target_idx, tgt_name, _qp_continue)
    if qp:
        options.append(qp)
    options.append(("Don't use", _skip_stunning_strike))
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Stunning Strike", options)


def offer_open_hand_rider(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Show Open Hand rider menu after a qualifying Flurry hit.
    Warrior of the Open Hand can spend 1 Focus Point to apply one of three riders:
    0=Knockdown (STR save or Prone), 1=Push (5 ft), 2=Deny Reaction.
    """
    atk_stats = app.combat.get_agent_stats(app.bm, atk_idx)
    fp = atk_stats.get_resource("Focus Points")

    # Can't use Open Hand rider if no Focus Points
    if not fp or fp.current <= 0:
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        return

    def _apply_knockdown():
        # Knockdown: STR save DC = 8 + DEX mod + prof, on fail apply Prone
        res = app.combat.apply_open_hand_rider(app.bm, atk_idx, target_idx, 0)
        if res.valid:
            if res.target_knocked_prone:
                app._combat_log_add(
                    f"  → Knockdown (STR save DC {res.knockdown_save_dc}: rolled {res.knockdown_save_roll}) — Prone!")
            else:
                app._combat_log_add(
                    f"  → Knockdown (STR save DC {res.knockdown_save_dc}: rolled {res.knockdown_save_roll}) — Resisted")
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _apply_push():
        # Push: 5 feet
        res = app.combat.apply_open_hand_rider(app.bm, atk_idx, target_idx, 1)
        if res.valid:
            app._combat_log_add(f"  → Push: {tgt_name} pushed back {res.push_distance} feet")
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _apply_deny_reaction():
        # Deny Reaction: set reaction_used on target
        res = app.combat.apply_open_hand_rider(app.bm, atk_idx, target_idx, 2)
        if res.valid:
            app._combat_log_add(f"  → Deny Reaction: {tgt_name} cannot use a reaction this turn")
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _skip_open_hand():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _qp_continue():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        (f"Knockdown (1 FP, STR save)", _apply_knockdown),
        (f"Push (1 FP, 5 ft)", _apply_push),
        (f"Deny Reaction (1 FP)", _apply_deny_reaction),
    ]
    # Quivering Palm (L17) is an alternate use of the same unarmed hit — offer it alongside.
    qp = app._quivering_palm_option(atk_idx, target_idx, tgt_name, _qp_continue)
    if qp:
        options.append(qp)
    options.append(("Don't use", _skip_open_hand))
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Open Hand Technique", options)


def offer_maneuver(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Show Battle Master Maneuver menu after a qualifying hit. Spend 1 Superiority Die for
    Trip (Prone), Menacing (Frightened), Pushing (15 ft), Goading (Disadvantage vs others),
    Distracting (allies get Advantage), Disarming (improvised Unarmed), or Sweeping (splash a
    2nd creature). Mirrors _offer_open_hand_rider; preserves the Extra Attack chain via
    _continue_attack_sequence_after_rider."""
    def _apply_save_maneuver(mtype, label, save_name):
        # Trip / Menacing / Goading / Disarming: a save-rider with a uniform log shape.
        res = app.combat.apply_maneuver_effect(app.bm, atk_idx, target_idx, mtype)
        if res.valid:
            outcome = "applied!" if res.condition_applied else "Resisted"
            app._combat_log_add(
                f"  → {label} ({save_name} save DC {res.save_dc}: rolled {res.save_roll}) — {outcome}")
            app._spawn_flash(target_idx, "Failed" if res.condition_applied else "Saved",
                              FLASH_BAD if res.condition_applied else FLASH_GOOD)
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        if result.target_down:
            app._drop_concentration_for_agent(target_idx)
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _apply_distracting():
        res = app.combat.apply_maneuver_effect(app.bm, atk_idx, target_idx, 4)
        if res.valid:
            app._combat_log_add(
                f"  → Distracting Strike: the next attack vs {tgt_name} by another creature has Advantage")
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        if result.target_down:
            app._drop_concentration_for_agent(target_idx)
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _apply_sweeping():
        # Mark the die-spend pending; the 2nd target is chosen by a follow-up map click.
        app._combat_log_add(atk_msg)
        app.pending_sweep = {"action": action, "result": result, "first": target_idx, "attacker": atk_idx}
        app._combat_log_add(f"Sweeping Attack — click a 2nd creature within 5 ft of {tgt_name}.")
        app._flush_combat_log()
        app._update_attack_overlay()

    def _apply_pushing():
        res = app.combat.apply_maneuver_effect(app.bm, atk_idx, target_idx, 2)
        if res.valid:
            app._combat_log_add(f"  → Pushing Attack: {tgt_name} pushed {res.push_distance} feet")
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        if result.target_down:
            app._drop_concentration_for_agent(target_idx)
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _skip_maneuver():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        ("Trip (1 die, STR save → Prone)",
            lambda: _apply_save_maneuver(0, "Tripping Attack", "STR")),
        ("Menacing (1 die, WIS save → Frightened)",
            lambda: _apply_save_maneuver(1, "Menacing Attack", "WIS")),
        ("Pushing (1 die, 15 ft push)", _apply_pushing),
        ("Goading (1 die, WIS save → Disadv. vs others)",
            lambda: _apply_save_maneuver(3, "Goading Attack", "WIS")),
        ("Distracting (1 die, allies get Advantage)", _apply_distracting),
        ("Disarming (1 die, STR save → improvised unarmed)",
            lambda: _apply_save_maneuver(5, "Disarming Attack", "STR")),
        ("Sweeping (1 die, splash a 2nd creature)", _apply_sweeping),
        ("Skip", _skip_maneuver),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: maneuver", options)


def offer_precision_attack(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Show Battle Master Precision Attack menu after a non-fumble miss.
    Spend 1 Superiority Die to add 1d8/d10 to the roll, potentially converting the miss to a hit.
    Mirrors _offer_guided_strike.
    """
    def _apply():
        app.combat.apply_precision_attack_effect(app.bm, action, result)
        if result.hit:
            dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{atk_name}→{tgt_name}: Precision Attack → HIT {result.total_damage}"
                f"{app._damage_breakdown_str(result)} {dmg_type_str}{' — DOWN' if result.target_down else ''}")
            if result.target_down:
                app._drop_concentration_for_agent(target_idx)
        else:
            app._combat_log_add(
                f"{atk_name}→{tgt_name}: Precision Attack +die → still misses "
                f"(roll {result.total_roll} vs AC {result.target_ac})")
        app._flush_combat_log()
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _skip():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        ("Precision Attack (spend 1 Superiority Die)", _apply),
        ("Skip", _skip),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Precision Attack", options)


def offer_reckless_reroll(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Offer a Barbarian a post-hoc Reckless Attack after a miss: reroll the SAME attack with
    advantage, at the cost of the downside (enemies have advantage vs you until your next turn).
    The other entry point is pre-declaring Reckless before attacking. Mirrors _offer_precision_attack."""
    def _apply():
        new_result = app.combat.apply_reckless_reroll(app.bm, atk_idx, target_idx, action.weapon_idx)
        if new_result.hit:
            dmg_parts = app._get_damage_type_names(new_result.magic_damage_types, new_result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{atk_name}→{tgt_name}: Reckless reroll → HIT {new_result.total_damage}"
                f"{app._damage_breakdown_str(new_result)} {dmg_type_str}"
                f"{' CRIT!' if new_result.critical else ''}{' — DOWN' if new_result.target_down else ''}")
            if new_result.target_down:
                app._drop_concentration_for_agent(target_idx)
        else:
            app._combat_log_add(
                f"{atk_name}→{tgt_name}: Reckless reroll → still misses "
                f"(roll {new_result.total_roll} vs AC {new_result.target_ac})")
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _skip():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        ("Reckless Attack — reroll w/ advantage (enemies gain advantage vs you)", _apply),
        ("Skip", _skip),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Reckless Attack", options)


def offer_homing_strike(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Soulknife L9 Homing Strikes: after a Psychic-Blade miss, spend a Psionic Energy Die to add
    to the attack roll; the die is spent only if it converts the miss to a hit. Mirrors
    _offer_reckless_reroll (the engine mutates `result` in place and rolls damage on a convert)."""
    def _apply():
        converted = app.combat.apply_homing_strike(app.bm, atk_idx, target_idx,
                                                    action.weapon_idx, result)
        app._flush_combat_log()   # engine logged the +N roll and the outcome
        if converted and result.hit:
            dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{atk_name}→{tgt_name}: Homing Strikes → HIT {result.total_damage}"
                f"{app._damage_breakdown_str(result)} {dmg_type_str}"
                f"{' — DOWN' if result.target_down else ''}")
            if result.target_down:
                app._drop_concentration_for_agent(target_idx)
        else:
            app._combat_log_add(f"{atk_name}→{tgt_name}: Homing Strikes — still a miss.")
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _skip():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        ("Homing Strikes — spend a Psionic Energy Die to add to the roll", _apply),
        ("Skip", _skip),
    ]
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Homing Strikes", options)


def offer_rend_mind(app, atk_idx, target_idx, tgt_name):
    """Soulknife L17 Rend Mind: after a Psychic-Blade Sneak Attack, optionally force a WIS save or
    be Stunned (1 minute). Costs the free Rend Mind use, else 3 Psionic Energy Dice."""
    def _apply():
        if app.combat.apply_rend_mind(app.bm, atk_idx, target_idx):
            app._flush_combat_log()
        else:
            app._combat_log_add(f"{tgt_name}: resists Rend Mind.")
            app._flush_combat_log()
    options = [
        ("Rend Mind — force a WIS save or Stun the target", _apply),
        ("Skip", lambda: None),
    ]
    app._ask_actor(atk_idx, "action", f"Rend Mind vs {tgt_name}", options)


def offer_bonus_maneuver(app, idx: int):
    """Battle Master bonus-action maneuvers menu: Rally (ally temp HP), Feinting (Advantage +
    die vs an adjacent creature), Quick Toss (thrown attack + die). Each spends 1 Superiority Die."""
    def _rally():
        app.pending_rally = idx
        app._combat_log_add("Rally — click a creature within 30 ft to bolster.")
        app._flush_combat_log()

    def _feint():
        app.pending_feint = idx
        app._combat_log_add("Feinting Attack — click a creature within 5 ft to feint.")
        app._flush_combat_log()

    def _quick_toss():
        if app.combat.prepare_quick_toss(app.bm, idx):
            app.bonus_used = True
            app._flush_combat_log()
            app._start_extra_attack(weapon_idx=app.pending_weapon_idx, offhand=False,
                                     resource=None, label="Quick Toss (thrown weapon)")
        else:
            app._combat_log_add("Quick Toss: no Superiority Dice left.")
            app._flush_combat_log()

    options = [
        ("Rally (ally within 30 ft gains temp HP)", _rally),
        ("Feinting Attack (creature within 5 ft)", _feint),
        ("Quick Toss (thrown attack + die)", _quick_toss),
    ]
    app._ask_actor(idx, "action",
                    f"{app._agent_name(idx)}: Bonus-Action maneuver", options)


def show_flurry_rider_menu(app, atk_idx):
    """Show Open Hand rider menu when Flurry of Blows is activated (Way of the Open Hand only)."""
    options = [
        ("Knockdown", lambda: app._execute_flurry(atk_idx, 0)),
        ("Push", lambda: app._execute_flurry(atk_idx, 1)),
        ("Deny Reaction", lambda: app._execute_flurry(atk_idx, 2)),
        ("No Rider", lambda: app._execute_flurry(atk_idx, -1)),
    ]
    app._ask_actor(atk_idx, "action",
                    f"{app._agent_name(atk_idx)}: Flurry of Blows rider", options)
