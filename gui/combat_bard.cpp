// ─────────────────────────────────────────────────────────────────────────────
//  combat_bard.cpp  –  CombatEngine Bard features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Glamour, Lore.
//  Contents: Bardic Inspiration dice, Mantle of Inspiration / Majesty, Unbreakable Majesty,
//  Beguiling Magic, Superior Inspiration, Cutting Words.
//
//  Split out of combat_riders.cpp and combat_resources.cpp in COMBAT_REFACTOR_PLAN.md R6
//  (plans/COMBAT_CLASS_SPLIT_PLAN.md).
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"
#include "rules.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <string>
#include <string_view>
#include <tuple>
#include <unordered_set>
#include <vector>

namespace rpg {

int CombatEngine::bardMantleOfInspiration(BattleMap& bm, int bard_idx,
                                          const std::vector<int>& targets) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (bard_idx < 0 || bard_idx >= n) return 0;

    Agent::Stats bs = bm.getAgentStats(bard_idx);
    if (bs.lacksClass(CharacterClass::Bard) ||
        bs.bard_subclass != BardCollege::GlamourPath || bs.classLevel(CharacterClass::Bard) < 3) {
        log_("{} cannot use Mantle of Inspiration (not a L3+ College of Glamour Bard)",
             agentName(bm, bard_idx));
        return 0;
    }
    const Resource* bi = bs.getResource("Bardic Inspiration");
    if (!bi || bi->current <= 0) {
        log_("{} has no Bardic Inspiration use for Mantle of Inspiration", agentName(bm, bard_idx));
        return 0;
    }
    spendResource(bm, bard_idx, "Bardic Inspiration", 1);

    // Roll the Bardic Inspiration die ONCE; every recipient gets twice that roll.
    const int rolled = roll(bs.bardic_inspiration_die_size);
    const int thp    = 2 * rolled;
    const int cap    = std::max(1, dndMod(bs.cha));   // up to CHA mod creatures (min 1)

    int granted = 0;
    for (int t : targets) {
        if (granted >= cap) break;
        if (t < 0 || t >= n || t == bard_idx) continue;   // 2024: "other creatures", not self
        Agent::Stats ts = bm.getAgentStats(t);
        grantTempHp(ts, thp, -1);                          // max() semantics, non-rage source
        bm.setAgentStats(t, ts);
        log_("{}: Mantle of Inspiration grants {} Temporary HP to {}",
             agentName(bm, bard_idx), thp, agentName(bm, t));
        ++granted;
    }
    log_("{} weaves Mantle of Inspiration (rolled {} on d{}): {} Temporary HP to {} creature(s)",
         agentName(bm, bard_idx), rolled, bs.bardic_inspiration_die_size, thp, granted);
    return thp;
}

bool CombatEngine::grantBardicDie(BattleMap& bm, int agent_idx, int d) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    // RAW: a creature holds only one Bardic Inspiration die at a time; overwrite.
    stats.bardic_inspiration_die = d;
    bm.setAgentStats(agent_idx, stats);

    log_("{} gains a Bardic Inspiration d{}", agentName(bm, agent_idx), d);
    return true;
}

int CombatEngine::useBardicDie(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    int d = stats.bardic_inspiration_die;
    if (d <= 0) {
        log_("{} has no Bardic Inspiration die to spend", agentName(bm, agent_idx));
        return 0;
    }

    int value = roll(d);            // roll the held die (1..d)
    ctx_.pending_roll_bonus_ = value;    // fold into the agent's NEXT d20 Test
    stats.bardic_inspiration_die = 0;  // consumed
    bm.setAgentStats(agent_idx, stats);

    log_("{} spends Bardic Inspiration d{}: +{} to the next D20 Test",
         agentName(bm, agent_idx), d, value);
    return value;
}

int CombatEngine::useBardicDieForDamage(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    int d = stats.bardic_inspiration_die;
    if (d <= 0) {
        log_("{} has no Bardic Inspiration die to spend", agentName(bm, agent_idx));
        return 0;
    }

    int value = roll(d);                   // roll the held die (1..d)
    ctx_.pending_damage_bonus_ = value;         // fold into the attacker's NEXT weapon damage roll
    stats.bardic_inspiration_die = 0;     // consumed
    bm.setAgentStats(agent_idx, stats);

    log_("{} spends Bardic Inspiration d{}: +{} to the next weapon damage roll",
         agentName(bm, agent_idx), d, value);
    return value;
}

int CombatEngine::bardRegainInspirationFromSlot(BattleMap& bm, int agent_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 1 || slot_level > 9) return -1;

    Agent::Stats stats = bm.getAgentStats(agent_idx);
    if (stats.lacksClass(CharacterClass::Bard) || stats.classLevel(CharacterClass::Bard) < 5) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;  // no slot of that level to spend

    Resource* bi = stats.getResource("Bardic Inspiration");
    if (!bi || bi->current >= bi->max) return -1;          // nothing to regain → don't waste a slot

    stats.spell_slots_remaining[si] -= 1;
    bi->gain(1);
    bm.setAgentStats(agent_idx, stats);

    log_("{} expends a level-{} slot (Font of Inspiration): Bardic Inspiration now {}/{}",
         agentName(bm, agent_idx), slot_level, bi->current, bi->max);
    return bi->current;
}

bool CombatEngine::activateMantleOfMajesty(BattleMap& bm, int bard_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.lacksClass(CharacterClass::Bard) ||
        stats.bard_subclass != GlamourPath || stats.classLevel(CharacterClass::Bard) < 6) return false;

    Resource* maj = stats.getResource("Mantle of Majesty");
    if (!maj || maj->current <= 0) return false;   // no use left → don't open the window

    // Spend the use (spendResource re-reads/writes stats internally).
    spendResource(bm, bard_idx, "Mantle of Majesty", 1);

    // The "unearthly appearance" is Concentration: replace any prior concentration spell first,
    // then concentrate on the literal window name so a later concentration spell / damage-broken
    // save ends the window (dropConcentration clears mantle_majesty_turns).
    (void)dropConcentration(bm, bard_idx);

    stats = bm.getAgentStats(bard_idx);
    stats.mantle_majesty_turns = 10;  // 1 minute = 10 rounds
    bm.setAgentStats(bard_idx, stats);

    Agent::Conditions cond = bm.getAgentConditions(bard_idx);
    cond.concentrating    = true;
    cond.concentrating_on = "Mantle of Majesty";
    bm.setAgentConditions(bard_idx, cond);

    log_("{} takes on an unearthly appearance (Mantle of Majesty): may cast Command as a Bonus "
         "Action with no slot for 1 minute", agentName(bm, bard_idx));
    return true;
}

int CombatEngine::bardRestoreMantleOfMajestyFromSlot(BattleMap& bm, int bard_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 3 || slot_level > 9) return -1;          // restorable only with a level 3+ slot

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.lacksClass(CharacterClass::Bard) ||
        stats.bard_subclass != GlamourPath || stats.classLevel(CharacterClass::Bard) < 6) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;      // no slot of that level to spend

    Resource* maj = stats.getResource("Mantle of Majesty");
    if (!maj || maj->current >= maj->max) return -1;          // already full → don't waste a slot

    stats.spell_slots_remaining[si] -= 1;
    maj->gain(1);
    bm.setAgentStats(bard_idx, stats);

    log_("{} expends a level-{} slot to restore Mantle of Majesty: now {}/{}",
         agentName(bm, bard_idx), slot_level, maj->current, maj->max);
    return maj->current;
}

bool CombatEngine::activateUnbreakableMajesty(BattleMap& bm, int bard_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return false;

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.lacksClass(CharacterClass::Bard) ||
        stats.bard_subclass != GlamourPath || stats.classLevel(CharacterClass::Bard) < 14) return false;

    Resource* maj = stats.getResource("Unbreakable Majesty");
    if (!maj || maj->current <= 0) return false;   // no use left

    // Spend the use
    spendResource(bm, bard_idx, "Unbreakable Majesty", 1);

    // The "majestic presence" is Concentration: replace any prior concentration spell first,
    // then concentrate on the literal window name so a later concentration spell / damage-broken
    // save ends the window (dropConcentration clears majestic_presence_turns).
    (void)dropConcentration(bm, bard_idx);

    stats = bm.getAgentStats(bard_idx);
    stats.majestic_presence_turns = 10;  // 1 minute = 10 rounds
    stats.majesty_checked_this_turn = false;  // fresh turn, ready to check
    bm.setAgentStats(bard_idx, stats);

    Agent::Conditions cond = bm.getAgentConditions(bard_idx);
    cond.concentrating    = true;
    cond.concentrating_on = "Unbreakable Majesty";
    bm.setAgentConditions(bard_idx, cond);

    log_("{} takes on a majestic presence (Unbreakable Majesty): melee attacks against {} trigger "
         "Psychic damage and a CHA save for 1 minute", agentName(bm, bard_idx), agentName(bm, bard_idx));
    return true;
}

int CombatEngine::bardRestoreUnbreakableMajestyFromSlot(BattleMap& bm, int bard_idx, int slot_level) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return -1;
    if (slot_level < 3 || slot_level > 9) return -1;          // restorable only with a level 3+ slot

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.lacksClass(CharacterClass::Bard) ||
        stats.bard_subclass != GlamourPath || stats.classLevel(CharacterClass::Bard) < 14) return -1;

    auto si = static_cast<std::size_t>(slot_level - 1);
    if (stats.spell_slots_remaining[si] <= 0) return -1;      // no slot of that level to spend

    Resource* maj = stats.getResource("Unbreakable Majesty");
    if (!maj || maj->current >= maj->max) return -1;          // already full → don't waste a slot

    stats.spell_slots_remaining[si] -= 1;
    maj->gain(1);
    bm.setAgentStats(bard_idx, stats);

    log_("{} expends a level-{} slot to restore Unbreakable Majesty: now {}/{}",
         agentName(bm, bard_idx), slot_level, maj->current, maj->max);
    return maj->current;
}

bool CombatEngine::bardBeguilingMagic(BattleMap& bm, int bard_idx, int target_idx,
                                      bool use_frightened) noexcept
{
    const auto& agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    if (bard_idx < 0 || bard_idx >= n || target_idx < 0 || target_idx >= n || target_idx == bard_idx)
        return false;

    Agent::Stats bs = bm.getAgentStats(bard_idx);
    if (bs.lacksClass(CharacterClass::Bard) ||
        bs.bard_subclass != BardCollege::GlamourPath || bs.classLevel(CharacterClass::Bard) < 3) {
        log_("{} cannot use Beguiling Magic (not a L3+ College of Glamour Bard)", agentName(bm, bard_idx));
        return false;
    }
    const Resource* beg = bs.getResource("Beguiling Magic");
    if (!beg || beg->current <= 0) {
        log_("{} has no Beguiling Magic use available", agentName(bm, bard_idx));
        return false;
    }
    // Must be a creature the bard can see within 60 ft (the GUI also gates LOS/perception).
    const int dist_ft = footprintDistance(agents[bard_idx].origin, agents[bard_idx].agent->getSize(),
                                          agents[target_idx].origin, agents[target_idx].agent->getSize()) * 5;
    if (dist_ft > 60) {
        log_("Beguiling Magic: {} is more than 60 ft away", agentName(bm, target_idx));
        return false;
    }

    // Using the benefit spends the use whether or not the target ultimately fails its save.
    spendResource(bm, bard_idx, "Beguiling Magic", 1);

    const char* cond_name = use_frightened ? "Frightened" : "Charmed";
    const int   dc        = rules::spellSaveDc(bs);
    const int   save_mod  = saveModFor(bm, target_idx, SaveWis);
    const int   save_roll = (conditionSaveAdvantage(bm, target_idx, cond_name) ? rollAdvantage(20)
                                                                                : roll(20)) + save_mod;

    if (save_roll >= dc) {
        log_("{} resists Beguiling Magic (WIS save {} vs DC {})", agentName(bm, target_idx), save_roll, dc);
        charmFearSaveSucceeded(bm, target_idx);   // Beguiling Twist's trigger
        return true;
    }
    // Frightened can be refused outright by Aura of Courage — the use is still spent.
    if (use_frightened && hasAuraOfCourage(bm, target_idx)) {
        log_("{} can't be Frightened (Aura of Courage) — Beguiling Magic has no effect",
             agentName(bm, target_idx));
        return true;
    }

    ActiveAgentCondition cond;
    cond.agent_idx        = target_idx;
    cond.caster_idx       = bard_idx;
    cond.condition_name   = cond_name;
    cond.turns_remaining  = 10;            // 1 minute = 10 rounds (ticked on the bard's turns)
    cond.save_ability     = SaveWis;
    cond.save_dc          = dc;
    cond.save_repeat_turns = 1;            // repeats at the start of each of the target's turns
    cond.next_save_turn   = 0;
    (void)addAgentCondition(bm, cond);
    log_("{} fails vs Beguiling Magic and is {} for 1 minute (WIS save {} vs DC {})",
         agentName(bm, target_idx), cond_name, save_roll, dc);
    return true;
}

int CombatEngine::bardRestoreBeguilingMagic(BattleMap& bm, int bard_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return -1;

    Agent::Stats bs = bm.getAgentStats(bard_idx);
    if (bs.lacksClass(CharacterClass::Bard) ||
        bs.bard_subclass != BardCollege::GlamourPath || bs.classLevel(CharacterClass::Bard) < 3) return -1;

    Resource* beg = bs.getResource("Beguiling Magic");
    if (!beg || beg->current >= beg->max) return -1;   // already full → don't waste an Inspiration
    const Resource* bi = bs.getResource("Bardic Inspiration");
    if (!bi || bi->current <= 0) return -1;            // no Bardic Inspiration use to spend

    spendResource(bm, bard_idx, "Bardic Inspiration", 1);
    // Re-read stats: spendResource mutated them; gain on a fresh copy and write back.
    bs = bm.getAgentStats(bard_idx);
    beg = bs.getResource("Beguiling Magic");
    if (!beg) return -1;
    beg->gain(1);
    bm.setAgentStats(bard_idx, bs);

    log_("{} expends a Bardic Inspiration use to restore Beguiling Magic: now {}/{}",
         agentName(bm, bard_idx), beg->current, beg->max);
    return beg->current;
}

void CombatEngine::applySuperiorInspiration(BattleMap& bm) noexcept
{
    auto agents = bm.placedAgents();
    const int n = static_cast<int>(agents.size());
    for (int i = 0; i < n; ++i) {
        Agent::Stats stats = bm.getAgentStats(i);
        if (stats.lacksClass(CharacterClass::Bard) || stats.classLevel(CharacterClass::Bard) < 18) continue;

        Resource* bi = stats.getResource("Bardic Inspiration");
        if (!bi || bi->current >= 2) continue;

        bi->current = std::min(bi->max, 2);  // regain up to 2 (never above the resource max)
        bm.setAgentStats(i, stats);
        log_("{} regains Bardic Inspiration to {} (Superior Inspiration)",
             agentName(bm, i), bi->current);
    }
}

int CombatEngine::bardCuttingWords(BattleMap& bm, int bard_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (bard_idx < 0 || bard_idx >= static_cast<int>(agents.size())) return 0;

    Agent::Stats stats = bm.getAgentStats(bard_idx);
    if (stats.lacksClass(CharacterClass::Bard) ||
        stats.bard_subclass != BardCollege::LorePath || stats.classLevel(CharacterClass::Bard) < 3) {
        log_("{} cannot use Cutting Words (not a L3+ College of Lore Bard)", agentName(bm, bard_idx));
        return 0;
    }

    Resource* bi = stats.getResource("Bardic Inspiration");
    if (!bi || bi->current <= 0) {
        log_("{} has no Bardic Inspiration use for Cutting Words", agentName(bm, bard_idx));
        return 0;
    }

    bi->current -= 1;
    int value = roll(stats.bardic_inspiration_die_size);
    ctx_.pending_roll_bonus_ = -value;   // SUBTRACT from the next D20 Test (the target's roll)
    bm.setAgentStats(bard_idx, stats);

    log_("{} uses Cutting Words: -{} to the next D20 Test ({} Bardic Inspiration left)",
         agentName(bm, bard_idx), value, bi->current);
    return value;
}

// ── College of Whispers: Psychic Blades (L3) ─────────────────────────────────

int CombatEngine::psychicBladesDice(int bard_level) noexcept
{
    if (bard_level >= 15) return 8;
    if (bard_level >= 10) return 5;
    if (bard_level >= 5)  return 3;
    if (bard_level >= 3)  return 2;
    return 0;
}

int CombatEngine::applyPsychicBlades(BattleMap& bm, int attacker_idx, int target_idx,
                                     AttackResult& result) noexcept
{
    const int n = static_cast<int>(bm.placedAgents().size());
    if (attacker_idx < 0 || attacker_idx >= n || target_idx < 0 || target_idx >= n) return -1;
    Agent::Conditions atk_cond = bm.getAgentConditions(attacker_idx);
    if (!atk_cond.psychic_blades_available || atk_cond.psychic_blades_used) return -1;
    const Agent::Stats atk_stats = bm.getAgentStats(attacker_idx);
    const int dice = psychicBladesDice(atk_stats.classLevel(CharacterClass::Bard));
    if (atk_stats.bard_subclass != WhispersPath || dice <= 0) return -1;
    if (!spendResource(bm, attacker_idx, "Bardic Inspiration", 1)) return -1;

    const int rolled = result.critical ? 2 * dice : dice;   // extra damage dice double on a crit
    int raw = 0;
    for (int i = 0; i < rolled; ++i) raw += roll(6);

    Agent::Stats tgt_stats = bm.getAgentStats(target_idx);
    const float mult = tgt_stats.magic_damage_multipliers[MagicDamage_t::Psychic];
    const int pb = static_cast<int>(static_cast<float>(raw) * mult);

    result.damage_breakdown.push_back({"psychic blades", pb});
    result.total_damage += pb;
    result.magic_damage_types.push_back(MagicDamage_t::Psychic);
    const int overflow = std::max(0, pb - tgt_stats.temp_hp);
    tgt_stats.temp_hp = std::max(0, tgt_stats.temp_hp - pb);
    tgt_stats.hp_cur  = std::clamp(tgt_stats.hp_cur - overflow, 0, tgt_stats.hp_max);
    result.hp_after    = tgt_stats.hp_cur;
    result.target_down = (tgt_stats.hp_cur <= 0);
    bm.setAgentStats(target_idx, tgt_stats);

    atk_cond = bm.getAgentConditions(attacker_idx);   // spendResource may have written the agent
    atk_cond.psychic_blades_used      = true;
    atk_cond.psychic_blades_available = false;
    bm.setAgentConditions(attacker_idx, atk_cond);

    log_("{} uses Psychic Blades: +{} Psychic ({}d6)", agentName(bm, attacker_idx), pb, rolled);
    if (pb > 0) {
        checkConcentrationOnDamage(bm, target_idx, pb);
        processDamageTaken(bm, target_idx, pb);
    }
    return pb;
}

} // namespace rpg
