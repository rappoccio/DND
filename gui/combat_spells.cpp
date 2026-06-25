// ─────────────────────────────────────────────────────────────────────────────
//  combat_spells.cpp  –  CombatEngine spellcasting, zones, concentration, slots
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  The spellcasting core: cast resolution (attack/save/automatic), Metamagic,
//  persistent zone/effect application & ticking, concentration management, and
//  Sorcerer/Abjurer spell-slot accounting.
//  Sections:
//    · Casting             — executeSpell, availableCastableSpells,
//                            getNumTargetsForSpell, metamagicSpCost
//    · Spell effects & zones— applySpellEffect, applyZoneIfNewThisTurn,
//                            recomputeAnchoredEffects, tickEffects, activeEffects,
//                            clearEffects
//    · Concentration       — concentrationSave, checkConcentrationOnDamage,
//                            dropConcentration, clearAllConcentration,
//                            clearSpellConditionEffect
//    · Slots               — createSpellSlot, convertSlotToSorceryPoints,
//                            expendArcaneWardSlot
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <numeric>
#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  G5b feats — caster resistance-ignore / treat-1-as-2 (Elemental Adept + Poisoner)
// ─────────────────────────────────────────────────────────────────────────────

float CombatEngine::effectiveMagicDamageMult(const Agent::Stats& caster, const Agent::Stats& target,
                                             MagicDamage_t type, bool from_spell) const noexcept
{
    float m = target.magic_damage_multipliers[type];
    if (m > 0.0f && m < 1.0f) {  // Resistance only — leave Immunity (0.0) and Vulnerability untouched
        if (type == Poison && caster.hasFeat("Poisoner")) return 1.0f;            // Potent Poison (any source)
        if (from_spell && caster.hasElementalAdeptType(type)) return 1.0f;        // Elemental Adept (spells)
    }
    return m;
}

int CombatEngine::rollDamageDice(int num_dice, int die_size, std::vector<int>& out_dice,
                                 bool boost1to2, int* empower_budget) noexcept
{
    if (num_dice <= 0 || die_size <= 0) return 0;
    std::vector<int> rolled;
    rolled.reserve(static_cast<std::size_t>(num_dice));
    for (int i = 0; i < num_dice; ++i) {
        int d = roll(die_size);
        if (boost1to2 && d == 1) d = 2;
        rolled.push_back(d);
    }

    // Empowered Spell metamagic: reroll the lowest below-average dice, up to the remaining budget.
    // Rerolling only dice strictly below the die's expected value ((size+1)/2), lowest-first, is the
    // greedy-optimal use of a limited reroll budget — it never lowers expected damage. The new roll
    // is always kept ("you must use the new rolls"), even if it lands lower than the original.
    if (empower_budget && *empower_budget > 0 && num_dice > 0) {
        const double avg = (die_size + 1) / 2.0;
        std::vector<int> idx(rolled.size());
        std::iota(idx.begin(), idx.end(), 0);
        std::sort(idx.begin(), idx.end(),
                  [&](int a, int b){ return rolled[static_cast<std::size_t>(a)] < rolled[static_cast<std::size_t>(b)]; });
        for (int k = 0; k < static_cast<int>(idx.size()) && *empower_budget > 0; ++k) {
            int i = idx[static_cast<std::size_t>(k)];
            if (rolled[static_cast<std::size_t>(i)] >= avg) break;  // ascending order — nothing left below average
            int nd = roll(die_size);
            if (boost1to2 && nd == 1) nd = 2;
            rolled[static_cast<std::size_t>(i)] = nd;
            --*empower_budget;
        }
    }

    int sum = 0;
    for (int d : rolled) { out_dice.push_back(d); sum += d; }
    return sum;
}

int CombatEngine::rollSpellTypeDamage(const Agent::Stats& caster, MagicDamage_t type,
                                      int num_dice, int die_size, std::vector<int>& out_dice,
                                      bool from_spell, int* empower_budget) noexcept
{
    const bool boost = from_spell && caster.hasElementalAdeptType(type);  // treat a 1 as a 2
    return rollDamageDice(num_dice, die_size, out_dice, boost, empower_budget);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Casting
// ─────────────────────────────────────────────────────────────────────────────

// Spell-attack to-hit roller — extracted from executeSpell's AttackRoll branch so a single-target
// attack spell can roll the to-hit ahead of the OnHit Shield window and have executeSpell consume the
// same roll (the spell analog of resolveAttack). Re-fetches caster/target/agents from `bm`; reproduces
// the AttackRoll branch's advantage/disadvantage conditions and the Seeking-Spell reroll verbatim.
SpellToHit CombatEngine::rollSpellAttack(BattleMap& bm, const SpellAction& action, int tgt_idx,
                                         MetamagicOption applied_metamagic)
{
    SpellToHit th{};
    auto agents = bm.placedAgents();
    if (action.caster_idx < 0 || action.caster_idx >= static_cast<int>(agents.size())) return th;
    if (tgt_idx < 0 || tgt_idx >= static_cast<int>(agents.size())) return th;
    const PlacedAgent& caster_pa     = agents[static_cast<std::size_t>(action.caster_idx)];
    const Agent::Stats& caster_stats = caster_pa.agent->getStats();

    const auto& spells = bm.getAgentSpells(action.caster_idx);
    if (action.spell_idx < 0 || action.spell_idx >= static_cast<int>(spells.size())) return th;
    const Spell& sp = spells[static_cast<std::size_t>(action.spell_idx)];

    // Apply advantage/disadvantage from caster conditions
    bool caster_adv = caster_pa.agent->hasAdvantage();
    bool caster_dis = caster_pa.agent->hasDisadvantage();

    // Blinded: caster's attacks have disadvantage
    if (caster_pa.agent->getConditions().blinded) {
        caster_dis = true;
        log_("Disadvantage: caster is blinded");
    }

    // Frightened: caster has disadvantage when fear source is in LOS
    if (caster_pa.agent->getConditions().frightened) {
        for (const auto& ac : activeAgentConditions_) {
            if (ac.agent_idx == action.caster_idx && ac.condition_name == "Frightened" && ac.caster_idx >= 0) {
                if (bm.hasLineOfSight(caster_pa.origin, caster_pa.agent->getSize(),
                                      bm.placedAgents()[ac.caster_idx].origin, 1)) {
                    caster_dis = true;
                    log_("Disadvantage: caster is frightened and fear source is in LOS");
                }
                break;
            }
        }
    }

    // Grappled: caster has disadvantage on spell attacks except against the grappler
    if (caster_pa.agent->getConditions().grappled) {
        if (tgt_idx != caster_pa.agent->getConditions().grappler_idx) {
            caster_dis = true;
            log_("Disadvantage: caster is grappled");
        }
    }

    // Apply engagement disadvantage for ranged spells. Spell Sniper (general feat) — Firing
    // in Melee: a nearby enemy imposes no Disadvantage on the caster's spell attack rolls.
    if (sp.range > 0 && isThreatened(bm, action.caster_idx)) {
        if (caster_stats.hasFeat("Spell Sniper"))
            log_("Spell Sniper: no Disadvantage casting a spell in melee");
        else {
            caster_dis = true;
            log_("Disadvantage: threatened (enemy within 10 ft)");
        }
    }
    if (caster_pa.agent->hasDisadvantage())
        log_("Disadvantage: condition");
    if (caster_pa.agent->hasAdvantage())
        log_("Advantage: condition");

    // Sorcerer Innate Sorcery: advantage on the caster's spell attack rolls while active.
    if (caster_stats.innate_sorcery_turns > 0) {
        caster_adv = true;
        log_("Advantage: Innate Sorcery");
    }

    // Caster is invisible: spell attacks have advantage (Invisibility ends after casting).
    if (caster_pa.agent->getConditions().invisible) {
        caster_adv = true;
        log_("Advantage: caster is invisible");
    }

    // Target blinded: attacker has advantage
    bool target_blinded = agents[static_cast<std::size_t>(tgt_idx)].agent->getConditions().blinded;
    if (target_blinded) {
        caster_adv = true;
        log_("Advantage: target is blinded");
    }

    // Target stunned: attacker has advantage
    bool target_stunned = agents[static_cast<std::size_t>(tgt_idx)].agent->getConditions().stunned;
    if (target_stunned) {
        caster_adv = true;
        log_("Advantage: target is stunned");
    }

    int d20_val;
    if (caster_adv && caster_dis) {
        d20_val = roll(20);  // Cancel out
    } else if (caster_adv) {
        d20_val = rollAdvantage(20);
    } else if (caster_dis) {
        d20_val = rollDisadvantage(20);
    } else {
        d20_val = roll(20);
    }
    int mod     = spellAttackMod(caster_stats);
    int total   = d20_val + mod;
    th.d20        = d20_val;
    th.attack_mod = mod;
    th.total_roll = total;
    th.target_ac  = calculateAC(bm, tgt_idx);
    th.critical   = (d20_val >= caster_stats.crit_threshold);
    th.hit        = th.critical || (d20_val != 1 && total >= th.target_ac);

    // Metamagic — Seeking Spell: reroll a missed spell attack once, keep the new roll.
    if (applied_metamagic == MetamagicSeeking && !th.hit) {
        int reroll;
        if (caster_adv && caster_dis)      reroll = roll(20);
        else if (caster_adv)               reroll = rollAdvantage(20);
        else if (caster_dis)               reroll = rollDisadvantage(20);
        else                               reroll = roll(20);
        log_("Metamagic Seeking: reroll {} (was {})", reroll, d20_val);
        d20_val       = reroll;
        total         = d20_val + mod;
        th.d20        = d20_val;
        th.total_roll = total;
        th.critical   = (d20_val >= caster_stats.crit_threshold);
        th.hit        = th.critical || (d20_val != 1 && total >= th.target_ac);
    }
    return th;
}

// Spell-save roller — extracted from executeSpell's Save branch so a Save-type spell can pre-roll every
// target's save ahead of the OnSaveFail window and have executeSpell consume the same (possibly
// rerolled) result. Re-fetches caster/target/agents; reproduces the Save branch's advantage/disadvantage
// (target conditions + Heightened + Eldritch Strike + Danger Sense) and the STR/DEX auto-fail verbatim.
// Consumes the Eldritch Strike tag exactly once (the preroll REPLACES the inline roll, never both).
SpellSave CombatEngine::rollSpellSave(BattleMap& bm, const SpellAction& action, int tgt_idx,
                                      MetamagicOption applied_metamagic)
{
    SpellSave ss{};
    auto agents = bm.placedAgents();
    if (action.caster_idx < 0 || action.caster_idx >= static_cast<int>(agents.size())) return ss;
    if (tgt_idx < 0 || tgt_idx >= static_cast<int>(agents.size())) return ss;
    const PlacedAgent& caster_pa     = agents[static_cast<std::size_t>(action.caster_idx)];
    const Agent::Stats& caster_stats = caster_pa.agent->getStats();

    const auto& spells = bm.getAgentSpells(action.caster_idx);
    if (action.spell_idx < 0 || action.spell_idx >= static_cast<int>(spells.size())) return ss;
    const Spell& sp = spells[static_cast<std::size_t>(action.spell_idx)];

    const PlacedAgent& target_pa         = agents[static_cast<std::size_t>(tgt_idx)];
    const Agent::Stats& tgt_stats        = target_pa.agent->getStats();
    const Agent::Conditions& target_cond = target_pa.agent->getConditions();

    ss.target_idx = tgt_idx;
    ss.ability    = sp.save_ability;
    ss.dc         = spellSaveDc(caster_stats);

    bool target_adv = target_pa.agent->hasAdvantage();
    bool target_dis = target_pa.agent->hasDisadvantage();

    // Metamagic — Heightened Spell: one target has disadvantage on its save.
    if (applied_metamagic == MetamagicHeightened &&
        !action.target_indices.empty() && tgt_idx == action.target_indices.front()) {
        target_dis = true;
        log_("Metamagic Heightened: {} has disadvantage on the save", agentName(bm, tgt_idx));
    }

    // Eldritch Knight L10 — Eldritch Strike: a creature the EK hit with a weapon has disadvantage on its
    // next save vs a spell the EK casts. One-shot: consume the tag.
    if (target_cond.eldritch_strike_by == action.caster_idx) {
        target_dis = true;
        log_("Eldritch Strike: {} has disadvantage on the save", agentName(bm, tgt_idx));
        Agent::Conditions clear_es = bm.getAgentConditions(tgt_idx);
        clear_es.eldritch_strike_by = -1;
        bm.setAgentConditions(tgt_idx, clear_es);
    }

    // Arcane Trickster L9 — Magical Ambush: if the AT is Hidden/Invisible (unseen) when casting a
    // spell that forces a save, the target has Disadvantage on that save.
    if (caster_stats.character_class == CharacterClass::Rogue &&
        caster_stats.rogue_subclass == ArcaneTricksterPath && caster_stats.char_level >= 9) {
        const Agent::Conditions& cc = caster_pa.agent->getConditions();
        if (cc.hidden || cc.invisible) {
            target_dis = true;
            log_("Magical Ambush: {} has Disadvantage on the save", agentName(bm, tgt_idx));
        }
    }

    // Cleric Light Domain L17 — Corona of Light: enemies within 60 ft of the caster have Disadvantage
    // on saves vs the caster's Fire/Radiant spells while the corona is active.
    if (caster_stats.corona_of_light_turns > 0 && action.caster_idx != tgt_idx &&
        !areAllies(bm, action.caster_idx, tgt_idx)) {
        bool fire_rad = false;
        for (const auto& d : sp.magic_damage_rolls)
            if (d.type == MagicDamage_t::Fire || d.type == MagicDamage_t::Radiant) { fire_rad = true; break; }
        if (fire_rad &&
            footprintDistance(caster_pa.origin, caster_pa.agent->getSize(),
                              target_pa.origin, target_pa.agent->getSize()) * 5 <= 60) {
            target_dis = true;
            log_("Corona of Light: {} has Disadvantage on the save", agentName(bm, tgt_idx));
        }
    }

    // Mantle of Majesty (Bard College of Glamour, L6): during the bard's unearthly-appearance
    // window, a creature Charmed by THIS bard automatically fails its save vs the Command the bard
    // casts. Scoped to sp.name == "Command" so unrelated Commands / casters are unaffected.
    const bool command_majesty_autofail =
        sp.name == "Command" && caster_stats.mantle_majesty_turns > 0 &&
        target_cond.charmed_by == action.caster_idx;

    // Paralyzed, Stunned, and Unconscious targets automatically fail STR and DEX saves
    bool auto_fail = command_majesty_autofail ||
                     ((target_cond.paralyzed || target_cond.stunned || target_cond.unconscious) &&
                      (sp.save_ability == SaveStr || sp.save_ability == SaveDex));

    // Barbarian Danger Sense (L2+): Advantage on DEX saves unless Incapacitated
    if (sp.save_ability == SaveDex && !target_cond.incapacitated &&
        tgt_stats.character_class == CharacterClass::Barbarian && tgt_stats.char_level >= 2) {
        target_adv = true;
        log_("Danger Sense: target has Advantage on DEX save");
    }

    // Fey Wanderer Beguiling Twist (L7): Advantage on a save vs a spell that applies Charmed/Frightened.
    if (!target_cond.incapacitated && tgt_stats.character_class == CharacterClass::Ranger &&
        tgt_stats.ranger_subclass == FeyWandererPath && tgt_stats.char_level >= 7) {
        for (const auto& c : sp.conditions)
            if (c.condition_name == "Charmed" || c.condition_name == "Frightened") {
                target_adv = true;
                log_("Beguiling Twist: {} has Advantage on the save vs charm/fear", agentName(bm, tgt_idx));
                break;
            }
    }

    // Aberrant Mind Psychic Defenses (L6): Advantage on saves vs spells that apply Charmed/Frightened.
    if (!target_cond.incapacitated && tgt_stats.character_class == CharacterClass::Sorcerer &&
        tgt_stats.sorcerer_subclass == SorcererSubclass::AberrantPath && tgt_stats.char_level >= 6) {
        for (const auto& c : sp.conditions)
            if (c.condition_name == "Charmed" || c.condition_name == "Frightened") {
                target_adv = true;
                log_("Psychic Defenses: {} has Advantage on the save vs charm/fear", agentName(bm, tgt_idx));
                break;
            }
    }

    // Zealot Zealous Presence (L10): target with zealous_blessing gets Advantage on saving throws
    if (target_cond.zealous_blessing) {
        target_adv = true;
        log_("Zealous Presence: {} has Advantage on the save", agentName(bm, tgt_idx));
    }

    int save_d20;
    if (auto_fail) {
        save_d20 = 1;  // Automatic fail
        if (command_majesty_autofail) {
            log_("Mantle of Majesty: {} is Charmed by {} and automatically fails its save vs Command",
                 agentName(bm, tgt_idx), agentName(bm, action.caster_idx));
        } else {
            std::string reason = target_cond.paralyzed ? "paralyzed" : (target_cond.stunned ? "stunned" : "unconscious");
            log_("Target is {}: automatically fails {} save",
                 reason, sp.save_ability == SaveStr ? "STR" : "DEX");
        }
    } else if (target_adv && target_dis) {
        save_d20 = roll(20);  // Cancel out
    } else if (target_adv) {
        save_d20 = rollAdvantage(20);
    } else if (target_dis) {
        save_d20 = rollDisadvantage(20);
    } else {
        save_d20 = roll(20);
    }
    // Clockwork L14 Trance of Order: floor the saver's own d20 (9-or-lower → 10). Gated on !auto_fail
    // so a forced automatic failure (save_d20 == 1) is never floored.
    if (!auto_fail) save_d20 = tgt_stats.applyTranceFloor(save_d20);
    ss.d20       = save_d20;
    ss.save_mod  = saveModFor(bm, tgt_idx, sp.save_ability);
    ss.bonus     = 0;
    ss.auto_fail = auto_fail;
    ss.total     = save_d20 + ss.save_mod;
    ss.total     = applyIndomitableMight(bm, tgt_idx, sp.save_ability, ss.total);
    ss.saved     = auto_fail ? false : (ss.total >= ss.dc);
    return ss;
}

SpellResult CombatEngine::executeSpell(BattleMap& bm, const SpellAction& action)
{
    SpellResult result;
    auto agents = bm.placedAgents();

    if (action.caster_idx < 0 || action.caster_idx >= static_cast<int>(agents.size()))
        return result;
    const PlacedAgent& caster_pa = agents[static_cast<std::size_t>(action.caster_idx)];
    if (caster_pa.agent->getConditions().incapacitated) return result;
    if (caster_pa.agent->hasSlippedThisTurn()) return result;

    const auto& spells = bm.getAgentSpells(action.caster_idx);
    if (action.spell_idx < 0 || action.spell_idx >= static_cast<int>(spells.size()))
        return result;
    // Mutable copy: some Metamagic options modify the spell for this cast only
    // (Distant doubles range, Extended doubles duration, Transmuted changes the
    // damage type, Quickened changes the casting time). The agent's stored spell
    // is untouched, and persistent effects copy this (already-modified) sp below.
    Spell sp = spells[static_cast<std::size_t>(action.spell_idx)];

    // Spell Thief (Arcane Trickster L17): a caster whose spell was stolen can't cast that spell
    // until its next long rest (the lock clears in applyLongRest). Refuse before any effect/slot.
    if (caster_pa.agent->getStats().spellIsStolen(sp.name)) {
        log_("{} can't cast {} — the spell was stolen (Spell Thief)",
             agentName(bm, action.caster_idx), sp.name);
        return result;   // valid == false → no effect
    }

    // Cast-time element choice (Chromatic Orb, Sorcerous Burst): the caster picks the
    // damage type per cast. Rewrite every magic-damage roll's type on this local copy
    // only — the stored spell keeps its placeholder type. Applied before Metamagic so
    // Transmuted (elemental-only) can still further convert if both are used.
    if (action.damage_type_override >= 0 && action.damage_type_override < NumMagicDamage_t) {
        auto chosen = static_cast<MagicDamage_t>(action.damage_type_override);
        for (auto& r : sp.magic_damage_rolls) r.type = chosen;
    }

    result.valid       = true;
    result.spell_idx   = action.spell_idx;
    result.spell_name  = sp.name;
    result.attack_type = sp.attack_type;

    const Agent::Stats& caster_stats = caster_pa.agent->getStats();

    // Casting a spell ends the caster's (non-Greater) Invisibility (RAW). Done before any new
    // grant below, so casting Invisibility/Greater Invisibility still leaves the caster invisible.
    {
        Agent::Conditions cc = bm.getAgentConditions(action.caster_idx);
        if (cc.invisible && !cc.invisible_persists_on_action) {
            cc.invisible = false;
            bm.setAgentConditions(action.caster_idx, cc);
            log_("{}'s invisibility ends (cast a spell)", agentName(bm, action.caster_idx));
        }
    }

    // Casting a spell ends the caster's own Sanctuary ward (RAW). Done before any new grant so a
    // creature re-warding itself nets out warded.
    {
        Agent::Conditions cc = bm.getAgentConditions(action.caster_idx);
        if (cc.sanctuary_active) {
            cc.sanctuary_active = false;
            cc.sanctuary_dc     = 0;
            bm.setAgentConditions(action.caster_idx, cc);
            log_("{}'s Sanctuary ends (cast a spell)", agentName(bm, action.caster_idx));
        }
    }


    // Eldritch Spear invocation: extend the cantrip's range before any range-dependent
    // logic (and before Distant Spell, so Distant doubles the already-extended range).
    sp.range = effectiveSpellRange(bm, action.caster_idx, sp);

    // ── Sorcerer Metamagic ────────────────────────────────────────────────────
    // Validate applicability, then deduct Sorcery Points up front and apply the
    // option by temporarily mutating the local `sp` copy (Distant/Extended/Quickened/
    // Transmuted) or, for Careful, building a per-cast safe-target set used in the AoE
    // exclusion below. Heightened/Seeking are resolved per target in the AttackRoll/
    // Save branches via applied_metamagic. Empowered is deferred and Subtle is flavor
    // only — both log and spend no SP. See known_limitations.md.
    MetamagicOption applied_metamagic = MetamagicNone;
    std::vector<int> careful_set;          // Careful: allies excluded from this spell's area (capped at CHA mod)
    const int cha_mod = abilityMod(caster_stats.cha);

    auto isElemental = [](MagicDamage_t t) {
        return t == Acid || t == Cold || t == Fire || t == Lightning || t == Poison || t == Thunder;
    };

    if (action.metamagic == MetamagicSubtle) {
        log_("Metamagic not applied: Subtle Spell has no effect in the combat engine");
    } else if (action.metamagic != MetamagicNone) {
        // Decide whether the option is applicable to THIS spell before spending SP.
        bool applicable = true;
        std::string why;
        switch (action.metamagic) {
            case MetamagicEmpowered:
                if (sp.magic_damage_rolls.empty() && sp.physical_damage_rolls.empty()) {
                    applicable = false; why = "Empowered needs a spell that rolls damage dice";
                }
                break;
            case MetamagicTransmuted: {
                bool valid_type = action.transmuted_damage_type >= 0 &&
                                  action.transmuted_damage_type < NumMagicDamage_t &&
                                  isElemental(static_cast<MagicDamage_t>(action.transmuted_damage_type));
                bool has_elem = std::any_of(sp.magic_damage_rolls.begin(), sp.magic_damage_rolls.end(),
                                            [&](const MagicDamageRoll& r){ return isElemental(r.type); });
                if (!valid_type)    { applicable = false; why = "no valid replacement damage type"; }
                else if (!has_elem) { applicable = false; why = "spell deals no Acid/Cold/Fire/Lightning/Poison/Thunder damage"; }
                break;
            }
            case MetamagicCareful:
                if (sp.attack_type != Spell::Save) { applicable = false; why = "Careful only affects saving-throw spells"; }
                break;
            case MetamagicExtended:
                if (sp.duration < 2) { applicable = false; why = "Extended needs a lasting (non-instantaneous) spell"; }
                break;
            case MetamagicQuickened:
                if (sp.casting_time != Spell::Action) { applicable = false; why = "Quickened needs an Action-cast spell"; }
                break;
            default: break;  // Distant / Heightened / Seeking / Twinned always apply
        }

        if (!applicable) {
            log_("Metamagic not applied: {}", why);
        } else if (!spendResource(bm, action.caster_idx, "Sorcery Points", metamagicSpCost(action.metamagic))) {
            log_("Metamagic not applied: not enough Sorcery Points");
        } else {
            const int cost = metamagicSpCost(action.metamagic);
            applied_metamagic = action.metamagic;
            switch (action.metamagic) {
                case MetamagicCareful:
                    // Same effect as the Evoker's safe targets: chosen allies are excluded from the area.
                    for (int t : action.careful_targets) {
                        if (static_cast<int>(careful_set.size()) >= std::max(1, cha_mod)) break;
                        careful_set.push_back(t);
                    }
                    log_("Metamagic: Careful Spell ({} SP) — {} creature(s) shielded from the area", cost, careful_set.size());
                    break;
                case MetamagicDistant:
                    sp.range = (sp.range >= 5) ? sp.range * 2 : 30;
                    log_("Metamagic: Distant Spell ({} SP) — range now {} ft", cost, sp.range);
                    break;
                case MetamagicExtended:
                    sp.duration *= 2;
                    log_("Metamagic: Extended Spell ({} SP) — duration now {} rounds", cost, sp.duration);
                    break;
                case MetamagicEmpowered:
                    log_("Metamagic: Empowered Spell ({} SP) — reroll up to {} damage die(s) this cast",
                         cost, std::max(1, cha_mod));
                    break;
                case MetamagicHeightened:
                    log_("Metamagic: Heightened Spell ({} SP)", cost);
                    break;
                case MetamagicQuickened:
                    sp.casting_time = Spell::BonusAction;
                    result.cast_as_bonus_action = true;
                    log_("Metamagic: Quickened Spell ({} SP) — cast as a Bonus Action", cost);
                    break;
                case MetamagicSeeking:
                    log_("Metamagic: Seeking Spell ({} SP)", cost);
                    break;
                case MetamagicTransmuted: {
                    auto new_type = static_cast<MagicDamage_t>(action.transmuted_damage_type);
                    for (auto& r : sp.magic_damage_rolls)
                        if (isElemental(r.type)) r.type = new_type;
                    log_("Metamagic: Transmuted Spell ({} SP) — elemental damage changed type", cost);
                    break;
                }
                case MetamagicTwinned:
                    sp.targets_per_upcast_level += 1;
                    log_("Metamagic: Twinned Spell ({} SP) — +1 target per upcast level", cost);
                    break;
                default: break;
            }
        }
    }

    // Upcast damage/healing scaling: a spell cast from a slot above its base level rolls extra dice
    // (upcast_dice_bonus dice per level above base). Applied here to the local `sp` copy so every
    // resolution branch — and Chromatic Orb's leap-match check — sees the larger dice pool. The
    // extra dice are added to the spell's primary rolls: magic rolls, physical rolls, or healing
    // rolls. slot_level 0 = NPC / base-level cast → never scales.
    if (action.slot_level > sp.level && sp.upcast_dice_bonus > 0) {
        int extra = sp.upcast_dice_bonus * (action.slot_level - sp.level);
        if (extra > 0) {
            // Add to the spell's primary rolls (magic, physical, or healing)
            if (!sp.magic_damage_rolls.empty())
                for (auto& r : sp.magic_damage_rolls) r.num_dice += extra;
            else if (!sp.physical_damage_rolls.empty())
                for (auto& r : sp.physical_damage_rolls) r.num_dice += extra;
            else if (sp.type == Spell::Heal)
                sp.healing_type.num_dice += extra;
            log_("Upcast: {} cast at level {} (+{} dice)",
                 sp.name, action.slot_level, extra);
        }
    }

    // Concentration management: check if casting a concentration spell
    if (sp.requires_concentration) {
        Agent::Conditions cond = bm.getAgentConditions(action.caster_idx);
        if (cond.concentrating) {
            // Drop previous concentration
            result.concentration_replaced    = true;
            result.prev_concentration_spell  = cond.concentrating_on;
            cond.concentrating    = false;
            cond.concentrating_on = {};
            bm.setAgentConditions(action.caster_idx, cond);
            // Remove old spell's terrain when dropping concentration
            [[maybe_unused]] auto removed_ids = bm.removeTerrainEffectsBySource(action.caster_idx);
        }
    }

    // Moving Sphere (Emanation): the area is centered on the caster, not an aimed point.
    const bool moving_sphere = (sp.geometry == Spell::Sphere && sp.moves_with_caster);
    int center_col = action.aoe_col;
    int center_row = action.aoe_row;
    if (moving_sphere) {
        center_col = caster_pa.origin.col;
        center_row = caster_pa.origin.row;
    }

    std::vector<int> targets =
        (sp.geometry == Spell::Single || sp.geometry == Spell::Multiple)
        ? action.target_indices
        : resolveAoeTargets(agents, sp, action.caster_idx, center_col, center_row,
                            action.aoe_col2, action.aoe_row2);

    // Faction rule 3 — beneficial (Heal) area/multi-target spells only affect the caster's
    // allies (same faction, incl. the caster). Enemies are never healed/buffed by a
    // "creatures of your choosing" heal. Single-target heals are left alone: the caster
    // deliberately chose that one creature (allowing a cross-faction heal if intended).
    // Only applies when the caster is on a real team — a neutral (faction 0) caster has no
    // allies, so it keeps the legacy "affect everyone in the area" behavior (no regression
    // for un-teamed encounters / old saves).
    const int caster_faction = bm.getAgentFaction(action.caster_idx);
    if (sp.type == Spell::Heal && sp.geometry != Spell::Single && caster_faction != 0) {
        std::erase_if(targets, [&](int t) {
            return !areAllies(bm, action.caster_idx, t);
        });
    }

    // Evoker safe targets fully exclude the caster's protected allies from AoE spells
    // (no save, no damage, no conditions). Metamagic Careful protects the chosen
    // creatures the same way for this one cast. Single/Multiple are directly targeted,
    // so they are untouched.
    if (sp.geometry != Spell::Single && sp.geometry != Spell::Multiple) {
        auto it = safeTargets_.find(action.caster_idx);
        std::vector<int> safe = (it != safeTargets_.end()) ? it->second : std::vector<int>{};
        safe.insert(safe.end(), careful_set.begin(), careful_set.end());
        // Faction rule 2 — "creatures of your choosing" harmful spells (e.g. Radiance of the
        // Dawn) intrinsically spare the caster's allies (same faction + claimed neutrals).
        // Ordinary AoEs (Fireball) leave selective_targeting false → friendly fire stays ON.
        if (sp.type == Spell::Harm && sp.selective_targeting && caster_faction != 0) {
            for (int t : targets)
                if (areAllies(bm, action.caster_idx, t)) safe.push_back(t);
        }
        if (!safe.empty()) {
            std::erase_if(targets, [&safe](int t) {
                return std::find(safe.begin(), safe.end(), t) != safe.end();
            });
        }
    }

    // Emanation ignores the caster's own space — the caster is never a target.
    if (moving_sphere)
        std::erase(targets, action.caster_idx);

    // Check if caster is charmed and any target is the charmer
    if (caster_pa.agent->getConditions().charmed) {
        int charmer_idx = -1;
        for (const auto& cond : activeAgentConditions_) {
            if (cond.agent_idx == action.caster_idx &&
                cond.condition_name == "Charmed") {
                charmer_idx = cond.caster_idx;
                break;
            }
        }

        if (charmer_idx >= 0) {
            // Check if charmer is in the target list
            for (int tgt_idx : targets) {
                if (tgt_idx == charmer_idx) {
                    log_("Spell blocked: caster is charmed and cannot target the charmer with a damaging spell");
                    return result;  // Invalid (valid = false)
                }
            }
        }
    }

    bool any_conditions_applied = false;

    // Life Domain rider context (Disciple of Life / Blessed Healer / Supreme Healing). The effective
    // slot level drives the bonus; a base-level cast (slot_level 0 / NPC) falls back to the spell level.
    const int  heal_slot          = action.slot_level > 0 ? action.slot_level : sp.level;
    const bool life_supreme_heal  = lifeSupremeHealing(caster_stats);
    const int  life_disciple_heal = discipleOfLifeBonus(caster_stats, heal_slot);
    bool       life_healed_other  = false;  // a creature other than the caster was healed → Blessed Healer

    // Chromatic Orb leap counter. When two or more of the orb's damage d8s show the same
    // number on a hit, the orb leaps to a new creature within 30 ft (a fresh attack + damage
    // roll). The leap target is appended to `targets` below, so the normal loop resolves it.
    // At base level the orb may leap only once; cast with a level-2+ slot it can keep leaping.
    int chromatic_leaps_done = 0;

    // TASK D: Radiant Soul (Celestial L6): does this spell deal Radiant(8) or Fire(2) damage?
    // Computed once per cast; the +CHA bonus below applies to the first damaged target this turn.
    bool spell_radiant_or_fire = false;
    for (const auto& rinfo : sp.magic_damage_rolls)
        if (rinfo.type == 8 || rinfo.type == 2) { spell_radiant_or_fire = true; break; }
    if (!spell_radiant_or_fire)
        for (const auto& rinfo : sp.physical_damage_rolls)
            if (rinfo.type == 8 || rinfo.type == 2) { spell_radiant_or_fire = true; break; }

    // Draconic Elemental Affinity (L6): +CHA mod to first damage roll of matching type this turn.
    // Local flag prevents double-application across multiple targets of the same AoE.
    // The per-turn gate (draconic_affinity_used_this_turn) is read once and persisted on first apply.
    bool draconic_affinity_available =
        caster_stats.sorcerer_subclass == SorcererSubclass::DraconicPath &&
        caster_stats.char_level >= 6 &&
        caster_stats.draconic_affinity_type >= 0 &&
        !caster_stats.draconic_affinity_used_this_turn;

    // AoE damage spells (Fireball, etc.) make ONE damage roll for the whole area; every
    // creature in the area takes that same rolled total — full on a failed save, half on a
    // success. RAW the caster does NOT re-roll the damage separately for each target. Pre-roll
    // the shared dice once here and reuse the per-type base damage for every target below; only
    // the target's own resistance multiplier and the half-on-save reduction differ per target.
    // Single-target and multi-beam spells (Magic Missile, Eldritch Blast, Scorching Ray) are not
    // area spells and keep their own per-target/per-beam rolls.
    const bool aoe_geometry = (sp.geometry != Spell::Single && sp.geometry != Spell::Multiple);
    const bool shared_damage_roll =
        aoe_geometry && sp.type == Spell::Harm &&
        (sp.attack_type == Spell::Save || sp.attack_type == Spell::Automatic);
    std::vector<int> shared_dice;        // dice faces (reused for every target's display)
    std::vector<int> shared_magic_base;  // base damage per magic_damage_rolls entry (pre-mult/halving)
    std::vector<int> shared_phys_base;   // base damage per physical_damage_rolls entry
    if (shared_damage_roll) {
        int empower_budget = (applied_metamagic == MetamagicEmpowered) ? std::max(1, cha_mod) : 0;
        for (const auto& roll_info : sp.magic_damage_rolls) {
            int type_damage = rollSpellTypeDamage(caster_stats, roll_info.type, roll_info.num_dice,
                                                  roll_info.die_size, shared_dice, true, &empower_budget);
            type_damage += roll_info.bonus;
            // Draconic Elemental Affinity (L6): +CHA mod to first matching-type roll this turn.
            if (draconic_affinity_available &&
                static_cast<int>(roll_info.type) == caster_stats.draconic_affinity_type) {
                int cha_bonus = abilityMod(caster_stats.cha);
                type_damage += cha_bonus;
                draconic_affinity_available = false;
                Agent::Stats mc = bm.getAgentStats(action.caster_idx);
                mc.draconic_affinity_used_this_turn = true;
                bm.setAgentStats(action.caster_idx, mc);
                log_("Elemental Affinity: +{} {} damage (CHA mod)", cha_bonus, static_cast<int>(roll_info.type));
            }
            shared_magic_base.push_back(type_damage);
        }
        for (const auto& roll_info : sp.physical_damage_rolls) {
            int type_damage = rollDamageDice(roll_info.num_dice, roll_info.die_size,
                                             shared_dice, false, &empower_budget);
            type_damage += roll_info.bonus;
            shared_phys_base.push_back(type_damage);
        }
    }

    // Index-based: the loop may append leap targets (Chromatic Orb) to `targets`, and
    // re-reading targets.size() each iteration lets those new targets be resolved too.
    for (std::size_t ti = 0; ti < targets.size(); ++ti) {
        int tgt_idx = targets[ti];
        if (tgt_idx < 0 || tgt_idx >= static_cast<int>(agents.size())) continue;

        Agent::Stats tgt_stats = bm.getAgentStats(tgt_idx);
        SpellTargetResult tr;
        tr.target_idx = tgt_idx;
        tr.hp_before  = tgt_stats.hp_cur;

        // Immunity to Magic Missile: the Shield spell, or Wild Magic band 2 (spectral shield).
        if (sp.name == "Magic Missile" && (tgt_stats.shield_active || tgt_stats.wild_magic_shield_turns > 0)) {
            tr.hp_after = tgt_stats.hp_cur;
            tr.log_message = agentName(bm, tgt_idx) + " is immune to Magic Missile ("
                           + (tgt_stats.shield_active ? "Shield" : "spectral shield") + ")";
            log_("{}", tr.log_message);
            result.target_results.push_back(tr);
            continue;
        }

        // Sanctuary ward: a damaging (Harm) spell aimed at a warded enemy forces the caster to
        // make a WIS save or lose the spell against that target (RAW: areas of effect are NOT
        // blocked — only directly-targeted Single/Multiple Harm spells gate here).
        if (sp.type == Spell::Harm &&
            (sp.geometry == Spell::Single || sp.geometry == Spell::Multiple) &&
            !areAllies(bm, action.caster_idx, tgt_idx)) {
            Agent::Conditions wcond = bm.getAgentConditions(tgt_idx);
            if (wcond.sanctuary_active) {
                int d20   = roll(20);
                int wmod  = saveModFor(bm, action.caster_idx, SaveWis);
                int total = d20 + wmod;
                if (total < wcond.sanctuary_dc) {
                    tr.hp_after    = tgt_stats.hp_cur;
                    tr.log_message = agentName(bm, action.caster_idx) + " fails the Sanctuary WIS save ("
                                   + std::to_string(d20) + "+" + std::to_string(wmod) + "="
                                   + std::to_string(total) + " vs DC " + std::to_string(wcond.sanctuary_dc)
                                   + ") — the spell can't target " + agentName(bm, tgt_idx);
                    log_("{}", tr.log_message);
                    result.target_results.push_back(tr);
                    continue;
                }
                log_("{} succeeds the Sanctuary WIS save ({}+{}={} vs DC {}) — may target {}",
                     agentName(bm, action.caster_idx), d20, wmod, total, wcond.sanctuary_dc,
                     agentName(bm, tgt_idx));
            }
        }

        // Help spells (e.g. Sanctuary) neither heal nor damage — they only apply their
        // conditions (handled after this switch). Mark a "hit" so condition application proceeds.
        if (sp.type == Spell::Help) {
            tr.hit = true;
        } else
        switch (sp.attack_type) {

        case Spell::AttackRoll: {
            // Roll the to-hit. A GUI single-target attack spell pre-rolled it in advanceCast and may
            // have opened an OnHit Shield window already (the +5 AC / negation is baked into the stored
            // SpellToHit) — consume that same roll so the player's outcome is what lands. Otherwise roll
            // now and offer the inline defender Shield (auto/RL via decider_, or auto-take for GUI
            // multi-beam attack spells, which have no per-beam decision cursor yet).
            SpellToHit th;
            if (castActive() && topCast().has_preroll &&
                tgt_idx == topCast().preroll_target) {
                th = topCast().preroll;
            } else {
                th = rollSpellAttack(bm, action, tgt_idx, applied_metamagic);
                if (maybeDefenderShieldInlineSpell(bm, action, tgt_idx, th))
                    tgt_stats = bm.getAgentStats(tgt_idx);   // Shield mutated the target's slot/AC
            }
            tr.d20        = th.d20;
            tr.attack_mod = th.attack_mod;
            tr.total_roll = th.total_roll;
            tr.target_ac  = th.target_ac;
            tr.critical   = th.critical;
            tr.hit        = th.hit;

            if (tr.hit) {
                std::vector<int> dice;
                int dmg = 0;
                // Empowered Spell: per-target reroll budget of CHA mod damage dice (0 = inactive).
                int empower_budget = (applied_metamagic == MetamagicEmpowered) ? std::max(1, cha_mod) : 0;

                if (sp.type == Spell::Heal) {
                    // Healing spell: roll healing_type dice + add spellcasting ability modifier
                    int n_dice = sp.healing_type.num_dice;
                    int die_size = sp.healing_type.die_size;
                    for (int i = 0; i < n_dice; ++i) {
                        int d = life_supreme_heal ? die_size : roll(die_size);
                        dice.push_back(d);
                        dmg += d;
                    }
                    dmg += sp.healing_type.bonus;
                    // Add spellcasting ability modifier
                    int ability_score = 10;  // default
                    if (caster_stats.spellcasting_ability == 0) ability_score = caster_stats.str;
                    else if (caster_stats.spellcasting_ability == 1) ability_score = caster_stats.dex;
                    else if (caster_stats.spellcasting_ability == 2) ability_score = caster_stats.con;
                    else if (caster_stats.spellcasting_ability == 3) ability_score = caster_stats.intel;
                    else if (caster_stats.spellcasting_ability == 4) ability_score = caster_stats.wis;
                    else if (caster_stats.spellcasting_ability == 5) ability_score = caster_stats.cha;
                    int ability_mod = abilityMod(ability_score);
                    dmg += ability_mod;
                    if (life_disciple_heal > 0) {
                        dmg += life_disciple_heal;  // Disciple of Life
                        log_("Disciple of Life: +{} HP", life_disciple_heal);
                    }
                    log_("[HEAL] Rolled {}d{} = {} + bonus {} + ability mod {} = total {}",
                         n_dice, die_size, std::accumulate(dice.begin(), dice.end(), 0),
                         sp.healing_type.bonus, ability_mod, dmg);
                } else if ( sp.type == Spell::Harm ) {
                    // Damage spell: roll per-damage-type damage and apply target's multipliers
                    for (const auto& roll_info : sp.magic_damage_rolls) {
                        int n_dice = tr.critical ? roll_info.num_dice * 2 : roll_info.num_dice;
                        // Elemental Adept: treat a 1 as a 2 on the caster's chosen elements (spells).
                        int type_damage = rollSpellTypeDamage(caster_stats, roll_info.type, n_dice,
                                                              roll_info.die_size, dice, true, &empower_budget);
                        // Draconic Elemental Affinity (L6): add CHA mod to first matching-type roll this turn.
                        if (draconic_affinity_available &&
                            static_cast<int>(roll_info.type) == caster_stats.draconic_affinity_type) {
                            int cha_bonus = abilityMod(caster_stats.cha);
                            type_damage += cha_bonus;
                            draconic_affinity_available = false;
                            Agent::Stats mc = bm.getAgentStats(action.caster_idx);
                            mc.draconic_affinity_used_this_turn = true;
                            bm.setAgentStats(action.caster_idx, mc);
                            log_("Elemental Affinity: +{} {} damage (CHA mod)", cha_bonus, static_cast<int>(roll_info.type));
                        }
                        // Resistance/vuln/immunity multiplier — Elemental Adept / Poisoner lift the
                        // caster-relevant Resistance to 1.0.
                        float multiplier = effectiveMagicDamageMult(caster_stats, tgt_stats, roll_info.type, true);
                        int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                        log_("[DAMAGE] Spell attack: type={} base={} mult={} result={}", static_cast<int>(roll_info.type), type_damage, multiplier, modified_damage);
                        dmg += modified_damage;
                    }
                    for (const auto& roll_info : sp.physical_damage_rolls) {
                        int n_dice = tr.critical ? roll_info.num_dice * 2 : roll_info.num_dice;
                        int type_damage = rollDamageDice(n_dice, roll_info.die_size, dice, false, &empower_budget);
                        // Apply target's resistance/vulnerability/immunity multiplier
                        float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                        int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                        dmg += modified_damage;
                    }

                    // Agonizing Blast: add CHA modifier to each Eldritch Blast beam's damage.
                    if (sp.name == "Eldritch Blast" &&
                        caster_stats.character_class == CharacterClass::Warlock &&
                        caster_stats.hasInvocation(0)) {
                        int chaMod = abilityMod(caster_stats.cha);
                        if (chaMod > 0) {
                            dmg += chaMod;
                            log_("Agonizing Blast: +{} damage", chaMod);
                        }
                    }
                }

                tr.dice_results = dice;

                if (sp.type == Spell::Heal) {
                    tr.total_healing = std::max(0, dmg);
                    tgt_stats.hp_cur = std::min(tgt_stats.hp_max,
                                                tgt_stats.hp_cur + tr.total_healing);
                } else if  (sp.type == Spell::Harm) {
                    tr.total_damage  = std::max(0, dmg);
                    // Bastion of Law ward (Clockwork L6) soaks damage before temp HP.
                    tr.total_damage  = applyBastionWard(bm, tgt_idx, tgt_stats, tr.total_damage);
                    // Temporary HP absorbs damage first, then overflow damages hp_cur
                    int overflow = std::max(0, tr.total_damage - tgt_stats.temp_hp);
                    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - tr.total_damage);
                    tgt_stats.hp_cur = std::max(0, tgt_stats.hp_cur - overflow);
                }

                // Chromatic Orb: if two or more of the damage d8s show the same number, the orb
                // leaps to a different creature within 30 ft of this target, with its own attack
                // roll and damage roll. Appending the chosen creature to `targets` lets the loop
                // resolve the leap exactly like a normal target (fresh to-hit + damage). At base
                // level the orb leaps at most once; a level-2+ slot lets it keep leaping (a fresh
                // match each hop). The next target is auto-picked: the nearest not-yet-targeted
                // enemy within 30 ft (the "different creature of your choice" — a sane caster aims
                // at a foe). Match is checked on `dice` (the d8 results just rolled for this hit).
                if (sp.name == "Chromatic Orb") {
                    const bool upcast   = action.slot_level >= 2;
                    const bool may_leap = (chromatic_leaps_done == 0) || upcast;
                    bool matched = false;
                    for (std::size_t a = 0; a < dice.size() && !matched; ++a)
                        for (std::size_t b = a + 1; b < dice.size(); ++b)
                            if (dice[a] == dice[b]) { matched = true; break; }
                    // Debug: surface the exact d8 faces rolled and whether they produced a
                    // leap-triggering match (the orb leaps only on two-or-more matching dice).
                    std::string face_str;
                    for (std::size_t k = 0; k < dice.size(); ++k)
                        face_str += (k ? "," : "") + std::to_string(dice[k]);
                    log_("[CHROMATIC ORB] d8s rolled: [{}] ({} dice) — match={}, may_leap={} (slot_level={})",
                         face_str, dice.size(), matched ? "YES" : "no",
                         may_leap ? "yes" : "no", action.slot_level);
                    if (may_leap && matched && chromatic_leaps_done < 20) {
                        const PlacedAgent& from_pa = agents[static_cast<std::size_t>(tgt_idx)];
                        // A creature is a legal leap target if it's a living non-ally that hasn't
                        // already been hit and sits within 30 ft of the creature we're leaping from.
                        auto eligible = [&](int cand) -> int {  // returns hop distance in cells, or -1
                            if (cand < 0 || cand >= static_cast<int>(agents.size())) return -1;
                            if (cand == action.caster_idx) return -1;
                            if (std::find(targets.begin(), targets.end(), cand) != targets.end()) return -1;
                            if (areAllies(bm, action.caster_idx, cand)) return -1;
                            if (bm.getAgentStats(cand).hp_cur <= 0) return -1;
                            const PlacedAgent& cpa = agents[static_cast<std::size_t>(cand)];
                            int d = footprintDistance(from_pa.origin, from_pa.agent->getSize(),
                                                      cpa.origin, cpa.agent->getSize());
                            return (d * 5 <= 30) ? d : -1;
                        };
                        int leap_to = -1, best = 999;
                        // Player's chosen chain takes priority: the pick earmarked for this hop, if legal.
                        if (chromatic_leaps_done < static_cast<int>(action.chromatic_leap_targets.size())) {
                            int pick = action.chromatic_leap_targets[static_cast<std::size_t>(chromatic_leaps_done)];
                            int d = eligible(pick);
                            if (d >= 0) { leap_to = pick; best = d; }
                        }
                        // Otherwise (no/invalid pick) auto-select the nearest eligible enemy.
                        if (leap_to < 0) {
                            for (int cand = 0; cand < static_cast<int>(agents.size()); ++cand) {
                                int d = eligible(cand);
                                if (d >= 0 && d < best) { best = d; leap_to = cand; }
                            }
                        }
                        if (leap_to >= 0) {
                            targets.push_back(leap_to);
                            ++chromatic_leaps_done;
                            log_("Chromatic Orb leaps to {} ({} ft away — matching d8s)",
                                 agentName(bm, leap_to), best * 5);
                        } else {
                            log_("Chromatic Orb's d8s match but no creature is within 30 ft to leap to");
                        }
                    }
                }
            }

            // Generate log message
            std::string crit_str = tr.critical ? " CRIT!" : "";
            std::string result_str = tr.total_healing ? "HEAL" : (tr.total_damage > 0 ? "HIT" : "HIT");
            std::string damage_str = std::to_string(tr.total_healing ? tr.total_healing : tr.total_damage);
            std::string down_str = tr.target_down ? " — DOWN" : "";

            if (tr.hit) {
                tr.log_message = "HIT (roll " + std::to_string(tr.d20) + " + " + std::to_string(tr.attack_mod)
                    + " = " + std::to_string(tr.total_roll) + " vs AC " + std::to_string(tr.target_ac) + ")"
                    + crit_str + " " + damage_str + down_str;
            } else {
                tr.log_message = "miss (roll " + std::to_string(tr.d20) + " + " + std::to_string(tr.attack_mod)
                    + " = " + std::to_string(tr.total_roll) + " vs AC " + std::to_string(tr.target_ac) + ")";
            }
            break;
        }

        case Spell::Save: {
            const Agent::Conditions& target_cond =
                agents[static_cast<std::size_t>(tgt_idx)].agent->getConditions();

            // Consume a pre-rolled save when one exists: the OnSaveFail window (advanceCast)
            // pre-rolls every target's save for a directly-targeted Save spell and may
            // have rerolled it (Countercharm / Indomitable). Otherwise roll it now via rollSpellSave, which
            // reproduces the same adv/dis + auto-fail logic AND consumes the Eldritch Strike tag exactly
            // once (the preroll REPLACES this roll, never both). Direct executeSpell callers (zones/NPC)
            // have no in-flight cast → has_save_preroll is false → they roll inline as before.
            SpellSave ss;
            if (castActive() && topCast().has_save_preroll) {
                for (const auto& p : topCast().save_prerolls)
                    if (p.target_idx == tgt_idx) { ss = p; break; }
            }
            if (ss.target_idx < 0) ss = rollSpellSave(bm, action, tgt_idx, applied_metamagic);
            tr.save_d20 = ss.d20;
            tr.save_mod = ss.save_mod + ss.bonus;   // ability + prof + auras (+ any reaction bonus)
            tr.save_dc  = ss.dc;
            tr.saved    = ss.saved;

            std::vector<int> dice;
            int dmg = 0;
            // Empowered Spell: per-target reroll budget of CHA mod damage dice (0 = inactive).
            int empower_budget = (applied_metamagic == MetamagicEmpowered) ? std::max(1, cha_mod) : 0;

            if (sp.type == Spell::Heal) {
                // Healing spell: roll healing_type dice + add spellcasting ability modifier
                int n_dice = sp.healing_type.num_dice;
                int die_size = sp.healing_type.die_size;
                for (int i = 0; i < n_dice; ++i) {
                    int d = life_supreme_heal ? die_size : roll(die_size);
                    dice.push_back(d);
                    dmg += d;
                }
                dmg += sp.healing_type.bonus;
                // Add spellcasting ability modifier
                int ability_score = 10;  // default
                if (caster_stats.spellcasting_ability == 0) ability_score = caster_stats.str;
                else if (caster_stats.spellcasting_ability == 1) ability_score = caster_stats.dex;
                else if (caster_stats.spellcasting_ability == 2) ability_score = caster_stats.con;
                else if (caster_stats.spellcasting_ability == 3) ability_score = caster_stats.intel;
                else if (caster_stats.spellcasting_ability == 4) ability_score = caster_stats.wis;
                else if (caster_stats.spellcasting_ability == 5) ability_score = caster_stats.cha;
                int ability_mod = abilityMod(ability_score);
                dmg += ability_mod;
                if (life_disciple_heal > 0) {
                    dmg += life_disciple_heal;  // Disciple of Life
                    log_("Disciple of Life: +{} HP", life_disciple_heal);
                }
                log_("[HEAL] Rolled {}d{} = {} + bonus {} + ability mod {} = total {}",
                     n_dice, die_size, std::accumulate(dice.begin(), dice.end(), 0),
                     sp.healing_type.bonus, ability_mod, dmg);
            } else if (shared_damage_roll) {
                // AoE: reuse the single area-wide roll made before the loop. Only the target's
                // own resistance multiplier and the half-on-save reduction vary per target.
                dice = shared_dice;
                for (std::size_t r = 0; r < sp.magic_damage_rolls.size(); ++r) {
                    const auto& roll_info = sp.magic_damage_rolls[r];
                    float multiplier = effectiveMagicDamageMult(caster_stats, tgt_stats, roll_info.type, true);
                    int modified_damage = static_cast<int>(static_cast<float>(shared_magic_base[r]) * multiplier);
                    if (tr.saved) modified_damage /= 2;
                    dmg += modified_damage;
                }
                for (std::size_t r = 0; r < sp.physical_damage_rolls.size(); ++r) {
                    const auto& roll_info = sp.physical_damage_rolls[r];
                    float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                    int modified_damage = static_cast<int>(static_cast<float>(shared_phys_base[r]) * multiplier);
                    if (tr.saved) modified_damage /= 2;
                    dmg += modified_damage;
                }

                // Rogue Evasion (L7+): on a DEX save, success = no damage, failure = half.
                if (sp.save_ability == SaveDex &&
                    tgt_stats.character_class == CharacterClass::Rogue && tgt_stats.char_level >= 7 &&
                    !target_cond.incapacitated) {
                    dmg = tr.saved ? 0 : (dmg / 2);
                    log_("Evasion: {} {} damage on a DEX save", agentName(bm, tgt_idx),
                         tr.saved ? "takes no" : "halves");
                }
            } else {
                // Damage spell: roll per-damage-type damage and apply target's multipliers
                for (const auto& roll_info : sp.magic_damage_rolls) {
                    // Elemental Adept: treat a 1 as a 2 on the caster's chosen elements (spells).
                    int type_damage = rollSpellTypeDamage(caster_stats, roll_info.type, roll_info.num_dice,
                                                          roll_info.die_size, dice, true, &empower_budget);
                    type_damage += roll_info.bonus;
                    // Draconic Elemental Affinity (L6): add CHA mod to first matching-type roll this turn.
                    if (draconic_affinity_available &&
                        static_cast<int>(roll_info.type) == caster_stats.draconic_affinity_type) {
                        int cha_bonus = abilityMod(caster_stats.cha);
                        type_damage += cha_bonus;
                        draconic_affinity_available = false;
                        Agent::Stats mc = bm.getAgentStats(action.caster_idx);
                        mc.draconic_affinity_used_this_turn = true;
                        bm.setAgentStats(action.caster_idx, mc);
                        log_("Elemental Affinity: +{} {} damage (CHA mod)", cha_bonus, static_cast<int>(roll_info.type));
                    }
                    // Resistance/vuln/immunity multiplier first (Elemental Adept / Poisoner lift the
                    // caster-relevant Resistance to 1.0).
                    float multiplier = effectiveMagicDamageMult(caster_stats, tgt_stats, roll_info.type, true);
                    int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                    // Then apply half damage on successful save
                    if (tr.saved) modified_damage /= 2;
                    dmg += modified_damage;
                }
                for (const auto& roll_info : sp.physical_damage_rolls) {
                    int type_damage = rollDamageDice(roll_info.num_dice, roll_info.die_size, dice, false, &empower_budget);
                    type_damage += roll_info.bonus;
                    // Apply target's resistance/vulnerability/immunity multiplier first
                    float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                    int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                    // Then apply half damage on successful save
                    if (tr.saved) modified_damage /= 2;
                    dmg += modified_damage;
                }

                // Rogue Evasion (L7+): on a DEX save, success = no damage, failure = half.
                // A successful save already halved per-roll above; override to the Evasion outcome.
                if (sp.save_ability == SaveDex &&
                    tgt_stats.character_class == CharacterClass::Rogue && tgt_stats.char_level >= 7 &&
                    !target_cond.incapacitated) {
                    dmg = tr.saved ? 0 : (dmg / 2);
                    log_("Evasion: {} {} damage on a DEX save", agentName(bm, tgt_idx),
                         tr.saved ? "takes no" : "halves");
                }
            }

            tr.dice_results = dice;

            if (sp.type == Spell::Heal) {
                tr.total_healing = std::max(0, dmg);
                tgt_stats.hp_cur = std::min(tgt_stats.hp_max,
                                            tgt_stats.hp_cur + tr.total_healing);
            } else {
                tr.total_damage  = std::max(0, dmg);
                // Bastion of Law ward (Clockwork L6) soaks damage before temp HP.
                tr.total_damage  = applyBastionWard(bm, tgt_idx, tgt_stats, tr.total_damage);
                // Temporary HP absorbs damage first, then overflow damages hp_cur
                int overflow = std::max(0, tr.total_damage - tgt_stats.temp_hp);
                tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - tr.total_damage);
                tgt_stats.hp_cur = std::max(0, tgt_stats.hp_cur - overflow);
            }
            break;
        }

        case Spell::Automatic:
        default: {
            // True Strike: make a weapon attack using spellcasting ability for attack and damage.
            if (sp.name == "True Strike") {
                tr.hp_before = tgt_stats.hp_cur;

                // Roll attack using spellcasting ability mod, not normal attack bonus
                int d20_val = roll(20);
                int mod = spellAttackMod(caster_stats);
                int total_roll = d20_val + mod;
                int target_ac = calculateAC(bm, tgt_idx);
                bool is_critical = (d20_val >= caster_stats.crit_threshold);
                tr.d20 = d20_val;
                tr.attack_mod = mod;
                tr.total_roll = total_roll;
                tr.target_ac = target_ac;
                tr.critical = is_critical;
                tr.hit = is_critical || (d20_val != 1 && total_roll >= target_ac);

                if (tr.hit) {
                    // Get the caster's primary weapon for damage rolling
                    auto caster_weapons = bm.getAgentWeapons(action.caster_idx);
                    if (!caster_weapons.empty()) {
                        const Weapon& weapon = caster_weapons[0];

                        // Roll damage using weapon damage dice + spellcasting ability mod
                        int damage = 0;

                        // Use weapon's physical damage rolls if available, otherwise fall back to convenience fields
                        if (!weapon.physicalDamageRolls.empty()) {
                            const auto& dmg_roll = weapon.physicalDamageRolls[0];  // Primary damage type
                            const int num_dice = tr.critical ? dmg_roll.num_dice * 2 : dmg_roll.num_dice;
                            for (int i = 0; i < num_dice; ++i) {
                                int d = roll(dmg_roll.die_size);
                                tr.dice_results.push_back(d);
                                damage += d;
                            }

                            // Add spellcasting ability modifier (not weapon ability modifier)
                            int ability_score = 10;
                            if (caster_stats.spellcasting_ability == 0) ability_score = caster_stats.str;
                            else if (caster_stats.spellcasting_ability == 1) ability_score = caster_stats.dex;
                            else if (caster_stats.spellcasting_ability == 2) ability_score = caster_stats.con;
                            else if (caster_stats.spellcasting_ability == 3) ability_score = caster_stats.intel;
                            else if (caster_stats.spellcasting_ability == 4) ability_score = caster_stats.wis;
                            else if (caster_stats.spellcasting_ability == 5) ability_score = caster_stats.cha;
                            int ability_mod = abilityMod(ability_score);
                            damage += ability_mod;

                            // Apply the weapon's damage type multiplier
                            float multiplier = tgt_stats.physical_damage_multipliers[dmg_roll.type];
                            int modified_damage = static_cast<int>(static_cast<float>(damage) * multiplier);

                            tr.total_damage = std::max(0, modified_damage);
                        } else {
                            // Fallback: use convenience fields (damage_dice, damage_dice_count)
                            const int num_dice = tr.critical ? weapon.damage_dice_count * 2 : weapon.damage_dice_count;
                            for (int i = 0; i < num_dice; ++i) {
                                int d = roll(weapon.damage_dice);
                                tr.dice_results.push_back(d);
                                damage += d;
                            }

                            // Add spellcasting ability modifier (not weapon ability modifier)
                            int ability_score = 10;
                            if (caster_stats.spellcasting_ability == 0) ability_score = caster_stats.str;
                            else if (caster_stats.spellcasting_ability == 1) ability_score = caster_stats.dex;
                            else if (caster_stats.spellcasting_ability == 2) ability_score = caster_stats.con;
                            else if (caster_stats.spellcasting_ability == 3) ability_score = caster_stats.intel;
                            else if (caster_stats.spellcasting_ability == 4) ability_score = caster_stats.wis;
                            else if (caster_stats.spellcasting_ability == 5) ability_score = caster_stats.cha;
                            int ability_mod = abilityMod(ability_score);
                            damage += ability_mod;

                            // Default to Bludgeoning multiplier for convenience-field weapons
                            float multiplier = tgt_stats.physical_damage_multipliers[Bludgeoning];
                            int modified_damage = static_cast<int>(static_cast<float>(damage) * multiplier);

                            tr.total_damage = std::max(0, modified_damage);
                        }

                        int overflow = std::max(0, tr.total_damage - tgt_stats.temp_hp);
                        tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - tr.total_damage);
                        tgt_stats.hp_cur = std::max(0, tgt_stats.hp_cur - overflow);

                        // Check if target is down
                        tr.target_down = (tgt_stats.hp_cur <= 0);

                        // Get spellcasting ability modifier for logging
                        int ability_score = 10;
                        if (caster_stats.spellcasting_ability == 0) ability_score = caster_stats.str;
                        else if (caster_stats.spellcasting_ability == 1) ability_score = caster_stats.dex;
                        else if (caster_stats.spellcasting_ability == 2) ability_score = caster_stats.con;
                        else if (caster_stats.spellcasting_ability == 3) ability_score = caster_stats.intel;
                        else if (caster_stats.spellcasting_ability == 4) ability_score = caster_stats.wis;
                        else if (caster_stats.spellcasting_ability == 5) ability_score = caster_stats.cha;
                        int ability_mod = abilityMod(ability_score);

                        // Build damage notation string (e.g., "1d8 + 3") for engine log
                        std::string damage_notation;
                        if (!weapon.physicalDamageRolls.empty()) {
                            const auto& dmg_roll = weapon.physicalDamageRolls[0];
                            damage_notation = std::to_string(tr.critical ? dmg_roll.num_dice * 2 : dmg_roll.num_dice) +
                                             "d" + std::to_string(dmg_roll.die_size);
                        } else {
                            damage_notation = std::to_string(tr.critical ? weapon.damage_dice_count * 2 : weapon.damage_dice_count) +
                                             "d" + std::to_string(weapon.damage_dice);
                        }

                        if (ability_mod >= 0) {
                            damage_notation += " + " + std::to_string(ability_mod);
                        } else {
                            damage_notation += " - " + std::to_string(-ability_mod);
                        }

                        // Build log message in the standard AttackRoll format (for GUI display)
                        std::string crit_str = tr.critical ? " CRIT!" : "";
                        std::string down_str = tr.target_down ? " — DOWN" : "";
                        tr.log_message = "HIT (roll " + std::to_string(d20_val) + " + " + std::to_string(mod)
                            + " = " + std::to_string(total_roll) + " vs AC " + std::to_string(target_ac) + ")"
                            + crit_str + " " + std::to_string(tr.total_damage) + down_str;

                        // Log detailed breakdown to engine log
                        log_("True Strike: {} attack roll ({} + {}) = {} vs AC {} — HIT",
                             agentName(bm, action.caster_idx), d20_val, mod, total_roll, target_ac);
                        log_("Damage: {} = {} dmg", damage_notation, tr.total_damage);
                    } else {
                        // No weapon equipped, treat as a miss
                        tr.hit = false;
                        log_("True Strike: {} has no equipped weapon", agentName(bm, action.caster_idx));
                    }
                } else {
                    tr.log_message = "miss (roll " + std::to_string(d20_val) + " + " +
                        std::to_string(mod) + " = " + std::to_string(total_roll) + " vs AC " +
                        std::to_string(target_ac) + ")";
                    log_("True Strike: {} {}", agentName(bm, action.caster_idx), tr.log_message);
                }

                // Store result - will be processed by post-switch code
                tr.hp_after = tgt_stats.hp_cur;
                bm.setAgentStats(tgt_idx, tgt_stats);
                break;  // Exit the attack-type switch, not the target loop
            }

            std::vector<int> dice;
            int total = 0;
            // Empowered Spell: per-target reroll budget of CHA mod damage dice (0 = inactive).
            int empower_budget = (applied_metamagic == MetamagicEmpowered) ? std::max(1, cha_mod) : 0;

            if (sp.type == Spell::Heal) {
                // Healing spell: roll healing_type dice + add spellcasting ability modifier
                int n_dice = sp.healing_type.num_dice;
                int die_size = sp.healing_type.die_size;
                for (int i = 0; i < n_dice; ++i) {
                    int d = life_supreme_heal ? die_size : roll(die_size);
                    dice.push_back(d);
                    total += d;
                }
                total += sp.healing_type.bonus;
                // Add spellcasting ability modifier
                int ability_score = 10;  // default
                if (caster_stats.spellcasting_ability == 0) ability_score = caster_stats.str;
                else if (caster_stats.spellcasting_ability == 1) ability_score = caster_stats.dex;
                else if (caster_stats.spellcasting_ability == 2) ability_score = caster_stats.con;
                else if (caster_stats.spellcasting_ability == 3) ability_score = caster_stats.intel;
                else if (caster_stats.spellcasting_ability == 4) ability_score = caster_stats.wis;
                else if (caster_stats.spellcasting_ability == 5) ability_score = caster_stats.cha;
                int ability_mod = abilityMod(ability_score);
                total += ability_mod;
                if (life_disciple_heal > 0) {
                    total += life_disciple_heal;  // Disciple of Life
                    log_("Disciple of Life: +{} HP", life_disciple_heal);
                }
                log_("[HEAL] Rolled {}d{} = {} + bonus {} + ability mod {} = total {}",
                     n_dice, die_size, std::accumulate(dice.begin(), dice.end(), 0),
                     sp.healing_type.bonus, ability_mod, total);
            } else if (shared_damage_roll) {
                // AoE: reuse the single area-wide roll made before the loop (no save here, so
                // only the target's own resistance multiplier varies per target).
                dice = shared_dice;
                for (std::size_t r = 0; r < sp.magic_damage_rolls.size(); ++r) {
                    const auto& roll_info = sp.magic_damage_rolls[r];
                    float multiplier = effectiveMagicDamageMult(caster_stats, tgt_stats, roll_info.type, true);
                    total += static_cast<int>(static_cast<float>(shared_magic_base[r]) * multiplier);
                }
                for (std::size_t r = 0; r < sp.physical_damage_rolls.size(); ++r) {
                    const auto& roll_info = sp.physical_damage_rolls[r];
                    float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                    total += static_cast<int>(static_cast<float>(shared_phys_base[r]) * multiplier);
                }
            } else {
                // Damage spell: roll per-damage-type damage and apply target's multipliers
                for (const auto& roll_info : sp.magic_damage_rolls) {
                    // Elemental Adept: treat a 1 as a 2 on the caster's chosen elements (spells).
                    int type_damage = rollSpellTypeDamage(caster_stats, roll_info.type, roll_info.num_dice,
                                                          roll_info.die_size, dice, true, &empower_budget);
                    type_damage += roll_info.bonus;
                    // Resistance/vuln/immunity multiplier (Elemental Adept / Poisoner lift the
                    // caster-relevant Resistance to 1.0).
                    float multiplier = effectiveMagicDamageMult(caster_stats, tgt_stats, roll_info.type, true);
                    int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                    total += modified_damage;
                }
                for (const auto& roll_info : sp.physical_damage_rolls) {
                    int type_damage = rollDamageDice(roll_info.num_dice, roll_info.die_size, dice, false, &empower_budget);
                    type_damage += roll_info.bonus;
                    // Apply target's resistance/vulnerability/immunity multiplier
                    float multiplier = tgt_stats.physical_damage_multipliers[roll_info.type];
                    int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
                    total += modified_damage;
                }
            }

            tr.dice_results = dice;
            tr.hit = true;

            if (sp.type == Spell::Heal) {
                tr.total_healing = std::max(0, total);
                tgt_stats.hp_cur = std::min(tgt_stats.hp_max,
                                            tgt_stats.hp_cur + tr.total_healing);
            } else {
                tr.total_damage  = std::max(0, total);
                // Bastion of Law ward (Clockwork L6) soaks damage before temp HP.
                tr.total_damage  = applyBastionWard(bm, tgt_idx, tgt_stats, tr.total_damage);
                // Temporary HP absorbs damage first, then overflow damages hp_cur
                int overflow = std::max(0, tr.total_damage - tgt_stats.temp_hp);
                tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - tr.total_damage);
                tgt_stats.hp_cur = std::max(0, tgt_stats.hp_cur - overflow);
            }
            break;
        }

        } // switch

        // Life Domain — Blessed Healer (L6): track whether any creature other than the caster was
        // healed this cast; if so the cleric heals itself once after the spell resolves (below).
        if (sp.type == Spell::Heal && tr.total_healing > 0 && tgt_idx != action.caster_idx)
            life_healed_other = true;

        // TASK D: Radiant Soul (Celestial L6+): once per turn, add CHA mod to one damaging
        // Radiant/Fire spell. Applies across all attack types (AttackRoll/Save/Automatic).
        if (tr.total_damage > 0 && sp.type != Spell::Heal && spell_radiant_or_fire &&
            caster_stats.character_class == CharacterClass::Warlock &&
            caster_stats.warlock_subclass == CelestialPath && caster_stats.char_level >= 6) {
            Agent::Conditions caster_cond = bm.getAgentConditions(action.caster_idx);
            if (!caster_cond.radiant_soul_used) {
                int chaMod = (caster_stats.cha - 10) / 2;
                if (caster_stats.cha < 10 && (caster_stats.cha - 10) % 2 != 0) --chaMod;
                if (chaMod > 0) {
                    int overflow = std::max(0, chaMod - tgt_stats.temp_hp);
                    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - chaMod);
                    tgt_stats.hp_cur  = std::max(0, tgt_stats.hp_cur - overflow);
                    tr.total_damage += chaMod;
                    log_("{}: Radiant Soul adds {} damage to {} spell", agentName(bm, action.caster_idx), chaMod, sp.name);
                }
                caster_cond.radiant_soul_used = true;
                bm.setAgentConditions(action.caster_idx, caster_cond);
            }
        }

        // Cleric Blessed Strikes — Potent Spellcasting (L7+): add WIS mod to Cleric cantrip damage.
        if (tr.total_damage > 0 && sp.type != Spell::Heal && sp.level == 0 &&
            caster_stats.character_class == CharacterClass::Cleric &&
            caster_stats.char_level >= 7 &&
            caster_stats.blessed_strike == BlessedStrikePotentSpellcasting) {
            int wisMod = (caster_stats.wis - 10) / 2;
            if (caster_stats.wis < 10 && (caster_stats.wis - 10) % 2 != 0) --wisMod;
            if (wisMod > 0) {
                int overflow = std::max(0, wisMod - tgt_stats.temp_hp);
                tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - wisMod);
                tgt_stats.hp_cur  = std::max(0, tgt_stats.hp_cur - overflow);
                tr.total_damage += wisMod;
                log_("{}: Potent Spellcasting adds {} damage to {}", agentName(bm, action.caster_idx), wisMod, sp.name);
            }
        }

        tr.hp_after    = tgt_stats.hp_cur;
        tr.target_down = (tgt_stats.hp_cur <= 0);
        bm.setAgentStats(tgt_idx, tgt_stats);

        // Repelling Blast: each Eldritch Blast beam that hits pushes the target 10 ft away.
        if (tr.hit && sp.name == "Eldritch Blast" &&
            caster_stats.character_class == CharacterClass::Warlock &&
            caster_stats.hasInvocation(1)) {
            int moved = bm.forceMoveAgent(tgt_idx, caster_pa.origin, 10);
            if (moved > 0)
                log_("Repelling Blast: {} pushed {} ft", agentName(bm, tgt_idx), moved * 5);
        }

        // Auto-trigger Unconscious if HP drops to 0 or below
        if (tgt_stats.hp_cur <= 0) {
            Agent::Conditions tgt_cond_before = bm.getAgentConditions(tgt_idx);
            bool spell_just_knocked_unconscious = (!tgt_cond_before.unconscious && !tgt_cond_before.dead);
            if (spell_just_knocked_unconscious) {
                log_("[SPELL KNOCKDOWN] {} going unconscious from spell damage ({})", agentName(bm, tgt_idx), sp.name);
                applyUnconscious(bm, tgt_idx);
                // Don't roll death save yet - they'll roll on their next turn or if they take more damage
                // Dark One's Blessing (Fiend L3): temp HP to the caster and allied Fiend warlocks
                // within 10 ft of each enemy this spell felled.
                grantDarkOnesBlessing(bm, tgt_idx, action.caster_idx);
            } else if (tgt_cond_before.unconscious && !tgt_cond_before.dead && tr.total_damage > 0) {
                log_("[SPELL DEATH SAVE] {} already unconscious, rolling death save from spell damage", agentName(bm, tgt_idx));
                // Death save on damage for agents already unconscious
                rollDeathSave(bm, tgt_idx);
            }
        } else {
            // HP is positive: if a healing spell brought a downed target back up, restore
            // consciousness so they aren't skipped in initiative (no-op otherwise).
            reviveOnHeal(bm, tgt_idx);
        }

        // Check concentration saves: once per damage instance (e.g., once per Magic Missile)
        if (tr.total_damage > 0 && !tr.dice_results.empty()) {
            // For spells with multiple damage instances (dice rolls), check concentration for each
            int num_instances = std::max(1, static_cast<int>(tr.dice_results.size()));
            int damage_per_instance = tr.total_damage / num_instances;
            if (damage_per_instance == 0 && tr.total_damage > 0) {
                damage_per_instance = 1;  // Ensure at least 1 damage per instance
            }
            for (int i = 0; i < num_instances && !tr.concentration_lost; ++i) {
                if (checkConcentrationOnDamage(bm, tgt_idx, damage_per_instance)) {
                    tr.concentration_checked = true;
                    tr.concentration_lost = true;
                }
            }
            if (damage_per_instance > 0) {
                tr.concentration_checked = true;
            }
        }

        // On-damage condition behavior (Sleep/Hypnotic Pattern end; Tasha's re-saves) for
        // any pre-existing condition on this target. Runs before this spell's own conditions
        // are applied, so a damaging spell can't instantly cancel the condition it just set.
        processDamageTaken(bm, tgt_idx, tr.total_damage);

        // Apply spell-based conditions (e.g., Hold Person applies Paralyzed)
        if (!sp.conditions.empty()) {
            auto ability_name = [](SaveAbility_t ab) -> std::string {
                switch (ab) {
                    case SaveStr: return "STR";
                    case SaveDex: return "DEX";
                    case SaveCon: return "CON";
                    case SaveInt: return "INT";
                    case SaveWis: return "WIS";
                    default: return "CHA";
                }
            };

            for (const auto& spell_cond : sp.conditions) {
                // Determine if this specific condition applies to the target
                log_("[COND] Processing condition '{}' for {}, requires_save={}, push_ft={}",
                     spell_cond.condition_name, agentName(bm, tgt_idx), spell_cond.requires_save, spell_cond.push_ft);
                bool condition_applies = false;
                bool target_failed_save = false;

                // Determine if condition applies based on spell type and whether it requires a save
                if (spell_cond.requires_save) {
                    // Condition requires a save
                    if (sp.attack_type == Spell::Save) {
                        // For Save spells, reuse the existing save result
                        target_failed_save = !tr.saved;
                        condition_applies = target_failed_save;
                        log_("[COND SAVE] {} vs {}: tr.saved={}, target_failed_save={}, condition_applies={}",
                             spell_cond.condition_name, agentName(bm, tgt_idx), tr.saved, target_failed_save, condition_applies);
                    } else {
                        // For other spell types, roll a new save for this condition
                        int save_dc = spellSaveDc(caster_stats);

                        // Fey Wanderer Beguiling Twist (L7): Advantage on a save vs Charmed/Frightened.
                        const bool fey_twist =
                            tgt_stats.character_class == CharacterClass::Ranger &&
                            tgt_stats.ranger_subclass == FeyWandererPath &&
                            tgt_stats.char_level >= 7 &&
                            (spell_cond.condition_name == "Charmed" ||
                             spell_cond.condition_name == "Frightened");
                        // Aberrant Mind Psychic Defenses (L6): same advantage vs Charmed/Frightened.
                        const bool aberrant_defense =
                            tgt_stats.character_class == CharacterClass::Sorcerer &&
                            tgt_stats.sorcerer_subclass == SorcererSubclass::AberrantPath &&
                            tgt_stats.char_level >= 6 &&
                            (spell_cond.condition_name == "Charmed" ||
                             spell_cond.condition_name == "Frightened");
                        int save_d20 = (fey_twist || aberrant_defense) ? rollAdvantage(20) : roll(20);
                        // Clockwork L14 Trance of Order: floor the saver's own d20 (9-or-lower → 10).
                        save_d20 = tgt_stats.applyTranceFloor(save_d20);
                        int cond_save_mod = saveModFor(bm, tgt_idx, spell_cond.save_ability);
                        int cond_save_total = save_d20 + cond_save_mod;
                        cond_save_total = applyIndomitableMight(bm, tgt_idx, spell_cond.save_ability, cond_save_total);

                        bool save_succeeded = (cond_save_total >= save_dc);
                        target_failed_save = !save_succeeded;
                        condition_applies = target_failed_save;

                        log_("{} save vs {} condition: rolled {} + {} = {} vs DC {} — {}",
                             ability_name(spell_cond.save_ability),
                             spell_cond.condition_name,
                             save_d20, cond_save_mod,
                             cond_save_total,
                             save_dc,
                             save_succeeded ? "SAVED" : "FAILED");
                    }
                } else {
                    // Condition doesn't require a save, apply based on spell attack type
                    if (sp.attack_type == Spell::AttackRoll) {
                        condition_applies = tr.hit;
                    } else {
                        condition_applies = true;
                    }
                }

                if (condition_applies) {
                    log_("[APPLY] Applying condition '{}' to {}, requires_save={}, push_ft={}",
                         spell_cond.condition_name, agentName(bm, tgt_idx), spell_cond.requires_save, spell_cond.push_ft);

                    ActiveAgentCondition cond;
                    cond.agent_idx   = tgt_idx;
                    cond.caster_idx  = action.caster_idx;
                    cond.spell_idx   = action.spell_idx;
                    cond.condition_name = spell_cond.condition_name;
                    cond.save_ability = spell_cond.save_ability;
                    cond.on_damage = spell_cond.on_damage;

                    // Condition duration: if condition_duration is 0, use spell duration
                    cond.turns_remaining = (spell_cond.condition_duration > 0) ? spell_cond.condition_duration : sp.duration;
                    // Save DC: use caster's spellcasting ability if SaveSpellcasterMod, else use specified ability
                    if (spell_cond.save_dc_ability == SaveSpellcasterMod) {
                        cond.save_dc = spellSaveDc(caster_stats);
                    } else {
                        cond.save_dc = spellSaveDcFromAbility(caster_stats, spell_cond.save_dc_ability);
                    }
                    // How often to repeat save checks
                    cond.save_repeat_turns = spell_cond.save_repeat_turns;
                    // Target can save at the start of their next turn (next_save_turn == 0 means "save now")
                    cond.next_save_turn = 0;

                    [[maybe_unused]] int cond_id = addAgentCondition(bm, cond);
                    any_conditions_applied = true;

                    // Apply spell push on failed save
                    if (spell_cond.condition_name == "Push" && spell_cond.push_ft > 0) {
                        log_("[PUSH] Attempting to push {} {} feet by spell '{}'", agentName(bm, tgt_idx), spell_cond.push_ft, sp.name);
                        auto spell_agents = bm.placedAgents();
                        if (action.caster_idx >= 0 && action.caster_idx < static_cast<int>(spell_agents.size())) {
                            const auto& caster = spell_agents[action.caster_idx];
                            log_("[PUSH] Caster at ({},{}), target at ({},{})", caster.origin.col, caster.origin.row, spell_agents[tgt_idx].origin.col, spell_agents[tgt_idx].origin.row);
                            int cells_moved = bm.forceMoveAgent(tgt_idx, caster.origin, spell_cond.push_ft);
                            log_("[PUSH] forceMoveAgent returned {} cells moved", cells_moved);
                            tr.push_ft_applied = cells_moved * 5;
                            if (cells_moved > 0) {
                                log_("Target pushed {} feet by {}", tr.push_ft_applied, sp.name);
                                log_("[PUSH] Target now at ({},{})", spell_agents[tgt_idx].origin.col, spell_agents[tgt_idx].origin.row);
                            } else {
                                log_("[PUSH] No movement occurred (blocked or out of range)");
                            }
                        } else {
                            log_("[PUSH] Invalid caster index: {}", action.caster_idx);
                        }
                    }
                }
            }
        }

        // Command: a target that fails its save obeys the chosen one-word command on its next turn.
        // The word maps onto an existing mechanic via applyCommandEffect (Drop/Flee/Grovel/Halt/
        // Approach). Command carries no sp.conditions, so this is its only mechanical effect.
        if (sp.name == "Command" && !tr.saved && tgt_idx >= 0 &&
            tgt_idx < static_cast<int>(agents.size())) {
            applyCommandEffect(bm, action.caster_idx, tgt_idx, action.command_word);
        }

        result.target_results.push_back(tr);
    }

    // Life Domain — Blessed Healer (L6): when a slot-level-1+ heal restores HP to another creature,
    // the cleric regains 2 + slot level HP as well.
    if (life_healed_other && heal_slot >= 1 &&
        caster_stats.character_class == CharacterClass::Cleric &&
        caster_stats.cleric_subclass == LifeDomain && caster_stats.char_level >= 6) {
        Agent::Stats cs = bm.getAgentStats(action.caster_idx);
        if (cs.hp_cur > 0) {
            const int self_heal = 2 + heal_slot;
            cs.hp_cur = std::min(cs.hp_max, cs.hp_cur + self_heal);
            bm.setAgentStats(action.caster_idx, cs);
            log_("{}: Blessed Healer restores {} HP to the caster", agentName(bm, action.caster_idx), self_heal);
        }
    }

    // Register persistent effects (duration > 1 means per-tick damage/heal on
    // subsequent turns; we already applied the first application above). Help spells
    // (e.g. Sanctuary) have no per-tick effect — their persistence is the applied
    // condition, which lives on its own timer — so they never register here.
    if (sp.duration > 1 && sp.type != Spell::Help) {
        for (int tgt_idx : targets) {
            if (tgt_idx < 0 || tgt_idx >= static_cast<int>(agents.size())) continue;
            ActiveEffect fx;
            fx.caster_idx      = action.caster_idx;
            fx.target_idx      = tgt_idx;
            fx.spell           = sp;
            fx.turns_remaining = sp.duration - 1;
            activeEffects_.push_back(fx);
        }
    }

    // Set concentration after successful spell cast (if required and if spell affected targets)
    // For condition-based spells, only set concentration if a condition was actually applied
    // For damage/heal spells or AoE terrain spells, set concentration if any targets were affected
    bool should_concentrate = false;
    if (sp.requires_concentration && result.valid) {
        const bool is_aoe = (sp.geometry != Spell::Single && sp.geometry != Spell::Multiple);
        if (is_aoe) {
            // AoE spells create a persistent area (terrain/zone); concentration holds
            // even with no current targets in the area.
            should_concentrate = true;
        } else if (!sp.conditions.empty()) {
            // Targeted (Single/Multiple) condition spell: only concentrate if a
            // condition actually landed (e.g. Hold Person fizzles if every target saved).
            should_concentrate = any_conditions_applied;
        } else {
            should_concentrate = true;
        }
    }

    if (should_concentrate) {
        Agent::Conditions cond = bm.getAgentConditions(action.caster_idx);
        cond.concentrating    = true;
        cond.concentrating_on = sp.name;
        bm.setAgentConditions(action.caster_idx, cond);
    }

    // Hunter's Mark / Hex: set the caster's marked-target rider state (cleared on concentration
    // drop). The +Xd6 on-hit damage is applied generically in applyAttackResult. Keys on the
    // single designated target (targets[0]); Foe Slayer (Ranger L20) upgrades the die to a d10.
    if (should_concentrate && !targets.empty() &&
        (sp.name == "Hunter's Mark" || sp.name == "Hex")) {
        Agent::Stats cs = bm.getAgentStats(action.caster_idx);
        cs.hunters_mark_target    = targets[0];
        cs.hunters_mark_dice      = 1;
        if (sp.name == "Hex") {
            cs.hunters_mark_die_size    = 6;
            cs.hunters_mark_damage_type = MagicDamage_t::Necrotic;  // 5
        } else {  // Hunter's Mark
            cs.hunters_mark_die_size    = (cs.character_class == CharacterClass::Ranger &&
                                           cs.char_level >= 20) ? 10 : 6;  // Foe Slayer
            cs.hunters_mark_damage_type = MagicDamage_t::Force;            // 3
        }
        bm.setAgentStats(action.caster_idx, cs);
    }

    // Create persistent spell effect if spell has AoE geometry and duration > 1
    if (result.valid && sp.duration > 1 && sp.geometry != Spell::Single) {
        std::vector<Cell> effect_cells;

        // Calculate cells based on spell geometry
        if (sp.geometry == Spell::Sphere) {
            // For a moving Sphere, center_col/center_row are the caster's origin.
            effect_cells = sphereCellsAround(center_col, center_row, sp.radius);
        } else if (sp.geometry == Spell::Rectangle) {
            // Oriented wall from the aim point toward the endpoint, clamped to
            // spell.length (falls back to a centered box when unaimed).
            effect_cells = bm.wallCells(Cell{action.aoe_col, action.aoe_row},
                                        Cell{action.aoe_col2, action.aoe_row2},
                                        sp.width, sp.length);
        } else if (sp.geometry == Spell::Square) {
            double w_cells = sp.width / 5.0;
            double l_cells = sp.length / 5.0;
            int cols = bm.gridCols();
            int rows = bm.gridRows();
            // Center the square on the clicked point
            for (int c = 0; c < cols; ++c) {
                for (int r = 0; r < rows; ++r) {
                    double dx = std::abs(c - action.aoe_col);
                    double dy = std::abs(r - action.aoe_row);
                    if (dx <= w_cells / 2.0 && dy <= l_cells / 2.0) {
                        effect_cells.push_back(Cell{c, r});
                    }
                }
            }
        } else if (sp.geometry == Spell::Line) {
            int length_cells = (sp.length + 4) / 5;
            // Assume horizontal for now (can be enhanced)
            for (int c = action.aoe_col; c < action.aoe_col + length_cells; ++c) {
                effect_cells.push_back(Cell{c, action.aoe_row});
            }
        } else if (sp.geometry == Spell::Cone) {
            int length_cells = (sp.length + 4) / 5;
            // Simple cone approximation (would need direction in real implementation)
            for (int dist = 0; dist < length_cells; ++dist) {
                for (int width = -dist; width <= dist; ++width) {
                    effect_cells.push_back(Cell{action.aoe_col + dist, action.aoe_row + width});
                }
            }
        }

        // Create ActiveSpellEffect if we have cells
        if (!effect_cells.empty()) {
            ActiveSpellEffect effect;
            effect.caster_idx = action.caster_idx;
            effect.spell_idx = action.spell_idx;
            effect.spell = sp;
            effect.cells = effect_cells;
            effect.turns_remaining = sp.duration;
            effect.effect_id = -1;  // Will be assigned by addSpellEffect
            effect.anchor_agent_idx = moving_sphere ? action.caster_idx : -1;
            [[maybe_unused]] int effect_id = bm.addSpellEffect(effect);
        }
    }

    // Terrain placement: if spell creates difficult terrain
    if (result.valid && sp.terrain_difficulty != TerrainDifficulty::Normal) {
        Cell center = Cell{action.aoe_col, action.aoe_row};
        Cell caster_origin = bm.placedAgents()[static_cast<std::size_t>(action.caster_idx)].origin;
        int caster_size = bm.placedAgents()[static_cast<std::size_t>(action.caster_idx)].agent->getSize();

        // A moving Sphere (Emanation, e.g. Spirit Guardians) centers its difficult terrain on
        // the caster and follows them (anchored). Other shapes place static terrain at the aim.
        std::vector<Cell> terrain_cells;
        int anchor_idx = -1, anchor_radius = 0;
        if (moving_sphere) {
            terrain_cells = sphereCellsAround(caster_origin.col, caster_origin.row, sp.radius);
            anchor_idx    = action.caster_idx;
            anchor_radius = sp.radius;
        } else {
            Cell endpoint = Cell{action.aoe_col2, action.aoe_row2};  // for oriented walls
            auto raw_cells = bm.aoeCells(center, sp, caster_origin, endpoint);
            terrain_cells = bm.filterSpellCells(raw_cells, caster_origin, caster_size, sp, center);
        }

        if (!terrain_cells.empty()) {
            int terrain_id = bm.placeTerrainEffect(
                sp.name, terrain_cells, sp.terrain_difficulty,
                sp.duration, action.caster_idx,
                sp.slip_save_dc, sp.slip_distance_feet,
                action.spell_idx, sp.requires_concentration,
                anchor_idx, anchor_radius, sp.selective_targeting);

            if (terrain_id >= 0) {
                result.terrain_effect_ids.push_back(terrain_id);

                // Slipping terrain: immediate DEX save for agents in the AoE
                if (sp.terrain_difficulty == TerrainDifficulty::Slipping) {
                    for (int i = 0; i < static_cast<int>(bm.placedAgents().size()); ++i) {
                        if (i == action.caster_idx) continue;
                        Cell agent_cell = bm.placedAgents()[static_cast<std::size_t>(i)].origin;
                        bool in_aoe = std::any_of(terrain_cells.begin(), terrain_cells.end(),
                            [&agent_cell](const Cell& c) { return c.col == agent_cell.col && c.row == agent_cell.row; });
                        if (!in_aoe) continue;
                        auto stats = getAgentStats(bm, i);
                        int dex_mod = (stats.dex - 10) / 2;
                        if (stats.dex < 10 && (stats.dex - 10) % 2 != 0) --dex_mod;  // floor for odd negative scores
                        if (stats.save_prof_dex) dex_mod += stats.prof_bonus;        // DEX save proficiency
                        int d20 = roll(20);
                        if (d20 + dex_mod < sp.slip_save_dc) {
                            Agent::Conditions cond_i = bm.getAgentConditions(i);
                            cond_i.prone = true;
                            bm.setAgentConditions(i, cond_i);
                            log_("Slipping terrain: {} fails DEX save (d20={}) — prone.",
                                 bm.placedAgents()[i].agent->name(), d20);
                        }
                    }
                }
            }
        }
    }

    // Light effect placement: if spell creates a light effect (e.g., Daylight, Light, Darkness)
    if (result.valid && sp.light_level >= 0) {
        Cell center = Cell{action.aoe_col, action.aoe_row};
        Cell caster_origin = bm.placedAgents()[static_cast<std::size_t>(action.caster_idx)].origin;
        int caster_size = bm.placedAgents()[static_cast<std::size_t>(action.caster_idx)].agent->getSize();

        // Light effects follow the same emanation rules as terrain: moving Sphere centers on caster,
        // other shapes place static light at the aim.
        std::vector<Cell> light_cells;
        if (moving_sphere) {
            light_cells = sphereCellsAround(caster_origin.col, caster_origin.row, sp.radius);
        } else {
            Cell endpoint = Cell{action.aoe_col2, action.aoe_row2};
            auto raw_cells = bm.aoeCells(center, sp, caster_origin, endpoint);
            light_cells = bm.filterSpellCells(raw_cells, caster_origin, caster_size, sp, center);
        }

        if (!light_cells.empty()) {
            // Light effects from spells persist for their full duration, which for
            // these spells (Darkness 10 min, Fog Cloud/Daylight 1 hr) far exceeds any
            // combat. Concentration light spells (Darkness, Fog Cloud) are removed when
            // concentration drops (dropConcentration -> removeLightEffectsBySource), so
            // they are placed as permanent (-1) here. Non-concentration light spells
            // (Daylight) also outlast combat, so they persist for the encounter.
            // spells.json carries a placeholder `duration` of 1 round for most spells;
            // a value > 1 is treated as an explicit rounds-based lifetime, otherwise the
            // effect is permanent-for-encounter rather than expiring after one round.
            int light_turns = (sp.duration > 1) ? sp.duration : -1;
            int light_id = bm.placeLightEffect(
                sp.name, light_cells,
                static_cast<VisibilityLevel>(sp.light_level),
                light_turns, action.caster_idx);

            if (light_id >= 0) {
                result.light_effect_ids.push_back(light_id);
            }
        }
    }

    // If caster was hidden and cast a spell, reveal them
    if (result.valid && action.caster_idx >= 0 && action.caster_idx < static_cast<int>(agents.size())) {
        const Agent::Conditions& caster_cond = agents[static_cast<std::size_t>(action.caster_idx)].agent->getConditions();
        if (caster_cond.hidden) {
            Agent::Conditions cond = bm.getAgentConditions(action.caster_idx);
            cond.hidden = false;
            bm.setAgentConditions(action.caster_idx, cond);
            log_("{} is no longer hidden", agents[static_cast<std::size_t>(action.caster_idx)].agent->name());
        }
    }

    // Decrement resources (uses or spell slots) after successful cast
    if (result.valid) {
        PlacedAgent& pa = bm.placedAgentMut(action.caster_idx);
        Spell& spell_mut = pa.spells[static_cast<std::size_t>(action.spell_idx)];
        Agent::Stats& stats = pa.agent->getStats();

        // Mark leveled spell cast (once per turn, even if upcasted)
        if (sp.level > 0) {
            stats.markLeveledSpellCast(sp.level);
        }

        if (!spell_mut.resource_name.empty()) {
            // Class feature: spend its named resource (e.g. Channel Divinity) instead of a slot.
            int cost = std::max(1, spell_mut.resource_cost);
            Resource* res = stats.getResource(spell_mut.resource_name);
            if (res) res->spend(cost);
            log_("{} spends {} {}", agentName(bm, action.caster_idx), cost, spell_mut.resource_name);
        } else if (stats.is_npc) {
            // NPC: decrement N/day uses
            if (spell_mut.uses_max > 0) {
                spell_mut.uses_remaining = std::max(0, spell_mut.uses_remaining - 1);
            }
        } else {
            // Player: decrement spell slot (if not a cantrip). A free cast (e.g. Mantle of Majesty's
            // Command) skips the slot decrement entirely — the caller still charges the action economy.
            int slot_level = action.slot_level > 0 ? action.slot_level : sp.level;
            if (!action.free_cast && slot_level > 0 && slot_level <= 9) {
                auto& slots = stats.spell_slots_remaining;
                slots[static_cast<std::size_t>(slot_level - 1)] =
                    std::max(0, slots[static_cast<std::size_t>(slot_level - 1)] - 1);

                // Wizard Diviner L6: Expert Divination
                // Cast Divination spell with L2+ slot → regain highest-level lower-level slot (max L5)
                if (stats.character_class == Wizard && stats.wizard_subclass == DivinierPath &&
                    spell_mut.school == Spell::Divination && slot_level >= 2) {
                    log_("[EXPERT DIVINATION] Restoring spell slot for spell: {}", spell_mut.name);
                    // Find highest expended lower-level slot (capped at L5)
                    int restore_level = -1;
                    for (int lvl = std::min(5, slot_level - 1); lvl >= 1; --lvl) {
                        if (slots[static_cast<std::size_t>(lvl - 1)] <
                            stats.spell_slots_max[static_cast<std::size_t>(lvl - 1)]) {
                            restore_level = lvl;
                            break;
                        }
                    }
                    if (restore_level > 0) {
                        slots[static_cast<std::size_t>(restore_level - 1)]++;
                        log_("{} Expert Divination: restored 1 level {} spell slot", agentName(bm, action.caster_idx), restore_level);
                    }
                }

                // Wizard Abjurer L3+: Arcane Ward auto-charging
                // Cast abjuration spell → Ward gains 2 × spell slot level (capped at max)
                if (stats.character_class == Wizard && stats.wizard_subclass == AbjurerPath &&
                    stats.char_level >= 3 && spell_mut.school == Spell::Abjuration) {
                    int max_ward = 2 * stats.char_level + (stats.intel - 10) / 2;
                    int ward_gain = 2 * slot_level;
                    stats.temp_hp = std::min(stats.temp_hp + ward_gain, max_ward);
                    log_("{} Arcane Ward charged: +{} HP ({}/{})", agentName(bm, action.caster_idx), ward_gain, stats.temp_hp, max_ward);
                }
            }
        }

        // Persist stats back to battle map after modifications
        bm.setAgentStats(action.caster_idx, stats);
    }

    // Battle Magic (Valor Bard L14+): casting a Bard spell via the Magic action sets a flag
    // enabling a bonus-action weapon attack. Gate on Valor L14+ (no class-feature check; we
    // assume this is called only for Bard spells; the GUI enforces that).
    if (result.valid && caster_pa.agent->getStats().character_class == CharacterClass::Bard &&
        caster_pa.agent->getStats().bard_subclass == ValorPath &&
        caster_pa.agent->getStats().char_level >= 14) {
        Agent::Conditions c = bm.getAgentConditions(action.caster_idx);
        c.battle_magic_available = true;
        bm.setAgentConditions(action.caster_idx, c);
        log_("{} casts a Bard spell (Battle Magic available for bonus-action weapon attack)",
             agentName(bm, action.caster_idx));
    }

    return result;
}

std::vector<int> CombatEngine::availableCastableSpells(
        const BattleMap& bm, int agent_idx) const
{
    std::vector<int> result;
    const auto& agents = bm.placedAgents();

    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size()))
        return result;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Stats& stats = pa.agent->getStats();
    const auto& spells = pa.spells;

    for (size_t i = 0; i < spells.size(); ++i) {
        const Spell& spell = spells[i];

        // Class feature: castable iff its named resource has enough charges.
        if (!spell.resource_name.empty()) {
            const Resource* res = stats.getResource(spell.resource_name);
            if (res && res->current >= std::max(1, spell.resource_cost))
                result.push_back(static_cast<int>(i));
            continue;
        }

        // Cantrips (level 0) are always available
        if (spell.level == 0) {
            result.push_back(static_cast<int>(i));
            continue;
        }

        // Check leveled spell per-turn rule
        if (!stats.canCastLeveledSpell()) {
            continue;  // Already cast a leveled spell this turn
        }

        if (stats.is_npc) {
            // NPC: need remaining uses
            if (spell.uses_max > 0 && spell.uses_remaining > 0) {
                result.push_back(static_cast<int>(i));
            }
        } else {
            // Player: need a spell slot at spell.level or higher
            bool hasSlot = false;
            for (int lvl = spell.level; lvl <= 9; ++lvl) {
                if (stats.spell_slots_remaining[static_cast<size_t>(lvl - 1)] > 0) {
                    hasSlot = true;
                    break;
                }
            }
            if (hasSlot) {
                result.push_back(static_cast<int>(i));
            }
        }
    }

    return result;
}

int CombatEngine::getNumTargetsForSpell(const Spell& sp, int slot_level,
                                        int caster_level) const noexcept
{
    // Eldritch Blast beams scale with CHARACTER level (cantrip), not slot level.
    if (sp.name == "Eldritch Blast" && caster_level >= 0) {
        int beams = 1;
        if (caster_level >= 5)  ++beams;
        if (caster_level >= 11) ++beams;
        if (caster_level >= 17) ++beams;
        return beams;
    }

    // For Multiple geometry spells, calculate targets based on upcast level
    if (sp.geometry != Spell::Multiple) {
        return (sp.geometry == Spell::Single) ? 1 : 0;
    }

    // Multiple geometry: num_targets + (slot_level - spell.level) * targets_per_upcast_level
    int num_targets = sp.num_targets;
    if (slot_level > 0 && slot_level > sp.level) {
        num_targets += (slot_level - sp.level) * sp.targets_per_upcast_level;
    }
    return std::max(1, num_targets);  // Always at least 1 target
}

int CombatEngine::effectiveSpellRange(const BattleMap& bm, int caster_idx, const Spell& sp) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (caster_idx < 0 || static_cast<std::size_t>(caster_idx) >= agents.size())
        return sp.range;
    const Agent::Stats& cs = agents[static_cast<std::size_t>(caster_idx)].agent->getStats();

    // Eldritch Spear (code 2): the chosen damage cantrip's range increases by 30 ft
    // per Warlock level (RAW requires a 10+ ft ranged cantrip — Eldritch Blast qualifies).
    if (sp.name == "Eldritch Blast" && cs.character_class == CharacterClass::Warlock &&
        cs.hasInvocation(2) && sp.range >= 10) {
        return sp.range + 30 * cs.char_level;
    }

    // Spell Sniper (general feat): a spell that requires an attack roll gains +60 ft of range
    // (only when it already has a meaningful ranged distance, excluding Touch/Self spells).
    if (sp.attack_type == Spell::AttackRoll && sp.range >= 10 && cs.hasFeat("Spell Sniper")) {
        return sp.range + 60;
    }
    return sp.range;
}

// Sorcerer Metamagic — Sorcery Point cost per option (2024 PHB).
int CombatEngine::metamagicSpCost(MetamagicOption opt) noexcept
{
    switch (opt) {
        case MetamagicHeightened:
        case MetamagicQuickened:   return 2;
        case MetamagicCareful:
        case MetamagicDistant:
        case MetamagicEmpowered:
        case MetamagicExtended:
        case MetamagicSeeking:
        case MetamagicSubtle:
        case MetamagicTransmuted:
        case MetamagicTwinned:     return 1;
        default:                   return 0;  // MetamagicNone
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Spell effects & zones
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::applySpellEffect(BattleMap& bm, const ActiveSpellEffect& effect, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (target_idx < 0 || static_cast<std::size_t>(target_idx) >= agents.size())
        return;

    Agent::Stats target_stats = bm.getAgentStats(target_idx);
    const Spell& sp = effect.spell;

    // Save-for-half: a damaging zone with a Save attack type lets the target make a
    // saving throw each time the effect is applied (half damage on success).
    const bool do_save = (sp.attack_type == Spell::Save && sp.type != Spell::Heal);
    bool saved = false;
    if (do_save) {
        const Agent& tgt = *agents[static_cast<std::size_t>(target_idx)].agent;
        const Agent::Conditions& tc = tgt.getConditions();

        // Auto-fail STR/DEX saves while paralyzed/stunned/unconscious.
        const bool auto_fail = (tc.paralyzed || tc.stunned || tc.unconscious) &&
                               (sp.save_ability == SaveStr || sp.save_ability == SaveDex);

        bool adv = tgt.hasAdvantage();
        bool dis = tgt.hasDisadvantage();
        // Barbarian Danger Sense (L2+): advantage on DEX saves unless incapacitated.
        if (sp.save_ability == SaveDex && !tc.incapacitated &&
            target_stats.character_class == CharacterClass::Barbarian && target_stats.char_level >= 2)
            adv = true;
        // Fey Wanderer Beguiling Twist (L7): Advantage on a save vs a spell that applies
        // Charmed or Frightened (this is the Save-for-half site; the condition reuses tr.saved).
        if (!tc.incapacitated && target_stats.character_class == CharacterClass::Ranger &&
            target_stats.ranger_subclass == FeyWandererPath && target_stats.char_level >= 7) {
            for (const auto& c : sp.conditions)
                if (c.condition_name == "Charmed" || c.condition_name == "Frightened") { adv = true; break; }
        }

        int save_d20;
        if (auto_fail)       save_d20 = 1;
        else if (adv && dis) save_d20 = roll(20);
        else if (adv)        save_d20 = rollAdvantage(20);
        else if (dis)        save_d20 = rollDisadvantage(20);
        else                 save_d20 = roll(20);
        // Clockwork L14 Trance of Order: floor the saver's own d20 (9-or-lower → 10), but never an
        // automatic failure.
        if (!auto_fail) save_d20 = target_stats.applyTranceFloor(save_d20);

        int dc = 0;
        if (effect.caster_idx >= 0 && static_cast<std::size_t>(effect.caster_idx) < agents.size())
            dc = spellSaveDcFromAbility(bm.getAgentStats(effect.caster_idx), sp.save_ability);
        saved = !auto_fail && (save_d20 + saveModFor(bm, target_idx, sp.save_ability) >= dc);
    }

    // Calculate total by rolling all damage types and applying multipliers (then halving on a save).
    // The caster's Elemental Adept / Poisoner can ignore the target's Resistance on a damaging zone.
    const Agent::Stats zone_caster =
        (effect.caster_idx >= 0 && static_cast<std::size_t>(effect.caster_idx) < agents.size())
            ? bm.getAgentStats(effect.caster_idx) : Agent::Stats{};
    int total = 0;
    for (const auto& roll_info : sp.magic_damage_rolls) {
        std::vector<int> zdice;  // per-type dice (discarded; rollSpellTypeDamage applies treat-1-as-2)
        int type_damage = rollSpellTypeDamage(zone_caster, roll_info.type, roll_info.num_dice,
                                              roll_info.die_size, zdice, true);
        type_damage += roll_info.bonus;
        float multiplier = effectiveMagicDamageMult(zone_caster, target_stats, roll_info.type, true);
        int modified = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        if (saved) modified /= 2;
        total += modified;
    }
    for (const auto& roll_info : sp.physical_damage_rolls) {
        int type_damage = 0;
        for (int i = 0; i < roll_info.num_dice; ++i) type_damage += roll(roll_info.die_size);
        type_damage += roll_info.bonus;
        float multiplier = target_stats.physical_damage_multipliers[roll_info.type];
        int modified = static_cast<int>(static_cast<float>(type_damage) * multiplier);
        if (saved) modified /= 2;
        total += modified;
    }

    // Rogue Evasion (L7+): on a DEX save, success = no damage, failure = half.
    if (do_save && sp.save_ability == SaveDex &&
        target_stats.character_class == CharacterClass::Rogue && target_stats.char_level >= 7 &&
        !agents[static_cast<std::size_t>(target_idx)].agent->getConditions().incapacitated) {
        total = saved ? 0 : (total / 2);
    }

    // Log the effect
    const char* verb = (sp.type == Spell::Heal) ? "healed" : "took";
    if (do_save)
        log_("{} {} {} from {} ({} save)", agents[static_cast<std::size_t>(target_idx)].agent->name(),
             verb, total, sp.name, saved ? "made" : "failed");
    else
        log_("{} {} {} from {}", agents[static_cast<std::size_t>(target_idx)].agent->name(), verb, total, sp.name);

    // Apply damage or healing
    if (sp.type == Spell::Heal) {
        healAgent(bm, target_idx, total);
    } else {
        damageAgent(bm, target_idx, total);
        processDamageTaken(bm, target_idx, total);  // zone damage ends/triggers on-damage conditions
    }
}

bool CombatEngine::zoneSparesTarget(const BattleMap& bm, const ActiveSpellEffect& effect,
                                    int target_idx) const noexcept
{
    // A creature is never caught in its own Emanation/zone.
    if (target_idx == effect.caster_idx) return true;

    const Spell& sp = effect.spell;
    // A neutral (faction 0) caster has no allies, so it keeps the legacy "affect everyone in
    // the area" behavior — no regression for un-teamed encounters / old saves.
    const int caster_faction = bm.getAgentFaction(effect.caster_idx);

    // Faction rule 3 — beneficial (Heal) zones only affect the caster's allies (incl. self).
    if (sp.type == Spell::Heal && caster_faction != 0 &&
        !areAllies(bm, effect.caster_idx, target_idx))
        return true;

    // Faction rule 2 — "creatures of your choice" harmful zones (selective_targeting, e.g.
    // Spirit Guardians) intrinsically spare the caster's allies. Ordinary zones (Wall of Fire)
    // leave selective_targeting false → friendly fire stays ON.
    if (sp.type == Spell::Harm && sp.selective_targeting && caster_faction != 0 &&
        areAllies(bm, effect.caster_idx, target_idx))
        return true;

    // Evoker safe targets are fully excluded from this caster's AoE/zone effects.
    auto it = safeTargets_.find(effect.caster_idx);
    if (it != safeTargets_.end() &&
        std::find(it->second.begin(), it->second.end(), target_idx) != it->second.end())
        return true;

    return false;
}

bool CombatEngine::applyZoneIfNewThisTurn(BattleMap& bm, const ActiveSpellEffect& effect, int target_idx) noexcept
{
    const int64_t key = (static_cast<int64_t>(effect.effect_id) << 32)
                      ^ static_cast<int64_t>(static_cast<uint32_t>(target_idx));
    auto it = zoneAppliedTurn_.find(key);
    if (it != zoneAppliedTurn_.end() && it->second == turnCounter_)
        return false;  // already applied to this target by this effect this turn
    applySpellEffect(bm, effect, target_idx);
    zoneAppliedTurn_[key] = turnCounter_;
    return true;
}

// Re-center any persistent Sphere effects anchored to this agent on their current
// position. Called when the agent moves and at the start of their turn so an
// Emanation (e.g. Spirit Guardians) tracks the caster.
void CombatEngine::recomputeAnchoredEffects(BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;
    const Cell origin = agents[static_cast<std::size_t>(agent_idx)].origin;

    std::vector<std::pair<int, int>> to_update;  // (effect_id, radius_ft)
    for (const auto& eff : bm.activeSpellEffects())
        if (eff.anchor_agent_idx == agent_idx)
            to_update.emplace_back(eff.effect_id, eff.spell.radius);

    for (const auto& [id, radius] : to_update)
        bm.setSpellEffectCells(id, sphereCellsAround(origin.col, origin.row, radius));

    // The Emanation's difficult-terrain footprint (e.g. Spirit Guardians' halved Speed) is a
    // separate anchored terrain effect — re-center it on the caster too.
    std::vector<std::pair<int, int>> terrain_to_update;  // (terrain_effect_id, radius_ft)
    for (const auto& te : bm.activeTerrainEffects())
        if (te.anchor_agent_idx == agent_idx)
            terrain_to_update.emplace_back(te.id, te.anchor_radius_ft);

    for (const auto& [id, radius] : terrain_to_update)
        bm.setTerrainEffectCells(id, sphereCellsAround(origin.col, origin.row, radius));
}

void CombatEngine::tickEffects(BattleMap& bm)
{
    auto agents = bm.placedAgents();
    for (auto& fx : activeEffects_) {
        if (fx.turns_remaining <= 0) continue;
        --fx.turns_remaining;

        if (fx.target_idx < 0 || fx.target_idx >= static_cast<int>(agents.size())) continue;
        Agent::Stats s = bm.getAgentStats(fx.target_idx);

        std::vector<int> dice;
        int total = 0;

        // Roll per-damage-type damage
        // Roll per-damage-type damage and apply target's multipliers. The caster's Elemental Adept /
        // Poisoner can ignore the target's Resistance on this ticking effect.
        const Agent::Stats tick_caster =
            (fx.caster_idx >= 0 && static_cast<std::size_t>(fx.caster_idx) < agents.size())
                ? bm.getAgentStats(fx.caster_idx) : Agent::Stats{};
        for (const auto& roll_info : fx.spell.magic_damage_rolls) {
            int type_damage = rollSpellTypeDamage(tick_caster, roll_info.type, roll_info.num_dice,
                                                  roll_info.die_size, dice, true);
            float multiplier = effectiveMagicDamageMult(tick_caster, s, roll_info.type, true);
            int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
            total += modified_damage;
        }
        for (const auto& roll_info : fx.spell.physical_damage_rolls) {
            int type_damage = 0;
            for (int i = 0; i < roll_info.num_dice; ++i) {
                int d = roll(roll_info.die_size);
                dice.push_back(d);
                type_damage += d;
            }
            // Apply target's resistance/vulnerability/immunity multiplier
            float multiplier = s.physical_damage_multipliers[roll_info.type];
            int modified_damage = static_cast<int>(static_cast<float>(type_damage) * multiplier);
            total += modified_damage;
        }

        if (fx.spell.type == Spell::Heal)
            s.hp_cur = std::min(s.hp_max, s.hp_cur + std::max(0, total));
        else {
            int damage = std::max(0, total);
            // Temporary HP absorbs damage first, then overflow damages hp_cur
            int overflow = std::max(0, damage - s.temp_hp);
            s.temp_hp = std::max(0, s.temp_hp - damage);
            s.hp_cur = std::max(0, s.hp_cur - overflow);
        }

        bm.setAgentStats(fx.target_idx, s);
        if (fx.spell.type != Spell::Heal)
            processDamageTaken(bm, fx.target_idx, std::max(0, total));
        else
            reviveOnHeal(bm, fx.target_idx);   // delayed/area heal can revive a downed target
    }

    auto expired = [](const ActiveEffect& fx) { return fx.turns_remaining <= 0; };
    activeEffects_.erase(
        std::remove_if(activeEffects_.begin(), activeEffects_.end(), expired),
        activeEffects_.end());
}

const std::vector<ActiveEffect>& CombatEngine::activeEffects() const noexcept
{
    return activeEffects_;
}

void CombatEngine::clearEffects() noexcept
{
    activeEffects_.clear();
    zoneAppliedTurn_.clear();
    turnCounter_ = 0;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Concentration
// ─────────────────────────────────────────────────────────────────────────────

ConcentrationSaveResult CombatEngine::concentrationSave(
        BattleMap& bm, int agent_idx, int damage_taken)
{
    ConcentrationSaveResult r;
    Agent::Conditions cond = bm.getAgentConditions(agent_idx);
    if (!cond.concentrating) return r;

    r.checked    = true;
    r.spell_name = cond.concentrating_on;
    r.save_dc    = std::max(10, damage_taken / 2);

    // Apply advantage/disadvantage from agent conditions
    bool has_adv = cond.has_advantage;
    {
        Agent::Stats cs = bm.getAgentStats(agent_idx);
        if (cs.character_class == CharacterClass::Warlock && cs.hasInvocation(3))
            has_adv = true;  // Eldritch Mind
        if (cs.hasFeat("War Caster"))
            has_adv = true;  // War Caster: Advantage on concentration saves
    }
    bool has_dis = cond.has_disadvantage;
    int save_d20;
    if (has_adv && has_dis) {
        save_d20 = roll(20);  // Cancel out
    } else if (has_adv) {
        save_d20 = rollAdvantage(20);
    } else if (has_dis) {
        save_d20 = rollDisadvantage(20);
    } else {
        save_d20 = roll(20);
    }
    // Clockwork L14 Trance of Order: floor the sorcerer's own d20 (9-or-lower → 10) on this
    // concentration save (a D20 Test). No auto-fail path here.
    save_d20 = bm.getAgentStats(agent_idx).applyTranceFloor(save_d20);
    r.save_d20   = save_d20;

    Agent::Stats s = bm.getAgentStats(agent_idx);
    int con_mod = (s.con - 10) / 2;
    if (s.con < 10 && (s.con - 10) % 2 != 0) --con_mod;
    con_mod += s.save_prof_con ? s.prof_bonus : 0;
    r.con_mod = con_mod;
    r.passed  = (r.save_d20 + con_mod >= r.save_dc);

    if (!r.passed) {
        r.concentration_lost = true;
        // Route through the full cascade (terrain + spell effects + spell-applied conditions +
        // summon dismissal), not a bare flag-clear — otherwise a failed save here would leak
        // a caster's zones/summons. Mirrors checkConcentrationOnDamage.
        (void)dropConcentration(bm, agent_idx);
    }
    return r;
}

bool CombatEngine::checkConcentrationOnDamage(BattleMap& bm, int target_idx, int damage, int damager_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (target_idx < 0 || static_cast<std::size_t>(target_idx) >= agents.size())
        return false;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(target_idx)];
    const Agent::Conditions& cond = pa.agent->getConditions();
    if (!cond.concentrating)
        return false;  // Not concentrating, no save needed

    // Relentless Hunter (Ranger L13+): taking damage can't break your concentration on Hunter's Mark.
    {
        const Agent::Stats& rs = pa.agent->getStats();
        if (rs.character_class == CharacterClass::Ranger && rs.char_level >= 13 &&
            cond.concentrating_on == "Hunter's Mark")
            return false;  // Concentration automatically holds
    }

    // DC is 10 or half damage, whichever is higher
    int dc = std::max(10, damage / 2);
    const Agent::Stats& cstats = pa.agent->getStats();
    int con_mod = (cstats.con - 10) / 2;
    if (cstats.con < 10 && (cstats.con - 10) % 2 != 0) --con_mod;  // floor for odd negative scores
    if (cstats.save_prof_con) con_mod += cstats.prof_bonus;       // CON save proficiency

    // War Caster (feat) → Advantage on the save; Mage Slayer (feat) on the damager → Disadvantage
    // (Concentration Breaker). Eldritch Mind invocation also grants Advantage. They cancel if both apply.
    bool adv = cstats.hasFeat("War Caster") ||
               (cstats.character_class == CharacterClass::Warlock && cstats.hasInvocation(3));
    bool dis = false;
    if (damager_idx >= 0 && static_cast<std::size_t>(damager_idx) < agents.size() &&
        bm.getAgentStats(damager_idx).hasFeat("Mage Slayer"))
        dis = true;
    int save_roll = (adv && dis) ? roll(20)
                  : adv          ? rollAdvantage(20)
                  : dis          ? rollDisadvantage(20)
                                 : roll(20);
    int save_total = save_roll + con_mod;

    if (save_total >= dc) {
        log_("Concentration save: {} rolled {} + {} = {} vs DC {} — HELD",
             pa.agent->name(), save_roll, con_mod, save_total, dc);
        return false;  // Save succeeded
    }

    log_("Concentration save: {} rolled {} + {} = {} vs DC {} — BROKEN",
         pa.agent->name(), save_roll, con_mod, save_total, dc);

    // Concentration lost — fully drop it (terrain + spell effects + spell-applied conditions + flags).
    (void)dropConcentration(bm, target_idx);
    return true;  // Concentration was lost
}

DropConcentrationResult CombatEngine::dropConcentration(BattleMap& bm, int agent_idx)
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size()))
        return {};
    Agent::Conditions cond = bm.getAgentConditions(agent_idx);
    if (!cond.concentrating)
        return {};

    DropConcentrationResult result;
    result.dropped    = true;
    result.spell_name = cond.concentrating_on;

    // 1. Remove this caster's concentration terrain only (leave non-concentration
    //    timed terrain, e.g. Grease, which is not a concentration spell in 5e).
    for (const auto& eff : bm.activeTerrainEffects()) {
        if (eff.source_agent_idx == agent_idx && eff.requires_concentration)
            result.removed_terrain_ids.push_back(eff.id);
    }
    for (int tid : result.removed_terrain_ids)
        bm.removeTerrainEffect(tid);

    // 2. Remove this caster's concentration spell-effects only
    for (const auto& eff : bm.activeSpellEffects()) {
        if (eff.caster_idx == agent_idx && eff.spell.requires_concentration)
            result.removed_spell_effect_ids.push_back(eff.effect_id);
    }
    for (int eid : result.removed_spell_effect_ids)
        bm.removeSpellEffect(eid);

    // 2a. Remove this caster's concentration light effects (Darkness, Fog Cloud, etc.)
    [[maybe_unused]] auto removed_light_ids = bm.removeLightEffectsBySource(agent_idx);

    // 3. Remove conditions applied by this agent's concentration spells.
    //    clearSpellConditionEffect REVERSES the condition's effect on the target
    //    (clears incapacitated/charmed/etc. flags so speed/actions are restored);
    //    removeAgentCondition only erases the tracking entry. Both are required —
    //    otherwise e.g. Hypnotic Pattern targets stay Incapacitated with speed 0
    //    after the caster's concentration drops.
    const auto& spells = bm.getAgentSpells(agent_idx);
    for (const auto& ac : activeAgentConditions_) {
        if (ac.caster_idx == agent_idx &&
            ac.spell_idx >= 0 && ac.spell_idx < static_cast<int>(spells.size()) &&
            spells[static_cast<std::size_t>(ac.spell_idx)].requires_concentration) {
            clearSpellConditionEffect(bm, ac);
            result.removed_condition_ids.push_back(ac.condition_id);
        }
    }
    for (int cid : result.removed_condition_ids)
        removeAgentCondition(cid);

    // 4. Clear C++ concentration state
    const bool was_mantle_majesty       = (cond.concentrating_on == "Mantle of Majesty");
    const bool was_unbreakable_majesty  = (cond.concentrating_on == "Unbreakable Majesty");
    cond.concentrating    = false;
    cond.concentrating_on = {};
    bm.setAgentConditions(agent_idx, cond);

    // 4a. Mantle of Majesty's "unearthly appearance" window IS the concentration — end it when
    //     concentration drops (a later concentration spell, or a damage-broken save).
    if (was_mantle_majesty) {
        Agent::Stats ms = bm.getAgentStats(agent_idx);
        if (ms.mantle_majesty_turns > 0) {
            ms.mantle_majesty_turns = 0;
            bm.setAgentStats(agent_idx, ms);
            log_("{}'s unearthly appearance fades (Mantle of Majesty ends)", agentName(bm, agent_idx));
        }
    }

    // 4a'. Unbreakable Majesty's "majestic presence" window IS the concentration — end it the
    //      same way (mirrors Mantle of Majesty above).
    if (was_unbreakable_majesty) {
        Agent::Stats ms = bm.getAgentStats(agent_idx);
        if (ms.majestic_presence_turns > 0) {
            ms.majestic_presence_turns = 0;
            bm.setAgentStats(agent_idx, ms);
            log_("{}'s majestic presence fades (Unbreakable Majesty ends)", agentName(bm, agent_idx));
        }
    }

    // 4b. Clear the Hunter's Mark / Hex marked-target rider. The mark is only ever set by those
    //     concentration spells, and a creature concentrates on one spell at a time, so dropping
    //     concentration always ends the mark.
    if (Agent::Stats cs = bm.getAgentStats(agent_idx); cs.hunters_mark_target >= 0) {
        cs.hunters_mark_target = -1;
        bm.setAgentStats(agent_idx, cs);
    }

    // 5. Dismiss this caster's summoned creatures. They are TOMBSTONED
    //    (removed_from_play = true), not erased from placedAgents_, so every
    //    index reference (caster_idx / agent_idx / initiative) stays valid.
    //    The GUI skips removed_from_play agents in turns and rendering.
    //    EXCEPTION: the Trickery Cleric's Invoke Duplicity illusion is NOT a concentration effect
    //    (Channel Divinity, 1-minute fixed duration), so losing concentration must not dismiss it.
    {
        auto summons = bm.placedAgents();
        for (int i = 0; i < static_cast<int>(summons.size()); ++i) {
            const auto& s = summons[static_cast<std::size_t>(i)];
            if (s.summoner_idx == agent_idx && !s.removed_from_play &&
                s.summon_spell != "Invoke Duplicity") {
                bm.setAgentRemovedFromPlay(i, true);
                result.dismissed_summons.push_back(i);
            }
        }
    }

    return result;
}

void CombatEngine::clearAllConcentration(BattleMap& bm)
{
    for (int i = 0; i < static_cast<int>(bm.placedAgents().size()); ++i) {
        if (bm.getAgentConditions(i).concentrating)
            (void)dropConcentration(bm, i);  // cascades: terrain + spell effects + conditions + flag
    }
}

void CombatEngine::clearSpellConditionEffect(BattleMap& bm, const ActiveAgentCondition& cond) noexcept
{
    const auto& agents = bm.placedAgents();
    if (cond.agent_idx < 0 || cond.agent_idx >= static_cast<int>(agents.size())) return;
    Agent::Conditions ac = bm.getAgentConditions(cond.agent_idx);
    const std::string& n = cond.condition_name;
    if      (n == "Paralyzed")     { ac.paralyzed = false; ac.incapacitated = false; }
    else if (n == "Blinded")       { ac.blinded = false; }
    else if (n == "Incapacitated") { ac.incapacitated = false; }
    else if (n == "Stunned")       { ac.stunned = false; ac.incapacitated = false; }
    else if (n == "Charmed")       { ac.charmed = false; ac.charmed_by = -1; }
    else if (n == "Frightened")    { ac.frightened = false; }
    else if (n == "Unconscious")   { ac.unconscious = false; ac.incapacitated = false; }
    else if (n == "Prone")         { ac.prone = false; }
    bm.setAgentConditions(cond.agent_idx, ac);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Slots
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::createSpellSlot(BattleMap& bm, int idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return -1;
    // Font of Magic creates only level 1-5 slots.
    if (slot_level < 1 || slot_level > 5) return -1;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer) return -1;

    static const int cost_by_level[6] = {0, 2, 3, 5, 6, 7};  // SP cost; index = slot level
    int cost = cost_by_level[slot_level];

    Resource* sp = stats.getResource("Sorcery Points");
    if (!sp || sp->current < cost) return -1;

    sp->spend(cost);
    auto si = static_cast<std::size_t>(slot_level - 1);
    stats.spell_slots_remaining[si] += 1;  // temporary slot; cleared at the next long rest
    bm.setAgentStats(idx, stats);

    log_("{} spends {} Sorcery Points to create a level-{} slot",
         agentName(bm, idx), cost, slot_level);
    return sp->current;
}

int CombatEngine::convertSlotToSorceryPoints(BattleMap& bm, int idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 1 || slot_level > 9) return -1;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;   // no slot of that level to spend

    Resource* sp = stats.getResource("Sorcery Points");
    if (!sp) return -1;

    stats.spell_slots_remaining[si] -= 1;
    sp->gain(slot_level);  // gain SP equal to the slot level (capped at max by Resource::gain)
    bm.setAgentStats(idx, stats);

    log_("{} converts a level-{} slot into Sorcery Points (now {}/{})",
         agentName(bm, idx), slot_level, sp->current, sp->max);
    return sp->current;
}

bool CombatEngine::spendSorceryPointsForSpell(BattleMap& bm, int idx, int spell_level) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    if (spell_level < 1) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer ||
        stats.sorcerer_subclass != SorcererSubclass::AberrantPath ||
        stats.char_level < 3) {
        return false;
    }

    Resource* sp = stats.getResource("Sorcery Points");
    if (!sp || sp->current < spell_level) return false;

    sp->spend(spell_level);
    bm.setAgentStats(idx, stats);

    log_("{} spends {} Sorcery Points to cast a level-{} psionic spell",
         agentName(bm, idx), spell_level, spell_level);
    return true;
}

int CombatEngine::sorcererBendLuck(BattleMap& bm, int idx, bool boost) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.char_level < 6) {
        log_("{} cannot use Bend Luck (not a L6+ Wild Magic Sorcerer)", agentName(bm, idx));
        return 0;
    }

    Resource* sp = stats.getResource("Sorcery Points");
    if (!sp || sp->current < 1) {
        log_("{} has no Sorcery Point for Bend Luck", agentName(bm, idx));
        return 0;
    }

    sp->current -= 1;
    int value = roll(4);                                 // 1d4
    pending_roll_bonus_ = boost ? value : -value;        // bonus or penalty to the next D20 Test
    bm.setAgentStats(idx, stats);

    log_("{} uses Bend Luck: {}{} to the next D20 Test ({} Sorcery Points left)",
         agentName(bm, idx), boost ? "+" : "-", value, sp->current);
    return value;
}

std::string CombatEngine::wildMagicSurgeDescription(int effect) noexcept
{
    // Curated d100 surge table (bands of 10 → effect 1-10). Applying each effect is the
    // caller's job; some bands are placeholders pending easier replacements (see notes).
    switch (effect) {
        case 1:  return "Plant Growth sprouts around your feet (difficult terrain in a sphere "
                        "centered on you).";
        case 2:  return "A spectral shield hovers near you for the next minute, granting you a "
                        "+2 bonus to AC and immunity to Magic Missile.";
        case 3:  return "For the next minute, you regain 5 Hit Points at the start of each of "
                        "your turns.";
        case 4:  return "Up to three creatures of your choice within 30 ft take 4d10 Lightning "
                        "damage.";
        case 5:  return "You cast Blindness on a creature you can see within range "
                        "(Constitution save or the Blinded condition).";
        case 6:  return "For the next minute, your spells that take an action to cast can be "
                        "cast as a Bonus Action.";
        case 7:  return "Your next turn is skipped.";
        case 8:  return "You can take one extra action on this turn.";
        case 9:  return "Your weapons are all dropped and appear on a random square you can see.";
        case 10: return "For the next minute, you can teleport up to 20 ft as a Bonus Action on "
                        "each of your turns.";
        default: return "";
    }
}

WildMagicSurgeResult CombatEngine::rollWildMagicSurge(BattleMap& bm, int idx) noexcept
{
    WildMagicSurgeResult res;
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return res;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.char_level < 3) {
        log_("{} cannot surge (not a L3+ Wild Magic Sorcerer)", agentName(bm, idx));
        return res;  // effect = 0
    }

    res.d100_roll  = roll(100);                       // 1-100
    res.effect      = (res.d100_roll - 1) / 10 + 1;   // → band 1-10
    res.description = wildMagicSurgeDescription(res.effect);

    log_("{} Wild Magic Surge (d100={}, effect {}): {}",
         agentName(bm, idx), res.d100_roll, res.effect, res.description);
    return res;
}

bool CombatEngine::applyWildMagicSurgeEffect(BattleMap& bm, int idx, int effect) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    if (effect == 1) {  // "Plant Growth sprouts around your feet" — cast Plant Growth on the caster.
        Cell origin = agents[static_cast<std::size_t>(idx)].origin;
        auto cells = sphereCellsAround(origin.col, origin.row, 10);  // 10-ft radius sphere
        [[maybe_unused]] int id = bm.placeTerrainEffect(
            "Plant Growth (Wild Magic Surge)", cells,
            TerrainDifficulty::Quartered, 10 /* rounds ≈ 1 minute */, idx);
        log_("{}: Plant Growth sprouts — difficult terrain over {} cells",
             agentName(bm, idx), cells.size());
        return true;
    }

    if (effect == 9) {  // "Your weapons are all dropped and appear on a random square you can see."
        // Simplified: the weapons land on the caster's own cell as ground items.
        Cell origin = agents[static_cast<std::size_t>(idx)].origin;
        auto weapons = bm.getAgentWeapons(idx);
        int dropped = 0;
        for (auto& w : weapons) {
            // Weapons without "Unarmed" in name are real weapons — only real weapons drop (not permanently armed).
            if (!w.name.empty() && w.name.find("Unarmed") == std::string::npos && !w.permanently_armed) {
                [[maybe_unused]] int item_id = bm.placeItem(origin, w);
                w = Weapon{};  // clear the slot back to the default (Unarmed)
                ++dropped;
            }
        }
        if (dropped > 0) bm.setAgentWeapons(idx, weapons);
        log_("{}: Wild Magic Surge drops {} weapon(s) to the ground", agentName(bm, idx), dropped);
        return true;
    }

    // Bands 2/3/6/7/8/10 are per-agent state effects, ticked at the start of the agent's turns.
    constexpr int kMinuteRounds = 10;
    Agent::Stats stats = bm.getAgentStats(idx);
    switch (effect) {
        case 2:  // Spectral shield: +2 AC + Magic Missile immunity for 1 minute.
            stats.ac_temporary_modifications += 2;       // removed when wild_magic_shield_turns hits 0
            stats.wild_magic_shield_turns = kMinuteRounds;
            log_("{}: a spectral shield grants +2 AC and Magic Missile immunity for 1 minute",
                 agentName(bm, idx));
            break;
        case 3:  // Regain 5 HP at the start of each of your turns for 1 minute.
            stats.wild_magic_regen_turns = kMinuteRounds;
            log_("{}: surging vitality — regain 5 HP at the start of each turn for 1 minute",
                 agentName(bm, idx));
            break;
        case 6:  // For 1 minute, action-cast spells can be cast as a Bonus Action (GUI-enforced).
            stats.wild_magic_bonus_cast_turns = kMinuteRounds;
            log_("{}: for 1 minute, spells that take an action can be cast as a Bonus Action",
                 agentName(bm, idx));
            break;
        case 7:  // Your next turn is skipped.
            stats.wild_magic_skip_next_turn = true;
            log_("{}: the surge will skip their next turn", agentName(bm, idx));
            break;
        case 8:  // You can take one extra action on this turn (enforced by the GUI turn economy).
            stats.wild_magic_extra_action = true;
            log_("{}: the surge grants one extra action this turn", agentName(bm, idx));
            break;
        case 10: // For 1 minute, teleport up to 20 ft as a Bonus Action each turn (GUI-enforced).
            stats.wild_magic_teleport_bonus_turns = kMinuteRounds;
            log_("{}: for 1 minute, can teleport up to 20 ft as a Bonus Action each turn",
                 agentName(bm, idx));
            break;
        default:
            return false;  // applied by the caller / not yet wired
    }
    bm.setAgentStats(idx, stats);
    return true;
}

bool CombatEngine::activateTidesOfChaos(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.char_level < 3) {
        log_("{} cannot use Tides of Chaos (not a L3+ Wild Magic Sorcerer)", agentName(bm, idx));
        return false;
    }

    Resource* tides = stats.getResource("Tides of Chaos");
    if (!tides || tides->current < 1) {
        log_("{} has no Tides of Chaos use left (recharges on a long rest or a Wild Magic Surge)",
             agentName(bm, idx));
        return false;
    }

    tides->current -= 1;
    grantPendingAdvantage(true);                 // Advantage on the next D20 Test
    bm.setAgentStats(idx, stats);

    log_("{} uses Tides of Chaos: Advantage on the next D20 Test", agentName(bm, idx));
    return true;
}

WildMagicSurgeOffer CombatEngine::offerWildMagicSurge(BattleMap& bm, int idx) noexcept
{
    WildMagicSurgeOffer offer;                   // surged == false → no surge
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return offer;

    Agent::Stats stats = bm.getAgentStats(idx);
    if (stats.character_class != CharacterClass::Sorcerer ||
        stats.sorcerer_subclass != SorcererSubclass::WildMagicPath || stats.char_level < 3) {
        return offer;                            // silent: only Wild Magic Sorcerers surge
    }

    // Tides of Chaos: if it is currently expended, the next slot-spell cast forces a surge
    // (and the surge then recharges it). Otherwise a surge needs a natural 20 on a d20.
    Resource* tides = stats.getResource("Tides of Chaos");
    offer.tides_expended = tides && tides->current < tides->max;

    const int d20 = roll(20);
    const bool surge = offer.tides_expended || (d20 == 20);
    log_("{}: Wild Magic Surge check — d20={}{}", agentName(bm, idx), d20,
         offer.tides_expended ? " (Tides of Chaos forces a surge)" : "");
    if (!surge) return offer;

    offer.surged = true;
    // Roll the table. Controlled Chaos (L14): roll twice and keep both bands so the caller may use
    // either result.
    const int rolls = (stats.char_level >= 14) ? 2 : 1;
    for (int i = 0; i < rolls; ++i) {
        WildMagicSurgeResult r = rollWildMagicSurge(bm, idx);   // rolls d100, classifies, logs
        if (r.effect > 0 &&
            std::find(offer.options.begin(), offer.options.end(), r.effect) == offer.options.end())
            offer.options.push_back(r.effect);
    }
    // Tamed Surge (L18): the caller may replace the rolled result with any band 1-10.
    offer.can_choose_any = (stats.char_level >= 18);
    return offer;
}

WildMagicSurgeResult CombatEngine::resolveWildMagicSurge(BattleMap& bm, int idx, int effect,
                                                         bool tides_expended) noexcept
{
    WildMagicSurgeResult res;                    // effect == 0 → nothing applied
    if (effect < 1 || effect > 10) return res;

    res.effect      = effect;
    res.description = wildMagicSurgeDescription(effect);
    applyWildMagicSurgeEffect(bm, idx, effect);  // mutates + persists stats internally
    if (tides_expended) {
        // Re-fetch (applyWildMagicSurgeEffect may have written stats) before recharging Tides
        // so the surge's own state changes aren't clobbered.
        Agent::Stats fresh = bm.getAgentStats(idx);
        if (Resource* t2 = fresh.getResource("Tides of Chaos")) {
            t2->current = t2->max;
            bm.setAgentStats(idx, fresh);
            log_("{}: the surge recharges Tides of Chaos", agentName(bm, idx));
        }
    }
    return res;
}

WildMagicSurgeResult CombatEngine::maybeWildMagicSurge(BattleMap& bm, int idx) noexcept
{
    // Non-interactive path: offer, then auto-apply the first rolled band (no Controlled Chaos /
    // Tamed Surge choice — the GUI uses offerWildMagicSurge + resolveWildMagicSurge for those).
    WildMagicSurgeOffer offer = offerWildMagicSurge(bm, idx);
    if (!offer.surged || offer.options.empty()) return WildMagicSurgeResult{};
    return resolveWildMagicSurge(bm, idx, offer.options.front(), offer.tides_expended);
}

bool CombatEngine::expendArcaneWardSlot(BattleMap& bm, int agent_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);

    // Validate: Abjurer L3+ with active ward
    if (stats.character_class != Wizard || stats.wizard_subclass != AbjurerPath ||
        stats.char_level < 3 || stats.temp_hp <= 0) {
        return false;
    }

    // Validate: slot_level is valid (1-9)
    if (slot_level < 1 || slot_level > 9) return false;

    // Validate: agent has remaining spell slot at this level
    if (stats.spell_slots_remaining[static_cast<std::size_t>(slot_level - 1)] <= 0) {
        return false;
    }

    // Expend the slot
    stats.spell_slots_remaining[static_cast<std::size_t>(slot_level - 1)]--;

    // Charge the ward
    int max_ward = 2 * stats.char_level + (stats.intel - 10) / 2;
    int ward_gain = 2 * slot_level;
    stats.temp_hp = std::min(stats.temp_hp + ward_gain, max_ward);

    // Save stats back
    bm.setAgentStats(agent_idx, stats);

    log_("{} expends Level {} slot, Arcane Ward now {}/{}",
         agentName(bm, agent_idx), slot_level, stats.temp_hp, max_ward);

    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
//  OnSaveFail window — reroll a just-failed spell save
//  Consumers: Countercharm (Bard L7 — reroll an ally's failed charm/frighten save WITH ADVANTAGE,
//  costs the bard's reaction) and Indomitable (Fighter L9 — reroll your OWN failed save + Fighter
//  level, costs an Indomitable use, not the reaction). "raising-only": a reroll can only turn a
//  failure into a success, so executeSpell consuming the corrected save needs no undo.
// ─────────────────────────────────────────────────────────────────────────────

// Does this spell apply Charmed or Frightened (the Countercharm trigger)?
static bool spellAppliesCharmOrFear(const Spell& sp)
{
    for (const auto& c : sp.conditions)
        if (c.condition_name == "Charmed" || c.condition_name == "Frightened") return true;
    return false;
}

// Shared alive/reaction/range/LoS gate for a save reactor. reactor==save_target (self) skips range/LoS.
// require_reaction=false lets Indomitable (RAW "no action") react even with its reaction already spent.
static bool saveReactorBase(const BattleMap& bm, int reactor, int save_target,
                            int range_ft, bool require_reaction)
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (reactor < 0 || reactor >= n || save_target < 0 || save_target >= n) return false;
    if (bm.isAgentOnDeck(reactor)) return false;          // On Deck reserves take no reactions until deployed
    const Agent::Conditions cond = bm.getAgentConditions(reactor);
    if (cond.incapacitated) return false;
    if (require_reaction && cond.reaction_used) return false;
    if (bm.getAgentStats(reactor).hp_cur <= 0) return false;
    if (reactor == save_target) return true;                      // self — no range/LoS needed
    const PlacedAgent& rpa = agents[static_cast<std::size_t>(reactor)];
    const PlacedAgent& tpa = agents[static_cast<std::size_t>(save_target)];
    if (footprintDistance(rpa.origin, rpa.agent->getSize(),
                          tpa.origin, tpa.agent->getSize()) * 5 > range_ft) return false;
    return bm.hasLineOfSight(rpa.origin, rpa.agent->getSize(), tpa.origin, tpa.agent->getSize());
}

bool CombatEngine::canCountercharm(const BattleMap& bm, int reactor, int save_target,
                                   const SpellAction& action) const
{
    if (reactor == action.caster_idx) return false;               // the caster won't aid its own target
    if (!saveReactorBase(bm, reactor, save_target, 30, /*require_reaction=*/true)) return false;
    const Agent::Stats s = bm.getAgentStats(reactor);
    if (s.character_class != CharacterClass::Bard || s.char_level < 7) return false;
    // Only vs a spell that would apply Charmed or Frightened.
    const auto& spells = bm.getAgentSpells(action.caster_idx);
    if (action.spell_idx < 0 || action.spell_idx >= static_cast<int>(spells.size())) return false;
    return spellAppliesCharmOrFear(spells[static_cast<std::size_t>(action.spell_idx)]);
}

bool CombatEngine::canIndomitable(const BattleMap& bm, int reactor, int save_target) const
{
    if (reactor != save_target) return false;                     // you reroll your OWN save
    if (!saveReactorBase(bm, reactor, save_target, 0, /*require_reaction=*/false)) return false;
    const Agent::Stats s = bm.getAgentStats(reactor);
    if (s.character_class != CharacterClass::Fighter || s.char_level < 9) return false;
    const Resource* ind = s.getResource("Indomitable");
    return ind && ind->current >= 1;
}

bool CombatEngine::canDarkOnesOwnLuck(const BattleMap& bm, int reactor, int save_target) const
{
    if (reactor != save_target) return false;                     // you add the die to your OWN save
    if (!saveReactorBase(bm, reactor, save_target, 0, /*require_reaction=*/false)) return false;
    const Agent::Stats s = bm.getAgentStats(reactor);
    if (s.character_class != CharacterClass::Warlock ||
        s.warlock_subclass != FiendPath || s.char_level < 6) return false;
    const Resource* luck = s.getResource("Dark One's Own Luck");
    return luck && luck->current >= 1;
}

void CombatEngine::reevaluateSave(SpellSave& ss) const noexcept
{
    ss.total = ss.d20 + ss.save_mod + ss.bonus;
    ss.saved = (ss.total >= ss.dc);
}

bool CombatEngine::applyCountercharmToSave(BattleMap& bm, int reactor, SpellSave& ss)
{
    const auto& agents = bm.placedAgents();
    if (reactor < 0 || reactor >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(reactor);
    Agent::Conditions cond = bm.getAgentConditions(reactor);
    if (cond.reaction_used || cond.incapacitated || s.hp_cur <= 0) return false;
    if (s.character_class != CharacterClass::Bard || s.char_level < 7) return false;

    cond.reaction_used = true;                                    // Countercharm costs the bard's reaction
    const int a = roll(20), b = roll(20);                         // reroll WITH ADVANTAGE
    ss.d20 = std::max(a, b);
    reevaluateSave(ss);
    bm.setAgentConditions(reactor, cond);
    log_("{} uses Countercharm: {} rerolls the save with advantage ({}/{}) → {} vs DC {} → {}",
         agentName(bm, reactor), agentName(bm, ss.target_idx), a, b, ss.total, ss.dc,
         ss.saved ? "SAVES" : "still fails");
    return true;
}

bool CombatEngine::applyIndomitableToSave(BattleMap& bm, int reactor, SpellSave& ss)
{
    const auto& agents = bm.placedAgents();
    if (reactor < 0 || reactor >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(reactor);
    if (s.hp_cur <= 0) return false;
    if (s.character_class != CharacterClass::Fighter || s.char_level < 9) return false;
    Resource* ind = s.getResource("Indomitable");
    if (!ind || ind->current < 1) return false;

    ind->current -= 1;                                            // costs an Indomitable use, NOT the reaction
    const int old_d20 = ss.d20;
    ss.d20   = roll(20);                                          // reroll the save
    ss.bonus = s.char_level;                                      // 2024: add the Fighter level to the new roll
    reevaluateSave(ss);
    bm.setAgentStats(reactor, s);
    log_("{} uses Indomitable: rerolls the save {}→{} +{} (level) = {} vs DC {} → {}",
         agentName(bm, reactor), old_d20, ss.d20, ss.bonus, ss.total, ss.dc,
         ss.saved ? "SAVES" : "still fails");
    return true;
}

bool CombatEngine::applyDarkOnesOwnLuckToSave(BattleMap& bm, int reactor, SpellSave& ss)
{
    const auto& agents = bm.placedAgents();
    if (reactor < 0 || reactor >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(reactor);
    if (s.hp_cur <= 0) return false;
    if (s.character_class != CharacterClass::Warlock ||
        s.warlock_subclass != FiendPath || s.char_level < 6) return false;
    Resource* luck = s.getResource("Dark One's Own Luck");
    if (!luck || luck->current < 1) return false;

    luck->current -= 1;                                          // costs a use, NOT the reaction
    const int d10 = roll(10);
    ss.bonus += d10;                                            // add the d10 to the failed save (post-roll)
    reevaluateSave(ss);
    bm.setAgentStats(reactor, s);
    log_("{} uses Dark One's Own Luck: +{} (d10) to the save → {} vs DC {} → {}",
         agentName(bm, reactor), d10, ss.total, ss.dc,
         ss.saved ? "SAVES" : "still fails");
    return true;
}

bool CombatEngine::canLegendaryResist(const BattleMap& bm, int reactor, int save_target) const
{
    if (reactor != save_target) return false;                     // creature uses it on its OWN save
    if (!saveReactorBase(bm, reactor, save_target, 0, /*require_reaction=*/false)) return false;
    const Agent::Stats s = bm.getAgentStats(reactor);
    return s.legendary_resistance_current >= 1;
}

bool CombatEngine::applyLegendaryResistanceToSave(BattleMap& bm, int reactor, SpellSave& ss)
{
    const auto& agents = bm.placedAgents();
    if (reactor < 0 || reactor >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(reactor);
    if (s.hp_cur <= 0) return false;
    if (s.legendary_resistance_current < 1) return false;

    s.legendary_resistance_current -= 1;                          // spend one legendary resistance use
    ss.bonus = 99;                                                // +99 ensures success on a failed save
    reevaluateSave(ss);
    bm.setAgentStats(reactor, s);
    log_("{} uses Legendary Resistance: the save {} vs DC {} → {}",
         agentName(bm, reactor), ss.total, ss.dc,
         ss.saved ? "SUCCEEDS" : "still fails");
    return true;
}

bool CombatEngine::canWarGodsBlessing(const BattleMap& bm, int reactor, int save_target) const
{
    // War Domain L6 Channel Divinity — grant +10 to a creature within 60 ft that just failed a save.
    // Costs the cleric's reaction even when aiding its own save (unlike Indomitable/Legendary Resistance),
    // so re-check reaction_used directly (saveReactorBase skips that test for reactor == save_target).
    if (!saveReactorBase(bm, reactor, save_target, 60, /*require_reaction=*/true)) return false;
    if (bm.getAgentConditions(reactor).reaction_used) return false;
    if (reactor != save_target && !areAllies(bm, reactor, save_target)) return false;   // only aid yourself/allies
    const Agent::Stats s = bm.getAgentStats(reactor);
    if (s.character_class != CharacterClass::Cleric ||
        s.cleric_subclass != WarDomain || s.char_level < 6) return false;
    const Resource* cd = s.getResource("Channel Divinity");
    return cd && cd->current >= 1;
}

bool CombatEngine::applyWarGodsBlessingToSave(BattleMap& bm, int reactor, SpellSave& ss)
{
    const auto& agents = bm.placedAgents();
    if (reactor < 0 || reactor >= static_cast<int>(agents.size())) return false;
    Agent::Stats s = bm.getAgentStats(reactor);
    Agent::Conditions cond = bm.getAgentConditions(reactor);
    if (cond.reaction_used || cond.incapacitated || s.hp_cur <= 0) return false;
    if (s.character_class != CharacterClass::Cleric ||
        s.cleric_subclass != WarDomain || s.char_level < 6) return false;
    Resource* cd = s.getResource("Channel Divinity");
    if (!cd || cd->current < 1) return false;

    cd->current -= 1;                                            // spend one Channel Divinity use
    cond.reaction_used = true;                                   // War God's Blessing costs the reaction
    ss.bonus += 10;                                              // +10 to the failed save (after the roll)
    reevaluateSave(ss);
    bm.setAgentStats(reactor, s);
    bm.setAgentConditions(reactor, cond);
    log_("{} uses War God's Blessing: +10 to {}'s save → {} vs DC {} → {}",
         agentName(bm, reactor), agentName(bm, ss.target_idx), ss.total, ss.dc,
         ss.saved ? "SUCCEEDS" : "still fails");
    return true;
}

// Everyone eligible for ANY reroll-save reaction vs one FAILED save, in index order: the target itself
// (Indomitable / Legendary Resistance) + bards within 30 ft on a charm/frighten spell (Countercharm).
std::vector<int> CombatEngine::saveFailReactors(const BattleMap& bm, const SpellAction& action,
                                                const SpellSave& ss) const
{
    std::vector<int> out;
    if (ss.saved || ss.auto_fail) return out;                     // nothing to reroll
    const int n = static_cast<int>(bm.placedAgents().size());
    for (int i = 0; i < n; ++i)
        if (canIndomitable(bm, i, ss.target_idx) || canLegendaryResist(bm, i, ss.target_idx) ||
            canCountercharm(bm, i, ss.target_idx, action) || canWarGodsBlessing(bm, i, ss.target_idx) ||
            canDarkOnesOwnLuck(bm, i, ss.target_idx))
            out.push_back(i);
    return out;
}

std::vector<ReactionOption> CombatEngine::saveFailOptions(const BattleMap& bm, int reactor,
                                                          const SpellAction& action,
                                                          const SpellSave& ss) const
{
    std::vector<ReactionOption> opts;
    if (ss.saved || ss.auto_fail) return opts;
    if (canIndomitable(bm, reactor, ss.target_idx))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                      "Use Indomitable (reroll your failed save)", "Indomitable"});
    if (canLegendaryResist(bm, reactor, ss.target_idx))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                      "Use Legendary Resistance (succeed on the failed save)", "LegendaryResistance"});
    if (canCountercharm(bm, reactor, ss.target_idx, action))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                      "Use Countercharm (reroll the failed save with advantage)", "Countercharm"});
    if (canWarGodsBlessing(bm, reactor, ss.target_idx))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                      "Use War God's Blessing (+10 to the failed save, 1 Channel Divinity)", "WarGodsBlessing"});
    if (canDarkOnesOwnLuck(bm, reactor, ss.target_idx))
        opts.push_back(ReactionOption{ReactionOption::Feature, -1,
                                      "Use Dark One's Own Luck (+1d10 to the failed save)", "DarkOnesOwnLuck"});
    if (!opts.empty())
        opts.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
    return opts;
}

void CombatEngine::applySaveFailReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp)
{
    if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) return;
    const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
    if (opt.kind != ReactionOption::Feature) return;              // Skip → no reaction
    // Find the pre-rolled save for the failed creature (carried in ctx.source_idx).
    SpellSave* ss = nullptr;
    for (auto& p : topCast().save_prerolls)
        if (p.target_idx == ctx.source_idx) { ss = &p; break; }
    if (!ss) return;
    if      (opt.feature == "Countercharm")         applyCountercharmToSave(bm, ctx.reactor_idx, *ss);
    else if (opt.feature == "Indomitable")          applyIndomitableToSave (bm, ctx.reactor_idx, *ss);
    else if (opt.feature == "LegendaryResistance")  applyLegendaryResistanceToSave(bm, ctx.reactor_idx, *ss);
    else if (opt.feature == "WarGodsBlessing")      applyWarGodsBlessingToSave(bm, ctx.reactor_idx, *ss);
    else if (opt.feature == "DarkOnesOwnLuck")       applyDarkOnesOwnLuckToSave(bm, ctx.reactor_idx, *ss);
}

// ─────────────────────────────────────────────────────────────────────────────
//  OnDeclareCast window — interruptible spell casting
//  beginCast wraps executeSpell with a pre-resolution reaction window. This pass: Shield vs
//  Magic Missile (a targeted creature reacts by casting Shield → Magic Missile immunity).
// ─────────────────────────────────────────────────────────────────────────────

bool CombatEngine::canCastShield(const BattleMap& bm, int idx) const
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    if (bm.isAgentOnDeck(idx)) return false;              // On Deck reserves take no reactions until deployed
    const Agent::Conditions cond = bm.getAgentConditions(idx);
    if (cond.reaction_used || cond.incapacitated) return false;
    const Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_cur <= 0) return false;
    bool has_slot = false;
    for (int i = 0; i < 9; ++i)
        if (s.spell_slots_remaining[static_cast<std::size_t>(i)] > 0) { has_slot = true; break; }
    if (!has_slot) return false;
    for (const auto& sp : bm.getAgentSpells(idx))
        if (sp.name == "Shield") return true;
    return false;
}

bool CombatEngine::canCastCounterspell(const BattleMap& bm, int idx, int caster_idx) const
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size())) return false;
    if (idx == caster_idx) return false;                          // can't counter your own spell
    if (bm.isAgentOnDeck(idx)) return false;                      // On Deck reserves take no reactions until deployed
    if (areAllies(bm, idx, caster_idx)) return false;             // never counter a teammate's spell
    const Agent::Conditions cond = bm.getAgentConditions(idx);
    if (cond.reaction_used || cond.incapacitated) return false;
    const Agent::Stats s = bm.getAgentStats(idx);
    if (s.hp_cur <= 0) return false;
    // Must know Counterspell and be able to pay for it. NPC innate casters pay an N/day use of the
    // spell itself (they have no spell slots); slot-based casters spend an L3+ spell slot.
    bool knows = false;
    int cs_uses_max = 0, cs_uses_remaining = 0;
    for (const auto& sp : bm.getAgentSpells(idx))
        if (sp.name == "Counterspell") {
            knows = true; cs_uses_max = sp.uses_max; cs_uses_remaining = sp.uses_remaining; break;
        }
    if (!knows) return false;
    if (s.is_npc) {
        if (cs_uses_max <= 0 || cs_uses_remaining <= 0) return false;
    } else {
        bool has_slot = false;                                    // Counterspell needs an L3+ slot
        for (int i = 2; i < 9; ++i)
            if (s.spell_slots_remaining[static_cast<std::size_t>(i)] > 0) { has_slot = true; break; }
        if (!has_slot) return false;
    }
    // "when you see a creature within 60 feet casting a spell": LOS + 60 ft to the caster.
    const PlacedAgent& rpa = agents[static_cast<std::size_t>(idx)];
    const PlacedAgent& cpa = agents[static_cast<std::size_t>(caster_idx)];
    if (footprintDistance(rpa.origin, rpa.agent->getSize(),
                          cpa.origin, cpa.agent->getSize()) * 5 > 60) return false;
    if (!bm.hasLineOfSight(rpa.origin, rpa.agent->getSize(),
                           cpa.origin, cpa.agent->getSize())) return false;
    return true;
}

bool CombatEngine::canSpellThief(const BattleMap& bm, int idx, int caster_idx) const
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;
    if (caster_idx < 0 || caster_idx >= static_cast<int>(agents.size())) return false;
    if (idx == caster_idx) return false;                          // can't steal your own spell
    if (bm.isAgentOnDeck(idx)) return false;                      // On Deck reserves take no reactions until deployed
    if (areAllies(bm, idx, caster_idx)) return false;            // never steal a teammate's spell
    const Agent::Stats s = bm.getAgentStats(idx);
    if (s.character_class != CharacterClass::Rogue ||
        s.rogue_subclass != ArcaneTricksterPath || s.char_level < 17) return false;
    if (s.hp_cur <= 0) return false;
    const Agent::Conditions cond = bm.getAgentConditions(idx);
    if (cond.reaction_used || cond.incapacitated) return false;
    // "when you see a creature within 60 feet casting a spell": LOS + 60 ft to the caster (mirrors
    // canCastCounterspell). Spell Thief is a class feature, so no slot/known-spell requirement.
    const PlacedAgent& rpa = agents[static_cast<std::size_t>(idx)];
    const PlacedAgent& cpa = agents[static_cast<std::size_t>(caster_idx)];
    if (footprintDistance(rpa.origin, rpa.agent->getSize(),
                          cpa.origin, cpa.agent->getSize()) * 5 > 60) return false;
    if (!bm.hasLineOfSight(rpa.origin, rpa.agent->getSize(),
                           cpa.origin, cpa.agent->getSize())) return false;
    return true;
}

std::vector<int>
CombatEngine::declareCastReactors(const BattleMap& bm, const SpellAction& action) const
{
    std::vector<int> reactors;
    const auto& agents = bm.placedAgents();
    if (action.caster_idx < 0 || action.caster_idx >= static_cast<int>(agents.size())) return reactors;
    const auto& spells = bm.getAgentSpells(action.caster_idx);
    if (action.spell_idx < 0 || action.spell_idx >= static_cast<int>(spells.size())) return reactors;
    const std::string castName = spells[static_cast<std::size_t>(action.spell_idx)].name;

    // Counterspell reactors first — it interrupts the whole cast. Any creature (not the caster) that
    // can see the caster within 60 ft and can cast Counterspell. A Counterspell can ITSELF be
    // countered: a counter-counterspell is a nested cast on the stack, so
    // we enroll counterspellers even when castName == "Counterspell". canCastCounterspell excludes
    // i == caster, so a caster can't counter its own Counterspell.
    for (int i = 0; i < static_cast<int>(agents.size()); ++i)
        if (i != action.caster_idx && canCastCounterspell(bm, i, action.caster_idx))
            reactors.push_back(i);

    // Spell Thief (Arcane Trickster L17): an AT who sees the cast within 60 ft may try to steal it
    // (caster INT save vs the AT's DC). Enroll alongside counterspellers; dedup so an AT who also
    // knows Counterspell is offered both options in stepTopCast.
    for (int i = 0; i < static_cast<int>(agents.size()); ++i)
        if (i != action.caster_idx && canSpellThief(bm, i, action.caster_idx) &&
            std::find(reactors.begin(), reactors.end(), i) == reactors.end())
            reactors.push_back(i);

    // Then Shield: only Magic Missile opens a Shield reaction (for each distinct target that can
    // Shield). A reactor already enrolled as a counterspeller is offered both options in advanceCast.
    if (castName == "Magic Missile")
        for (int t : action.target_indices) {
            if (std::find(reactors.begin(), reactors.end(), t) != reactors.end()) continue;  // dedup
            if (canCastShield(bm, t)) reactors.push_back(t);
        }
    return reactors;
}

bool CombatEngine::applyShield(BattleMap& bm, int reactor_idx) noexcept
{
    if (!canCastShield(bm, reactor_idx)) return false;
    Agent::Stats s = bm.getAgentStats(reactor_idx);
    for (int i = 0; i < 9; ++i)                                   // spend the lowest available L1+ slot
        if (s.spell_slots_remaining[static_cast<std::size_t>(i)] > 0) {
            s.spell_slots_remaining[static_cast<std::size_t>(i)] -= 1; break;
        }
    if (!s.shield_active) { s.shield_active = true; s.ac_temporary_modifications += 5; }
    bm.setAgentStats(reactor_idx, s);
    Agent::Conditions c = bm.getAgentConditions(reactor_idx);
    c.reaction_used = true;
    bm.setAgentConditions(reactor_idx, c);
    log_("{} casts Shield (+5 AC until their next turn; immune to Magic Missile)",
         agentName(bm, reactor_idx));
    return true;
}

// Would casting Shield flip this spell-attack hit into a miss, and can the target do it right now?
// Value-based sibling of shouldOfferDefenderShield (the weapon version, which takes an AttackResult).
bool CombatEngine::shouldOfferSpellShield(const BattleMap& bm, int tgt_idx, const SpellToHit& th) const
{
    if (!th.hit || th.critical) return false;
    if (th.total_roll >= th.target_ac + 5) return false;
    return canCastShield(bm, tgt_idx);
}

// Inline defender Shield vs a spell attack (auto/RL path + GUI multi-beam). Mirrors the Shield branch
// of maybeDefenderOnHitInline (the weapon version). On a flippable hit: decide via decider_ when one is
// installed (RL/headless/tests); with no decider, AUTO-TAKE the Shield — the GUI has no per-beam
// decision cursor for multi-beam attack spells yet (known_limitations.md). On accept, applyShield then
// recompute th.hit against the new (+5) AC so the consumer sees the negated hit. The caller refetches
// the target's stats afterward (applyShield spent the target's slot + raised its AC).
bool CombatEngine::maybeDefenderShieldInlineSpell(BattleMap& bm, const SpellAction& action,
                                                  int tgt_idx, SpellToHit& th)
{
    if (!shouldOfferSpellShield(bm, tgt_idx, th)) return false;

    bool take_shield;
    if (decider_) {
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnHit;
        ctx.reactor_idx = tgt_idx;
        ctx.source_idx  = action.caster_idx;
        ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                                             "Cast Shield (+5 AC — the spell attack misses)", "Shield"});
        ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
        const ReactionResponse resp = decider_->chooseReaction(ctx);
        if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) return false;
        const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
        take_shield = (opt.kind == ReactionOption::Feature && opt.feature == "Shield");
    } else if (castActive() && topCast().interactive) {
        take_shield = true;   // GUI multi-beam: no decider + no per-beam cursor → auto-take (documented)
    } else {
        return false;         // headless/RL with no decider: no reaction (matches maybeDefenderOnHitInline)
    }
    if (!take_shield) return false;

    if (applyShield(bm, tgt_idx)) {
        th.target_ac = calculateAC(bm, tgt_idx);   // +5 from Shield is now live
        th.hit = th.critical || (th.d20 != 1 && th.total_roll >= th.target_ac);
        log_("{} casts Shield (+5 AC) — the spell attack misses!", agentName(bm, tgt_idx));
        return true;
    }
    return false;
}

bool CombatEngine::applyCounterspell(BattleMap& bm, int reactor_idx, int caster_idx) noexcept
{
    if (!canCastCounterspell(bm, reactor_idx, caster_idx)) return false;
    // Spend the counterspeller's payment + its reaction (regardless of the save outcome — Counterspell
    // itself is cast and the resource is gone; only the *countered* spell keeps its slot).
    spendCounterspellCost(bm, reactor_idx);
    // 2024 Counterspell: the original caster makes a CON save vs the counterspeller's spell save DC.
    const Agent::Stats rs = bm.getAgentStats(reactor_idx);
    const int dc = spellSaveDc(rs);
    const Agent::Stats cs = bm.getAgentStats(caster_idx);
    const int save_mod = abilityMod(cs.con) + (cs.save_prof_con ? cs.prof_bonus : 0);
    const int d20      = roll(20);
    const int total    = d20 + save_mod;
    log_("{} casts Counterspell — {} must make a DC {} CON save (rolled {}{}{} = {})",
         agentName(bm, reactor_idx), agentName(bm, caster_idx), dc,
         d20, save_mod >= 0 ? "+" : "", save_mod, total);
    if (total >= dc) {
        log_("{} succeeds — the spell resolves normally", agentName(bm, caster_idx));
        return false;
    }
    log_("{}'s spell is countered and fails (its slot is retained)", agentName(bm, caster_idx));
    return true;
}

void CombatEngine::applyCastReaction(BattleMap& bm, const ReactionCtx& ctx, const ReactionResponse& resp)
{
    if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) return;  // skip/invalid
    const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
    if (opt.kind != ReactionOption::Feature) return;
    // Counterspell is NOT handled here — it pushes a nested cast (see submitDecision / stepTopCast),
    // so a deeper Counterspell can negate it before it resolves.
    if (opt.feature == "SpellThief") {
        // Spell Thief (Arcane Trickster L17): the caster (ctx.source_idx) makes an INT save vs the
        // AT's spell save DC. The reaction is spent regardless of the outcome. On a failure the cast
        // is countered (fizzles, slot kept) AND the caster can't recast that spell until a long rest.
        if (!canSpellThief(bm, ctx.reactor_idx, ctx.source_idx)) return;
        Agent::Conditions rc = bm.getAgentConditions(ctx.reactor_idx);
        rc.reaction_used = true;
        bm.setAgentConditions(ctx.reactor_idx, rc);

        const Agent::Stats at_stats = bm.getAgentStats(ctx.reactor_idx);
        const int dc    = spellSaveDc(at_stats);
        const int total = roll(20) + saveModFor(bm, ctx.source_idx, SaveInt);
        // Resolve the spell name from the in-flight cast (ctx.spell_idx on the caster's list).
        std::string castName;
        const auto& spells = bm.getAgentSpells(ctx.source_idx);
        if (ctx.spell_idx >= 0 && ctx.spell_idx < static_cast<int>(spells.size()))
            castName = spells[static_cast<std::size_t>(ctx.spell_idx)].name;
        if (total >= dc) {
            log_("Spell Thief: {} succeeds on the INT save ({} vs DC {}) — the spell is not stolen",
                 agentName(bm, ctx.source_idx), total, dc);
        } else {
            if (castActive()) topCast().countered = true;       // fizzle the cast (slot kept), like Counterspell
            if (!castName.empty()) {
                Agent::Stats cs = bm.getAgentStats(ctx.source_idx);
                if (!cs.spellIsStolen(castName)) {
                    cs.stolen_spell_names.push_back(castName);
                    bm.setAgentStats(ctx.source_idx, cs);
                }
            }
            log_("Spell Thief: {} fails the INT save ({} vs DC {}) — {} steals {} (it can't be recast "
                 "until a long rest)", agentName(bm, ctx.source_idx), total, dc,
                 agentName(bm, ctx.reactor_idx), castName);
        }
        return;
    }
    if (opt.feature == "Shield") {
        if (applyShield(bm, ctx.reactor_idx) && ctx.window == ReactionWindow::OnHit &&
            topCast().has_preroll && topCast().preroll_target == ctx.reactor_idx) {
            // Spell-attack OnHit window: recompute the pre-rolled to-hit against the new (+5) AC so
            // executeSpell consumes the negated hit (the OnDeclareCast Magic-Missile Shield needs no
            // recompute — that immunity is handled by shield_active inside executeSpell).
            SpellToHit& p = topCast().preroll;
            p.target_ac = calculateAC(bm, ctx.reactor_idx);
            p.hit = p.critical || (p.d20 != 1 && p.total_roll >= p.target_ac);
            log_("{} casts Shield (+5 AC) — the spell attack misses!", agentName(bm, ctx.reactor_idx));
        }
    }
}

int CombatEngine::agentSpellIndex(const BattleMap& bm, int idx, const std::string& name) const
{
    const auto& spells = bm.getAgentSpells(idx);
    for (int i = 0; i < static_cast<int>(spells.size()); ++i)
        if (spells[static_cast<std::size_t>(i)].name == name) return i;
    return -1;
}

bool CombatEngine::isCounterspellChoice(const ReactionCtx& ctx, const ReactionResponse& resp) const
{
    if (resp.option < 0 || resp.option >= static_cast<int>(ctx.options.size())) return false;
    const ReactionOption& opt = ctx.options[static_cast<std::size_t>(resp.option)];
    return opt.kind == ReactionOption::Feature && opt.feature == "Counterspell";
}

// Spend the cost of casting Counterspell for this reactor and mark its reaction used. NPC innate
// casters pay an N/day use of their Counterspell spell (they hold no spell slots); slot-based casters
// spend their lowest L3+ slot. (Eligibility was validated by canCastCounterspell.)
void CombatEngine::spendCounterspellCost(BattleMap& bm, int reactor) noexcept
{
    PlacedAgent& pa = bm.placedAgentMut(reactor);
    Agent::Stats& s = pa.agent->getStats();
    if (s.is_npc) {
        for (auto& sp : pa.spells)
            if (sp.name == "Counterspell" && sp.uses_max > 0) {
                sp.uses_remaining = std::max(0, sp.uses_remaining - 1); break;
            }
    } else {
        for (int i = 2; i < 9; ++i)
            if (s.spell_slots_remaining[static_cast<std::size_t>(i)] > 0) {
                s.spell_slots_remaining[static_cast<std::size_t>(i)] -= 1; break;
            }
    }
    Agent::Conditions rc = bm.getAgentConditions(reactor);
    rc.reaction_used = true;
    bm.setAgentConditions(reactor, rc);
}

void CombatEngine::castCounterspell(BattleMap& bm, int reactor, int /*target_caster*/) noexcept
{
    // Declaration only: spend the counterspeller's payment + its reaction. The CON save is deferred to
    // resolveCounterspellEffect (pop time) so a deeper Counterspell can negate this one first.
    // (canCastCounterspell was already validated at enumeration/choice time.)
    spendCounterspellCost(bm, reactor);
    log_("{} casts Counterspell, interrupting the spell", agentName(bm, reactor));
}

void CombatEngine::pushCounterspell(BattleMap& bm, int reactor, int target_caster)
{
    // Synthesize a Counterspell SpellAction so the existing castName/canCastCounterspell machinery
    // keeps working, then push it as a nested in-flight cast targeting the parent's caster.
    SpellAction csa{};
    csa.caster_idx     = reactor;
    csa.spell_idx      = agentSpellIndex(bm, reactor, "Counterspell");
    csa.target_indices = { target_caster };
    InFlightCast child{};
    child.active                = true;
    child.interactive           = !cast_stack_.empty() && cast_stack_.back().interactive;  // inherit driver
    child.action                = csa;
    child.is_counterspell       = true;
    child.counter_target_caster = target_caster;
    child.reactors              = declareCastReactors(bm, csa);     // who can counter THIS counterspell
    cast_stack_.push_back(std::move(child));                        // ⚠ any prior back() ref now invalid
}

void CombatEngine::resolveCounterspellEffect(BattleMap& bm, InFlightCast& c)
{
    const int reactor = c.action.caster_idx;             // the counterspeller
    const int target  = c.counter_target_caster;         // the caster being countered
    const Agent::Stats rs = bm.getAgentStats(reactor);
    const int dc = spellSaveDc(rs);
    const Agent::Stats cs = bm.getAgentStats(target);
    const int save_mod = abilityMod(cs.con) + (cs.save_prof_con ? cs.prof_bonus : 0);
    const int d20 = roll(20), total = d20 + save_mod;
    log_("{} must make a DC {} CON save vs Counterspell (rolled {}{}{} = {})",
         agentName(bm, target), dc, d20, save_mod >= 0 ? "+" : "", save_mod, total);
    if (total >= dc) { log_("{} resists — the spell resolves", agentName(bm, target)); return; }
    log_("{}'s spell is countered and fails (its slot is retained)", agentName(bm, target));
    if (cast_stack_.size() >= 2)                          // mark the PARENT (directly below) countered
        cast_stack_[cast_stack_.size() - 2].countered = true;
}

// One step of cast_stack_.back() through its windows. Operates on a re-fetched back() reference and
// NEVER touches it after a push_back (which would dangle it) — the Counterspell branch captures all
// values it needs before pushing, then returns Pushed immediately.
CombatEngine::CastStep CombatEngine::stepTopCast(BattleMap& bm)
{
    InFlightCast& c = cast_stack_.back();
    const auto& agents = bm.placedAgents();
    std::string castName;                                            // the spell being cast (for option gating)
    if (c.action.caster_idx >= 0 && c.action.caster_idx < static_cast<int>(agents.size())) {
        const auto& spells = bm.getAgentSpells(c.action.caster_idx);
        if (c.action.spell_idx >= 0 && c.action.spell_idx < static_cast<int>(spells.size()))
            castName = spells[static_cast<std::size_t>(c.action.spell_idx)].name;
    }
    while (c.cursor < c.reactors.size() && !c.countered) {
        const int reactor = c.reactors[c.cursor];
        ReactionCtx ctx;
        ctx.window       = ReactionWindow::OnDeclareCast;
        ctx.reactor_idx  = reactor;
        ctx.source_idx   = c.action.caster_idx;
        ctx.spell_idx    = c.action.spell_idx;
        // Build this reactor's options fresh (eligibility may have changed since enumeration). A
        // reactor can be offered both Counterspell and Shield when both apply. A Counterspell can now
        // itself be countered, so the option is offered regardless of castName.
        if (canCastCounterspell(bm, reactor, c.action.caster_idx))
            ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                "Cast Counterspell vs " + agentName(bm, c.action.caster_idx) + "'s " + castName,
                "Counterspell"});
        if (canSpellThief(bm, reactor, c.action.caster_idx))
            ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                "Spell Thief: steal " + agentName(bm, c.action.caster_idx) + "'s " + castName +
                " (it makes an INT save)", "SpellThief"});
        if (castName == "Magic Missile" && canCastShield(bm, reactor) &&
            std::find(c.action.target_indices.begin(), c.action.target_indices.end(), reactor)
                != c.action.target_indices.end())
            ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                                                 "Cast Shield (+5 AC, immune to Magic Missile)", "Shield"});
        if (ctx.options.empty()) { ++c.cursor; continue; }           // lost eligibility since enumeration
        ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
        if (c.interactive) {
            pending_decision_ = PendingDecision{true, ctx};         // suspend; GUI resumes via submitDecision
            return CastStep::Awaiting;
        }
        const ReactionResponse resp = decider_ ? decider_->chooseReaction(ctx) : ReactionResponse{};
        // Counterspell → push a nested cast (defensive depth cap backstops the economy bound).
        if (isCounterspellChoice(ctx, resp) && cast_stack_.size() <= agents.size()) {
            const int target_caster = c.action.caster_idx;           // capture BEFORE the push (c dangles after)
            ++c.cursor;                                              // this reactor is handled in the parent
            castCounterspell(bm, reactor, target_caster);
            pushCounterspell(bm, reactor, target_caster);
            return CastStep::Pushed;                                 // ⚠ do NOT touch c after this
        }
        applyCastReaction(bm, ctx, resp);
        ++c.cursor;
    }

    // ── Single-target spell-attack OnHit Shield window (GUI suspend) ──
    // Once the OnDeclareCast windows close (and the cast wasn't countered), a single-target AttackRoll
    // spell pre-rolls its to-hit here so the target can react with Shield — the spell analog of
    // beginAttack's OnHit window. Only for the interactive (GUI) path and only when the target can
    // actually cast Shield (so the common no-Shield cast still rolls inside executeSpell, in order).
    // The auto/RL path and GUI multi-beam attack spells use maybeDefenderShieldInlineSpell instead.
    // A Counterspell cast is not an AttackRoll spell, so this window self-skips for it.
    if (c.interactive && !c.countered && !c.attack_window_done) {
        c.attack_window_done = true;                                 // evaluate the window at most once
        int  single_target   = (c.action.target_indices.size() == 1) ? c.action.target_indices[0] : -1;
        bool is_attack_spell = false;
        if (single_target >= 0 && c.action.caster_idx >= 0 &&
            c.action.caster_idx < static_cast<int>(agents.size())) {
            const auto& spells = bm.getAgentSpells(c.action.caster_idx);
            if (c.action.spell_idx >= 0 && c.action.spell_idx < static_cast<int>(spells.size()))
                is_attack_spell = (spells[static_cast<std::size_t>(c.action.spell_idx)].attack_type
                                   == Spell::AttackRoll);
        }
        if (is_attack_spell && canCastShield(bm, single_target)) {
            c.preroll        = rollSpellAttack(bm, c.action, single_target, MetamagicNone);
            c.has_preroll    = true;                                 // executeSpell consumes this roll
            c.preroll_target = single_target;
            if (shouldOfferSpellShield(bm, single_target, c.preroll)) {
                ReactionCtx ctx;
                ctx.window      = ReactionWindow::OnHit;
                ctx.reactor_idx = single_target;
                ctx.source_idx  = c.action.caster_idx;
                ctx.spell_idx   = c.action.spell_idx;
                ctx.options.push_back(ReactionOption{ReactionOption::Feature, -1,
                                                     "Cast Shield (+5 AC — the spell attack misses)", "Shield"});
                ctx.options.push_back(ReactionOption{ReactionOption::Skip, -1, "Skip", ""});
                pending_decision_ = PendingDecision{true, ctx};     // suspend; GUI resumes via submitDecision
                return CastStep::Awaiting;
            }
        }
    }

    // ── OnSaveFail window: pre-roll a directly-targeted Save spell's saves and let
    // creatures reroll a FAILURE → possible success (Countercharm / Indomitable). Runs for BOTH drivers
    // (interactive suspends; auto resolves inline via the decider, like the OnDeclareCast loop above).
    // AoE-geometry save spells (cone/cube/sphere) are deferred — their target list is resolved inside
    // executeSpell, so only Single/Multiple geometry (targets == action.target_indices) is pre-rolled (§8).
    // A Counterspell cast is not a Save spell, so this window self-skips for it.
    if (!c.countered && !c.save_window_built) {
        c.save_window_built = true;
        bool is_save_spell = false;
        if (c.action.caster_idx >= 0 && c.action.caster_idx < static_cast<int>(agents.size())) {
            const auto& spells = bm.getAgentSpells(c.action.caster_idx);
            if (c.action.spell_idx >= 0 && c.action.spell_idx < static_cast<int>(spells.size())) {
                const Spell& sp = spells[static_cast<std::size_t>(c.action.spell_idx)];
                is_save_spell = (sp.attack_type == Spell::Save) &&
                                (sp.geometry == Spell::Single || sp.geometry == Spell::Multiple);
            }
        }
        if (is_save_spell) {
            for (int tgt : c.action.target_indices)
                c.save_prerolls.push_back(rollSpellSave(bm, c.action, tgt, c.action.metamagic));
            c.has_save_preroll = true;                              // executeSpell consumes these
            for (const SpellSave& ss : c.save_prerolls)
                for (int reactor : saveFailReactors(bm, c.action, ss))
                    c.savefail_pairs.emplace_back(ss.target_idx, reactor);
        }
    }
    while (c.savefail_cursor < c.savefail_pairs.size()) {
        const int save_target = c.savefail_pairs[c.savefail_cursor].first;
        const int reactor     = c.savefail_pairs[c.savefail_cursor].second;
        SpellSave* ss = nullptr;
        for (auto& p : c.save_prerolls) if (p.target_idx == save_target) { ss = &p; break; }
        // Re-gate: an earlier reaction may have flipped this save to a success or spent the resource.
        auto opts = (ss && !ss->saved) ? saveFailOptions(bm, reactor, c.action, *ss)
                                       : std::vector<ReactionOption>{};
        if (opts.size() <= 1) { ++c.savefail_cursor; continue; }   // only Skip / nothing left to offer
        ReactionCtx ctx;
        ctx.window      = ReactionWindow::OnSaveFail;
        ctx.reactor_idx = reactor;
        ctx.source_idx  = save_target;                             // the creature that failed the save
        ctx.spell_idx   = c.action.spell_idx;
        ctx.d20_value   = ss->total;
        ctx.options     = opts;
        if (c.interactive) {
            pending_decision_ = PendingDecision{true, ctx};        // suspend; GUI resumes via submitDecision
            return CastStep::Awaiting;
        }
        applySaveFailReaction(bm, ctx, decider_ ? decider_->chooseReaction(ctx) : ReactionResponse{});
        ++c.savefail_cursor;
    }

    return CastStep::Completed;
}

// Resolve cast_stack_.back() and pop it. No push happens in here, so the reference stays valid.
void CombatEngine::finalizeAndPop(BattleMap& bm)
{
    InFlightCast& c = cast_stack_.back();
    if (c.is_counterspell) {
        if (!c.countered)                                 // not itself countered → it works
            resolveCounterspellEffect(bm, c);             // deferred CON save → maybe mark parent .countered
        // a counterspell yields no SpellResult of interest
    } else if (!c.countered) {
        c.result = executeSpell(bm, c.action);            // normal resolution (slot spent inside, late)
    }
    c.active = false;
    const bool bottom = (cast_stack_.size() == 1);
    const SpellResult r = c.result;
    const bool cnt = c.countered;
    cast_stack_.pop_back();
    if (bottom) { last_cast_result_ = r; last_cast_countered_ = cnt; }
}

FlowStatus CombatEngine::advanceCast(BattleMap& bm)
{
    while (!cast_stack_.empty()) {
        const CastStep st = stepTopCast(bm);               // runs back()'s windows; may push/suspend
        if (st == CastStep::Awaiting) return FlowStatus::AwaitingDecision;  // GUI suspend
        if (st == CastStep::Pushed)   continue;            // a counterspell went on top → loop to it
        finalizeAndPop(bm);                                // Completed → resolve + pop back()
    }
    pending_decision_.active = false;
    return FlowStatus::Completed;
}

FlowStatus CombatEngine::beginCast(BattleMap& bm, const SpellAction& action)
{
    cast_stack_.clear();
    InFlightCast c{};
    c.active      = true;
    c.interactive = true;
    c.action      = action;
    c.reactors    = declareCastReactors(bm, action);
    cast_stack_.push_back(std::move(c));
    return advanceCast(bm);
}

SpellResult CombatEngine::resolveCast(BattleMap& bm, const SpellAction& action)
{
    cast_stack_.clear();
    InFlightCast c{};
    c.active      = true;
    c.interactive = false;                                 // auto driver: resolve each checkpoint inline
    c.action      = action;
    c.reactors    = declareCastReactors(bm, action);
    cast_stack_.push_back(std::move(c));
    (void)advanceCast(bm);
    return last_cast_result_;                              // snapshot, set when the bottom popped
}

} // namespace rpg
