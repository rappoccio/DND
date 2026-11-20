"""Attack actions: the Attack action's sequence (arm, resolve, finish, Extra Attack,
off-hand and Nick attacks, attack replacements), its riders and follow-ups (Cleave,
Sweep, Horde Breaker, Sudden Strike, Beast's Strike, Great Weapon Master's Hew, Flurry
of Blows, Quivering Palm), and the special attacks that take an attack's place (unarmed
punch / grapple / push, Vampiric Bite, Shove, grapple escape and drop).

Moved out of `App` in APP_REFACTOR_PLAN.md A2 (the "Special Attacks" cut). Module-level
functions taking the app, the pattern `app_initiative.py` and `menus/*.py` already use.
The arm itself is `app.pending` / `app.attack_seq` (`pending.py`); `combat`, `bm` and
the turn state stay on `app` (D3).

`App` keeps a one-line forwarder for each function here that is reached by name from
outside `main.py` (`menus/riders.py`, `menus/reactions.py`, `menus/features.py`,
`net/picks.py`, `actions.py`, `app_initiative.py`, tests) or bound as a callback
(`_finish_attack`, the reaction continuation). Calls between those go through the
forwarder (`app._finish_attack()`), so a test that wraps one on the instance still sees
every call; the rest are called directly.
"""

import random

import rpg_battle_map as rpg

import pending
from constants import FLASH_BAD, FLASH_CRIT, FLASH_GOOD
from menus import reactions, riders


def activate_reckless_and_attack(app, idx: int, slot: str):
    """Set Reckless Attack flag and proceed with attack."""
    cond = app.combat.get_agent_conditions(app.bm, idx)
    cond.reckless_attack = True
    app.combat.set_agent_conditions(app.bm, idx, cond)
    app.combat.log_event("reckless", idx=idx)  # record for checked replay
    agent = app.bm.placed_agents[idx]
    app._combat_log_add(f"{agent.name}: Activates Reckless Attack (enemies gain advantage)")
    # Continue with weapon selection
    app._start_attack(slot)


def continue_attack_sequence_after_rider(app, atk_idx: int):
    """After a rider effect (Stunning Strike, etc.) is applied, check if more attacks remain
    and either re-prompt or end the attack sequence. Called from rider callbacks."""
    # Determine if more attacks remain. Key on the DURABLE attack_seq.slot (not the
    # transient Attack arm, which _finish_attack disarms centrally so the player can
    # move between attacks — see the "central disarm" note there).
    seq_slot = app.attack_seq.slot
    has_more_attacks = False
    if seq_slot == "bonus":
        stats = app.combat.get_agent_stats(app.bm, atk_idx)
        has_more_attacks = stats.bonus_attacks_remaining > 0
    elif seq_slot == "action":
        has_more_attacks = app.attack_seq.remaining > 0

    if has_more_attacks:
        atk_name = app.bm.placed_agents[atk_idx].name
        if seq_slot == "bonus":
            # Bonus multi-attack (Flurry, etc.): single target — keep auto-targeting (unchanged).
            stats = app.combat.get_agent_stats(app.bm, atk_idx)
            rem = stats.bonus_attacks_remaining
            app._disarm(pending.Attack)  # Clear to let _start_attack re-seed
            app._start_attack(app.attack_seq.slot)
            app._combat_log_add(
                f"{atk_name}: {rem} attack{'s' if rem != 1 else ''} remaining — click a target.")
        else:
            # Action Extra-Attack sequence: DISARM between attacks so the player can move; the
            # standing "⚔ Attack (N)" button resumes (count preserved, no re-seed). Mirrors the
            # non-rider path in _finish_attack.
            rem = app.attack_seq.remaining
            app._disarm(pending.Attack)
            app._combat_log_add(
                f"{atk_name}: {rem} attack{'s' if rem != 1 else ''} remaining — "
                f"move if you wish, then click Attack to continue.")
    else:
        # Attacks exhausted
        app._disarm(pending.Attack)
        app.attack_seq.slot = ""
        app.attack_seq.offhand = None
        app.attack_seq.resource = None
        # Boon of Dimensional Travel — arm Blink Steps once the Attack action is fully spent (this is
        # the rider-path twin of the exhausted branch in _finish_attack).
        if seq_slot == "action":
            app._arm_blink_steps(atk_idx)

    app._update_attack_overlay()


def weapon_usable(w) -> bool:
    """A weapon with an N/day cap or a Recharge action is unusable when expended or out of uses."""
    if getattr(w, "expended", False):
        return False
    if getattr(w, "uses_max", 0) > 0 and getattr(w, "uses_remaining", 0) <= 0:
        return False
    return True


def weapon_menu_label(w) -> str:
    """Decorate a weapon's picker label with N/M usage + a ⟳ recharge marker when limited."""
    label = w.name
    if getattr(w, "uses_max", 0) > 0 or getattr(w, "recharge_min", 0) > 0:
        cap = w.uses_max if w.uses_max > 0 else 1
        label += f"  {w.uses_remaining}/{cap}"
        if getattr(w, "expended", False):
            label += " ⟳recharge"
        elif getattr(w, "recharge_min", 0) > 0:
            label += f" ⟳{w.recharge_min}+"
    return label


def attack_action_budget(app, idx: int) -> int:
    """How many weapon attacks one Attack action makes for agent `idx`.

    A Vampire-style stat block ("makes two attacks and uses Bite") counts its grapple-Bite in
    `num_attacks` and in the NPC recipe, but the Bite is not one of the DM's swings: it is the
    separate "🧛 Bite (grappled)" button, used on a creature the vampire is grappling or has
    Charmed. So the DM-driven budget drops the Bite's share of the multiattack recipe."""
    stats = app.combat.get_agent_stats(app.bm, idx)
    n = stats.num_attacks
    recipe = list(stats.multiattack)
    if recipe:
        weapons = app.combat.get_agent_weapons(app.bm, idx)
        bite = {i for i, w in enumerate(weapons) if w.auto_use_when_grappling}
        n -= sum(cnt for slot, cnt in recipe if slot in bite)
    return max(1, n)


def start_attack(app, slot: str):
    """Begin target-selection for an attack in the given slot."""
    idx = app._current_agent_idx()
    if idx < 0:
        return
    weapons = app.combat.get_agent_weapons(app.bm, idx)
    if not weapons:
        app._combat_log_add("No weapons equipped!")
        if slot == "action":
            app.action_used = True
        else:
            app.bonus_used = True
        return

    stats = app.combat.get_agent_stats(app.bm, idx)
    conds = app.combat.get_agent_conditions(app.bm, idx)

    # Reckless Attack prompt for Barbarians
    if (stats.character_class == rpg.CharacterClass.Barbarian and
        conds.raging and not conds.reckless_attack):
        def _proceed_normal():
            app._start_attack(slot)
        options = [
            ("Use Reckless Attack", lambda: activate_reckless_and_attack(app, idx, slot)),
            ("Normal Attack", _proceed_normal)
        ]
        app._ask_actor(idx, "action", f"{app._agent_name(idx)}: Reckless Attack?",
                        options, anchor=(app._panel_x() + app._PANEL_PAD, 290))
        return

    # Only seed attack_seq.remaining when starting a fresh sequence (== 0).
    # If mid-sequence and same slot, don't reset. If mid-sequence and different slot, reject.
    if app.attack_seq.remaining == 0:
        # Fresh start
        if slot == "action":
            app.attack_seq.remaining = attack_action_budget(app, idx)
            # War Magic gates once per Attack action; a fresh Attack action (including the
            # second one granted by Action Surge) re-enables the substitution.
            if conds.war_magic_used:
                conds.war_magic_used = False
                app.combat.set_agent_conditions(app.bm, idx, conds)
        else:
            # Bonus slot: check C++ bonus_attacks_remaining (Flurry, Martial Arts, etc.)
            app.attack_seq.remaining = stats.bonus_attacks_remaining if stats.bonus_attacks_remaining > 0 else 1
        app.attack_seq.slot = slot
        # A normal attack uses default (slot-derived) proficiency and no resource cost.
        app.attack_seq.offhand = None
        app.attack_seq.resource = None
    elif slot != app.attack_seq.slot:
        # Can't start a different slot while attacks are pending
        return
    elif slot == "action" and app.attack_seq.offhand is True:
        # Nick's relocated off-hand swing is the one attack owed (only Nick arms an off-hand
        # swing in the action slot), so "⚔ Attack (1)" resumes THAT swing with the off-hand
        # weapon. The weapon picker let it become a main-hand attack that kept the off-hand flag
        # and never spent the off-hand attack, so Nick came back on offer after it.
        wi = app._nick_offhand_idx(idx)
        if wi >= 0:
            app.pending = pending.Attack(slot)
            app.attack_seq.weapon_idx  = wi
            app._combat_log_add("Nick: off-hand attack (part of Attack action) — click a target.")
            return

    def _activate(s, wi_):
        app.pending = pending.Attack(s)
        app.attack_seq.weapon_idx  = wi_
        rem = app.attack_seq.remaining
        suffix = f" ({rem} attack{'s' if rem != 1 else ''} remaining)"
        app._combat_log_add(f"Click a target on the map.{suffix}")

    # FLAG: Move to C++
    # Filter weapons for bonus attacks: only show off-hand weapons
    weapons_to_use = weapons
    if slot == "bonus":
        offhand_weapons = [w for w in weapons if w.off_hand]
        if offhand_weapons:
            weapons_to_use = offhand_weapons
    elif slot == "action":
        # A grapple-Bite is not one of the Attack action's swings — it has its own button.
        plain = [w for w in weapons if not w.auto_use_when_grappling]
        if plain:
            weapons_to_use = plain

    # Eldritch Knight War Magic (L7+): during the Attack action, one attack may be replaced by
    # casting a spell. Offer it only when the engine gate is open AND there is an eligible spell.
    war_magic_option = None
    if (slot == "action" and app.combat.can_use_war_magic(app.bm, idx)
            and app.combat.available_war_magic_spells(app.bm, idx)):
        def _pick_war_magic():
            app._disarm(pending.Attack)   # leave attack-target mode; enter spell-target mode
            app.attack_seq.weapon_idx  = 0
            app._start_cast_spell("war_magic")
        war_magic_option = ("War Magic: cast spell (replaces an attack)", _pick_war_magic)

    if len(weapons_to_use) == 1 and war_magic_option is None:
        # Auto-select if only one weapon (or one off-hand weapon for bonus)
        only = weapons_to_use[0]
        if not app._weapon_usable(only):
            why = "recharging" if getattr(only, "expended", False) else "out of uses"
            app._combat_log_add(f"{only.name} is {why} — cannot attack with it.")
            return
        wi = next((i for i, w in enumerate(weapons) if w == only), 0)
        _activate(slot, wi)
    else:
        options = []
        for w in weapons_to_use:
            wi = next((i for i, weapon in enumerate(weapons) if weapon == w), 0)
            if not app._weapon_usable(w):
                # Show the depleted weapon greyed-in label, but make selecting it a no-op warning.
                def _blocked(nm=w.name, exp=getattr(w, "expended", False)):
                    app._combat_log_add(f"{nm} is {'recharging' if exp else 'out of uses'} — cannot attack with it.")
                options.append((weapon_menu_label(w), _blocked))
                continue
            def _pick(s=slot, wi_=wi):
                _activate(s, wi_)
            options.append((weapon_menu_label(w), _pick))
        if war_magic_option is not None:
            options.append(war_magic_option)
        app._ask_actor(idx, "action",
                        f"{app._agent_name(idx)}: pick a weapon for the {slot} attack",
                        options, anchor=(app._panel_x() + app._PANEL_PAD, 290))


def damage_breakdown_str(app, result) -> str:
    """Return ' [4 (weapon) + 3 (rage)]' when a hit has multiple damage sources, else ''."""
    bd = getattr(result, "damage_breakdown", None)
    if not bd or len(bd) <= 1:
        return ""
    return " [" + " + ".join(f"{amt} ({label})" for label, amt in bd) + "]"


def start_extra_attack(app, weapon_idx=0, offhand=False, resource=None, label="Extra attack",
                        slot="bonus"):
    """Generic 'make one extra weapon attack' setup — reused by War Priest, Great Weapon Master,
    Nick, etc. Configures the pending-attack knobs and enters target selection; the shared
    target-click → _resolve_combat_attack does the attack and spends `resource` (if any).

    slot="bonus" consumes the bonus action (most callers); slot="action" adds the attack to the
    Attack action without touching the bonus action (Nick's off-hand relocation)."""
    idx = app._current_agent_idx()
    if idx < 0:
        return
    app.attack_seq.slot = slot
    # Only set attack_seq.remaining if not already set (e.g., by Flurry of Blows which queues multiple)
    if app.attack_seq.remaining == 0:
        if slot == "bonus":
            stats = app.combat.get_agent_stats(app.bm, idx)
            app.attack_seq.remaining = stats.bonus_attacks_remaining if stats.bonus_attacks_remaining > 0 else 1
        else:
            app.attack_seq.remaining = 1   # a single extra Attack-action attack (Nick)
    app.pending = pending.Attack(slot)
    app.attack_seq.weapon_idx = weapon_idx
    app.attack_seq.offhand = offhand     # proficient (not an off-hand strike) when False
    app.attack_seq.resource = resource   # spent on a valid attack (e.g. "War Priest")
    app._combat_log_add(f"{label} — click a target.")


def offhand_bonus_available(app, idx: int) -> bool:
    """Can this agent make an off-hand attack as a Bonus Action right now?

    The single Light-property off-hand extra attack lands in the bonus action by default. Once
    it's been spent (e.g. relocated into the Attack action via Nick, or already taken in the
    bonus), only the Dual Wielder feat grants a second bonus-action off-hand attack."""
    if idx < 0 or idx >= len(app.bm.placed_agents):
        return False
    weapons = app.combat.get_agent_weapons(app.bm, idx)
    if not any(w.off_hand for w in weapons):
        return False
    conds = app.combat.get_agent_conditions(app.bm, idx)
    if not conds.offhand_attack_used:
        return True
    return app.combat.get_agent_stats(app.bm, idx).has_feat("Dual Wielder")


def nick_offhand_idx(app, idx: int) -> int:
    """Weapon-array index of an off-hand weapon whose Nick mastery can relocate the off-hand
    attack into the Attack action right now (agent has the Weapon Mastery feature and the
    off-hand extra attack hasn't been spent), else -1."""
    if idx < 0 or idx >= len(app.bm.placed_agents):
        return -1
    # The Weapon Master general feat grants access to a weapon's Mastery property to anyone, so
    # it satisfies the same gate as the martials' auto-granted "Weapon Mastery" feature.
    st = app.combat.get_agent_stats(app.bm, idx)
    if not (st.has_feat("Weapon Mastery") or st.has_feat("Weapon Master")):
        return -1
    if app.combat.get_agent_conditions(app.bm, idx).offhand_attack_used:
        return -1
    weapons = app.combat.get_agent_weapons(app.bm, idx)
    for i, w in enumerate(weapons):
        if w.off_hand and w.mastery == rpg.WeaponMastery.Nick:
            return i
    return -1


def mark_offhand_attack_used(app, idx: int):
    """Mark the single per-turn off-hand extra attack as spent on agent `idx`."""
    if idx < 0 or idx >= len(app.bm.placed_agents):
        return
    conds = app.combat.get_agent_conditions(app.bm, idx)
    conds.offhand_attack_used = True
    app.combat.set_agent_conditions(app.bm, idx, conds)


def attack_is_a_throw(app, atk_idx: int, target_idx: int, weapon_idx: int) -> bool:
    """Is this attack a THROW — i.e. does the weapon leave the attacker's hand?

    A Thrown weapon is hurled when the DM targets something the attacker cannot reach with it:
    that attack is otherwise simply illegal (the engine's canAttack rejects it), so reading it
    as a throw adds the throw without ever turning an ordinary melee swing into one. A Ranged
    weapon with the Thrown property (a Dart) is thrown at any distance — throwing IS how it is
    used. The engine spends the copy and lands it on the ground (applyAttackResult); a weapon
    with no copies left is refused there, so no check for that is needed here."""
    weapons = app.combat.get_agent_weapons(app.bm, atk_idx)
    if not (0 <= weapon_idx < len(weapons)):
        return False
    w = weapons[weapon_idx]
    if not w.thrown:
        return False
    if w.type == rpg.WeaponType.Ranged:
        return True
    dist_ft = app._footprint_dist_ft(atk_idx, target_idx)
    return dist_ft > w.reach_ft


def untouchable_apart(app, a: int, b: int) -> bool:
    """True when exactly one of agents a, b is Untouchable (the engine's two-way seal)."""
    ca = app.combat.get_agent_conditions(app.bm, a)
    cb = app.combat.get_agent_conditions(app.bm, b)
    return bool(ca.untouchable) != bool(cb.untouchable)


def resolve_combat_attack(app, target_idx: int):
    """Resolve the pending attack against target_idx.

    Routes through begin_attack (not execute_action) so the target can cast Shield (+5 AC) as a
    reaction before any damage (the OnHit window). begin_attack rolls the
    attack, then either parks at the Shield checkpoint (AwaitingDecision) or resolves immediately
    (Completed). _finish_attack runs the post-resolution rider chain + logging in both cases,
    reading the result from last_attack_result()."""
    atk_idx = app._current_agent_idx()
    slot    = app._armed_slot(pending.Attack)
    if atk_idx < 0 or not slot:
        return
    if untouchable_apart(app, atk_idx, target_idx):
        app._combat_log_add("Untouchable: that creature is out of reach — pick another target.")
        app._flush_combat_log()
        return
    if app.pending_beasts_strike_targets:
        if target_idx not in app.pending_beasts_strike_targets:
            app._combat_log_add("Beast's Strike: pick a creature the companion can reach.")
            app._flush_combat_log()
            return
        app.pending_beasts_strike_targets = []
        app._beasts_strike_paid_now = False
        app._disarm(pending.Attack)
        app._reaction_finish = lambda i=atk_idx: finish_beasts_strike(app, i)
        status = app.combat.beasts_strike(app.bm, atk_idx, target_idx)
        app._flush_combat_log()
        if status == rpg.FlowStatus.AwaitingDecision:
            app._show_pending_reaction_menu()
        else:
            finish_beasts_strike(app, atk_idx)
        return
    if app.pending_horde_breaker_targets:
        if target_idx not in app.pending_horde_breaker_targets:
            app._combat_log_add("Horde Breaker: pick a creature within 5 ft of the first target "
                                 "that you haven't attacked this turn.")
            app._flush_combat_log()
            return
        app.pending_horde_breaker_targets = []
        hb = app.combat.get_agent_conditions(app.bm, atk_idx)
        hb.horde_breaker_used      = True   # before the swing: it must not re-arm itself
        hb.horde_breaker_available = False
        app.combat.set_agent_conditions(app.bm, atk_idx, hb)
    if app.pending_sudden_strike_targets:
        if target_idx not in app.pending_sudden_strike_targets:
            app._combat_log_add("Sudden Strike: pick a different creature within 5 ft of the "
                                 "Dreadful Strike target.")
            app._flush_combat_log()
            return
        app.pending_sudden_strike_targets = []
        ss = app.combat.get_agent_conditions(app.bm, atk_idx)
        ss.sudden_strike_available = False   # spent with this swing
        app.combat.set_agent_conditions(app.bm, atk_idx, ss)
    action = rpg.Attack(atk_idx, target_idx, app.attack_seq.weapon_idx)
    action.is_offhand = (slot == "bonus") if app.attack_seq.offhand is None else app.attack_seq.offhand
    action.attack_slot = slot  # Pass the slot type to C++ ("action" or "bonus")
    action.thrown = attack_is_a_throw(app, atk_idx, target_idx, app.attack_seq.weapon_idx)
    action.bite_empower = app.pending_bite_empower   # read only for the "Vampiric Bite" weapon

    # Stash what _finish_attack needs (the app.pending_* attrs stay set across the suspend) and
    # arm it as the reaction continuation, then begin the attack.
    app._attack_post = dict(atk_idx=atk_idx, target_idx=target_idx, slot=slot, action=action)
    app._reaction_finish = app._finish_attack

    status = app.combat.begin_attack(app.bm, action)
    app._flush_combat_log()
    if status == rpg.FlowStatus.AwaitingDecision:
        app._show_pending_reaction_menu()   # target's Shield menu; _submit_reaction → _finish_attack
    else:
        app._finish_attack()


def apply_chaos_staff_rider(app, atk_idx: int, target_idx: int, weapon_idx: int, tgt_name: str):
    """Green Slaad's Chaos Staff on-hit rider. On a hit, roll 1d4: the target is Charmed (1),
    Frightened (2), Poisoned (3), or Incapacitated (4) until the start of the Slaad's next turn.
    The random pick lives here in Python; the condition itself is applied + ticked by the C++
    engine (add_agent_condition fully sets the flags; tick_agent_conditions_for_caster expires
    it when the caster's next turn begins, so turns_remaining=1)."""
    weapons = app.combat.get_agent_weapons(app.bm, atk_idx)
    if not (0 <= weapon_idx < len(weapons)):
        return
    if weapons[weapon_idx].name != "Chaos Staff":
        return

    roll = random.randint(1, 4)
    condition = {1: "Charmed", 2: "Frightened", 3: "Poisoned", 4: "Incapacitated"}[roll]

    cond = rpg.ActiveAgentCondition()
    cond.agent_idx       = target_idx
    cond.caster_idx      = atk_idx
    cond.spell_idx       = -1            # weapon rider, not a spell
    cond.condition_name  = condition
    cond.turns_remaining = 1             # expires at the start of the Slaad's next turn
    app.combat.add_agent_condition(app.bm, cond)

    app._combat_log_add(
        f"Chaos Staff (1d4={roll}): {tgt_name} is {condition} until the start of the Slaad's next turn.")


def attack_outcome_msg(app, atk_name: str, tgt_name: str, result, exh_note: str = "") -> str:
    """The one-line HIT / miss log entry for a resolved AttackResult."""
    if result.hit:
        dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
        dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
        return (f"{atk_name}→{tgt_name}: "
                f"HIT {result.total_damage}{app._damage_breakdown_str(result)} {dmg_type_str}"
                f"{' CRIT!' if result.critical else ''}"
                f"{' — DOWN' if result.target_down else ''}"
                f"{exh_note}")
    return (f"{atk_name}→{tgt_name}: "
            f"miss (roll {result.total_roll} vs AC {result.target_ac})"
            f"{exh_note}")


def report_attack_outcome(app, atk_idx: int, target_idx: int, label: str = "") -> bool:
    """Log + flash the last begin_attack result for an out-of-turn strike that skips the
    finish_attack rider chain (legendary actions, lair spawns). `label` prefixes the line
    (e.g. "Legendary Unarmed Strike"). Returns result.valid."""
    result = app.combat.last_attack_result()
    agents = app.bm.placed_agents
    atk_name = agents[atk_idx].name if 0 <= atk_idx < len(agents) else "?"
    tgt_name = agents[target_idx].name if 0 <= target_idx < len(agents) else "?"
    if not result.valid:
        return False
    msg = attack_outcome_msg(app, atk_name, tgt_name, result)
    app._combat_log_add(f"{label}: {msg}" if label else msg)
    if result.hit:
        flash_txt = f"Crit ({result.total_damage})" if result.critical else f"Hit ({result.total_damage})"
        app._spawn_flash(target_idx, flash_txt, FLASH_CRIT if result.critical else FLASH_GOOD)
    else:
        app._spawn_flash(target_idx, "Miss", FLASH_BAD)
    return True


def finish_attack(app):
    """Post-resolution of a begin_attack flow (immediate or after the OnHit Shield window). Reads
    the AttackResult from last_attack_result() and runs the attacker rider-offer chain + logging."""
    ctx        = app._attack_post
    atk_idx    = ctx["atk_idx"]
    target_idx = ctx["target_idx"]
    slot       = ctx["slot"]
    action     = ctx["action"]
    result     = app.combat.last_attack_result()

    # Generic extra-attack cost (War Priest, etc.): spend the resource once, only on a valid attack.
    if result.valid and app.attack_seq.resource:
        app.combat.spend_resource(app.bm, atk_idx, app.attack_seq.resource)
        app.attack_seq.resource = None

    # Spend the single per-turn off-hand extra attack when this strike used the off-hand weapon
    # (base bonus off-hand, Nick relocation, or Dual Wielder's bonus). Once spent, the base
    # bonus off-hand attack is no longer offered — only Dual Wielder grants a second one.
    if result.valid:
        weapons = app.combat.get_agent_weapons(app.bm, atk_idx)
        wi = action.weapon_idx
        if 0 <= wi < len(weapons) and weapons[wi].off_hand:
            mark_offhand_attack_used(app, atk_idx)

    app._flush_combat_log()

    agents   = app.bm.placed_agents
    atk_name = agents[atk_idx].name if atk_idx < len(agents) else "?"
    tgt_name = agents[target_idx].name if target_idx < len(agents) else "?"

    # FLAG: Move to C++
    if not result.valid:
        # Check if attack failed because agent slipped
        if atk_idx >= 0 and atk_idx < len(agents) and agents[atk_idx].conditions.slipped_this_turn:
            app._combat_log_add(f"{atk_name} slipped and cannot act — turn ends.")
            app._disarm(pending.Attack)
            app.attack_seq.remaining   = 0
            app._advance_turn()
        else:
            # Out of range / invalid target: this is a misclick, NOT a spent attack. Do not
            # decrement (the decrement is below this return) and — critically — do not zero
            # attack_seq.remaining. _start_attack re-seeds the count only when it is 0, so zeroing
            # here would let the next Attack click re-seed to num_attacks and hand out a bonus
            # attack (e.g. after a Forceful Blow / Push knocks the target out of reach mid-
            # sequence). Just disarm the Attack so the player can reposition (drag-to-
            # move); clicking Attack again resumes the SAME sequence with the remaining count.
            rem = app.attack_seq.remaining
            tail = (f" ({rem} attack{'s' if rem != 1 else ''} remaining)" if rem > 0 else "")
            if not app.combat.can_perceive_target(app.bm, atk_idx, target_idx):
                app._combat_log_add(
                    f"{atk_name}: can't see that target — move or click Attack to retry{tail}")
            else:
                app._combat_log_add(
                    f"{atk_name}: out of range — move closer or click Attack to retry{tail}")
            app._disarm(pending.Attack)
        return

    # Check if attacker has exhaustion for potential penalty note
    # FLAG: Move to C++
    atk_cond = app.combat.get_agent_conditions(app.bm, atk_idx) if 0 <= atk_idx < len(agents) else None
    exh_note = ""
    if atk_cond and atk_cond.exhaustion_level >= 1:
        penalty = 2 * atk_cond.exhaustion_level
        exh_note = f" [−{penalty} exhaustion]"

    # FLAG: Move to C++
    # Check for a post-hit rider menu (Cunning Strike or Brutal Strike) before logging.
    has_brutal_strike = False
    has_cunning_strike = False
    has_divine_strike = False
    has_guided_strike = False
    has_peerless_aim = False
    has_restore_balance_miss = False
    has_push = False
    has_topple = False
    has_cleave = False
    has_stunning_strike = False
    has_open_hand_rider = False
    has_quivering_palm = False
    has_hand_of_harm = False
    has_elemental_move = False
    has_maneuver = False
    has_precision = False
    has_psionic_strike = False
    has_punch_and_grab = False
    has_divine_smite = False
    has_eldritch_smite = False
    has_reckless_reroll = False
    has_riposte = False
    has_protective_field = False
    has_interception = False
    has_sentinel_guard = False
    has_soul_of_vengeance = False
    has_dreadful_strike = False
    has_homing_strike = False
    if result.valid:
        atk_cond = app.combat.get_agent_conditions(app.bm, atk_idx)
        # Riposte is a DEFENDER reaction: the flag is set on the target, not the attacker.
        tgt_cond = app.combat.get_agent_conditions(app.bm, target_idx) if 0 <= target_idx < len(agents) else None
        if result.hit and atk_cond and atk_cond.cunning_strike_available:
            has_cunning_strike = True
        elif result.hit and atk_cond and atk_cond.brutal_strike_available:
            has_brutal_strike = True
        elif result.hit and atk_cond and atk_cond.stunning_strike_available and app._armed_slot(pending.Attack) == "action":
            has_stunning_strike = True
        elif result.hit and atk_cond and atk_cond.open_hand_rider_available:
            has_open_hand_rider = True
        # Quivering Palm (Open Hand L17): a standalone fallback offer for unarmed hits where neither
        # Stunning Strike (action) nor the Open Hand Flurry rider (bonus) claimed the hit. When one
        # of those DID fire, the plant option is injected into that menu instead (no shadowing).
        elif result.hit and atk_cond and atk_cond.quivering_palm_available:
            has_quivering_palm = True
        elif result.hit and atk_cond and atk_cond.hand_of_harm_available:
            has_hand_of_harm = True
        elif result.hit and atk_cond and atk_cond.elemental_attunement_move_available:
            has_elemental_move = True
        elif result.hit and atk_cond and atk_cond.divine_strike_available:
            has_divine_strike = True
        # Dreadful Strike (Gloom Stalker): an on-hit Psychic rider, like Divine Strike. At L11 its
        # prompt chains the Stalker's Flurry choice (Sudden Strike / Mass Fear / neither).
        elif result.hit and atk_cond and atk_cond.dreadful_strike_available:
            has_dreadful_strike = True
        elif result.hit and atk_cond and atk_cond.psionic_strike_available:
            has_psionic_strike = True
        elif result.hit and atk_cond and atk_cond.grappler_punch_grab_available:
            has_punch_and_grab = True
        elif result.hit and atk_cond and atk_cond.divine_smite_available:
            has_divine_smite = True
        elif result.hit and atk_cond and atk_cond.eldritch_smite_available:
            has_eldritch_smite = True
        elif result.hit and atk_cond and atk_cond.maneuver_available:
            has_maneuver = True
        elif (not result.hit) and atk_cond and atk_cond.peerless_aim_available:
            has_peerless_aim = True
        elif (not result.hit) and atk_cond and atk_cond.guided_strike_available:
            has_guided_strike = True
        elif (not result.hit) and atk_cond and atk_cond.restore_balance_miss_available:
            has_restore_balance_miss = True
        elif (not result.hit) and atk_cond and atk_cond.maneuver_precision_available:
            has_precision = True
        elif (not result.hit) and atk_cond and atk_cond.reckless_reroll_available:
            has_reckless_reroll = True
        # Homing Strikes (Soulknife L9): on a miss with a Psychic Blade, spend a Psionic Energy
        # Die to add to the roll and (maybe) convert it to a hit.
        elif (not result.hit) and app._can_homing_strike(atk_idx, action):
            has_homing_strike = True
        # Riposte is offered LAST among on-miss options (v1): an attacker on-miss rider above
        # shadows the defender's riposte this swing (see known_limitations.md; full chaining is v2).
        elif (not result.hit) and tgt_cond and tgt_cond.riposte_available:
            has_riposte = True
        # Great Weapon Master — Hew is NOT offered here: a melee crit/kill with a Heavy weapon arms
        # the gwm_hew_available flag (in C++), which surfaces as a standalone bonus-action button
        # (see _start_gwm_hew). Keeping it out of this on-hit elif chain lets the weapon-mastery
        # riders below (Cleave/Push/Topple) resolve on the triggering hit without being shadowed.
        elif result.hit and atk_cond and atk_cond.push_available:
            has_push = True
        elif result.hit and atk_cond and atk_cond.topple_available:
            has_topple = True
        elif result.hit and atk_cond and atk_cond.cleave_available:
            has_cleave = True
        # Protective Field is a DEFENDER on-hit reaction (the flag-less mechanic re-validates in
        # C++). Offered LAST among on-hit options (v1): an attacker on-hit rider above shadows the
        # defender's Protective Field this swing (see known_limitations.md). Mirrors riposte's
        # on-miss shadowing.
        elif app._can_protective_field(target_idx, result):
            has_protective_field = True
        # Interception is a BYSTANDER on-hit damage-reduction reaction: an ally within 5 ft of the
        # target spends its reaction to reduce the damage by 1d10 + PB (post-hit heal-back). Offered
        # among the on-hit reductions; the full eligibility scan lives in C++ (can_intercept).
        elif (result.hit and result.total_damage > 0 and not result.target_down
              and app._find_interceptor(action, target_idx, result) >= 0):
            has_interception = True
        # Sentinel Guardian is a BYSTANDER reaction (a third creature near the attacker), fired on a
        # hit OR a miss. Flagged on the attacker; offered LAST among the v1 single-rider chain (an
        # attacker's own rider shadows it this swing — see known_limitations.md).
        elif atk_cond and atk_cond.sentinel_guard_available:
            has_sentinel_guard = True
        # Soul of Vengeance (Oath of Vengeance L15): the sworn foe just attacked; the paladin holding
        # the Vow of Enmity may counter-strike. Flagged on the attacker (the sworn foe); fires on hit OR miss.
        elif atk_cond and atk_cond.soul_of_vengeance_available:
            has_soul_of_vengeance = True

    # FLAG: Move to C++
    atk_msg = attack_outcome_msg(app, atk_name, tgt_name, result, exh_note)

    # On-map outcome flash above the targeted token.
    if result.hit:
        flash_txt = f"Crit ({result.total_damage})" if result.critical else f"Hit ({result.total_damage})"
        app._spawn_flash(target_idx, flash_txt, FLASH_CRIT if result.critical else FLASH_GOOD)
    else:
        app._spawn_flash(target_idx, "Miss", FLASH_BAD)

    # Green Slaad Chaos Staff: on a hit, the target gains a random condition until the
    # start of the Slaad's next turn. The 1d4 condition pick happens here in Python.
    if result.hit:
        app._apply_chaos_staff_rider(atk_idx, target_idx, action.weapon_idx, tgt_name)

    # Decrement attack counter: action attacks use Python attack_seq.remaining,
    # bonus-action attacks use C++ bonus_attacks_remaining
    has_more_attacks = False
    if app._armed_slot(pending.Attack) == "bonus":
        has_more_attacks = app.combat.consume_bonus_attack(app.bm, atk_idx)
    elif app._armed_slot(pending.Attack) == "action":
        app.attack_seq.remaining -= 1
        has_more_attacks = app.attack_seq.remaining > 0

    # Central disarm for the ACTION sequence: disarm the Attack NOW, before any rider
    # menu, so the map leaves target-selection between attacks regardless of which rider (if any)
    # fires. Without this, the many on-hit riders that don't re-prompt (brutal/cunning/divine/
    # push/topple/…) left the map armed → clicking your own sprite resolved as a app-attack
    # ("out of range"). The standing "⚔ Attack (N)" button resumes the sequence; the count is
    # preserved. Bonus sequences keep their own armed auto-target flow (single target). The
    # rider continuations and the no-rider block below key on attack_seq.slot, not this
    # field, so the early clear is safe. Also commit the Action here (and end the sequence when
    # the last attack is spent) so it happens even for the many riders that skip the no-rider
    # block — otherwise a rider on the LAST attack would leave action_used False + a stale
    # attack_seq.slot, and the next Attack click would re-seed a fresh full set of attacks.
    # action_used True mid-sequence is fine: mid_sequence_action keeps the "⚔ Attack (N)" button
    # alive (and the handler lets it fire). Frenzy / unarmed-weapon restore stay in the no-rider
    # block (rider-laden actions skip them — a pre-existing edge, see known_limitations.md).
    if app.attack_seq.slot == "action":
        app._disarm(pending.Attack)
        app.action_used = True
        app.attack_action_taken = True   # a vampire may still Bite after its last swing
        if not has_more_attacks:
            app.attack_seq.slot = ""
            app.attack_seq.offhand = None
            app.attack_seq.resource = None

    # FLAG: Move to C++
    # A weapon grants at most one Mastery, but it stacks with a class on-hit rider (e.g. a
    # Barbarian's Brutal Strike + a Topple maul, or a Paladin's Divine Smite + a Cleave greataxe).
    # The old single-rider elif chain let the class rider shadow the Mastery. Now, when a Class B
    # "extra-damage/effect" rider fires AND a Mastery (Push/Topple/Cleave) is also pending, the
    # damage rider is offered with on_done = the Mastery prompt, so BOTH resolve on the one hit.
    mastery_offer = pending_mastery_offer(app, 
        atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, action.weapon_idx)

    # Grave Domain Path to the Grave: a hit on a creature cursed by a Grave cleric (the attacker
    # itself, or an ally that cleric can see) lets the cleric end the curse for +cleric-level
    # Radiant/Necrotic damage. Offered FIRST and on its own prompt, then the normal rider chain
    # below resumes from the prompt's callback, so no single-choice rider can shadow it.
    path_state = {"applied": False}

    def _resume():
        nonlocal atk_msg
        if path_state["applied"]:
            # The detonation raised the damage; rebuild the HIT line the chain will log.
            atk_msg = attack_outcome_msg(app, atk_name, tgt_name, result, exh_note)
        # Defer logging until the rider effect is chosen; otherwise log immediately.
        if has_cunning_strike:
            riders.offer_cunning_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_stunning_strike:
            riders.offer_stunning_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_open_hand_rider:
            riders.offer_open_hand_rider(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_quivering_palm:
            riders.offer_quivering_palm(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_hand_of_harm:
            riders.offer_hand_of_harm(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_elemental_move:
            riders.offer_elemental_move(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_brutal_strike:
            riders.offer_brutal_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=mastery_offer)
        elif has_divine_strike:
            riders.offer_divine_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=mastery_offer)
        elif has_dreadful_strike:
            riders.offer_dreadful_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=mastery_offer)
        elif has_psionic_strike:
            riders.offer_psionic_strike(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=mastery_offer)
        elif has_punch_and_grab:
            riders.offer_punch_and_grab(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_divine_smite:
            riders.offer_divine_smite(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=mastery_offer)
        elif has_eldritch_smite:
            riders.offer_eldritch_smite(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, on_done=mastery_offer)
        elif has_peerless_aim:
            riders.offer_peerless_aim(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_guided_strike:
            riders.offer_guided_strike(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_restore_balance_miss:
            reactions.offer_restore_balance_miss(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_maneuver:
            riders.offer_maneuver(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_precision:
            riders.offer_precision_attack(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_reckless_reroll:
            riders.offer_reckless_reroll(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_homing_strike:
            riders.offer_homing_strike(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_riposte:
            reactions.offer_riposte(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_protective_field:
            reactions.offer_protective_field(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_interception:
            reactions.offer_interception(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_sentinel_guard:
            reactions.offer_sentinel_guard(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_soul_of_vengeance:
            reactions.offer_soul_of_vengeance(app, action, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_push:
            riders.offer_push(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg)
        elif has_topple:
            riders.offer_topple(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, action.weapon_idx)
        elif has_cleave:
            riders.offer_cleave(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, action.weapon_idx)
        else:
            app._combat_log_add(atk_msg)

        # Concentration on weapon damage is rolled inside execute_action (C++ owns the CON save and,
        # on a failure, fully drops the spell's terrain/effects/conditions). Surface the log + sync caches.
        if result.hit and result.total_damage > 0:
            app._flush_combat_log()
            app._sync_spell_effect_cache()

        # FLAG: Move to C++
        # If target is down, drop their concentration
        if result.target_down:
            app._drop_concentration_for_agent(target_idx)

        # Only run this re-prompt logic if NO rider was offered. If a rider was offered,
        # the rider callback will handle re-prompting via _continue_attack_sequence_after_rider().
        has_rider = has_cunning_strike or has_stunning_strike or has_open_hand_rider or has_quivering_palm or has_hand_of_harm or has_brutal_strike or has_divine_strike or has_psionic_strike or has_guided_strike or has_peerless_aim or has_restore_balance_miss or has_push or has_topple or has_cleave or has_reckless_reroll or has_protective_field or has_interception or has_dreadful_strike
        if not has_rider:
            # Check if more attacks are queued (action or bonus)
            if has_more_attacks:
                # More attacks left in this sequence.
                if app.attack_seq.slot == "bonus":
                    # Bonus multi-attack (e.g. Flurry of Blows): single target, no standing
                    # mid-sequence button, so keep auto-targeting the next strike (unchanged).
                    stats = app.combat.get_agent_stats(app.bm, atk_idx)
                    rem = stats.bonus_attacks_remaining
                    app._disarm(pending.Attack)  # Clear to let _start_attack re-seed
                    app._start_attack("bonus")
                    app._combat_log_add(
                        f"{atk_name}: {rem} attack{'s' if rem != 1 else ''} remaining — click a target.")
                else:
                    # Action Extra-Attack sequence: DISARM target-selection between attacks so the
                    # player can move (clicking your own sprite no longer reads as a app-attack).
                    # The standing "⚔ Attack (N)" button (mid_sequence_action) resumes the sequence;
                    # the count is preserved, so re-clicking does NOT re-seed to a fresh full set
                    # (see _start_attack's `attack_seq.remaining == 0` guard). Requested by the user as
                    # the general fix for "allow movement mid-attack-sequence".
                    rem = app.attack_seq.remaining
                    app._disarm(pending.Attack)
                    app._combat_log_add(
                        f"{atk_name}: {rem} attack{'s' if rem != 1 else ''} remaining — "
                        f"move if you wish, then click Attack to continue.")
            else:
                # Attacks exhausted — mark action used and clear sequence state
                app._disarm(pending.Attack)
                app.attack_seq.slot = ""
                # Clear the generic extra-attack knobs so they don't leak to the next attack.
                app.attack_seq.offhand = None
                app.attack_seq.resource = None
                # Boon of Dimensional Travel — arm Blink Steps: the Attack action is fully spent.
                if slot == "action":
                    app._arm_blink_steps(atk_idx)

            # Restore original weapons if this was an unarmed strike
            if app._unarmed_strike_original_weapons:
                idx_to_restore, orig_weapons = app._unarmed_strike_original_weapons
                app.combat.set_agent_weapons(app.bm, idx_to_restore, orig_weapons)
                app._unarmed_strike_original_weapons = None
            app.pending_bite_empower = 0

            # FLAG: Move to C++
            if slot == "action":
                app.action_used = True
                # 2024 Berserker Frenzy = extra Nd6 damage (N = Rage damage bonus),
                # applied engine-side in combat_attack.cpp. No bonus attack in 2024
                # (that was the 2014 version), so nothing to trigger here.
            else:
                app.bonus_used = True
        # Refresh attack overlay (HP may have changed).
        app._update_attack_overlay()

    path_cleric = (app.combat.path_to_the_grave_cleric(app.bm, atk_idx, target_idx)
                   if result.valid and result.hit else -1)
    if path_cleric >= 0:
        riders.offer_path_to_the_grave(app, path_cleric, atk_idx, target_idx, result,
                                       path_state, _resume)
    else:
        _resume()


def pending_mastery_offer(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, weapon_idx):
    """If a weapon-Mastery on-hit rider (Push/Topple/Cleave) is still pending on this hit, return a
    zero-arg callable that presents it as a CHAINED rider (suppressing the duplicate HIT-line log,
    since the preceding rider already logged the final damage). A weapon grants at most one Mastery,
    so at most one applies. Returns None when no Mastery is pending. Used by _finish_attack to let a
    Mastery resolve after a class on-hit rider (Brutal Strike, Divine Smite, …) instead of being
    shadowed by it."""
    if not result.hit:
        return None
    c = app.combat.get_agent_conditions(app.bm, atk_idx)
    if c.push_available:
        return lambda: riders.offer_push(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, chained=True)
    if c.topple_available:
        return lambda: riders.offer_topple(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, weapon_idx, chained=True)
    if c.cleave_available:
        return lambda: riders.offer_cleave(app, atk_idx, target_idx, atk_name, tgt_name, result, atk_msg, weapon_idx, chained=True)
    return None


def cleave_valid_targets(app, atk: int, first: int, weapon_idx: int) -> list:
    """Foes a Cleave second attack may legally strike: a different, living, non-ally creature
    that is BOTH within 5 ft of the first target AND within the attacker's reach with the Cleave
    weapon. Footprint-aware (handles large creatures). Mirrors the RAW Cleave constraints."""
    agents = app.bm.placed_agents
    weapons = app.combat.get_agent_weapons(app.bm, atk)
    reach = weapons[weapon_idx].reach_ft if 0 <= weapon_idx < len(weapons) else 5
    out = []
    for t in range(len(agents)):
        if t == atk or t == first:
            continue
        if app.combat.get_agent_stats(app.bm, t).hp_cur <= 0:
            continue
        if app._are_allies(atk, t):
            continue
        if app._footprint_dist_ft(first, t) > 5:
            continue
        if app._footprint_dist_ft(atk, t) > reach:
            continue
        if not app._can_reach_through(atk, t):
            continue
        out.append(t)
    return out


def cancel_cleave(app):
    """Esc out of a pending Cleave second-target pick. Refunds the once-per-turn use so the
    player can still Cleave on a later attack this turn."""
    info = app._pick_data("cleave")
    app._drop_pick("cleave")
    if not info:
        return
    c = app.combat.get_agent_conditions(app.bm, info["attacker"])
    c.cleave_used_this_turn = False
    app.combat.set_agent_conditions(app.bm, info["attacker"], c)
    app._combat_log_add("Cleave cancelled.")
    app._flush_combat_log()
    app._update_attack_overlay()


def resolve_cleave(app, second_target: int):
    """Resolve a pending Cleave attack against the clicked 2nd creature. One weapon attack with
    no positive ability modifier on damage. The click must be one of the highlighted legal
    targets (within 5 ft of the first AND within reach); a stray click re-arms rather than
    wasting the Cleave. No action/bonus is consumed."""
    info = app._pick_data("cleave")
    app._drop_pick("cleave")
    if not info:
        return
    atk, first, wi = info["attacker"], info["first"], info["weapon"]
    valid = info.get("valid")
    if valid is None:
        valid = app._cleave_valid_targets(atk, first, wi)
    agents = app.bm.placed_agents
    if not (0 <= second_target < len(agents)):
        app._set_pick("cleave", info)  # off-map click — keep waiting
        return
    if second_target not in valid:
        app._combat_log_add(
            "Cleave: pick a highlighted creature within 5 ft of the first target "
            "and within your reach.")
        app._flush_combat_log()
        app._set_pick("cleave", info)  # re-arm so a misclick doesn't waste the Cleave
        return

    action = rpg.Attack(atk, second_target, wi)
    action.no_ability_damage = True
    # FLAG: stays on execute_action (the auto Shield path) by design — a Cleave is itself a
    # rider-spawned attack, so routing it through begin_attack would open a Shield window during
    # another reaction (reaction-during-reaction), which the engine has no decision stack for yet.
    # Move to begin_attack once that stack lands.
    result = app.combat.execute_action(app.bm, action)
    app._flush_combat_log()

    atk_name = agents[atk].name if atk < len(agents) else "?"
    tgt_name = agents[second_target].name
    if not result.valid:
        app._combat_log_add(f"Cleave: {tgt_name} is out of reach.")
    elif result.hit:
        dmg_parts = app._get_damage_type_names(result.magic_damage_types, result.physical_damage_types)
        dmg_type_str = "/".join(dmg_parts) if dmg_parts else "untyped"
        app._combat_log_add(
            f"Cleave {atk_name}→{tgt_name}: HIT {result.total_damage}"
            f"{app._damage_breakdown_str(result)} {dmg_type_str}"
            f"{' — DOWN' if result.target_down else ''}")
        app._spawn_flash(second_target, f"Hit ({result.total_damage})",
                          FLASH_CRIT if result.critical else FLASH_GOOD)
        if result.target_down:
            app._drop_concentration_for_agent(second_target)
    else:
        app._combat_log_add(
            f"Cleave {atk_name}→{tgt_name}: miss (roll {result.total_roll} vs AC {result.target_ac})")
        app._spawn_flash(second_target, "Miss", FLASH_BAD)
    app._flush_combat_log()
    app._update_attack_overlay()


def gwm_heavy_weapon_idx(app, atk_idx: int) -> int:
    """Index of the agent's equipped Heavy melee (or thrown) weapon — the one a GWM Hew bonus
    attack is made with. Returns the first match, or -1 if none is equipped."""
    weapons = app.combat.get_agent_weapons(app.bm, atk_idx)
    for i, w in enumerate(weapons):
        if w.heavy and (w.type == rpg.WeaponType.Melee or w.thrown):
            return i
    return -1


def start_horde_breaker(app, atk_idx: int):
    """Horde Breaker (Hunter L3): arm the extra attack an earlier attack this turn earned —
    the same weapon, against a creature within 5 ft of that attack's target that hasn't been
    attacked this turn. The engine lists the legal targets; `_resolve_combat_attack` refuses
    any other click and spends the feature (horde_breaker_used) when the swing is made."""
    targets = list(app.combat.horde_breaker_targets(app.bm, atk_idx))
    if not targets:
        return
    c = app.combat.get_agent_conditions(app.bm, atk_idx)
    app.pending_horde_breaker_targets = targets
    app._start_extra_attack(weapon_idx=c.horde_breaker_weapon, offhand=False, slot="action",
                             label="Horde Breaker (a creature within 5 ft of the first target)")
    app._update_attack_overlay()


def start_sudden_strike(app, atk_idx: int):
    """Stalker's Flurry — Sudden Strike (Gloom Stalker L11): arm the free attack the player chose
    when Dreadful Strike landed — the same weapon, against a different creature within 5 ft of
    that target. The engine lists the legal targets; `_resolve_combat_attack` refuses any other
    click and spends the feature (sudden_strike_available) when the swing is made."""
    targets = list(app.combat.sudden_strike_targets(app.bm, atk_idx))
    if not targets:
        return
    c = app.combat.get_agent_conditions(app.bm, atk_idx)
    app.pending_sudden_strike_targets = targets
    app._start_extra_attack(weapon_idx=c.dreadful_strike_weapon, offhand=False, slot="action",
                             label="Sudden Strike (a creature within 5 ft of the first target)")
    app._update_attack_overlay()


def start_beasts_strike(app, atk_idx: int):
    """Beast's Strike (Beast Master, D9): give up one attack of the Attack action and the Primal
    Companion strikes at once — twice from L11 (Bestial Fury). The first click pays the attack
    (`_consume_attack_replacement`) and arms the strikes in the engine (beast_strikes_left); each
    strike is then a target click, refused unless the engine lists it (`beasts_strike_targets`)."""
    targets = list(app.combat.beasts_strike_targets(app.bm, atk_idx))
    if not targets:
        return
    app._beasts_strike_paid_now = False
    if app.combat.get_agent_conditions(app.bm, atk_idx).beast_strikes_left <= 0:
        if not app._can_replace_attack(atk_idx) or not app.combat.arm_beasts_strike(app.bm, atk_idx):
            return
        consume_attack_replacement(app, atk_idx)
        app._beasts_strike_paid_now = True
        app._flush_combat_log()
    app.pending_beasts_strike_targets = targets
    app.pending = pending.Attack("action")
    app._combat_log_add("Beast's Strike — click a creature the companion can reach.")
    app._update_attack_overlay()


def finish_beasts_strike(app, atk_idx: int):
    """After a Beast's Strike resolves (inline or after a defender's reaction): refresh, and arm
    the second strike Bestial Fury owes, if it has a target."""
    app._flush_combat_log()
    app._sync_spell_effect_cache()
    app.sprites.clear()
    if (app.combat.get_agent_conditions(app.bm, atk_idx).beast_strikes_left > 0
            and app.combat.beasts_strike_targets(app.bm, atk_idx)):
        start_beasts_strike(app, atk_idx)
    app._update_attack_overlay()


def start_gwm_hew(app, atk_idx: int):
    """Great Weapon Master — Hew: after a Critical Hit or a kill with a Heavy weapon (flagged in
    C++ as gwm_hew_available), make one attack with that weapon as a Bonus Action. Driven by the
    standalone bonus-action button rather than an on-hit popup, so it no longer competes with the
    weapon-mastery on-hit riders (Cleave/Topple/Push) that resolve on the triggering hit. Routes
    through the shared extra-attack flow (which spends the bonus action) and clears the flag."""
    c = app.combat.get_agent_conditions(app.bm, atk_idx)
    if not c.gwm_hew_available:
        return
    if app.bonus_used:
        app._combat_log_add("Hew: bonus action already used.")
        app._flush_combat_log()
        return
    weapon_idx = gwm_heavy_weapon_idx(app, atk_idx)
    if weapon_idx < 0:
        app._combat_log_add("Hew: no Heavy weapon equipped.")
        app._flush_combat_log()
        return
    c.gwm_hew_available = False
    app.combat.set_agent_conditions(app.bm, atk_idx, c)
    app._start_extra_attack(weapon_idx=weapon_idx, offhand=False,
                             label="Great Weapon Master: Hew")
    app._update_attack_overlay()


def eligible_guided_clerics(app, atk_idx):
    """War Clerics (L3+, Channel Divinity left) who can Guide a missed attack: the attacker, or an
    ally within 30 ft who still has a reaction. apply_guided_strike_effect re-validates in C++."""
    agents = app.bm.placed_agents
    out = []
    if not (0 <= atk_idx < len(agents)):
        return out
    ao = agents[atk_idx].origin
    for ci in range(len(agents)):
        s = app.combat.get_agent_stats(app.bm, ci)
        if (s.character_class != rpg.CharacterClass.Cleric or
                s.cleric_subclass != rpg.ClericSubclass.WarDomain or s.char_level < 3):
            continue
        cd = s.get_resource("Channel Divinity")
        if not cd or cd.current <= 0:
            continue
        if ci == atk_idx:
            out.append(ci)
            continue
        if app.combat.get_agent_conditions(app.bm, ci).reaction_used:
            continue
        co = agents[ci].origin
        reach = 60 if s.char_level >= 6 else 30  # War God's Blessing extends Guided Strike's reach at L6
        if ((co.col - ao.col) ** 2 + (co.row - ao.row) ** 2) ** 0.5 * 5 <= reach:
            out.append(ci)
    return out


def eligible_restore_balance_clockworks(app, atk_idx, result):
    """Clockwork Soul Sorcerers (L3+, >=1 Restore Balance use, reaction free, within 60 ft + LoS,
    ally of the attacker) who can cancel Disadvantage on this disadvantaged miss. The C++ gate
    can_restore_balance_miss re-validates everything (incl. result.disadvantage and the raise)."""
    out = []
    for ci in range(len(app.bm.placed_agents)):
        if app.combat.can_restore_balance_miss(app.bm, ci, atk_idx, result):
            out.append(ci)
    return out


def execute_flurry(app, atk_idx, rider_option):
    """Execute Flurry of Blows with the chosen rider option."""
    agents = app.bm.placed_agents
    if atk_idx < 0 or atk_idx >= len(agents):
        return

    # Prompt for target selection
    app.pending_flurry_atk_idx = atk_idx
    app.pending_flurry_rider_option = rider_option
    app._arm_pick("flurry_target")
    app.hint = "Click target for Flurry of Blows"


def resolve_flurry_target(app, target_idx):
    """Resolve Flurry of Blows target selection and execute."""
    if not hasattr(app, 'pending_flurry_atk_idx') or not app._picking("flurry_target"):
        return

    atk_idx = app.pending_flurry_atk_idx
    rider_option = app.pending_flurry_rider_option
    app._drop_pick("flurry_target")

    # Execute Flurry in C++
    result = app.combat.execute_flurry_of_blows(
        app.bm, atk_idx, target_idx, rider_option
    )

    agents = app.bm.placed_agents
    atk_name = agents[atk_idx].name if atk_idx < len(agents) else "?"
    tgt_name = agents[target_idx].name if target_idx < len(agents) else "?"

    # Log both attacks
    if result.attack1.valid:
        msg1 = f"{atk_name}→{tgt_name}: "
        if result.attack1.hit:
            msg1 += f"HIT {result.attack1.total_damage} Bludgeoning"
        else:
            msg1 += "MISS"
        app._combat_log_add(msg1)
        if result.attack1.hit:
            app._spawn_flash(target_idx, f"Hit ({result.attack1.total_damage})",
                              FLASH_CRIT if result.attack1.critical else FLASH_GOOD)
        else:
            app._spawn_flash(target_idx, "Miss", FLASH_BAD)

    if result.attack2.valid:
        msg2 = f"{atk_name}→{tgt_name}: "
        if result.attack2.hit:
            msg2 += f"HIT {result.attack2.total_damage} Bludgeoning"
        else:
            msg2 += "MISS"
        app._combat_log_add(msg2)
        if result.attack2.hit:
            app._spawn_flash(target_idx, f"Hit ({result.attack2.total_damage})",
                              FLASH_CRIT if result.attack2.critical else FLASH_GOOD)
        else:
            app._spawn_flash(target_idx, "Miss", FLASH_BAD)

    # Log rider results if applicable
    if result.rider1.valid and result.attack1.hit:
        if result.rider1.option == 0:
            app._combat_log_add(
                f"  → Knockdown (STR save DC {result.rider1.knockdown_save_dc}: rolled {result.rider1.knockdown_save_roll}) "
                f"— {'Prone!' if result.rider1.target_knocked_prone else 'Resisted'}")
            app._spawn_flash(target_idx, "Failed" if result.rider1.target_knocked_prone else "Saved",
                              FLASH_BAD if result.rider1.target_knocked_prone else FLASH_GOOD)
        elif result.rider1.option == 1:
            app._combat_log_add(f"  → Push: {tgt_name} pushed back {result.rider1.push_distance} feet")
        elif result.rider1.option == 2:
            app._combat_log_add(f"  → Deny Reaction: {tgt_name} cannot use a reaction")

    if result.rider2.valid and result.attack2.hit:
        if result.rider2.option == 0:
            app._combat_log_add(
                f"  → Knockdown (STR save DC {result.rider2.knockdown_save_dc}: rolled {result.rider2.knockdown_save_roll}) "
                f"— {'Prone!' if result.rider2.target_knocked_prone else 'Resisted'}")
            app._spawn_flash(target_idx, "Failed" if result.rider2.target_knocked_prone else "Saved",
                              FLASH_BAD if result.rider2.target_knocked_prone else FLASH_GOOD)
        elif result.rider2.option == 1:
            app._combat_log_add(f"  → Push: {tgt_name} pushed back {result.rider2.push_distance} feet")
        elif result.rider2.option == 2:
            app._combat_log_add(f"  → Deny Reaction: {tgt_name} cannot use a reaction")

    app._flush_combat_log()
    app.bonus_used = True


def plant_quivering_palm(app, atk_idx, target_idx, tgt_name):
    """Plant Quivering Palm vibrations in the target (Open Hand L17, 4 Focus). Shared by the
    standalone offer and the Stunning Strike / Open Hand rider menus. Returns True if planted."""
    ok = app.combat.plant_quivering_palm(app.bm, atk_idx, target_idx)
    if ok:
        app._combat_log_add(f"  → Quivering Palm: vibrations planted in {tgt_name} (4 Focus)")
    else:
        app._combat_log_add("  → Quivering Palm unavailable (needs 4 Focus Points)")
    return ok


def quivering_palm_option(app, atk_idx, target_idx, tgt_name, continuation):
    """Return a (label, fn) menu tuple for planting Quivering Palm, or None if not available
    (not flagged this hit, or fewer than 4 Focus Points). `continuation` runs after planting."""
    atk_cond = app.combat.get_agent_conditions(app.bm, atk_idx)
    if not (atk_cond and atk_cond.quivering_palm_available):
        return None
    atk_stats = app.combat.get_agent_stats(app.bm, atk_idx)
    fp = atk_stats.get_resource("Focus Points")
    if not fp or fp.current < 4:
        return None
    def _plant():
        plant_quivering_palm(app, atk_idx, target_idx, tgt_name)
        continuation()
    return ("Quivering Palm (4 FP)", _plant)


def resolve_sweep(app, second_target: int):
    """Resolve a pending Sweeping Attack against the clicked 2nd creature (within 5 ft of the
    first target). Spends the superiority die; the original attack roll is reused to see if it
    would hit the 2nd creature's AC. No new attack roll, no action/bonus consumed."""
    info = app._pick_data("sweep")
    app._drop_pick("sweep")
    if not info:
        return
    atk, first = info["attacker"], info["first"]
    agents = app.bm.placed_agents
    if not (0 <= second_target < len(agents)) or second_target in (atk, first):
        app._combat_log_add("Sweeping Attack: must target a different creature.")
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk)
        return
    fo, so = agents[first].origin, agents[second_target].origin
    if max(abs(fo.col - so.col), abs(fo.row - so.row)) > 1:
        app._combat_log_add("Sweeping Attack: the 2nd creature must be within 5 ft of the first target.")
        app._flush_combat_log()
        app._continue_attack_sequence_after_rider(atk)
        return
    res = app.combat.apply_sweeping_attack(app.bm, info["action"], info["result"], second_target)
    tgt2 = agents[second_target].name
    if res.valid and res.condition_applied:
        app._combat_log_add(
            f"  → Sweeping Attack: {tgt2} takes {res.extra_damage} damage "
            f"(roll {res.save_roll} vs AC {res.save_dc}){' — DOWN' if res.extra_target_down else ''}")
        app._spawn_flash(second_target, f"Hit ({res.extra_damage})", FLASH_GOOD)
        if res.extra_target_down:
            app._drop_concentration_for_agent(second_target)
    elif res.valid:
        app._combat_log_add(
            f"  → Sweeping Attack misses {tgt2} (roll {res.save_roll} vs AC {res.save_dc})")
        app._spawn_flash(second_target, "Miss", FLASH_BAD)
    app._flush_combat_log()
    app._update_attack_overlay()
    app._continue_attack_sequence_after_rider(atk)


def create_unarmed_punch_weapon(app):
    """Create a synthetic unarmed punch weapon (1 + STR bludgeoning)."""
    unarmed = rpg.Weapon()
    unarmed.name = "Unarmed Strike"
    unarmed.type = rpg.WeaponType.Melee
    unarmed.proficient = True
    unarmed.finesse = True
    unarmed.reach_ft = 5
    unarmed.bonus_hit = 0
    dmg_roll = rpg.PhysicalDamageRoll()
    dmg_roll.type = rpg.PhysicalDamage.Bludgeoning
    dmg_roll.num_dice = 1
    dmg_roll.die_size = 1
    dmg_roll.bonus = 0
    unarmed.physical_damage_types = [dmg_roll]
    return unarmed


def start_vampiric_bite(app, empower: int):
    """Dhampir Vampiric Bite: an Unarmed Strike dealing 1d4 + CON Piercing, armed like the
    punch. `empower` (1 Drain, 2 Strengthen) rides the Attack to the engine, which spends a
    use only if the bite deals damage to a creature that isn't a Construct or Undead."""
    idx = app._current_agent_idx()
    if idx < 0:
        return
    stats = app.combat.get_agent_stats(app.bm, idx)
    app._start_unarmed_punch(create_vampiric_bite_weapon(app, stats))
    app.pending_bite_empower = int(empower)
    app._combat_log_add("Click a creature to bite (Vampiric Bite — "
                         f"{'Drain' if empower == 1 else 'Strengthen'}).")


def create_vampiric_bite_weapon(app, stats):
    """The Dhampir's bite: 1d4 Piercing; the engine adds CON (rules::damageAbilityMod).
    The attack roll is an Unarmed Strike's: STR, or DEX for a Monk."""
    bite = rpg.Weapon()
    bite.name = "Vampiric Bite"
    bite.type = rpg.WeaponType.Melee
    bite.proficient = True
    bite.finesse = stats.has_class(rpg.CharacterClass.Monk)
    bite.reach_ft = 5
    bite.bonus_hit = 0
    dmg_roll = rpg.PhysicalDamageRoll()
    dmg_roll.type = rpg.PhysicalDamage.Piercing
    dmg_roll.num_dice = 1
    dmg_roll.die_size = 4
    dmg_roll.bonus = 0
    bite.physical_damage_types = [dmg_roll]
    return bite


def start_unarmed_punch(app, unarmed=None):
    """Damage option of an Unarmed Strike (1 + STR Bludgeoning). Resolved as a normal attack
    with a synthetic unarmed weapon in slot 0, so it counts against the Attack action's attacks
    and the real weapons are restored afterward by _finish_attack. `unarmed` swaps in another
    Unarmed Strike weapon (the Dhampir's bite)."""
    idx = app._current_agent_idx()
    if idx < 0:
        return
    app.pending_bite_empower = 0
    is_punch = unarmed is None
    if is_punch:
        unarmed = create_unarmed_punch_weapon(app)
    # Re-arming before the swing (punch, then bite): slot 0 is already the synthetic weapon,
    # so restore from the real loadout saved the first time, not from it.
    saved = app._unarmed_strike_original_weapons
    if saved and saved[0] == idx:
        orig_weapons = saved[1]
    else:
        orig_weapons = app.combat.get_agent_weapons(app.bm, idx)
    new_weapons = [unarmed] + list(orig_weapons[1:])
    app.combat.set_agent_weapons(app.bm, idx, new_weapons)
    app._unarmed_strike_original_weapons = (idx, orig_weapons)
    # Seed the Attack-action budget on a fresh action, then arm a normal attack with the
    # unarmed weapon (slot 0). The standard attack dispatch (the Attack arm) +
    # _finish_attack handle decrementing the count and restoring the weapons.
    if app.attack_seq.remaining == 0:
        app.attack_seq.remaining = attack_action_budget(app, idx)
        app.attack_seq.slot = "action"
    app.pending = pending.Attack("action")
    app.attack_seq.weapon_idx      = 0
    app.attack_seq.offhand  = None
    app.attack_seq.resource = None
    # (the Attack arm replaces any armed Unarmed option: the Damage option goes through the
    # normal attack path, not _resolve_unarmed_option)
    if is_punch:
        app._combat_log_add("Click a target to strike (Unarmed Strike — Damage).")


def start_unarmed_grapple(app):
    """Grapple option of an Unarmed Strike (requires target selection)."""
    if app._current_agent_idx() < 0:
        return
    app.pending = pending.Unarmed("grapple")
    app._combat_log_add("Click a target to grapple (Unarmed Strike — counts as one attack).")


def start_unarmed_push(app):
    """Shove (push 5 ft) option of an Unarmed Strike (requires target selection)."""
    if app._current_agent_idx() < 0:
        return
    app.pending = pending.Unarmed("push")
    app._combat_log_add("Click a target to shove 5 ft (Unarmed Strike — counts as one attack).")


def resolve_unarmed_option(app, target_idx: int):
    """Route an Unarmed Strike option to its resolver. The Damage option is handled through the
    normal attack path (the Attack arm); only Grapple and Shove land here."""
    unarmed = app._armed(pending.Unarmed)
    if unarmed is None:
        return

    if unarmed.type == "grapple":
        resolve_unarmed_grapple(app, target_idx)
    elif unarmed.type == "push":
        resolve_unarmed_push(app, target_idx)

    app._disarm(pending.Unarmed)


def spend_unarmed_attack(app, atk_idx: int) -> bool:
    """Charge an Unarmed Strike option (Grapple / Push) against the Attack action's attack
    budget. Seeds the budget on a fresh action (so a lone Unarmed Strike costs the whole
    Attack action), spends one attack, and commits the Action. Returns True if attacks remain
    (Extra Attack) so the caller can let the player continue — the standing "⚔ Attack (N)" and
    Unarmed buttons resume the sequence."""
    if app.attack_seq.remaining == 0:
        app.attack_seq.remaining = attack_action_budget(app, atk_idx)
        app.attack_seq.slot = "action"
    app.attack_seq.remaining -= 1
    app.action_used = True
    app.attack_action_taken = True
    if app.attack_seq.remaining > 0:
        atk_name = app.bm.placed_agents[atk_idx].name
        app._combat_log_add(
            f"{atk_name}: {app.attack_seq.remaining} attack"
            f"{'s' if app.attack_seq.remaining != 1 else ''} remaining — "
            f"move if you wish, then click Attack or Unarmed to continue.")
        return True
    app.attack_seq.slot = ""
    return False


def resolve_unarmed_grapple(app, target_idx: int):
    """Grapple as an Unarmed Strike (counts against the Attack action's attacks). The grapple
    itself runs in C++ via execute_grapple (contested check + computed escape DC). An invalid
    grapple (out of reach) is treated as a misclick and does NOT spend an attack."""
    atk_idx = app._current_agent_idx()
    if atk_idx < 0:
        return
    action = rpg.GrappleAction()
    action.attacker_idx = atk_idx
    action.target_idx   = target_idx
    result = app.combat.execute_grapple(app.bm, action)
    if result.valid:
        app._combat_log_add(result.log_message)
        if result.success:
            app._update_reach()
            app._update_attack_overlay()
        spend_unarmed_attack(app, atk_idx)
    else:
        app._combat_log_add(f"Grapple failed: {result.log_message}")


def resolve_unarmed_push(app, target_idx: int):
    """Shove (push 5 ft) as an Unarmed Strike (counts against the Attack action's attacks). The
    retained Shove bonus action is separate. An invalid shove (out of reach) is a misclick and
    does NOT spend an attack."""
    atk_idx = app._current_agent_idx()
    if atk_idx < 0:
        return
    action = rpg.ShoveAction()
    action.attacker_idx = atk_idx
    action.target_idx   = target_idx
    action.knock_prone  = False  # the unarmed Push option pushes 5 ft (Shove-Prone uses the bonus action)
    result = app.combat.execute_shove(app.bm, action)
    if result.valid:
        app._combat_log_add(result.log_message)
        if result.push_ft_applied > 0 or result.knocked_prone:
            app._update_reach()
            app._update_attack_overlay()
        spend_unarmed_attack(app, atk_idx)
    else:
        app._combat_log_add(f"Shove failed: {result.log_message}")


def quivering_palm_id_for(app, idx):
    """Return the condition_id of a Quivering Palm planted by agent `idx`, or -1 if none."""
    for c in app.combat.active_agent_conditions:
        if (c.delayed_trigger and c.caster_idx == idx and
                c.condition_name == "QuiveringPalm"):
            return c.condition_id
    return -1


def detonate_quivering_palm(app, idx):
    """Open Hand L17 — take an action to detonate planted Quivering Palm vibrations: forces the
    target's CON save and deals 10d12 Force (half on a save). Resolved entirely in C++."""
    cid = app._quivering_palm_id_for(idx)
    if cid < 0:
        return
    dmg = app.combat.trigger_delayed_effect(app.bm, cid)
    if dmg >= 0:
        app._combat_log_add(f"💥 Quivering Palm detonates — {dmg} Force damage")
    app._flush_combat_log()
    app.action_used = True
    app._update_attack_overlay()


def can_replace_attack(app, idx: int) -> bool:
    """True if this actor still has a weapon attack a thrown item could replace — either one
    left in an Attack action already under way, or an unspent Attack action to start."""
    if app.attack_seq.slot == "bonus":
        return False                      # finish the bonus-action attacks first
    if app.attack_seq.slot == "action" and app.attack_seq.remaining > 0:
        return True
    return not app.action_used


def consume_attack_replacement(app, user_idx: int):
    """Charge a thrown item to the Attack action: it "replaces one of your attacks", so it
    spends one swing out of the attack budget — seeding a fresh Attack action if the actor had
    not started one. Mirrors _consume_cast_slot's War Magic branch, including the disarm that
    lets the player move between attacks and resume with the standing "⚔ Attack (N)" button."""
    if app.attack_seq.slot != "action" or app.attack_seq.remaining <= 0:
        app.attack_seq.remaining     = attack_action_budget(app, user_idx)
        app.attack_seq.slot = "action"

    # The Attack action itself is spent the moment it is taken — exactly as _finish_attack marks
    # it on the first swing. Any swings still owed stay live through mid_sequence_action, which
    # keeps the standing "⚔ Attack (N)" button (and its handler) working while action_used is set.
    app.attack_seq.remaining -= 1
    app.action_used = True
    app.attack_action_taken = True
    if app.attack_seq.remaining > 0:
        app._disarm(pending.Attack)
        rem = app.attack_seq.remaining
        nm  = app.bm.placed_agents[user_idx].name
        app._combat_log_add(
            f"{nm}: {rem} attack{'s' if rem != 1 else ''} remaining — "
            f"move if you wish, then click Attack to continue.")
    else:
        app.attack_seq.slot = ""


def start_shove(app, shove_type: str):
    """Start a shove action (requires target selection)."""
    if app.bonus_used:
        return
    app.pending = pending.Shove("bonus", shove_type)
    hint = f"shove and {'knock prone' if shove_type == 'prone' else 'push 5ft'}"
    app._combat_log_add(f"Click a target to {hint}.")


def start_telekinetic_shove(app):
    """Telekinetic feat — Telekinetic Shove (bonus action, 30 ft, STR save or pushed 5 ft)."""
    if app.bonus_used:
        return
    app.pending = pending.Shove("bonus", "telekinetic")
    app._combat_log_add("Click a target within 30 ft to telekinetically shove (STR save or pushed 5 ft).")


def resolve_shove(app, target_idx: int):
    """Execute the pending shove action."""
    shove = app._armed(pending.Shove)
    if shove is None or not shove.type:
        return

    atk_idx = app._current_agent_idx()
    if atk_idx < 0:
        app._disarm(pending.Shove)
        return

    # Telekinetic Shove is a STR-save shove at 30 ft (reuses the C++ Thunderwave knockback);
    # the ordinary push/prone shove is a contested Athletics check at 5 ft.
    if shove.type == "telekinetic":
        result = app.combat.apply_telekinetic_shove(app.bm, atk_idx, target_idx)
        if result.valid:
            app._combat_log_add(result.log_message)
            if result.push_ft_applied > 0:
                app._update_reach()
                app._update_attack_overlay()
        else:
            app._combat_log_add(f"Telekinetic Shove failed: {result.log_message}")
        app._disarm(pending.Shove)
        app.bonus_used = True
        return

    # Create ShoveAction
    action = rpg.ShoveAction()
    action.attacker_idx = atk_idx
    action.target_idx = target_idx
    action.knock_prone = (shove.type == "prone")

    # Execute shove
    result = app.combat.execute_shove(app.bm, action)

    # Log result
    if result.valid:
        app._combat_log_add(result.log_message)
        if result.push_ft_applied > 0 or result.knocked_prone:
            app._update_reach()
            app._update_attack_overlay()
    else:
        app._combat_log_add(f"Shove failed: {result.log_message}")

    # Mark bonus action as used
    app._disarm(pending.Shove)
    app.bonus_used = True


def execute_grapple_escape(app):
    """Execute escape from grapple (bonus action, no target selection)."""
    if app.bonus_used:
        return

    agent_idx = app._current_agent_idx()
    if agent_idx < 0:
        return

    # Check if agent is actually grappled
    conds = app.combat.get_agent_conditions(app.bm, agent_idx)
    if not conds.grappled:
        app._combat_log_add("Not grappled!")
        return

    # Execute escape
    result = app.combat.execute_grapple_escape(app.bm, agent_idx)

    # Log result
    if result.valid:
        app._combat_log_add(result.log_message)
        if result.success:
            app._update_reach()
            app._update_attack_overlay()
    else:
        app._combat_log_add(f"Escape failed: {result.log_message}")

    # Mark bonus action as used
    app.bonus_used = True


def execute_grapple_drop(app):
    """Voluntarily drop all grapples initiated by the current agent (free action)."""
    agent_idx = app._current_agent_idx()
    if agent_idx < 0:
        return

    # Check if agent is grappling anyone
    agents = app.bm.placed_agents
    is_grappling = any(
        agents[i].conditions.grappler_idx == agent_idx and agents[i].conditions.grappled
        for i in range(len(agents))
    )
    if not is_grappling:
        app._combat_log_add("Not grappling anyone!")
        return

    # Drop all grapples
    app.combat.drop_grapples_by(app.bm, agent_idx)
    agent_name = agents[agent_idx].name if agent_idx < len(agents) else "Unknown"
    app._combat_log_add(f"{agent_name} releases all grappled targets.")
    app._update_reach()
    app._update_attack_overlay()
