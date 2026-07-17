// ─────────────────────────────────────────────────────────────────────────────
//  combat_conditions.cpp  –  CombatEngine status-effect application + lifecycle
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Sections:
//    · Condition application — apply* status setters (Paralyzed, Blinded, …),
//                              updateDarknessBlinding, dropAgentWeapons
//    · Condition lifecycle   — addAgentCondition, removeAgentCondition,
//                              activeAgentConditions, tickAgentConditions,
//                              tickAgentConditionsForCaster
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"

#include <algorithm>
#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Condition application
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::applyParalyzed(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Paralyzed IS Incapacitated: route the shared side-effects (movement→0, grapples released,
    // and — critically — concentration broken) through applyIncapacitated so a paralyzed caster
    // (e.g. Hold Person) drops its concentration spell like Spirit Guardians. Then layer on the
    // Paralyzed-specific flag.
    applyIncapacitated(bm, idx);

    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.paralyzed = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent paralyzed: movement speed set to 0, incapacitated");
}

void CombatEngine::applyBlinded(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set blinded condition
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.blinded = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent blinded: attack rolls have disadvantage, attacks against have advantage");
}

void CombatEngine::updateDarknessBlinding(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    const PlacedAgent& pa = agents[static_cast<std::size_t>(agent_idx)];
    const Agent::Stats& stats = pa.agent->getStats();
    // Single source of truth: the live light-effect layer, as perceived by THIS agent. A Shadow Arts:
    // Darkness caster sees through their own Darkness (getLightLevelFor reports a non-dark level for
    // them), so it never blinds them. The dead obscuration layer is no longer consulted — fog/cloud
    // spells now write light_level into this same layer (DARKNESS_MERGE_HANDOFF.md Phase 1).
    const VisibilityLevel light = bm.getLightLevelFor(pa.origin, agent_idx);

    Agent::Conditions cond = bm.getAgentConditions(agent_idx);
    bool should_be_blinded = false;

    // Magical darkness is the most restrictive, so it takes priority.
    if (light == VisibilityLevel::MagicalDark) {
        // Magically Dark (Impenetrable): blinded unless have devil's sight
        should_be_blinded = (stats.devilssight_range == 0);
    } else if (light == VisibilityLevel::HeavilyObscured) {
        // Fog/smoke (non-magical heavy obscurement): blinded unless Truesight/Blindsight. Neither
        // darkvision nor devil's sight pierces a physical cloud.
        should_be_blinded = (stats.truesight_range == 0 && stats.blindsight_range == 0);
    } else if (light == VisibilityLevel::Dark) {
        // Heavily Obscured by Darkness: blinded unless have darkvision
        should_be_blinded = (stats.darkvision_range == 0);
    }
    // BrightLight: full visibility, never blinded
    // DimLight: lightly obscured but visible, never blinded
    // PartiallyObscured: not fully blinded (disadvantage on perception, but not Blinded condition)

    // Apply or remove blinded condition as needed
    if (should_be_blinded && !cond.blinded) {
        cond.blinded = true;
	cond.has_disadvantage = true; 
        bm.setAgentConditions(agent_idx, cond);
        log_("{} is blinded by darkness", pa.agent->name());
    } else if (!should_be_blinded && cond.blinded) {
        // Only remove blinded if it was from darkness (not from a spell like Blindness/Deafness)
        // For now, we'll remove it - in future we could track the source
        cond.blinded = false;
	cond.has_disadvantage = false; 
        bm.setAgentConditions(agent_idx, cond);
        log_("{} can see again", pa.agent->name());
    }
}

void CombatEngine::applyIncapacitated(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set incapacitated condition
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.incapacitated = true;
    bm.setAgentConditions(idx, cond);

    // A grapple ends the moment the grappler is Incapacitated (RAW). Release every
    // creature this agent was holding so they regain their Speed immediately.
    dropGrapplesBy(bm, idx);

    // Break concentration if the agent is concentrating.
    // dropConcentration cascades removal of terrain + spell-effects + conditions.
    if (cond.concentrating) {
        [[maybe_unused]] auto dropped = dropConcentration(bm, idx);
        log_("Agent incapacitated: concentration broken");
    }

    // Set all movement speeds to 0
    Agent::Stats stats = bm.getAgentStats(idx);
    stats.speed_walk_remaining = 0;
    stats.speed_fly_remaining = 0;
    stats.speed_swim_remaining = 0;
    stats.speed_burrow_remaining = 0;
    bm.setAgentStats(idx, stats);

    log_("Agent incapacitated: cannot act, movement speed set to 0");
}

void CombatEngine::applyStunned(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Stunned IS Incapacitated: route the shared side-effects (movement→0, grapples released,
    // concentration broken) through applyIncapacitated so a stunned caster drops its concentration
    // spell. Then layer on the Stunned-specific flag.
    applyIncapacitated(bm, idx);

    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.stunned = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent stunned: cannot act, auto-fails STR/DEX saves, attacks have advantage");
}

void CombatEngine::applyCharmed(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Beguiling Defenses (Archfey Warlock L10+): immune to the Charmed condition.
    {
        const Agent::Stats s = bm.getAgentStats(idx);
        if (s.character_class == CharacterClass::Warlock &&
            s.warlock_subclass == ArchfeyPath && s.char_level >= 10) {
            log_("{} can't be Charmed (Beguiling Defenses)", agentName(bm, idx));
            return;
        }
    }

    // Set charmed condition
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.charmed = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent charmed: cannot attack the charmer or target with damaging abilities/effects");
}

void CombatEngine::dropAgentWeapons(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Get mutable reference and drop all non-empty weapons (except permanently armed ones)
    PlacedAgent& pa = const_cast<PlacedAgent&>(agents[idx]);
    for (auto& w : pa.weapons) {
        if (!w.name.empty() && w.name.find("Unarmed") == std::string::npos && !w.permanently_armed) {
	    log_("{} dropped weapon {}", agentName(bm, idx), w.name);
            (void)bm.placeItem(pa.origin, w, "");
            w = Weapon{};
        }
    }
}

void CombatEngine::applyFrightened(BattleMap& bm, int idx) noexcept
{
    // Aura of Courage (allied Paladin L10+ in range): immune to the Frightened condition.
    if (hasAuraOfCourage(bm, idx)) {
        log_("{} can't be Frightened (Aura of Courage)", agentName(bm, idx));
        return;
    }
    dropAgentWeapons(bm, idx);
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.frightened = true;
    bm.setAgentConditions(idx, cond);
    log_("Agent is Frightened: dropped weapons, disadvantage on attacks/checks when fear source in LOS, cannot approach");
}

void CombatEngine::applyProne(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set prone condition (movement restricted to crawling, disadvantage on attacks)
    Agent::Conditions cond = bm.getAgentConditions(idx);
    // A creature in gaseous form (Gaseous Form / vampire Misty Escape) is immune to the Prone condition.
    if (cond.gaseous_form) {
        log_("{} is in gaseous form and is immune to Prone", agentName(bm, idx));
        return;
    }
    cond.prone = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent is now prone: movement costs doubled (triple in difficult terrain), disadvantage on attack rolls");
}

// ─────────────────────────────────────────────────────────────────────────────
//  Burning [Hazard] and the Net — the two conditions carried by thrown items
// ─────────────────────────────────────────────────────────────────────────────

void CombatEngine::applyBurning(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (cond.burning) return;   // already alight — a second flask does not stack a second fire
    cond.burning = true;
    bm.setAgentConditions(idx, cond);
    log_("{} is Burning: 1d4 Fire damage at the start of each of its turns until the fire is put out",
         agentName(bm, idx));
}

bool CombatEngine::extinguishBurning(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (!cond.burning) return false;

    // "As an action, you can extinguish fire on yourself by giving yourself the Prone condition and
    // rolling on the ground." Note applyProne re-reads the conditions, so clear the flame afterwards
    // rather than in one write — and go through applyProne so the Prone rules (gaseous-form immunity)
    // stay in one place.
    applyProne(bm, idx);
    cond = bm.getAgentConditions(idx);
    cond.burning = false;
    bm.setAgentConditions(idx, cond);
    log_("{} drops and rolls, putting out the flames (no longer Burning)", agentName(bm, idx));
    return true;
}

EscapeNetResult CombatEngine::escapeNet(BattleMap& bm, int actor_idx, int target_idx) noexcept
{
    EscapeNetResult res;
    const auto& agents = bm.placedAgents();
    if (actor_idx  < 0 || actor_idx  >= static_cast<int>(agents.size())) return res;
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return res;

    Agent::Conditions tc = bm.getAgentConditions(target_idx);
    if (!tc.netted) return res;

    // The actor has to be able to act, and be the netted creature or a creature within 5 ft of it.
    const Agent::Conditions ac = bm.getAgentConditions(actor_idx);
    if (ac.dead || ac.unconscious || ac.incapacitated) return res;
    if (actor_idx != target_idx) {
        const PlacedAgent& apa = agents[static_cast<std::size_t>(actor_idx)];
        const PlacedAgent& tpa = agents[static_cast<std::size_t>(target_idx)];
        if (footprintDistance(apa.origin, apa.agent->getSize(),
                              tpa.origin, tpa.agent->getSize()) * 5 > 5) return res;
    }

    // DC 10 Strength (Athletics) check. Skill proficiency is not modeled, so this is d20 + STR mod —
    // the same shape as the grapple-escape check.
    const Agent::Stats as = bm.getAgentStats(actor_idx);
    int str_mod = (as.str - 10) / 2;
    if (as.str < 10 && (as.str - 10) % 2 != 0) --str_mod;

    res.valid = true;
    res.dc    = tc.net_escape_dc;
    res.d20   = roll(20);
    res.total = res.d20 + str_mod;
    res.freed = (res.total >= res.dc);

    if (res.freed) {
        tc.netted     = false;
        tc.restrained = false;
        bm.setAgentConditions(target_idx, tc);
    }
    log_("{} makes a DC {} STR check to free {} from the Net: {} + {} = {} ({})",
         agentName(bm, actor_idx), res.dc,
         (actor_idx == target_idx) ? "itself" : agentName(bm, target_idx),
         res.d20, str_mod, res.total, res.freed ? "FREED" : "FAILED");
    return res;
}

int CombatEngine::applyPush(BattleMap& bm, int attacker_idx, int target_idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (attacker_idx < 0 || attacker_idx >= static_cast<int>(agents.size()) ||
        target_idx   < 0 || target_idx   >= static_cast<int>(agents.size())) return 0;

    Agent::Conditions ac = bm.getAgentConditions(attacker_idx);
    if (!ac.push_available) return 0;          // only after a qualifying Push hit
    ac.push_available = false;
    ac.push_used_this_turn = true;             // mark as used (once per turn)
    bm.setAgentConditions(attacker_idx, ac);

    const Cell origin = agents[static_cast<std::size_t>(attacker_idx)].origin;
    int feet = bm.forceMoveAgent(target_idx, origin, 10) * 5;
    if (feet > 0)
        log_("{} pushes {} {} ft (Push mastery)",
             agentName(bm, attacker_idx), agentName(bm, target_idx), feet);
    return feet;
}

void CombatEngine::applyHidden(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.hidden = true;
    bm.setAgentConditions(idx, cond);

    log_("{} is now hidden", agents[static_cast<std::size_t>(idx)].agent->name());
}

void CombatEngine::applyUnconscious(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    dropAgentWeapons(bm, idx);

    // ── Single down/death chokepoint: release EVERY effect this creature sustains on the battle ──
    // Dropping to 0 HP makes the agent Incapacitated, which ends any grapple it was
    // maintaining — free its victims so they aren't stuck at Speed 0 by a dead grappler.
    dropGrapplesBy(bm, idx);

    // Break concentration (cascades removal of this caster's concentration terrain, spell-effects,
    // light effects, and the conditions those sustained). Mirrors applyIncapacitated, which
    // applyUnconscious does NOT route through (it sets the incapacitated flag directly below).
    if (bm.getAgentConditions(idx).concentrating) {
        [[maybe_unused]] auto dropped = dropConcentration(bm, idx);
        log_("Agent falls unconscious: concentration broken");
    }

    // Release all remaining influence: non-concentration conditions this agent imposed on others,
    // plus every reverse-reference mark (charmed_by, *_marked_by, goaded_by, …) pointing back at it.
    releaseAgentInfluence(bm, idx);

    // Paladin Oath of Vengeance — Vow of Enmity transfer: if this creature was a paladin's sworn
    // foe, the vow moves (no action) to a different creature within 30 ft of that paladin; if none
    // is in range, the vow simply lapses. Runs before the NPC early-return so corpses hand it off.
    for (int p = 0; p < static_cast<int>(agents.size()); ++p) {
        Agent::Stats ps = bm.getAgentStats(p);
        if (ps.vow_of_enmity_turns <= 0 || ps.vow_of_enmity_target != idx) continue;
        const PlacedAgent& pp = agents[static_cast<std::size_t>(p)];
        int best = -1, best_d = 7;   // 30 ft = 6 cells; keep the nearest strictly within range
        for (int e = 0; e < static_cast<int>(agents.size()); ++e) {
            if (e == p || e == idx) continue;
            if (areAllies(bm, p, e)) continue;
            const PlacedAgent& ep = agents[static_cast<std::size_t>(e)];
            if (bm.getAgentStats(e).hp_cur <= 0 || bm.getAgentConditions(e).dead) continue;
            const int d = footprintDistance(pp.origin, pp.agent->getSize(),
                                            ep.origin, ep.agent->getSize());
            if (d * 5 > 30) continue;
            if (!bm.hasLineOfSight(pp.origin, pp.agent->getSize(), ep.origin, ep.agent->getSize())) continue;
            if (d < best_d) { best_d = d; best = e; }
        }
        ps.vow_of_enmity_target = best;
        if (best < 0) ps.vow_of_enmity_turns = 0;
        bm.setAgentStats(p, ps);
        if (best >= 0)
            log_("Vow of Enmity transfers from {} to {}",
                 agentName(bm, idx), agentName(bm, best));
    }

    // Gaseous Form / vampire Misty Escape ends when the creature drops to 0 HP (RAW). It is a SELF
    // condition, which releaseAgentInfluence deliberately skips, so end it here: restore the snapshot,
    // clear the flag, and drop the tracked "Gaseous" condition so nothing lingers past death/revival.
    if (bm.getAgentConditions(idx).gaseous_form) {
        endGaseousForm(bm, idx);
        std::vector<int> gaseous_ids;
        for (const auto& ac : activeAgentConditions_)
            if (ac.agent_idx == idx && ac.condition_name == "Gaseous")
                gaseous_ids.push_back(ac.condition_id);
        for (int gid : gaseous_ids) removeAgentCondition(bm, gid);
    }

    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.unconscious = true;
    cond.incapacitated = true;
    cond.prone = true;

    // NPCs do not make death saves: they die outright at 0 HP. Only player
    // characters fall unconscious and roll death saves on their turns.
    if (bm.getAgentStats(idx).is_npc) {
        cond.dead = true;
        bm.setAgentConditions(idx, cond);
        log_("{} drops to 0 HP and dies (NPC — no death saves)", agents[static_cast<std::size_t>(idx)].agent->name());
        return;
    }

    bm.setAgentConditions(idx, cond);

    log_("Agent is Unconscious: incapacitated, prone, speed 0, attacks have advantage, auto-fail STR/DEX saves, auto-crit within 5ft");
}

void CombatEngine::reviveOnHeal(BattleMap& bm, int idx) noexcept
{
    const auto& agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    if (bm.getAgentStats(idx).hp_cur <= 0) return;   // still at 0 HP — nothing to recover from

    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (cond.dead) return;                     // true death needs revival magic, not healing
    // Only act when the creature was actually downed; a heal on a conscious creature is a no-op here.
    if (!cond.unconscious && !cond.stabilized &&
        cond.death_save_successes == 0 && cond.death_save_failures == 0)
        return;

    // Regaining any HP from 0 returns the creature to consciousness and clears death saves
    // (D&D 5e), so begin_turn no longer skips them. Prone is left in place — they stand on
    // their turn, per RAW. Static (no `this`), so the heal log lives at the calling sites.
    cond.unconscious          = false;
    cond.incapacitated        = false;
    cond.stabilized           = false;
    cond.death_save_successes  = 0;
    cond.death_save_failures   = 0;
    bm.setAgentConditions(idx, cond);
}

void CombatEngine::applyPoisoned(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    // Petrified agents are immune to poison
    if (cond.petrified) {
        log_("Agent is immune to poison (petrified)");
        return;
    }

    cond.poisoned = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent is Poisoned: disadvantage on attack rolls and ability checks");
}

void CombatEngine::applyDeafened(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.deafened = true;
    bm.setAgentConditions(idx, cond);

    log_("Agent is Deafened: cannot hear; auto-fail ability checks requiring hearing");
}

void CombatEngine::applyPetrified(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    // Set condition flags
    Agent::Conditions cond = bm.getAgentConditions(idx);
    cond.petrified = true;
    cond.incapacitated = true;
    bm.setAgentConditions(idx, cond);

    // Snapshot the real speeds and damage multipliers BEFORE overwriting them, so curePetrified
    // (Greater Restoration) can restore them. Guard against a double-apply clobbering a good snapshot
    // with the already-petrified 0-speed / 0.5× values.
    Agent::Stats stats = bm.getAgentStats(idx);
    if (petrifySnapshots_.find(idx) == petrifySnapshots_.end()) {
        PetrifySnapshot snap;
        snap.speed_walk   = stats.speed_walk;
        snap.speed_fly    = stats.speed_fly;
        snap.speed_swim   = stats.speed_swim;
        snap.speed_burrow = stats.speed_burrow;
        snap.magic_mult   = stats.magic_damage_multipliers;
        snap.phys_mult    = stats.physical_damage_multipliers;
        petrifySnapshots_[idx] = snap;
    }

    // Set all movement speeds to 0
    stats.speed_walk = 0;
    stats.speed_fly = 0;
    stats.speed_swim = 0;
    stats.speed_burrow = 0;
    stats.speed_walk_remaining = 0;
    stats.speed_fly_remaining = 0;
    stats.speed_swim_remaining = 0;
    stats.speed_burrow_remaining = 0;

    // Set all damage multipliers to 0.5 (resistance to all damage)
    for (std::size_t i = 0; i < stats.magic_damage_multipliers.size(); ++i) {
        stats.magic_damage_multipliers[i] = 0.5f;
    }
    for (std::size_t i = 0; i < stats.physical_damage_multipliers.size(); ++i) {
        stats.physical_damage_multipliers[i] = 0.5f;
    }

    bm.setAgentStats(idx, stats);
    log_("Agent is Petrified: incapacitated, speed 0, resistance to all damage (0.5x), immune to poisoned, auto-fail STR/DEX saves, attacks have advantage");
}

void CombatEngine::applyGaseousForm(BattleMap& bm, int idx, bool physical_immune) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (cond.gaseous_form) return;   // already gaseous — don't re-snapshot the mist-form values
    cond.gaseous_form = true;
    bm.setAgentConditions(idx, cond);

    // Snapshot the real speeds and physical multipliers BEFORE overwriting them so endGaseousForm
    // can restore them. Guard against a double-apply clobbering a good snapshot.
    Agent::Stats stats = bm.getAgentStats(idx);
    if (gaseousSnapshots_.find(idx) == gaseousSnapshots_.end()) {
        GaseousSnapshot snap;
        snap.speed_walk   = stats.speed_walk;
        snap.speed_fly    = stats.speed_fly;
        snap.speed_swim   = stats.speed_swim;
        snap.speed_burrow = stats.speed_burrow;
        snap.phys_mult    = stats.physical_damage_multipliers;
        gaseousSnapshots_[idx] = snap;
    }

    // Fly-only movement: Fly Speed 20 ft, all other speeds 0. Also zero this turn's remaining walk
    // budget and seed the fly budget so the change takes effect immediately (mirrors applyPetrified).
    stats.speed_walk = 0;
    stats.speed_fly = 20;
    stats.speed_swim = 0;
    stats.speed_burrow = 0;
    stats.speed_walk_remaining = 0;
    stats.speed_fly_remaining = 20;
    stats.speed_swim_remaining = 0;
    stats.speed_burrow_remaining = 0;

    // Resistance to Bludgeoning/Piercing/Slashing — Immunity (0x) for a vampire's Misty Escape.
    const float mult = physical_immune ? 0.0f : 0.5f;
    for (auto t : {PhysicalDamage_t::Bludgeoning, PhysicalDamage_t::Piercing, PhysicalDamage_t::Slashing})
        stats.physical_damage_multipliers[static_cast<std::size_t>(t)] = mult;

    bm.setAgentStats(idx, stats);
    log_("{} assumes gaseous form: Fly 20 ft, can't attack or cast, {} to Bludgeoning/Piercing/Slashing, immune to Prone",
         agentName(bm, idx), physical_immune ? "Immunity" : "Resistance");
}

void CombatEngine::endGaseousForm(BattleMap& bm, int idx) noexcept
{
    auto agents = bm.placedAgents();
    if (idx < 0 || idx >= static_cast<int>(agents.size())) return;

    Agent::Conditions cond = bm.getAgentConditions(idx);
    if (!cond.gaseous_form) return;
    cond.gaseous_form = false;
    bm.setAgentConditions(idx, cond);

    // Restore the pre-form speeds + physical multipliers from the snapshot (fall back to a plain
    // reset if the snapshot was lost to a save taken mid-form).
    Agent::Stats stats = bm.getAgentStats(idx);
    auto it = gaseousSnapshots_.find(idx);
    if (it != gaseousSnapshots_.end()) {
        stats.speed_walk   = it->second.speed_walk;
        stats.speed_fly    = it->second.speed_fly;
        stats.speed_swim   = it->second.speed_swim;
        stats.speed_burrow = it->second.speed_burrow;
        stats.physical_damage_multipliers = it->second.phys_mult;
        gaseousSnapshots_.erase(it);
    } else {
        stats.speed_walk = std::max(stats.speed_walk, 0);
        for (auto t : {PhysicalDamage_t::Bludgeoning, PhysicalDamage_t::Piercing, PhysicalDamage_t::Slashing})
            stats.physical_damage_multipliers[static_cast<std::size_t>(t)] = 1.0f;
    }

    bm.setAgentStats(idx, stats);
    log_("{} reverts from gaseous form", agentName(bm, idx));
}

void CombatEngine::applyGrappled(BattleMap& bm, int target_idx, int grappler_idx, int escape_dc) noexcept
{
    Agent::Conditions cond = getAgentConditions(bm, target_idx);
    cond.grappled = true;
    cond.grappler_idx = grappler_idx;
    cond.grapple_escape_dc = escape_dc;
    cond.grapple_range_ft = 5;
    setAgentConditions(bm, target_idx, cond);
}

void CombatEngine::dropGrapplesBy(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    for (size_t i = 0; i < agents.size(); ++i) {
        Agent::Conditions cond = getAgentConditions(bm, static_cast<int>(i));
        if (cond.grappler_idx == agent_idx && cond.grappled) {
            cond.grappled = false;
            cond.grappler_idx = -1;
            setAgentConditions(bm, static_cast<int>(i), cond);
        }
    }
}

void CombatEngine::releaseAgentInfluence(BattleMap& bm, int agent_idx) noexcept
{
    auto agents = bm.placedAgents();
    if (agent_idx < 0 || agent_idx >= static_cast<int>(agents.size())) return;

    // 1. End every ActiveAgentCondition this agent imposed on others. Concentration-sustained ones
    //    were already cleared by dropConcentration (called first in applyUnconscious); this catches
    //    the rest (innate/monster-ability conditions, non-concentration spell riders). Collect the ids
    //    first — removeAgentCondition mutates activeAgentConditions_ (and its onConditionEnded kickback
    //    can cascade into dropConcentration), so we must not iterate-and-erase in place.
    std::vector<int> imposed_ids;
    for (const auto& ac : activeAgentConditions_) {
        if (ac.caster_idx != agent_idx) continue;
        if (ac.agent_idx == agent_idx) continue;   // a self-condition is not "influence over others"
        imposed_ids.push_back(ac.condition_id);
    }
    // removeAgentCondition → onConditionEnded reverses each imposed flag (restores speed/actions).
    for (int cid : imposed_ids)
        removeAgentCondition(bm, cid);

    // 2. Clear every reverse-reference mark that other creatures hold pointing back at this agent.
    //    These are cross-turn fields normally cleared "at the start of <agent_idx>'s next turn" — a
    //    turn that never comes once it is down — so they must be released here or they dangle forever.
    for (std::size_t i = 0; i < agents.size(); ++i) {
        if (static_cast<int>(i) == agent_idx) continue;
        Agent::Conditions c = getAgentConditions(bm, static_cast<int>(i));
        bool dirty = false;

        auto clear_ref = [&](int& field) {
            if (field == agent_idx) { field = -1; dirty = true; }
        };
        // Paired mark+source fields: clear the source AND the effect flag it gated.
        auto clear_marked = [&](int& src, bool& flag) {
            if (src == agent_idx) { src = -1; flag = false; dirty = true; }
        };

        clear_ref(c.charmed_by);
        clear_ref(c.retaliation_target_idx);
        clear_ref(c.eldritch_strike_by);
        clear_ref(c.goaded_by);
        clear_ref(c.distracted_by);
        clear_ref(c.feint_target_idx);
        clear_ref(c.vex_target_idx);
        clear_ref(c.sundering_target_idx);
        clear_marked(c.disarmed_by,        c.disarmed);
        clear_marked(c.crusher_marked_by,  c.crusher_marked);
        clear_marked(c.slasher_marked_by,  c.slasher_marked);
        clear_marked(c.zealous_blessing_by, c.zealous_blessing);

        // Hunter Multiattack Defense tracks a list of attackers — drop this agent from it.
        auto& hit_by = c.multiattack_def_hit_by;
        if (!hit_by.empty()) {
            auto it = std::remove(hit_by.begin(), hit_by.end(), agent_idx);
            if (it != hit_by.end()) { hit_by.erase(it, hit_by.end()); dirty = true; }
        }

        if (dirty) setAgentConditions(bm, static_cast<int>(i), c);
    }
}

bool CombatEngine::grapplerActive(const BattleMap& bm, int victim_idx) const noexcept
{
    const auto& agents = bm.placedAgents();
    if (victim_idx < 0 || victim_idx >= static_cast<int>(agents.size())) return false;
    Agent::Conditions vc = bm.getAgentConditions(victim_idx);
    if (!vc.grappled) return false;
    const int g = vc.grappler_idx;
    if (g < 0 || g >= static_cast<int>(agents.size())) return false;   // stale / out-of-bounds
    Agent::Conditions gc = bm.getAgentConditions(g);
    const Agent::Stats& gs = bm.getAgentStats(g);
    // A grapple ends the instant the grappler is Incapacitated/Unconscious/dead (RAW).
    if (gc.dead || gc.unconscious || gc.incapacitated || gs.hp_cur <= 0) return false;
    return true;
}

void CombatEngine::reconcileGrapples(BattleMap& bm) noexcept
{
    auto agents = bm.placedAgents();
    for (std::size_t i = 0; i < agents.size(); ++i) {
        Agent::Conditions vc = getAgentConditions(bm, static_cast<int>(i));
        if (!vc.grappled) continue;
        if (grapplerActive(bm, static_cast<int>(i))) continue;   // grapple still legitimately held
        vc.grappled = false;
        vc.grappler_idx = -1;
        setAgentConditions(bm, static_cast<int>(i), vc);
        log_("{}'s grapple ends: the grappler can no longer maintain it",
             agentName(bm, static_cast<int>(i)));
    }
}

void CombatEngine::applyCommandEffect(BattleMap& bm, int bard_idx, int target_idx, int word) noexcept
{
    auto agents = bm.placedAgents();
    if (target_idx < 0 || target_idx >= static_cast<int>(agents.size())) return;
    if (word < 0 || word > 4) word = 3;  // default to Halt when the caller doesn't specify a word

    // The movement / incapacitation effects are keyed to the bard with a 1-turn duration, so they
    // expire when the bard's next turn begins (tickAgentConditionsForCaster) — i.e. they constrain
    // exactly the target's one intervening "next turn", matching Command's RAW timing.
    switch (word) {
        case 0: {  // Drop — drops what it's holding (reuse the Disarming Strike path)
            dropAgentWeapons(bm, target_idx);
            Agent::Conditions tc = bm.getAgentConditions(target_idx);
            tc.disarmed    = true;
            tc.disarmed_by = bard_idx;
            bm.setAgentConditions(target_idx, tc);
            log_("Command (Drop): {} drops what it is holding", agentName(bm, target_idx));
            break;
        }
        case 1: {  // Flee — moves away from the bard; modeled as a 1-turn "can't approach" restriction
            ActiveAgentCondition c;
            c.agent_idx       = target_idx;
            c.caster_idx      = bard_idx;
            c.condition_name  = "CommandFlee";
            c.turns_remaining = 1;
            c.save_repeat_turns = -1;  // Command grants NO repeated save (RAW). Without this the struct
                                       // default (repeat every turn, DC 0, SaveDex) auto-passes at the
                                       // victim's turn start and strips the command before it can flee.
            (void)addAgentCondition(bm, c);
            log_("Command (Flee): {} must move away from {} on its next turn",
                 agentName(bm, target_idx), agentName(bm, bard_idx));
            break;
        }
        case 2:    // Grovel — the target falls Prone and ends its turn
            applyProne(bm, target_idx);
            log_("Command (Grovel): {} falls Prone", agentName(bm, target_idx));
            break;
        case 3: {  // Halt — no move, no action, no Bonus Action next turn (Incapacitated for one turn)
            ActiveAgentCondition c;
            c.agent_idx        = target_idx;
            c.caster_idx       = bard_idx;
            c.condition_name   = "Incapacitated";
            c.turns_remaining  = 1;
            c.save_repeat_turns = -1;  // no save — the target simply skips its next turn
            (void)addAgentCondition(bm, c);
            log_("Command (Halt): {} won't move or act on its next turn", agentName(bm, target_idx));
            break;
        }
        case 4: {  // Approach — moves toward the bard; modeled as a 1-turn "can't retreat" restriction
            ActiveAgentCondition c;
            c.agent_idx       = target_idx;
            c.caster_idx      = bard_idx;
            c.condition_name  = "CommandApproach";
            c.turns_remaining = 1;
            c.save_repeat_turns = -1;  // no repeated save (RAW) — see the Flee case above
            (void)addAgentCondition(bm, c);
            log_("Command (Approach): {} must move toward {} on its next turn",
                 agentName(bm, target_idx), agentName(bm, bard_idx));
            break;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Condition lifecycle
// ─────────────────────────────────────────────────────────────────────────────

int CombatEngine::addAgentCondition(BattleMap& bm, ActiveAgentCondition cond) noexcept
{
    cond.condition_id = nextConditionId_++;

    // Apply the condition to the agent
    if (cond.agent_idx >= 0) {
        auto agents = bm.placedAgents();
        if (cond.agent_idx < static_cast<int>(agents.size())) {
            if (cond.condition_name == "Paralyzed") {
                applyParalyzed(bm, cond.agent_idx);
            } else if (cond.condition_name == "Blinded") {
                applyBlinded(bm, cond.agent_idx);
            } else if (cond.condition_name == "Incapacitated") {
                applyIncapacitated(bm, cond.agent_idx);
            } else if (cond.condition_name == "Stunned") {
                applyStunned(bm, cond.agent_idx);
            } else if (cond.condition_name == "Charmed") {
                applyCharmed(bm, cond.agent_idx);
                // Track the charm source so Mantle of Majesty can auto-fail Command for a creature
                // Charmed by the casting bard.
                auto cc = bm.getAgentConditions(cond.agent_idx);
                cc.charmed_by = cond.caster_idx;
                bm.setAgentConditions(cond.agent_idx, cc);
            } else if (cond.condition_name == "Frightened") {
                applyFrightened(bm, cond.agent_idx);
            } else if (cond.condition_name == "Restrained") {
                auto ac = bm.getAgentConditions(cond.agent_idx);
                ac.restrained = true;
                bm.setAgentConditions(cond.agent_idx, ac);
            } else if (cond.condition_name == "Unconscious") {
                applyUnconscious(bm, cond.agent_idx);
            } else if (cond.condition_name == "Poisoned") {
                applyPoisoned(bm, cond.agent_idx);
            } else if (cond.condition_name == "Deafened") {
                applyDeafened(bm, cond.agent_idx);
            } else if (cond.condition_name == "Petrified") {
                applyPetrified(bm, cond.agent_idx);
            } else if (cond.condition_name == "Invisible" || cond.condition_name == "GreaterInvisible") {
                auto ac = bm.getAgentConditions(cond.agent_idx);
                ac.invisible = true;
                // Greater Invisibility does not end when the creature attacks or casts.
                ac.invisible_persists_on_action = (cond.condition_name == "GreaterInvisible");
                bm.setAgentConditions(cond.agent_idx, ac);
            } else if (cond.condition_name == "Sanctuary") {
                // Sanctuary ward: store the WIS save DC attackers must beat (the caster's spell save DC).
                auto ac = bm.getAgentConditions(cond.agent_idx);
                ac.sanctuary_active = true;
                ac.sanctuary_dc     = cond.save_dc;
                bm.setAgentConditions(cond.agent_idx, ac);
            } else if (cond.condition_name == "Gaseous") {
                // Gaseous Form (self-buff). A vampire's Misty Escape grants Immunity to physical
                // damage instead of Resistance — driven by the target's is_vampire, so the exception
                // is intrinsic to being a vampire rather than keyed off the spell name.
                const bool physical_immune = bm.getAgentStats(cond.agent_idx).is_vampire;
                applyGaseousForm(bm, cond.agent_idx, physical_immune);
            } else if (cond.condition_name == "Blessed") {
                // Bless (Phase 1) — flag lives on Stats so it reaches rollToHit/rollSpellAttack
                // (const Agent::Stats&) and saveModFor. Cleared via clearSpellConditionEffect.
                Agent::Stats st = bm.getAgentStats(cond.agent_idx);
                st.blessed = true;
                bm.setAgentStats(cond.agent_idx, st);
            } else if (cond.condition_name == "Hasted") {
                // Haste (Phase 2) — +2 AC, Advantage on DEX saves, doubled walk Speed, and an
                // extra limited action each turn (refilled in beginTurn). Idempotent: never stack
                // the buff, so a re-cast can't double the AC/speed. The exact walk-speed bonus is
                // recorded so clearSpellConditionEffect restores Speed precisely.
                Agent::Stats st = bm.getAgentStats(cond.agent_idx);
                if (!st.hasted) {
                    st.ac_temporary_modifications += 2;
                    st.haste_speed_bonus = st.speed_walk;
                    st.speed_walk       += st.haste_speed_bonus;
                    st.save_advantage_mask |= (1 << SaveDex);
                    st.haste_action_available = true;
                    st.hasted = true;
                    bm.setAgentStats(cond.agent_idx, st);
                }
            } else if (cond.condition_name == "HasteLethargy") {
                // Haste's end-of-spell lethargy — Incapacitated + Speed 0 until the end of the
                // target's next turn. Route through applyIncapacitated for the shared side-effects
                // (movement→0, grapples released, concentration broken), then zero the walk Speed
                // itself so beginTurn's refill still yields 0. haste_speed_bonus (0 once Haste is
                // fully torn down) holds the speed to give back when this condition ends.
                applyIncapacitated(bm, cond.agent_idx);
                Agent::Stats st = bm.getAgentStats(cond.agent_idx);
                st.haste_speed_bonus = st.speed_walk;
                st.speed_walk = 0;
                bm.setAgentStats(cond.agent_idx, st);
            } else if (cond.condition_name == "Aided") {
                // Aid (Phase 3) — raise both maximum and current HP by 5, +5 per slot level above 2.
                // cast_level (Phase 0.2) carries the actual slot used. Idempotent: never stack the
                // bonus, so a re-cast can't permanently inflate hp_max. The granted amount is stashed
                // in aid_hp_bonus so clearSpellConditionEffect gives back exactly what it added.
                Agent::Stats st = bm.getAgentStats(cond.agent_idx);
                if (st.aid_hp_bonus == 0) {
                    const int bonus = 5 * (1 + std::max(0, cond.cast_level - 2));
                    st.hp_max      += bonus;
                    st.aid_hp_bonus = bonus;
                    bm.setAgentStats(cond.agent_idx, st);
                    // Route the current-HP gain through healAgent so a downed ally is revived and
                    // rejoins initiative (the short-rest heal sets this precedent). Caps at the
                    // freshly raised effectiveMaxHp.
                    healAgent(bm, cond.agent_idx, bonus);
                }
            }
            log_("Applied condition '{}' to {} for {} turns",
                 cond.condition_name, agentName(bm, cond.agent_idx), cond.turns_remaining);
        }
    }

    activeAgentConditions_.push_back(cond);
    return cond.condition_id;
}

void CombatEngine::removeAgentCondition(BattleMap& bm, int condition_id) noexcept
{
    auto it = std::find_if(activeAgentConditions_.begin(), activeAgentConditions_.end(),
                          [condition_id](const ActiveAgentCondition& c) { return c.condition_id == condition_id; });
    if (it != activeAgentConditions_.end()) {
        // Fire the caster "kickback" (Vistani Curse) on a copy BEFORE erasing — onConditionEnded
        // may apply damage that drops the caster and cascades into dropConcentration →
        // removeAgentCondition, mutating this container. No-op unless kickback_dice > 0.
        ActiveAgentCondition ended = *it;
        activeAgentConditions_.erase(it);
        onConditionEnded(bm, ended);
    }
}

const std::vector<ActiveAgentCondition>& CombatEngine::activeAgentConditions() const noexcept
{
    return activeAgentConditions_;
}

std::vector<int> CombatEngine::tickAgentConditions(BattleMap& bm) noexcept
{
    std::vector<int> removed_ids;
    // Delayed effects that auto-detonate on expiry (Delayed Blast Fireball) are resolved AFTER the
    // loop: resolveDelayedEffect can drop a creature unconscious → dropConcentration, which mutates
    // activeAgentConditions_ and would invalidate the iterators below. Copy them out and fire later.
    std::vector<ActiveAgentCondition> auto_detonate;
    // Every ended condition is torn down AFTER the list is rebuilt, through the onConditionEnded
    // chokepoint (flags + curse teardown + kickback). Deferred because that teardown may ADD a new
    // condition (Haste lethargy) or cascade into dropConcentration (curse kickback) — either would
    // invalidate the iterators below if fired mid-loop.
    std::vector<ActiveAgentCondition> ended;

    for (auto& cond : activeAgentConditions_) {
        --cond.turns_remaining;
        if (cond.turns_remaining <= 0) {
            removed_ids.push_back(cond.condition_id);
            // Owner-triggered effects (Quivering Palm) leave delay_auto_on_expire false and simply
            // fade harmlessly when the duration runs out.
            if (cond.delayed_trigger && cond.delay_auto_on_expire)
                auto_detonate.push_back(cond);
            ended.push_back(cond);
            if (cond.agent_idx >= 0 && cond.agent_idx < static_cast<int>(bm.placedAgents().size()))
                log_("Condition '{}' expired for {}",
                     cond.condition_name, agentName(bm, cond.agent_idx));
        }
    }

    // Remove expired conditions
    std::vector<ActiveAgentCondition> remaining;
    for (const auto& cond : activeAgentConditions_) {
        if (std::find(removed_ids.begin(), removed_ids.end(), cond.condition_id) == removed_ids.end()) {
            remaining.push_back(cond);
        }
    }
    activeAgentConditions_ = remaining;

    // List is stable again — fire auto-detonations first (Delayed Blast Fireball), then run the
    // single-chokepoint teardown for every ended condition.
    for (const auto& cond : auto_detonate)
        (void)resolveDelayedEffect(bm, cond);
    for (const auto& cond : ended)
        onConditionEnded(bm, cond);

    return removed_ids;
}

std::vector<int> CombatEngine::tickAgentConditionsForCaster(BattleMap& bm, int caster_idx) noexcept
{
    std::vector<int> removed_ids;
    // Every ended condition is torn down after the rebuild through the onConditionEnded chokepoint —
    // same iterator-stability rationale as tickAgentConditions (teardown may add a condition or
    // cascade into dropConcentration).
    std::vector<ActiveAgentCondition> ended;

    for (auto& cond : activeAgentConditions_) {
        // Only tick conditions cast by this caster
        if (cond.caster_idx != caster_idx) continue;

        --cond.turns_remaining;
        if (cond.turns_remaining <= 0) {
            removed_ids.push_back(cond.condition_id);
            ended.push_back(cond);
            if (cond.agent_idx >= 0 && cond.agent_idx < static_cast<int>(bm.placedAgents().size()))
                log_("Condition '{}' expired for {} (spell duration ended)",
                     cond.condition_name, agentName(bm, cond.agent_idx));
        }
    }

    // Remove expired conditions
    std::vector<ActiveAgentCondition> remaining;
    for (const auto& cond : activeAgentConditions_) {
        if (std::find(removed_ids.begin(), removed_ids.end(), cond.condition_id) == removed_ids.end()) {
            remaining.push_back(cond);
        }
    }
    activeAgentConditions_ = remaining;

    // Container is stable again — run the single-chokepoint teardown for every ended condition.
    for (const auto& cond : ended)
        onConditionEnded(bm, cond);

    return removed_ids;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Delayed / stored effects (general mechanism)
// ─────────────────────────────────────────────────────────────────────────────

namespace {
    // File-local damage-type name for delayed-effect log lines (combat_resources.cpp's elementName
    // lives in its own anonymous namespace and isn't visible here).
    const char* delayDamageName(MagicDamage_t t) noexcept {
        switch (t) {
            case Acid: return "Acid";   case Cold: return "Cold";   case Fire: return "Fire";
            case Force: return "Force"; case Lightning: return "Lightning"; case Necrotic: return "Necrotic";
            case Poison: return "Poison"; case Psychic: return "Psychic"; case Radiant: return "Radiant";
            case Thunder: return "Thunder"; default: return "damage";
        }
    }
}

int CombatEngine::resolveDelayedEffect(BattleMap& bm, const ActiveAgentCondition& cond) noexcept
{
    const auto& agents = bm.placedAgents();
    const int t = cond.agent_idx;
    if (t < 0 || t >= static_cast<int>(agents.size())) return 0;

    Agent::Stats ts = bm.getAgentStats(t);
    if (ts.hp_max == 0 && ts.hp_cur == 0) return 0;          // not a real combatant

    const std::string label = cond.delay_label.empty() ? cond.condition_name : cond.delay_label;

    // Roll the stored dice + flat bonus.
    int rolled = cond.delay_flat_bonus;
    for (int i = 0; i < cond.delay_dice; ++i)
        rolled += roll(cond.delay_die_size > 0 ? cond.delay_die_size : 1);

    // The owner's stats drive the multiplier (target-side resistance / vulnerability honored).
    Agent::Stats owner = (cond.caster_idx >= 0 && cond.caster_idx < static_cast<int>(agents.size()))
                       ? bm.getAgentStats(cond.caster_idx) : Agent::Stats{};
    float multiplier = effectiveMagicDamageMult(owner, ts, cond.delay_damage_type, true);
    int dmg = static_cast<int>(static_cast<float>(rolled) * multiplier);

    bool saved = false;
    if (cond.delay_requires_save) {
        int save_d20 = roll(20);
        int save_mod = saveModFor(bm, t, cond.save_ability);
        int save_tot = applyIndomitableMight(bm, t, cond.save_ability, save_d20 + save_mod);
        saved = (save_tot >= cond.save_dc);
        log_("{} {} {} ({} vs DC {})", agentName(bm, t),
             saved ? "saves vs" : "fails the save against", label, save_tot, cond.save_dc);
    }

    // Drop-to-zero variant (2014-style Quivering Palm): a failed save reduces the target to 0 HP
    // outright, ignoring the rolled dice. Otherwise a successful save halves (or negates) the damage.
    if (cond.delay_drop_to_zero && !saved) {
        dmg = ts.hp_cur + ts.temp_hp;
    } else if (saved) {
        dmg = cond.delay_half_on_save ? dmg / 2 : 0;
    }

    log_("{} detonates on {}: {} {} damage",
         label, agentName(bm, t), dmg, delayDamageName(cond.delay_damage_type));

    if (dmg > 0) {
        // Apply temp HP first, then real HP (mirrors elementalBurst / applyHandOfHarmEffect).
        int overflow = std::max(0, dmg - ts.temp_hp);
        ts.temp_hp = std::max(0, ts.temp_hp - dmg);
        ts.hp_cur  = std::clamp(ts.hp_cur - overflow, 0, ts.hp_max);
        bm.setAgentStats(t, ts);

        checkConcentrationOnDamage(bm, t, dmg);
        processDamageTaken(bm, t, dmg);
        if (ts.hp_cur <= 0) {
            Agent::Conditions tc = bm.getAgentConditions(t);
            if (!tc.unconscious && !tc.dead) applyUnconscious(bm, t);
        }
    }
    return dmg;
}

void CombatEngine::onConditionEnded(BattleMap& bm, const ActiveAgentCondition& cond) noexcept
{
    const auto& agents = bm.placedAgents();

    // ── Base-flag teardown (THE single chokepoint) ──────────────────────────────
    // Reverse the condition's base-flag effect (paralyzed/charmed/invisible/gaseous/…) so speed,
    // actions, and visibility are restored on EVERY end path — save success, duration expiry,
    // concentration drop, Dispel Magic, and death cleanup all funnel through here. Buff-spell
    // teardowns (Bless/Haste/Aid) will hang off this call site too.
    clearSpellConditionEffect(bm, cond);

    // ── Vistani Curse of Vulnerability teardown ─────────────────────────────────
    // Restore the target's prior damage multiplier for the cursed type. Done on EVERY
    // end path (before the kickback gates below) so the vulnerability never lingers.
    if (cond.curse_vuln_type_code >= 0) {
        const int tv = cond.agent_idx;
        if (tv >= 0 && tv < static_cast<int>(agents.size())) {
            Agent::Stats ts = bm.getAgentStats(tv);
            const int code = cond.curse_vuln_type_code;
            if (code >= 100) {
                const int pi = code - 100;
                if (pi >= 0 && pi < NumPhysicalDamage_t)
                    ts.physical_damage_multipliers[static_cast<std::size_t>(pi)] = cond.curse_vuln_prev_mult;
            } else if (code < NumMagicDamage_t) {
                ts.magic_damage_multipliers[static_cast<std::size_t>(code)] = cond.curse_vuln_prev_mult;
            }
            bm.setAgentStats(tv, ts);
        }
    }

    // Only curse-style conditions carry a kickback; everything else ends silently here.
    if (cond.kickback_dice <= 0) return;

    // Decision (LOCKED, Vistani plan): no kickback when the cursed target has died — the Vistana
    // is not punished for killing its victim. The tracking entry may still reach an end-path
    // (e.g. duration expiry) while the target is dead, so gate here rather than at each call site.
    const int t = cond.agent_idx;
    if (t >= 0 && t < static_cast<int>(agents.size())) {
        Agent::Conditions tc = bm.getAgentConditions(t);
        if (tc.dead || bm.getAgentStats(t).hp_cur <= 0) return;
    }

    const int c = cond.caster_idx;
    if (c < 0 || c >= static_cast<int>(agents.size())) return;

    Agent::Stats cs = bm.getAgentStats(c);
    if (cs.hp_max == 0 && cs.hp_cur == 0) return;               // not a real combatant

    // Roll the kickback dice (automatic — no save).
    int rolled = 0;
    for (int i = 0; i < cond.kickback_dice; ++i)
        rolled += roll(cond.kickback_die_size > 0 ? cond.kickback_die_size : 1);

    // Honor the caster's own resistance / vulnerability to the kickback damage type.
    float multiplier = effectiveMagicDamageMult(cs, cs, cond.kickback_damage_type, true);
    int dmg = static_cast<int>(static_cast<float>(rolled) * multiplier);

    log_("Curse rebounds on {}: {} {} damage",
         agentName(bm, c), dmg, delayDamageName(cond.kickback_damage_type));

    if (dmg > 0) {
        // Apply temp HP first, then real HP (mirrors resolveDelayedEffect).
        int overflow = std::max(0, dmg - cs.temp_hp);
        cs.temp_hp = std::max(0, cs.temp_hp - dmg);
        cs.hp_cur  = std::clamp(cs.hp_cur - overflow, 0, cs.hp_max);
        bm.setAgentStats(c, cs);

        checkConcentrationOnDamage(bm, c, dmg);
        processDamageTaken(bm, c, dmg);
        if (cs.hp_cur <= 0) {
            Agent::Conditions cc = bm.getAgentConditions(c);
            if (!cc.unconscious && !cc.dead) applyUnconscious(bm, c);
        }
    }
}

int CombatEngine::triggerDelayedEffect(BattleMap& bm, int condition_id) noexcept
{
    auto it = std::find_if(activeAgentConditions_.begin(), activeAgentConditions_.end(),
                           [condition_id](const ActiveAgentCondition& c) {
                               return c.condition_id == condition_id && c.delayed_trigger; });
    if (it == activeAgentConditions_.end()) {
        log_("triggerDelayedEffect: no delayed effect with id {}", condition_id);
        return -1;
    }
    // Resolve on a copy, then remove the planted condition (it is spent whether it hits or misses).
    ActiveAgentCondition cond = *it;
    int dmg = resolveDelayedEffect(bm, cond);
    removeAgentCondition(bm, condition_id);
    return dmg;
}

} // namespace rpg
