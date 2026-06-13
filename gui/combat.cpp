// ─────────────────────────────────────────────────────────────────────────────
//  combat.cpp  –  residual non-CombatEngine definitions
// ─────────────────────────────────────────────────────────────────────────────
//
//  The CombatEngine implementation has been split into focused translation units
//  (see combat_internal.hpp for the shared helpers and the combat_*.cpp files for
//  each subsystem). What remains here is Agent::Stats::initializeClassResources,
//  which is a member of Agent::Stats — not CombatEngine — and so did not belong in
//  any of the engine buckets.
//
#include "combat.hpp"
#include "battle_map.hpp"

#include <algorithm>

namespace rpg {

// ── Resource Initialization by Class and Level ──────────────────────────────
void Agent::Stats::initializeClassResources(CharacterClass cls, int level) {
  resources.clear();

  switch (cls) {
    case Barbarian: {
      // Rage: uses per day scales with level
      // Level 1-2: 2 uses, Level 3-4: 3 uses, Level 5-6: 3 uses, Level 7-8: 4 uses,
      // Level 9-10: 4 uses, Level 11-12: 4 uses, Level 13-14: 5 uses, Level 15-16: 5 uses,
      // Level 17-18: 6 uses, Level 19-20: 6 uses (but 20 is unlimited)
      int rage_uses = 2;
      if (level >= 3) rage_uses = 3;
      if (level >= 5) rage_uses = 3;
      if (level >= 7) rage_uses = 4;
      if (level >= 9) rage_uses = 4;
      if (level >= 11) rage_uses = 4;
      if (level >= 13) rage_uses = 5;
      if (level >= 15) rage_uses = 5;
      if (level >= 17) rage_uses = 6;

      Resource rage("Rage", rage_uses, 10);  // 10-turn duration (~1 minute)
      rage.short_rest_regen = 1;  // regain 1 use on short rest
      rage.long_rest_regen = rage_uses;
      resources["Rage"] = rage;

      // Extra Attack (L5+): gain second weapon attack per action
      if (level >= 5) {
        num_attacks = 2;
      }

      // Fast Movement (L5+): +10 feet speed (not in heavy armor, but we can't check that here)
      if (level >= 5) {
        speed_walk += 10;
      }

      // Brutal Strike (L9+): 1d10 damage; L17+: 2d10 damage
      if (level >= 9) {
        brutal_strike_damage_dice = 1;
      }
      if (level >= 17) {
        brutal_strike_damage_dice = 2;
      }
      break;
    }

    case Monk: {
      // Chassis: Dexterity + Wisdom save proficiencies
      save_prof_dex = true;
      save_prof_wis = true;

      // Focus Points: number of focus points = character level
      Resource focus_points("Focus Points", level, 0);  // no duration
      focus_points.short_rest_regen = level;  // fully restored on short rest
      focus_points.long_rest_regen = level;
      resources["Focus Points"] = focus_points;

      // Extra Attack (L5+): 2 attacks per action
      if (level >= 5) {
        num_attacks = 2;
      }

      // Unarmored Defense (L1+): AC = 10 + DEX + WIS is applied in the AC calculation
      // (see the Monk branch in computeAC ~combat.cpp:313), so nothing to grant here.
      break;
    }

    case Rogue: {
      // Chassis: Dexterity + Intelligence saving-throw proficiencies.
      save_prof_dex = true;
      save_prof_intel = true;
      // Cunning Action (L2+): Dash/Disengage/Hide as a bonus action.
      if (level >= 2) has_cunning_action = true;
      // Slippery Mind (L15+): proficiency in Wisdom and Charisma saves.
      if (level >= 15) {
        save_prof_wis = true;
        save_prof_cha = true;
      }
      break;
    }

    case Sorcerer: {
      // Chassis: Constitution + Charisma saving-throw proficiencies (2024 PHB)
      save_prof_con = true;
      save_prof_cha = true;

      // Subclass features (Phase 3, combat-core slice):
      //   Draconic L3 — Draconic Resilience: AC = 10 + DEX + CHA (applied in computeAC).
      //   Wild Magic L6 — Bend Luck: see sorcererBendLuck (spends Sorcery Points).
      // Deferred (see known_limitations.md): Draconic Elemental Affinity + HP bonus,
      // Wild Magic Surge table / Tides of Chaos, Clockwork (reaction interrupt), Aberrant
      // (psionic spell list cast via SP).

      // Sorcery Points: equal to sorcerer level
      Resource sp("Sorcery Points", level, 0);
      sp.short_rest_regen = 0;
      sp.long_rest_regen = level;
      resources["Sorcery Points"] = sp;

      // Innate Sorcery (L1): Bonus Action self-buff, 2 uses, regain on long rest.
      Resource innate("Innate Sorcery", 2, 0);
      innate.short_rest_regen = 0;
      innate.long_rest_regen = 2;
      resources["Innate Sorcery"] = innate;
      break;
    }

    case Fighter: {
      // Extra Attack (L5+): 2 at L5, 3 at L11, 4 at L20
      if (level >= 20) {
        num_attacks = 4;
      } else if (level >= 11) {
        num_attacks = 3;
      } else if (level >= 5) {
        num_attacks = 2;
      }

      // Second Wind (L1+): 1d10 + level, regains on short/long rest
      int sw_uses = 1;
      Resource sw("Second Wind", sw_uses, 0);
      sw.short_rest_regen = 1;
      sw.long_rest_regen = 1;
      resources["Second Wind"] = sw;

      // Action Surge (L1+): 1 use at L1, 2 at L17, regains on long rest
      int as_uses = (level >= 17) ? 2 : 1;
      Resource as("Action Surge", as_uses, 0);
      as.long_rest_regen = as_uses;
      resources["Action Surge"] = as;

      // Indomitable (L9+): reroll a failed saving throw (+ Fighter level on the new roll). 1 use at L9,
      // 2 at L13, 3 at L17. Regains on long rest. Consumed by the OnSaveFail reaction window
      // costs the use only, not the reaction (RAW "no action").
      if (level >= 9) {
        int ind_uses = (level >= 17) ? 3 : (level >= 13) ? 2 : 1;
        Resource ind("Indomitable", ind_uses, 0);
        ind.long_rest_regen = ind_uses;
        resources["Indomitable"] = ind;
      }

      // Weapon Mastery (L1+): activate the mastery system
      weapon_mastery = 1;

      // Champion: lower crit threshold
      if (fighter_subclass == ChampionPath) {
        if (level >= 15) {
          crit_threshold = 18;  // L15: critical on 18-20
        } else if (level >= 3) {
          crit_threshold = 19;  // L3: critical on 19-20
        }
      }

      // Battle Master: Superiority Dice resource (4 at L3, 5 at L7, 6 at L10, 7 at L15, 8 at L18)
      if (fighter_subclass == BattleMasterPath) {
        int sd_count = 0;
        if (level >= 18)      sd_count = 8;
        else if (level >= 15) sd_count = 7;
        else if (level >= 10) sd_count = 6;
        else if (level >= 7)  sd_count = 5;
        else if (level >= 3)  sd_count = 4;
        if (sd_count > 0) {
          Resource sd("Superiority Dice", sd_count, 0);
          sd.short_rest_regen = sd_count;
          sd.long_rest_regen  = sd_count;
          resources["Superiority Dice"] = sd;
          superiority_die_size = (level >= 10) ? 10 : 8;
        }
      }

      // Psi Warrior (L3+): Psionic Energy Dice = 2 × proficiency bonus; die size scales by level.
      // Also grants Telekinetic Movement (once per short/long rest).
      if (fighter_subclass == PsiWarriorPath && level >= 3) {
        int prof = 2 + (level - 1) / 4;          // PHB proficiency bonus by level
        int ped_count = 2 * prof;
        Resource ped("Psionic Energy", ped_count, 0);
        ped.short_rest_regen = 1;                // regain one die on a short rest
        ped.long_rest_regen  = ped_count;        // all dice on a long rest
        resources["Psionic Energy"] = ped;
        psionic_die_size = (level >= 17) ? 12 : (level >= 11) ? 10 : (level >= 5) ? 8 : 6;

        Resource tk("Telekinetic Movement", 1, 0);
        tk.short_rest_regen = 1;
        tk.long_rest_regen  = 1;
        resources["Telekinetic Movement"] = tk;
      }

      // Eldritch Knight (L3+): third-caster, INT, Wizard spell list. compute_class_slots(Fighter)
      // returns zeros (it can't see the subclass), so override the slot table here. This runs
      // AFTER set_class_level and AFTER fighter_subclass is set (see main.py apply order), so the
      // override sticks. Cantrips/spells themselves come from the normal spell-assignment UI.
      if (fighter_subclass == EldritchKnightPath && level >= 3) {
        spell_slots_max       = compute_third_caster_slots(level);
        spell_slots_remaining = spell_slots_max;
        spellcasting_ability  = 3;   // 3 = INT (SaveAbility_t::SaveInt), matches Wizard chassis
        can_cast_spell        = true;
      }
      break;
    }

    case Druid: {
      // Druid: WIS full caster (like Cleric)
      spellcasting_ability = 4;  // 4 = WIS (SaveAbility_t::SaveWis)
      can_cast_spell = true;
      save_prof_intel = true;
      save_prof_wis = true;

      // Weapon Mastery (L1+): activate the mastery system for beast form attacks
      weapon_mastery = 1;

      // Wild Shape (L2+): uses scale with level
      // L2-5: 2 uses, L6-16: 3 uses, L17+: 4 uses
      int ws_uses = 0;
      if (level >= 2) ws_uses = 2;
      if (level >= 6) ws_uses = 3;
      if (level >= 17) ws_uses = 4;
      // Note: Wild Shape can be used unlimited times at L20, but that's handled separately

      Resource ws("Wild Shape", ws_uses, 0);
      ws.short_rest_regen = 1;  // regain one use on short rest
      ws.long_rest_regen = ws_uses;  // full on long rest
      resources["Wild Shape"] = ws;
      break;
    }

    case Cleric: {
      // Channel Divinity (2024): 2 uses at L2, 3 at L6, 4 at L18 (none before L2).
      // Regain one use on a Short Rest, all on a Long Rest.
      int cd_uses = (level >= 18) ? 4 : (level >= 6) ? 3 : (level >= 2) ? 2 : 0;
      Resource cd("Channel Divinity", cd_uses, 0);
      cd.short_rest_regen = 1;       // regain one use on a short rest
      cd.long_rest_regen = cd_uses;  // full on a long rest
      resources["Channel Divinity"] = cd;

      // War Domain — War Priest (L3+): WIS-mod (min 1) bonus-action weapon attacks per Short/Long Rest.
      if (cleric_subclass == WarDomain && level >= 3) {
        int wp = std::max(1, _mod(wis));
        Resource war_priest("War Priest", wp, 0);
        war_priest.short_rest_regen = wp;  // regained on a Short or Long Rest
        war_priest.long_rest_regen = wp;
        resources["War Priest"] = war_priest;
      }
      break;
    }

    case Wizard: {
      // Arcane Recovery: recover spell levels = ceil(level / 2) once per long rest
      // Full mechanic deferred; for now just track the resource exists
      Resource ar("Arcane Recovery", 1, 0);  // 1 use per long rest
      ar.long_rest_regen = 1;
      resources["Arcane Recovery"] = ar;

      // Memorize Spell (L5+): swap 1 prepared spell after short rest
      if (level >= 5) {
        Resource ms("Memorize Spell", 1, 0);  // 1 use per short rest
        ms.short_rest_regen = 1;
        ms.long_rest_regen = 1;  // Also restored on long rest
        resources["Memorize Spell"] = ms;
      }

      // Portent Dice (L3+): Diviner only, but we create the resource for all Wizards
      // It will only be usable if wizard_subclass == Diviner
      if (level >= 3) {
        int portent_max = 2;
        if (level >= 14) portent_max = 3;
        Resource pd("Portent Dice", portent_max, 0);  // Uses per long rest
        pd.long_rest_regen = portent_max;
        resources["Portent Dice"] = pd;
        // Note: portent_dice deque will be populated on long rest or first use
      }

      // Spellcasting ability is INT for Wizards
      spellcasting_ability = 3;  // 3 = INT (SaveAbility_t::SaveInt)

      // Cantrips known: 3 at L1, +1 at L4 and L10
      // This is tracked separately in the spell system; just mark can_cast_spell
      can_cast_spell = true;

      break;
    }

    case Warlock: {
      // Pact Magic: Charisma caster. Pact slots come from kPact (set by set_class_level);
      // they all share one level and recharge on a SHORT or long rest.
      spellcasting_ability = 5;  // 5 = CHA
      can_cast_spell = true;
      save_prof_wis = true;      // Warlock saving-throw proficiencies: WIS and CHA
      save_prof_cha = true;
      spell_slots_remaining = spell_slots_max;  // start with pact slots full

      // Magical Cunning (L2+): once per long rest, recover expended pact slots up to
      // ceil(max/2) — or all of them at L20 (Eldritch Master). See useMagicalCunning.
      if (level >= 2) {
        Resource mc("Magical Cunning", 1, 1);  // 1 use, available now, restored on long rest
        mc.long_rest_regen = 1;
        resources["Magical Cunning"] = mc;
      }

      // Subclass-specific features
      if (warlock_subclass == FiendPath && level >= 10 && fiendish_resilience_type >= 0) {
        set_magic_damage_multiplier(fiendish_resilience_type, 0.5f);
      }
      if (warlock_subclass == CelestialPath && level >= 6) {
        set_magic_damage_multiplier(8 /* Radiant */, 0.5f);
      }
      if (warlock_subclass == GreatOldOnePath && level >= 10) {
        set_magic_damage_multiplier(7 /* Psychic */, 0.5f);
      }

      // Healing Light (Celestial L3): pool of d6 healing
      if (warlock_subclass == CelestialPath && level >= 3) {
        Resource hl("Healing Light", 1 + level, 1 + level);
        hl.long_rest_regen = 1 + level;
        resources["Healing Light"] = hl;
      }

      // Thirsting Blade (invocation 14, L5+, requires Pact of the Blade): a second
      // attack with the pact weapon as part of the Attack action. Modeled as the engine's
      // global Extra Attack (num_attacks = 2). v1 simplification: this is not gated to
      // pact-weapon attacks only — a Thirsting-Blade Warlock gets two swings with any
      // weapon, matching how every other class's Extra Attack is global.
      if (level >= 5 && hasInvocation(14) && hasInvocation(13)) {
        num_attacks = 2;
        // Devouring Blade (invocation 17, L12+, requires Thirsting Blade): the extra attack
        // becomes TWO extra attacks → three total.
        if (level >= 12 && hasInvocation(17))
          num_attacks = 3;
      }
      break;
    }

    case Paladin: {
      // Paladin: CHA half-caster (spell slots already set via set_class_level using kHalf column)
      spellcasting_ability = 5;  // 5 = CHA (SaveAbility_t::SaveCha)
      can_cast_spell = true;
      save_prof_wis = true;

      // Extra Attack (L5+): 2 attacks per action
      if (level >= 5) {
        num_attacks = 2;
      }

      // Channel Oath (L1+): 2 uses at L1, 3 at L6, 4 at L18 (like Channel Divinity)
      int co_uses = (level >= 18) ? 4 : (level >= 6) ? 3 : 2;
      Resource co("Channel Oath", co_uses, 0);
      co.short_rest_regen = 1;       // regain one use on a short rest
      co.long_rest_regen = co_uses;  // full on a long rest
      resources["Channel Oath"] = co;

      // Lay on Hands (L1+): pool of 5 × level HP to heal
      Resource loh("Lay on Hands", 5 * level, 5 * level);
      loh.long_rest_regen = 5 * level;
      resources["Lay on Hands"] = loh;
      break;
    }

    case Bard: {
      // 2024 Bard: Charisma full caster (table A slots already set via set_class_level);
      // Dexterity + Charisma saving-throw proficiencies.
      spellcasting_ability = 5;  // 5 = CHA
      can_cast_spell = true;
      save_prof_dex = true;
      save_prof_cha = true;

      // Bardic Inspiration: max(1, CHA mod) uses. Long-rest regain now; short-rest
      // regain added at L5 (Font of Inspiration).
      int bi_uses = std::max(1, _mod(cha));
      Resource bi("Bardic Inspiration", bi_uses, 0);
      bi.long_rest_regen = bi_uses;
      if (level >= 5) bi.short_rest_regen = bi_uses;  // Font of Inspiration
      resources["Bardic Inspiration"] = bi;

      // Die size the bard grants: d6 (L1) → d8 (L5) → d10 (L10) → d12 (L15).
      bardic_inspiration_die_size =
          (level >= 15) ? 12 : (level >= 10) ? 10 : (level >= 5) ? 8 : 6;

      // ── College subclass features (Phase 3) ──
      // Dance L3: Unarmored Defense (AC = 10 + DEX + CHA) — applied in computeAC.
      // Lore L3: Cutting Words — see bardCuttingWords (reaction, negative die).
      // Valor L6: Extra Attack.
      if (bard_subclass == ValorPath && level >= 6) {
        num_attacks = 2;
      }
      // Other college features (Glamour, Dance L6/L14, Lore Peerless Skill,
      // Valor Combat Inspiration / Battle Magic) are deferred — see known_limitations.md.
      break;
    }

    case Ranger: {
      // Ranger: WIS half-caster (kHalf slots already set via set_class_level).
      // Saving-throw proficiencies: Strength + Dexterity (2024 PHB).
      spellcasting_ability = 4;  // 4 = WIS (SaveAbility_t::SaveWis)
      can_cast_spell = true;
      save_prof_str = true;
      save_prof_dex = true;

      // Extra Attack (L5+): 2 attacks per action.
      if (level >= 5) num_attacks = 2;

      // Roving (L6+): +10 ft Speed; also gain Climb and Swim speeds equal to your Speed.
      if (level >= 6) {
        speed_walk += 10;
        speed_climb = speed_walk;
        speed_swim  = speed_walk;
      }

      // Favored Enemy (L1): Hunter's Mark is always prepared and can be cast without a
      // spell slot a number of times equal to your Proficiency Bonus per Long Rest
      // (uses scale 2→6 by level, matching PB). See Phase 2 for the on-hit rider.
      int pb = 2 + (level - 1) / 4;
      Resource fe("Favored Enemy", pb, 0);
      fe.long_rest_regen = pb;
      resources["Favored Enemy"] = fe;

      // Foe Slayer (L20): the Hunter's Mark die becomes a d10 (set the default the
      // marked-target rider seeds from; live state is set when the mark is cast).
      if (level >= 20) hunters_mark_die_size = 10;

      // ── Gloom Stalker (subclass) — Dread Ambusher + Iron Mind ───────────
      if (ranger_subclass == GloomStalkerPath && level >= 3) {
        // Initiative Bonus: add your WIS modifier to Initiative rolls (initiativeModifier).
        dread_ambusher = true;
        // Dreadful Strike: a class action that arms +2d6 Psychic on your next weapon hit this
        // turn (+10 ft Speed that turn — Ambusher's Leap, applied GUI-side). Becomes 2d8 at L11
        // (Stalker's Flurry). Uses = WIS modifier (min 1) per Long Rest, once per turn.
        dreadful_strike_dice     = 2;
        dreadful_strike_die_size = (level >= 11) ? 8 : 6;
        int wis_mod = _mod(wis);
        int uses = std::max(1, wis_mod);
        Resource da("Dread Ambusher", uses, 0);
        da.long_rest_regen = uses;
        resources["Dread Ambusher"] = da;
        // Iron Mind (L7): proficiency in Wisdom saving throws.
        if (level >= 7) save_prof_wis = true;
      }

      // ── Fey Wanderer (subclass) — Dreadful Strikes ──────────────────────
      // L3: a weapon hit deals +1d4 Psychic (→1d6 at L11), once per turn. No resource.
      // L7 Beguiling Twist (Advantage on saves vs Charmed/Frightened) is gated inline at
      // the spell-save site on ranger_subclass/char_level — no field needed here.
      if (ranger_subclass == FeyWandererPath && level >= 3) {
        fey_dreadful_strikes = true;
        fey_dreadful_strikes_die_size = (level >= 11) ? 6 : 4;
      }

      // ── Class utility (no subclass gate) ────────────────────────────────
      // Tireless (L10): a Magic action grants yourself 1d8 + WIS mod (min 1) temp
      // HP. Uses = max(1, WIS mod) per Long Rest. (The RAW Exhaustion-reduction on
      // a short rest is omitted — no exhaustion-on-short-rest system.)
      if (level >= 10) {
        int uses = std::max(1, _mod(wis));
        Resource tl("Tireless", uses, 0);
        tl.long_rest_regen = uses;
        resources["Tireless"] = tl;
      }

      // Nature's Veil (L14): a Bonus Action turns you Invisible until the end of
      // your next turn. Uses = max(1, WIS mod) per Long Rest. (The "ends end of next
      // turn" timer is approximated by the base Invisible drop-on-attack behaviour.)
      if (level >= 14) {
        int uses = std::max(1, _mod(wis));
        Resource nv("Nature's Veil", uses, 0);
        nv.long_rest_regen = uses;
        resources["Nature's Veil"] = nv;
      }

      // Feral Senses (L18): gain Blindsight out to 30 ft (re-derived on init,
      // honoured by piercesInvisibility). No save/load — recomputed like Roving.
      if (level >= 18) blindsight_range = std::max(blindsight_range, 30);
      break;
    }

    // Other classes without resources (Rogue) have no custom resources
    default:
      break;
  }

  // ── Weapon Mastery feature (2024) ─────────────────────────────────────────
  // The five martial classes gain Weapon Mastery at level 1, letting them use their
  // weapons' mastery properties (here it gates the Nick action-economy relocation).
  // Stored as a feat so hasFeat("Weapon Mastery") is the single gate; guarded so a
  // re-init doesn't duplicate the entry. (Monk does NOT get Weapon Mastery.)
  switch (cls) {
    case Barbarian:
    case Fighter:
    case Paladin:
    case Ranger:
    case Rogue:
      if (!hasFeat("Weapon Mastery")) addFeat("Weapon Mastery");
      break;
    default:
      break;
  }
}

} // namespace rpg
