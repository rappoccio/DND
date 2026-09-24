"""The defender and third-party reactions — the choice a hit hands to someone else.

Six builders, reached from the same post-hit dispatcher as `riders.py` and separated
from it by one judgement, which is the whole reason they are their own module: the
creature that ANSWERS is not the creature acting. `owner` follows the reactor — the
defender for Riposte and Protective Field, the bystander who steps in for Interception,
Sentinel Guard and Soul of Vengeance, the Clockwork Sorcerer for Restore Balance — and
the attacker's player is refused (M1 Step 0.2's G3, pinned by
`test_prompts.test_defender_reaction_is_owned_by_the_defender`).

`_ask_actor` derives the owner from whoever is anchored, so each site's contribution is
simply passing the REACTOR's index rather than the actor's.
"""

import rpg_battle_map as rpg

from constants import FLASH_BAD, FLASH_CRIT, FLASH_GOOD


def offer_riposte(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Offer a Battle Master DEFENDER a Riposte after a melee attack misses them: spend the
    reaction + 1 Superiority Die to make a melee attack back at the attacker, adding the die to
    the damage on a hit. The reactor is the TARGET of the missed attack. Mirrors _offer_reckless_reroll."""
    def _apply():
        # Riposte = the target (defender) attacks the original attacker.
        rip = app.combat.apply_riposte(app.bm, target_idx, atk_idx, action.weapon_idx)
        app._combat_log_add(atk_msg)   # the original miss still happened
        if rip.valid and rip.hit:
            dmg_parts = app._get_damage_type_names(rip.magic_damage_types, rip.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{tgt_name}→{atk_name}: Riposte → HIT {rip.total_damage}"
                f"{app._damage_breakdown_str(rip)} {dmg_type_str}"
                f"{' CRIT!' if rip.critical else ''}{' — DOWN' if rip.target_down else ''}")
            app._spawn_flash(atk_idx, f"Hit ({rip.total_damage})",
                              FLASH_CRIT if rip.critical else FLASH_GOOD)
            if rip.target_down:
                app._drop_concentration_for_agent(atk_idx)
        elif rip.valid:
            app._combat_log_add(
                f"{tgt_name}→{atk_name}: Riposte → misses "
                f"(roll {rip.total_roll} vs AC {rip.target_ac})")
            app._spawn_flash(atk_idx, "Miss", FLASH_BAD)
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _skip():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        ("Riposte — melee attack back (reaction + 1 Superiority Die)", _apply),
        ("Skip", _skip),
    ]
    # The reactor is the DEFENDER, so `owner` follows target_idx and not the actor —
    # _ask_actor derives it from whoever is anchored (Step 0.2's G3).
    app._ask_actor(target_idx, "reaction", f"{tgt_name} may Riposte {atk_name}", options)


def offer_sentinel_guard(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Offer a Sentinel BYSTANDER a Guardian reaction after an adjacent enemy attacks an ally: spend
    the reaction to make a melee attack at the attacker. The reactor is a third creature within 5 ft
    of the attacker (NOT the attacker or the attack's target). Scans for the first eligible Sentinel
    via can_sentinel_guard. Fires on a hit OR a miss; never alters the original attack. Mirrors
    _offer_riposte, but the reactor is found by scan (like _offer_guided_strike)."""
    agents = app.bm.placed_agents
    sentinel_idx = -1
    for i in range(len(agents)):
        if app.combat.can_sentinel_guard(app.bm, action, i):
            sentinel_idx = i
            break
    if sentinel_idx < 0:                       # eligibility lapsed since the flag was set
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)
        return
    sent_name = agents[sentinel_idx].name if sentinel_idx < len(agents) else "?"
    # First melee weapon the Sentinel wields (mirrors C++ riposteWeaponIdx; the engine re-validates).
    widx = next((i for i, w in enumerate(app.combat.get_agent_weapons(app.bm, sentinel_idx))
                 if w.type == rpg.WeaponType.Melee), -1)

    def _apply():
        app._combat_log_add(atk_msg)          # the original attack still happened
        grd = app.combat.apply_sentinel_guard(app.bm, sentinel_idx, atk_idx, widx)
        if grd.valid and grd.hit:
            dmg_parts = app._get_damage_type_names(grd.magic_damage_types, grd.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{sent_name}→{atk_name}: Sentinel Guardian → HIT {grd.total_damage}"
                f"{app._damage_breakdown_str(grd)} {dmg_type_str}"
                f"{' CRIT!' if grd.critical else ''}{' — DOWN' if grd.target_down else ''}")
            if grd.target_down:
                app._drop_concentration_for_agent(atk_idx)
        elif grd.valid:
            app._combat_log_add(
                f"{sent_name}→{atk_name}: Sentinel Guardian → misses "
                f"(roll {grd.total_roll} vs AC {grd.target_ac})")
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _skip():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        (f"Sentinel Guardian — {sent_name} melee attacks the attacker (reaction)", _apply),
        ("Skip", _skip),
    ]
    app._ask_actor(sentinel_idx, "reaction",
                    f"{sent_name} may guard {tgt_name} — Sentinel reaction vs {atk_name}",
                    options)


def offer_soul_of_vengeance(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Offer a Vengeance paladin (L15+) a Soul of Vengeance reaction after its sworn foe (under the
    paladin's Vow of Enmity) makes an attack: spend the reaction to make a melee attack at that foe.
    The reactor is found by scan via can_soul_of_vengeance. Fires on a hit OR a miss; never alters the
    original attack. Mirrors _offer_sentinel_guard."""
    agents = app.bm.placed_agents
    pal_idx = -1
    for i in range(len(agents)):
        if app.combat.can_soul_of_vengeance(app.bm, action, i):
            pal_idx = i
            break
    if pal_idx < 0:                            # eligibility lapsed since the flag was set
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)
        return
    pal_name = agents[pal_idx].name if pal_idx < len(agents) else "?"
    # First melee weapon the paladin wields (mirrors C++ riposteWeaponIdx; the engine re-validates).
    widx = next((i for i, w in enumerate(app.combat.get_agent_weapons(app.bm, pal_idx))
                 if w.type == rpg.WeaponType.Melee), -1)

    def _apply():
        app._combat_log_add(atk_msg)          # the original attack still happened
        grd = app.combat.apply_soul_of_vengeance(app.bm, pal_idx, atk_idx, widx)
        if grd.valid and grd.hit:
            dmg_parts = app._get_damage_type_names(grd.magic_damage_types, grd.physical_damage_types)
            dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
            app._combat_log_add(
                f"{pal_name}→{atk_name}: Soul of Vengeance → HIT {grd.total_damage}"
                f"{app._damage_breakdown_str(grd)} {dmg_type_str}"
                f"{' CRIT!' if grd.critical else ''}{' — DOWN' if grd.target_down else ''}")
            if grd.target_down:
                app._drop_concentration_for_agent(atk_idx)
        elif grd.valid:
            app._combat_log_add(
                f"{pal_name}→{atk_name}: Soul of Vengeance → misses "
                f"(roll {grd.total_roll} vs AC {grd.target_ac})")
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _skip():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        (f"Soul of Vengeance — {pal_name} melee attacks its sworn foe (reaction)", _apply),
        ("Skip", _skip),
    ]
    app._ask_actor(pal_idx, "reaction",
                    f"{pal_name} may strike back at {atk_name} — Soul of Vengeance",
                    options)


def offer_protective_field(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Offer a Psi Warrior DEFENDER (Fighter L3+) Protective Field after they're hit: spend the
    reaction + 1 Psionic Energy die to reduce the damage by (die + INT mod), healing back what the
    hit actually cost. The reactor is the TARGET of the hit. apply_protective_field re-validates and
    applies in C++. Mirrors _offer_riposte (DEFENDER reaction keyed on the target)."""
    def _apply():
        app._combat_log_add(atk_msg)   # the hit (and its damage) still landed
        prevented = app.combat.apply_protective_field(app.bm, target_idx, result.total_damage)
        if prevented > 0:
            app._combat_log_add(
                f"{tgt_name}: Protective Field — prevents {prevented} damage (reaction + 1 Psionic die).")
        else:
            app._combat_log_add(f"{tgt_name}: Protective Field had no effect.")
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _skip():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        ("Protective Field — reduce damage (reaction + 1 Psionic die)", _apply),
        ("Skip", _skip),
    ]
    app._ask_actor(target_idx, "reaction",
                    f"{tgt_name} may blunt {atk_name}'s hit — Protective Field",
                    options)


def offer_interception(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """Offer a bystander with the Interception fighting style (holding a Shield/weapon, within 5 ft
    of the target) to spend its reaction reducing the damage by 1d10 + PB. The reactor is a THIRD
    creature (not the target). apply_interception re-validates and heals the target back in C++.
    Mirrors _offer_protective_field but keyed on the interceptor."""
    agents = app.bm.placed_agents
    interceptor_idx = app._find_interceptor(action, target_idx, result)
    itc_name = agents[interceptor_idx].name if 0 <= interceptor_idx < len(agents) else "Ally"

    def _apply():
        app._combat_log_add(atk_msg)   # the hit (and its damage) still landed
        prevented = app.combat.apply_interception(app.bm, interceptor_idx, target_idx, result.total_damage)
        if prevented > 0:
            app._combat_log_add(
                f"{itc_name}: Interception — prevents {prevented} damage to {tgt_name} (reaction + 1d10 + PB).")
        else:
            app._combat_log_add(f"{itc_name}: Interception had no effect.")
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()
        app._continue_attack_sequence_after_rider(atk_idx)

    def _skip():
        app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk_idx)

    options = [
        (f"Interception — {itc_name} reduces damage (reaction + 1d10 + PB)", _apply),
        ("Skip", _skip),
    ]
    app._ask_actor(interceptor_idx if interceptor_idx >= 0 else target_idx, "reaction",
                    f"{itc_name} may intercept {atk_name}'s hit on {tgt_name}",
                    options)


def offer_restore_balance_miss(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg):
    """After a disadvantaged miss, offer Clockwork Restore Balance to cancel the Disadvantage (raise
    d20 → d20_primary) via an eligible ally. apply_restore_balance_miss_to_attack re-validates in C++
    and rolls/applies damage if the cancel turns the miss into a hit."""
    agents = app.bm.placed_agents
    eligible = app._eligible_restore_balance_clockworks(atk_idx, result)

    def _apply(reactor_idx):
        if reactor_idx is not None:
            app.combat.apply_restore_balance_miss_to_attack(app.bm, action, reactor_idx, result)
            if result.hit:
                dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
                dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
                app._combat_log_add(
                    f"{atk_name}→{tgt_name}: Restore Balance cancels Disadvantage → HIT {result.total_damage}"
                    f"{app._damage_breakdown_str(result)} {dmg_type_str}{' — DOWN' if result.target_down else ''}")
            else:
                app._combat_log_add(
                    f"{atk_name}→{tgt_name}: Restore Balance cancels Disadvantage → still misses "
                    f"(roll {result.total_roll} vs AC {result.target_ac})")
        else:
            app._combat_log_add(atk_msg)
        app._flush_combat_log()
        app._sync_spell_effect_cache()
        app._update_attack_overlay()

    options = []
    for ri in eligible:
        options.append((f"Restore Balance: {agents[ri].name} reacts (cancel Disadvantage)",
                        (lambda r=ri: _apply(r))))
    options.append(("Skip Restore Balance", lambda: _apply(None)))
    app._ask_actor(atk_idx, "action", f"{atk_name}→{tgt_name}: Restore Balance", options)
