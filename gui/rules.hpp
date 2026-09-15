#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  rules.hpp – pure D&D 5e rules primitives, free of CombatEngine
// ─────────────────────────────────────────────────────────────────────────────
//
//  R3 of COMBAT_REFACTOR_PLAN.md. combat_core.cpp's dice/modifier/AC/save/aura
//  primitives, lifted out as free functions in namespace rpg::rules. This is
//  the "950-in / 7-out sink" the plan's call-graph measurement found: nearly
//  every combat_*.cpp TU calls into these, and they call almost nothing back.
//  Header-only + `inline`, matching combat_internal.hpp's existing convention
//  for helpers shared across the combat_*.cpp translation units — no dedicated
//  .cpp, no CMakeLists.txt change.
//
//  Every function here takes `(const BattleMap&, ...)` and, only where a die is
//  actually rolled, a `CombatContext&` for rng_/logger_/the pending-roll state.
//  That's what makes them unit-testable with no CombatEngine and no map image.
//
//  Sequencing (per the plan): this header lands additively. CombatEngine's
//  methods in combat_core.cpp become one-line forwarders to these; nothing
//  else changes behavior. Migrating the ~950 call sites to call rules::
//  directly, and deleting the forwarders, is later, incremental, TU-by-TU
//  work — never a single sweep.
//
//  areAllies' team-check is duplicated here (2 lines) rather than depending on
//  CombatEngine::areAllies (combat_visibility.cpp), which needs a live engine
//  instance for no real reason (it only reads bm.getAgentFaction). Dedupe when
//  R4 extracts VisibilityService.
// ─────────────────────────────────────────────────────────────────────────────

#include "battle_map.hpp"
#include "combat_context.hpp"
#include "combat_internal.hpp"   // dndMod

#include <algorithm>
#include <cassert>
#include <format>
#include <random>
#include <string>

namespace rpg::rules {

// ─────────────────────────────────────────────────────────────────────────────
//  Dice & RNG
// ─────────────────────────────────────────────────────────────────────────────

inline int roll(CombatContext& ctx, int sides, int modifier = 0)
{
    assert(sides >= 2 && "Die must have at least 2 sides");
    // One-shot advantage/disadvantage applies only to d20 Tests (damage dice ignore it).
    const int adv = (sides == 20) ? ctx.consumePendingAdvantage() : 0;

    // Portent Dice: if pending, return it instead of rolling (and clear).
    if (ctx.pending_portent_die_ >= 0) {
        int result = ctx.pending_portent_die_;
        ctx.pending_portent_die_ = -1;
        return result + modifier + ctx.consumePendingRollBonus();
    }

    std::uniform_int_distribution<int> d{1, sides};
    int die;
    if (adv > 0)      die = std::max(d(ctx.rng_), d(ctx.rng_));   // advantage
    else if (adv < 0) die = std::min(d(ctx.rng_), d(ctx.rng_));   // disadvantage
    else              die = d(ctx.rng_);
    return die + modifier + ctx.consumePendingRollBonus();
}

inline int rollAdvantage(CombatContext& ctx, int sides, int modifier = 0)
{
    // Check if portent die is pending (need to apply after advantage logic).
    int pending_portent = ctx.pending_portent_die_;
    if (pending_portent >= 0) {
        ctx.pending_portent_die_ = -1;  // Consume it now
    }
    // Capture the Bardic bonus before the inner rolls so they don't consume it
    // mid-selection; it is added once after max().
    int roll_bonus = ctx.consumePendingRollBonus();
    // Consume any pending one-shot advantage/disadvantage up front so the inner roll()s don't
    // re-trigger it. A pending disadvantage cancels this explicit advantage (roll straight).
    const int pa = (sides == 20) ? ctx.consumePendingAdvantage() : 0;

    int result = (pa < 0) ? roll(ctx, sides) : std::max(roll(ctx, sides), roll(ctx, sides));

    // Apply portent die if one was pending (after advantage selection).
    if (pending_portent >= 0) {
        if (ctx.logger_)
            ctx.logger_->log(std::format("Portent Die: replacing roll {} with {}", result, pending_portent));
        result = pending_portent;
    }

    // Flat modifier + Bardic bonus added once, after die selection / portent replacement.
    return result + modifier + roll_bonus;
}

inline int rollDisadvantage(CombatContext& ctx, int sides, int modifier = 0)
{
    // Check if portent die is pending (need to apply after disadvantage logic).
    int pending_portent = ctx.pending_portent_die_;
    if (pending_portent >= 0) {
        ctx.pending_portent_die_ = -1;  // Consume it now
    }
    // Capture the Bardic bonus before the inner rolls so they don't consume it
    // mid-selection; it is added once after min().
    int roll_bonus = ctx.consumePendingRollBonus();
    // Consume any pending one-shot advantage/disadvantage up front. A pending advantage
    // cancels this explicit disadvantage (roll straight).
    const int pa = (sides == 20) ? ctx.consumePendingAdvantage() : 0;

    int result = (pa > 0) ? roll(ctx, sides) : std::min(roll(ctx, sides), roll(ctx, sides));

    // Apply portent die if one was pending (after disadvantage selection).
    if (pending_portent >= 0) {
        if (ctx.logger_)
            ctx.logger_->log(std::format("Portent Die: replacing roll {} with {}", result, pending_portent));
        result = pending_portent;
    }

    // Flat modifier + Bardic bonus added once, after die selection / portent replacement.
    return result + modifier + roll_bonus;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Modifiers
// ─────────────────────────────────────────────────────────────────────────────

inline int attackModifier(const Weapon& w, const Agent::Stats& s) noexcept
{
    int base;
    if (w.finesse)
        base = std::max(abilityMod(s.str), abilityMod(s.dex));
    else if (w.thrown || w.type == WeaponType::Melee)
        base = abilityMod(s.str);
    else
        base = abilityMod(s.dex);

    // Pact of the Blade: the Warlock may use Charisma instead of STR/DEX for the
    // pact weapon's attack rolls (modeled as "whichever is best" — never worse).
    if (w.pact_weapon)
        base = std::max(base, abilityMod(s.cha));

    // Archery fighting style: +2 to attack rolls with Ranged weapons (not thrown
    // melee weapons, which are Melee-type with the Thrown property).
    if (w.type == WeaponType::Ranged && !w.thrown && s.hasFeat("Archery"))
        base += 2;

    return base + (w.proficient ? s.prof_bonus : 0);
}

inline int damageAbilityMod(const Weapon& w, const Agent::Stats& s) noexcept
{
    int base;
    if (w.finesse)
        base = std::max(abilityMod(s.str), abilityMod(s.dex));
    else if (w.thrown || w.type == WeaponType::Melee)
        base = abilityMod(s.str);
    else
        base = abilityMod(s.dex);

    // Pact of the Blade: CHA option for the pact weapon's damage rolls (never worse).
    if (w.pact_weapon)
        base = std::max(base, abilityMod(s.cha));

    return base;
}

inline int spellAttackMod(const Agent::Stats& s) noexcept
{
    auto abilityScore = [&]() -> int {
        switch (s.spellcasting_ability) {
            case 0: return s.str;
            case 1: return s.dex;
            case 2: return s.con;
            case 3: return s.intel;
            case 4: return s.wis;
            default: return s.cha;
        }
    }();
    int m = (abilityScore - 10) / 2;
    if (abilityScore < 10 && (abilityScore - 10) % 2 != 0) --m;
    return s.prof_bonus + m;
}

inline int spellSaveDc(const Agent::Stats& s) noexcept
{
    // Sorcerer Innate Sorcery: +1 to spell save DC while active.
    int innate = (s.innate_sorcery_turns > 0) ? 1 : 0;
    return 8 + spellAttackMod(s) + innate;
}

inline int spellSaveDcFromAbility(const Agent::Stats& s, SaveAbility_t ability) noexcept
{
    auto abilityScore = [&]() -> int {
        switch (ability) {
            case SaveStr:  return s.str;
            case SaveDex:  return s.dex;
            case SaveCon:  return s.con;
            case SaveInt:  return s.intel;
            case SaveWis:  return s.wis;
            default:              return s.cha;
        }
    }();
    int m = (abilityScore - 10) / 2;
    if (abilityScore < 10 && (abilityScore - 10) % 2 != 0) --m;
    // Sorcerer Innate Sorcery: +1 to spell save DC while active.
    int innate = (s.innate_sorcery_turns > 0) ? 1 : 0;
    return 8 + s.prof_bonus + m + innate;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Armor Class
// ─────────────────────────────────────────────────────────────────────────────

inline int calculateAC(const BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return 10;  // default AC

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];

    // Check if any armor is equipped.
    bool has_armor = false;
    for (const auto& piece : pa.armor) {
        if (!piece.name.empty()) {
            has_armor = true;
            break;
        }
    }

    // Barbarian Unarmored Defense: AC = 10 + DEX + CON (no armor worn).
    if (pa.agent->getStats().hasClass(CharacterClass::Barbarian) && !has_armor) {
        int dex_mod = (pa.agent->getStats().dex - 10) / 2;
        int con_mod = (pa.agent->getStats().con - 10) / 2;
        int ac = 10 + dex_mod + con_mod;

        for (const Weapon& shield : pa.weapons) {
            if (shield.is_shield || shield.name.find("Shield") != std::string::npos || shield.off_hand) {
                ac += shield.ac_bonus;
                break;
            }
        }
        ac += pa.agent->getStats().ac_temporary_modifications;
        return ac;
    }

    // Monk Unarmored Defense: AC = 10 + DEX + WIS (no armor worn).
    if (pa.agent->getStats().hasClass(CharacterClass::Monk) && !has_armor) {
        int dex_mod = (pa.agent->getStats().dex - 10) / 2;
        int wis_mod = (pa.agent->getStats().wis - 10) / 2;
        int ac = 10 + dex_mod + wis_mod;

        for (const Weapon& shield : pa.weapons) {
            if (shield.is_shield || shield.name.find("Shield") != std::string::npos || shield.off_hand) {
                ac += shield.ac_bonus;
                break;
            }
        }
        ac += pa.agent->getStats().ac_temporary_modifications;
        return ac;
    }

    // College of Dance Bard (L3+) Unarmored Defense: AC = 10 + DEX + CHA (no armor worn).
    if (pa.agent->getStats().hasClass(CharacterClass::Bard) &&
        pa.agent->getStats().bard_subclass == BardCollege::DancePath &&
        pa.agent->getStats().classLevel(CharacterClass::Bard) >= 3 && !has_armor) {
        int dex_mod = (pa.agent->getStats().dex - 10) / 2;
        int cha_mod = (pa.agent->getStats().cha - 10) / 2;
        int ac = 10 + dex_mod + cha_mod;

        for (const Weapon& shield : pa.weapons) {
            if (shield.is_shield || shield.name.find("Shield") != std::string::npos || shield.off_hand) {
                ac += shield.ac_bonus;
                break;
            }
        }
        ac += pa.agent->getStats().ac_temporary_modifications;
        return ac;
    }

    // Draconic Sorcerer (L3+) Draconic Resilience: AC = 10 + DEX + CHA (no armor worn).
    if (pa.agent->getStats().hasClass(CharacterClass::Sorcerer) &&
        pa.agent->getStats().sorcerer_subclass == SorcererSubclass::DraconicPath &&
        pa.agent->getStats().classLevel(CharacterClass::Sorcerer) >= 3 && !has_armor) {
        int dex_mod = (pa.agent->getStats().dex - 10) / 2;
        int cha_mod = (pa.agent->getStats().cha - 10) / 2;
        int ac = 10 + dex_mod + cha_mod;

        for (const Weapon& shield : pa.weapons) {
            if (shield.is_shield || shield.name.find("Shield") != std::string::npos || shield.off_hand) {
                ac += shield.ac_bonus;
                break;
            }
        }
        ac += pa.agent->getStats().ac_temporary_modifications;
        return ac;
    }

    // Armor of Shadows invocation (code 5): the Warlock keeps Mage Armor up at all
    // times (free, no slot), so model it as unarmored defense AC = 13 + DEX when no
    // armor is worn. Mage Armor does not cap DEX.
    if (pa.agent->getStats().hasClass(CharacterClass::Warlock) &&
        pa.agent->getStats().hasInvocation(5) && !has_armor) {
        int dex_mod = (pa.agent->getStats().dex - 10) / 2;
        int ac = 13 + dex_mod;

        for (const Weapon& shield : pa.weapons) {
            if (shield.is_shield || shield.name.find("Shield") != std::string::npos || shield.off_hand) {
                ac += shield.ac_bonus;
                break;
            }
        }
        ac += pa.agent->getStats().ac_temporary_modifications;
        return ac;
    }

    // Standard AC calculation (non-Barbarian/Monk or wearing armor).
    int ac = pa.agent->getStats().base_ac;

    // base_ac carries two conventions depending on origin:
    //   · PCs (is_npc == false): base_ac is the PRE-DEX armor base entered in the GUI
    //     stat dialog (e.g. 11 for leather). DEX, armor-piece bonuses, shield, and the
    //     defensive fighting styles/feats are layered on here.
    //   · NPCs / monsters (is_npc == true): base_ac is the FINAL published AC from the
    //     stat block, with DEX/armor/shield already folded in. Re-adding any of them
    //     would double-count, so the whole layering block is skipped for NPCs — only
    //     transient ac_temporary_modifications (Shield spell, acid, etc.) apply below.
    if (!pa.agent->getStats().is_npc) {
        int dex_mod = (pa.agent->getStats().dex - 10) / 2;
        int dex_mod_cap = 30;  // Default: no cap (light armor/unarmored)

        for (const auto& piece : pa.armor) {
            if (!piece.name.empty()) {
                dex_mod_cap = std::min(dex_mod_cap, piece.dex_mod_cap);
            }
        }

        // Medium Armor Master (general feat) — while wearing Medium armor, the DEX bonus to AC may be
        // as high as +3 instead of the usual +2. Medium armor is the equipped set whose most restrictive
        // cap is 2 (heavy armor's cap is 0 and is left unchanged).
        if (dex_mod_cap == 2 && pa.agent->getStats().hasFeat("Medium Armor Master"))
            dex_mod_cap = 3;

        int capped_dex_mod = std::min(dex_mod, dex_mod_cap);
        ac += capped_dex_mod;

        for (const auto& piece : pa.armor) {
            if (!piece.name.empty()) {
                ac += piece.ac_bonus;
            }
        }

        for (const Weapon& shield : pa.weapons) {
            if (shield.is_shield || shield.name.find("Shield") != std::string::npos || shield.off_hand) {
                ac += shield.ac_bonus;
                break;
            }
        }

        // Defense fighting style: +1 AC while wearing armor (the unarmored Barbarian/Monk
        // branches above return early, so this correctly applies only with armor on).
        if (has_armor && pa.agent->getStats().hasFeat("Defense"))
            ac += 1;

        // Dual Wielder (general feat) — Enhanced Dual Wielding grants +1 AC while wielding a melee
        // weapon in each hand (the main-hand and off-hand slots both hold a real, non-Shield melee
        // weapon). The off-hand bonus attack itself is already modeled via the off_hand weapon flag.
        if (pa.agent->getStats().hasFeat("Dual Wielder")) {
            auto is_melee_weapon = [](const Weapon& w) {
                return w.type == WeaponType::Melee && !w.is_shield &&
                       w.name.find("Shield") == std::string::npos &&
                       (!w.physicalDamageRolls.empty() || !w.magicDamageRolls.empty());
            };
            const auto& ws = pa.weapons;
            if (ws.size() >= 2 && is_melee_weapon(ws[0]) && is_melee_weapon(ws[1]))
                ac += 1;
        }
    }

    // Add temporary modifications (apply to PCs and NPCs alike — Shield spell, acid, etc.)
    ac += pa.agent->getStats().ac_temporary_modifications;

    return ac;
}

inline bool isHoldingShield(const BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return false;
    for (const Weapon& w : agents[static_cast<std::size_t>(agent_idx)].weapons) {
        if (w.is_shield || (!w.name.empty() && w.name.find("Shield") != std::string::npos))
            return true;
    }
    return false;
}

inline bool canEquipArmor(const BattleMap& bm, int agent_idx, const Armor& armor) noexcept
{
    // If armor has no STR requirement, it can always be equipped.
    if (!armor.requires_strength)
        return true;

    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size())
        return false;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];
    return pa.agent->getStats().str >= armor.str_requirement;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Paladin / advantage auras (team-scoped emanations)
// ─────────────────────────────────────────────────────────────────────────────

// Same-team-or-self check, duplicated from CombatEngine::areAllies (combat_visibility.cpp) —
// see the file header note on why this isn't a shared call.
inline bool alliedFactions(const BattleMap& bm, int a_idx, int b_idx) noexcept
{
    if (a_idx == b_idx) return true;
    int fa = bm.getAgentFaction(a_idx);
    int fb = bm.getAgentFaction(b_idx);
    return fa != 0 && fa == fb;
}

inline int bestPaladinAura(const BattleMap& bm, int agent_idx, int min_level,
                            PaladinOath require_oath = PaladinOathNone) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size()) return 0;
    const PlacedAgent& self_pa = agents[static_cast<std::size_t>(agent_idx)];
    const int self_size = self_pa.agent->getSize();

    int best = 0;
    for (int p = 0; p < static_cast<int>(agents.size()); ++p) {
        const PlacedAgent& ppa = agents[static_cast<std::size_t>(p)];
        const Agent::Stats& ps = ppa.agent->getStats();
        if (ps.lacksClass(CharacterClass::Paladin) || ps.classLevel(CharacterClass::Paladin) < min_level) continue;
        // Oath-specific auras (e.g. Aura of Warding) emanate only from a Paladin of that oath.
        if (require_oath != PaladinOathNone && ps.paladin_oath != require_oath) continue;
        // The aura emanates only from a conscious Paladin.
        if (ps.hp_cur <= 0) continue;
        const Agent::Conditions& pc = ppa.agent->getConditions();
        if (pc.unconscious || pc.incapacitated) continue;
        // The Paladin always benefits from its own aura; others must be same-team allies.
        if (p != agent_idx && !alliedFactions(bm, agent_idx, p)) continue;
        const int radius_ft = (ps.classLevel(CharacterClass::Paladin) >= 18) ? 30 : 10;
        const int d = footprintDistance(self_pa.origin, self_size,
                                        ppa.origin, ppa.agent->getSize());
        if (d * 5 > radius_ft) continue;
        // An aura is an Emanation, and an Emanation is blocked by Total Cover: standing on the
        // far side of a wall from the Paladin puts you outside the aura even when you're close.
        if (p != agent_idx &&
            !bm.hasLineOfSight(ppa.origin, ppa.agent->getSize(), self_pa.origin, self_size))
            continue;
        best = std::max(best, std::max(1, dndMod(ps.cha)));
    }
    return best;
}

inline int auraSaveBonus(const BattleMap& bm, int agent_idx) noexcept
{
    return bestPaladinAura(bm, agent_idx, 6);   // Aura of Protection (L6+)
}

inline bool hasAuraOfCourage(const BattleMap& bm, int agent_idx) noexcept
{
    return bestPaladinAura(bm, agent_idx, 10) > 0;   // Aura of Courage (L10+)
}

inline bool hasAuraOfWarding(const BattleMap& bm, int agent_idx) noexcept
{
    // Oath of the Ancients L7+ Aura of Warding: Resistance to Necrotic/Psychic/Radiant in the aura.
    return bestPaladinAura(bm, agent_idx, 7, OathOfAncientsPath) > 0;
}

inline bool hasAuraOfAlacrity(const BattleMap& bm, int agent_idx) noexcept
{
    // Oath of Glory L7+ Aura of Alacrity: +10 ft Speed while in the aura (self always qualifies).
    return bestPaladinAura(bm, agent_idx, 7, OathOfGloryPath) > 0;
}

inline bool hasAdvantageAura(const BattleMap& bm, int agent_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size()) return false;
    const PlacedAgent& self_pa = agents[static_cast<std::size_t>(agent_idx)];

    for (const ActiveSpellEffect& eff : bm.activeSpellEffects()) {
        if (!eff.spell.grants_advantage_aura) continue;

        const int src = eff.caster_idx;
        if (src < 0 || static_cast<std::size_t>(src) >= agents.size()) continue;

        // The emanation radiates only from a conscious caster (mirrors the Paladin aura).
        const PlacedAgent& src_pa = agents[static_cast<std::size_t>(src)];
        if (src_pa.agent->getStats().hp_cur <= 0) continue;
        const Agent::Conditions& sc = src_pa.agent->getConditions();
        if (sc.unconscious || sc.incapacitated) continue;

        // The caster always benefits from its own aura; everyone else must be a same-team ally.
        if (agent_idx != src && !alliedFactions(bm, agent_idx, src)) continue;

        // Euclidean emanation radius (cell distance × 5 ft), matching Spirit Guardians / Zealous
        // Presence. Compared as integer squared feet to avoid floating point. Reads the caster's
        // live origin, so the aura follows them with no extra bookkeeping.
        const int dx = self_pa.origin.col - src_pa.origin.col;
        const int dy = self_pa.origin.row - src_pa.origin.row;
        const int dist_sq_ft = (dx * dx + dy * dy) * 25;     // (cells*5)^2 = cells^2 * 25
        if (dist_sq_ft > eff.spell.radius * eff.spell.radius) continue;
        // Blocked by Total Cover, like every other Emanation.
        if (agent_idx != src &&
            !bm.hasLineOfSight(src_pa.origin, src_pa.agent->getSize(),
                               self_pa.origin, self_pa.agent->getSize()))
            continue;
        return true;
    }
    return false;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Saving throws
// ─────────────────────────────────────────────────────────────────────────────

// Canonical saving-throw modifier for agent_idx vs ability `ab`: ability modifier + proficiency
// (if proficient) + aura bonuses. Not const-safe by nature: rolls Bless's 1d4 (mutates ctx.rng_)
// when the saver is blessed.
inline int saveModFor(const BattleMap& bm, CombatContext& ctx, int agent_idx, SaveAbility_t ab) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size()) return 0;
    const Agent::Stats& s = agents[static_cast<std::size_t>(agent_idx)].agent->getStats();
    int score = 0; bool prof = false;
    switch (ab) {
        case SaveStr: score = s.str;   prof = s.save_prof_str;   break;
        case SaveDex: score = s.dex;   prof = s.save_prof_dex;   break;
        case SaveCon: score = s.con;   prof = s.save_prof_con;   break;
        case SaveInt: score = s.intel; prof = s.save_prof_intel; break;
        case SaveWis: score = s.wis;   prof = s.save_prof_wis;   break;
        default:      score = s.cha;   prof = s.save_prof_cha;   break;
    }
    int m = dndMod(score) + (prof ? s.prof_bonus : 0);
    // Bless — add 1d4 to the saving throw (rolled fresh per save).
    if (s.blessed) {
        int bless_d4 = roll(ctx, 4);
        m += bless_d4;
        if (ctx.logger_)
            ctx.logger_->log(std::format("Bless: +{} to {} save", bless_d4,
                                          agents[static_cast<std::size_t>(agent_idx)].agent->name()));
    }
    // Bane — subtract 1d4 from the saving throw (rolled fresh per save). Stacks with Bless.
    if (s.baned) {
        int bane_d4 = roll(ctx, 4);
        m -= bane_d4;
        if (ctx.logger_)
            ctx.logger_->log(std::format("Bane: -{} to {} save", bane_d4,
                                          agents[static_cast<std::size_t>(agent_idx)].agent->name()));
    }
    return m + auraSaveBonus(bm, agent_idx);
}

// Ability-scoped save Advantage (Phase 0.3) — the symmetric counterpart to
// CombatEngine::curseSaveDisadvantage (which stays on the engine: it reads
// activeAgentConditions_, not just the BattleMap). Data-driven off
// Stats::save_advantage_mask so any "Advantage on X saves" buff (Haste's DEX
// save, future effects) is honored at every save site without a per-feature branch.
inline bool saveAdvantageFor(const BattleMap& bm, int agent_idx, SaveAbility_t ab) noexcept
{
    const auto& agents = bm.placedAgents();
    if (agent_idx < 0 || static_cast<std::size_t>(agent_idx) >= agents.size()) return false;
    const Agent::Stats& s = agents[static_cast<std::size_t>(agent_idx)].agent->getStats();
    // Foresight grants Advantage on ALL saving throws (in addition to attack rolls), so it is
    // honored here for every ability without needing to flip each mask bit.
    if (s.has_foresight) return true;
    return (s.save_advantage_mask & (1 << static_cast<int>(ab))) != 0;
}

} // namespace rpg::rules
