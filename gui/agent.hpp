#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <concepts>
#include <deque>
#include <filesystem>
#include <iostream>
#include <string>
#include <string_view>
#include <map>
#include <vector>
#include <nlohmann/json.hpp>
#include "character_class.hpp"
#include "damage.hpp"
#include "weapon.hpp"
#include "resource.hpp"

namespace rpg {


  typedef std::map<std::string,MagicDamage_t> MagicDamageMap;
  typedef std::map<std::string,PhysicalDamage_t> PhysicalDamageMap;


  static MagicDamageMap const magicDamageMap = {
    {"Acid",     MagicDamage_t::Acid},
    {"Cold",     MagicDamage_t::Cold},
    {"Fire",     MagicDamage_t::Fire},
    {"Force",    MagicDamage_t::Force},
    {"Lightning",MagicDamage_t::Lightning},
    {"Necrotic", MagicDamage_t::Necrotic},
    {"Poison",   MagicDamage_t::Poison},
    {"Psychic",  MagicDamage_t::Psychic},
    {"Radiant",  MagicDamage_t::Radiant},
    {"Thunder",  MagicDamage_t::Thunder}
  };

  static PhysicalDamageMap const physicalDamageMap = {
    {"Bludgeoning", PhysicalDamage_t::Bludgeoning},
    {"Piercing",    PhysicalDamage_t::Piercing},
    {"Slashing",    PhysicalDamage_t::Slashing}	
  };

  // ── Size constraint: agents are NxN where N ∈ [1, 6] ──────────────────────
  template <int N>
  concept ValidAgentSize = (N >= 1 && N <= 6);

  // ── The core concept: anything that satisfies AgentLike can be used as an agent
  template <typename T>
  concept AgentLike = requires(T t, int x, int y, int z) {
    { t.getX() }            -> std::same_as<int>;
    { t.getY() }            -> std::same_as<int>;
    { t.getZ() }            -> std::same_as<int>;
    { t.setPosition(x,y,z) }-> std::same_as<void>;
    { t.getSize() }         -> std::convertible_to<int>;
    { t.getSprite() }       -> std::convertible_to<std::filesystem::path>;
    { t.takeTurn() }        -> std::same_as<void>;
    { t.action() }          -> std::same_as<void>;
    { t.attack() }          -> std::same_as<void>;
    { t.dash() }            -> std::same_as<void>;
    { t.disengage() }       -> std::same_as<void>;
    { t.dodge() }           -> std::same_as<void>;
    { t.hide() }            -> std::same_as<void>;
    { t.bonusAction() }     -> std::same_as<void>;
    { t.walk() }            -> std::same_as<void>;
    { t.fly() }             -> std::same_as<void>;
    { t.reaction() }        -> std::same_as<void>;
  };

  // ── Abstract base class implementing the AgentLike contract ───────────────
  class Agent {
  public:
    // ── D&D 5.5e character stats (nested so Agent owns the concept) ────────
    struct Stats {
      // Ability scores (1–30; default 10 = no modifier)
      int str{10}, dex{10}, con{10};
      int intel{10}, wis{10}, cha{10};  // 'int' is a keyword; use 'intel'

      // Combat
      int hp_max{10}, hp_cur{10};
      int base_ac{10};  // Base AC before armor/shield (10 = unarmored, modified by class)
      int ac_temporary_modifications{0};  // Temporary AC changes (acid damage, etc.)
      int speed_walk{30};  // total walking speed in feet
      int speed_swim{0};   // total swimming speed in feet (0 = cannot swim)
      int speed_fly{0};    // total flying speed in feet   (0 = cannot fly)
      int speed_climb{0};  // total climbing speed in feet (0 = cannot climb; Wild Heart L6 Panther aspect)
      int speed_burrow{0}; // total burrowing speed in feet (0 = cannot burrow)
      int speed_walk_remaining{30}; // remaining walking speed in feet
      int speed_swim_remaining{0};  // remaining swimming speed in feet
      int speed_fly_remaining{0};   // remaining flying speed in feet
      int speed_climb_remaining{0}; // remaining climbing speed in feet
      int speed_burrow_remaining{0};// remaining burrowing speed in feet      
      int prof_bonus{2};   // proficiency bonus (+2 at level 1–4)

      // ── Saving throw proficiency flags (set per class) ────────────────
      // When true, prof_bonus is added to that ability's Spell Save DC.
      bool save_prof_str{false};
      bool save_prof_dex{false};
      bool save_prof_con{false};
      bool save_prof_intel{false};
      bool save_prof_wis{false};
      bool save_prof_cha{false};

      // ── Skill proficiency flags ────────────────────────────────────────
      bool stealth_prof{false};     // proficiency in Stealth (DEX-based)
      bool perception_prof{false};  // proficiency in Perception (WIS-based)
      bool sleight_of_hand_prof{false};      // proficiency in Sleight of Hand (DEX-based; picks locks)
      bool sleight_of_hand_expertise{false}; // expertise: prof_bonus counted twice

      // ── Spellcasting ──────────────────────────────────────────────────
      // 0=STR 1=DEX 2=CON 3=INT 4=WIS 5=CHA — drives spell attack rolls and
      // save DCs.  Matches SaveAbility_t ordinal values.
      int spellcasting_ability{5};   // default CHA

      // ── Class-feature capability flags ───────────────────────────────
      // Controls which action/bonus-action buttons are shown in the GUI.
      int  num_attacks{1};             // weapon attacks per Action (Extra Attack feature)
      // NPC multiattack recipe: ordered (weapon_slot 0..2, count) segments.
      // Empty ⇒ legacy behavior (num_attacks swings with one auto-selected slot). NPC auto-turn only.
      std::vector<std::pair<int,int>> multiattack;
      int  bonus_attacks_remaining{0}; // bonus-action attacks queued (Flurry, Martial Arts, etc.)
      // Bonus-action budget (general action economy). Distinct from bonus_attacks_remaining,
      // which sequences multiple attacks WITHIN a single bonus action. A turn grants
      // bonus_actions_max bonus actions (base 1; feats may raise it); the engine refills
      // bonus_actions_remaining to max at the start of each turn and decrements on each use
      // (off-hand attack, Cunning Action, Rage, Healing Word, Divine Smite, etc.).
      int  bonus_actions_max{1};       // bonus actions granted per turn (feats can raise)
      int  bonus_actions_remaining{1}; // refilled to max each turn; spent on each bonus action
      bool has_cunning_action{false};  // Rogue: Dash/Disengage/Hide as bonus action
      bool has_offhand_attack{false};  // TWF / light weapon: off-hand bonus attack
      bool can_cast_spell{false};      // spellcaster: Cast Spell action/bonus action
      // OnTurnStartNearby reactions: a creature starting its turn within
      // this reactor's 5 ft reach may be reacted to. has_sentinel → a melee weapon strike (v1
      // turn-start approximation of the Sentinel feat); has_branches_of_the_tree → a STR-save-or-Grappled.
      bool has_sentinel{false};
      bool has_branches_of_the_tree{false};

      // ── Initiative ────────────────────────────────────────────────────
      // When true, prof_bonus is also added to the initiative roll
      // (e.g. the Rogue's "Expertise in Initiative" or similar features).
      bool initiative_prof{false};

      // ── Character Class & Spell Slots ─────────────────────────────────
      CharacterClass character_class{CharClassNone};
      int char_level{1};  // Character level 1-20
      std::array<int,9> spell_slots_max{};       // max slots per level (1-9)
      std::array<int,9> spell_slots_remaining{}; // current remaining slots

      // ── Vision ─────────────────────────────────────────────────────────
      int darkvision_range{0};   // feet; 0 = no darkvision. See normally in Darkness within range.
      int truesight_range{0};    // feet; 0 = no truesight. See normally in all light including magical darkness.
      int devilssight_range{0};  // feet; 0 = no devil's sight. See in Darkness and MagicalDarkness within range.
      int blindsight_range{0};   // feet; 0 = no blindsight. Perceive without sight (pierces the Invisible condition) within range.

      // ── NPC Spell System ────────────────────────────────────────────────
      // When true: use N/day system (Spell::uses_remaining); when false: use spell slots
      bool is_npc{false};

      // ── D&D 5e Turn-Based Spell Limits ─────────────────────────────────
      // D&D 5e rule: only one leveled spell (level >= 1) can be cast per turn
      // (cantrips and action-economy actions don't count).
      bool leveled_spell_cast_this_turn{false};  // reset at start of agent's turn

      // ── Temporary Hit Points & Damage Multipliers ──────────────────────
      int temp_hp{0};  // absorbs damage before hp_cur
      // Provenance for rage-sourced temp HP (World Tree "Vitality of the Tree" turn-start grant):
      // the index of the Barbarian whose Rage granted the current temp_hp, or -1 if it came from
      // any other source. endRage clears temp_hp on creatures tagged with the ending Barbarian's
      // index. 5e temp HP never stacks, so temp_hp has exactly one source at a time.
      int rage_thp_source_idx{-1};
      // The mirror image of temp_hp: a non-negative reduction to the creature's hit point maximum
      // (e.g. a vampire's Bite life-drain). effectiveMaxHp() = max(0, hp_max - available_hit_points),
      // and hp_cur can never exceed it. Unlike temp_hp this never absorbs damage — it just lowers the
      // ceiling. Cleared on a long rest (see CombatEngine::applyLongRest).
      int available_hit_points{0};

      // The creature's current usable HP maximum after any max-HP reduction (vampiric drain, etc.).
      [[nodiscard]] int effectiveMaxHp() const noexcept {
        return std::max(0, hp_max - available_hit_points);
      }
      // 0.0=immune, 0.5=resist, 1.0=normal, 2.0=vuln; initialized in constructor
      std::array<float, NumMagicDamage_t> magic_damage_multipliers;
      std::array<float, NumPhysicalDamage_t> physical_damage_multipliers;

      // Initiative modifier: DEX mod [+ prof_bonus if initiative_prof].
      // CombatEngine::rollInitiative() adds a d20 on top of this.
      [[nodiscard]] int initiativeModifier() const noexcept {
	return _mod(dex) + (initiative_prof ? prof_bonus : 0)
	     + (dread_ambusher ? _mod(wis) : 0);   // Gloom Stalker Dread Ambusher: Initiative Bonus
      }

      // ── Spell Save DCs (computed, read-only) ─────────────────────────
      // Proficient:     8 + prof_bonus + floor((score - 10) / 2)
      // Not proficient: 8              + floor((score - 10) / 2)
      [[nodiscard]] int spellSaveDcStr()   const noexcept { return _dc(str,   save_prof_str);   }
      [[nodiscard]] int spellSaveDcDex()   const noexcept { return _dc(dex,   save_prof_dex);   }
      [[nodiscard]] int spellSaveDcCon()   const noexcept { return _dc(con,   save_prof_con);   }
      [[nodiscard]] int spellSaveDcIntel() const noexcept { return _dc(intel, save_prof_intel); }
      [[nodiscard]] int spellSaveDcWis()   const noexcept { return _dc(wis,   save_prof_wis);   }
      [[nodiscard]] int spellSaveDcCha()   const noexcept { return _dc(cha,   save_prof_cha);   }

      // ── Skill bonuses (computed, read-only) ──────────────────────────
      [[nodiscard]] int stealthBonus() const noexcept {
        return _mod(dex) + (stealth_prof ? prof_bonus : 0);
      }
      [[nodiscard]] int passivePerception() const noexcept {
        return 10 + _mod(wis) + (perception_prof ? prof_bonus : 0);
      }
      [[nodiscard]] int sleightOfHand() const noexcept {
        int p = sleight_of_hand_prof ? prof_bonus : 0;
        if (sleight_of_hand_expertise) p += prof_bonus;  // expertise doubles the bonus
        return _mod(dex) + p;
      }

      // Default constructor (initializes damage multiplier arrays to 1.0)
      Stats() {
        magic_damage_multipliers.fill(1.0f);
        physical_damage_multipliers.fill(1.0f);
      }

      // Factory: create Stats from a JSON string
      [[nodiscard]] static Agent::Stats fromJsonString(const std::string& json_str) {
        return Agent::Stats(nlohmann::json::parse(json_str));
      }

      // Constructor from JSON (e.g., from DND2024_MonsterStats.json)
      explicit Stats(const nlohmann::json& j) {
        // Helper: convert modifier to ability score (score = 10 + 2*mod)
        auto modToScore = [&j](const std::string& key) -> int {
          std::string s = j.value(key, "0");
          return s.empty() ? 10 : 10 + 2 * std::stoi(s);
        };

        // HP
        hp_max = hp_cur = std::stoi(j["HP"].get<std::string>());

        // AC
        base_ac = std::stoi(j["AC"].get<std::string>());

        // Proficiency bonus
        prof_bonus = std::stoi(j["PB"].get<std::string>());

        // Movement speeds
        speed_walk = std::stoi(j["Walk"].get<std::string>());
        {
          std::string fly = j.value("Fly", "");
          speed_fly = fly.empty() ? 0 : std::stoi(fly);
        }
        {
          std::string swim = j.value("Swim", "");
          speed_swim = swim.empty() ? 0 : std::stoi(swim);
        }
        {
          std::string burrow = j.value("Burrow", "");
          speed_burrow = burrow.empty() ? 0 : std::stoi(burrow);
        }

        // Ability scores from modifiers
        str   = modToScore("STR Mod");
        dex   = modToScore("DEX Mod");
        con   = modToScore("CON Mod");
        intel = modToScore("INT Mod");
        wis   = modToScore("WIS Mod");
        cha   = modToScore("CHA Mod");

        // Initialize multiplier arrays to 1.0 (normal damage)
        magic_damage_multipliers.fill(1.0f);
        physical_damage_multipliers.fill(1.0f);

        // Helper: normalize type name to title case (e.g., "FIRE" -> "Fire")
        auto normalize_type = [](std::string s) -> std::string {
          if (s.empty()) return s;
          s[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(s[0])));
          for (size_t i = 1; i < s.length(); ++i)
            s[i] = static_cast<char>(std::tolower(static_cast<unsigned char>(s[i])));
          return s;
        };

        // Load damage multipliers from JSON if present (case-insensitive)
        if (j.contains("magic_resistances")) {
          for (const auto& res : j["magic_resistances"]) {
            std::string type_name = normalize_type(res.get<std::string>());
            if (magicDamageMap.count(type_name)) {
              magic_damage_multipliers[magicDamageMap.at(type_name)] = 0.5f;
            }
          }
        }
        if (j.contains("magic_immunities")) {
          for (const auto& imm : j["magic_immunities"]) {
            std::string type_name = normalize_type(imm.get<std::string>());
            if (magicDamageMap.count(type_name)) {
              int type_idx = magicDamageMap.at(type_name);
              magic_damage_multipliers[type_idx] = 0.0f;
            }
          }
        }
        if (j.contains("magic_vulnerabilities")) {
          for (const auto& vuln : j["magic_vulnerabilities"]) {
            std::string type_name = normalize_type(vuln.get<std::string>());
            if (magicDamageMap.count(type_name)) {
              magic_damage_multipliers[magicDamageMap.at(type_name)] = 2.0f;
            }
          }
        }
        if (j.contains("physical_resistances")) {
          for (const auto& res : j["physical_resistances"]) {
            std::string type_name = normalize_type(res.get<std::string>());
            if (physicalDamageMap.count(type_name)) {
              physical_damage_multipliers[physicalDamageMap.at(type_name)] = 0.5f;
            }
          }
        }
        if (j.contains("physical_immunities")) {
          for (const auto& imm : j["physical_immunities"]) {
            std::string type_name = normalize_type(imm.get<std::string>());
            if (physicalDamageMap.count(type_name)) {
              physical_damage_multipliers[physicalDamageMap.at(type_name)] = 0.0f;
            }
          }
        }
        if (j.contains("physical_vulnerabilities")) {
          for (const auto& vuln : j["physical_vulnerabilities"]) {
            std::string type_name = normalize_type(vuln.get<std::string>());
            if (physicalDamageMap.count(type_name)) {
              physical_damage_multipliers[physicalDamageMap.at(type_name)] = 2.0f;
            }
          }
        }
      }

      // Set character class and level; computes spell_slots_max.
      void set_class_level(CharacterClass cls, int level) {
        character_class = cls;
        char_level = std::max(1, std::min(20, level));
        spell_slots_max = compute_class_slots(cls, char_level);
        // Note: can_cast_spell is now derived from the actual spell list, not set here
      }

      // Restore remaining spell slots to their maximum (Long Rest).
      void restore_spell_slots() {
        spell_slots_remaining = spell_slots_max;
      }

      // Pact Magic: the single slot level a Warlock's slots occupy (1-5), or 0 if none.
      // Warlock pact slots are all the same level (see kPact), so the spell-cast UI uses
      // this to cast at — and consume — the pact slot.
      [[nodiscard]] int pact_slot_level() const noexcept {
        for (int i = 0; i < static_cast<int>(spell_slots_max.size()); ++i)
          if (spell_slots_max[static_cast<std::size_t>(i)] > 0) return i + 1;
        return 0;
      }

      // D&D 5e rule: only one leveled spell (level >= 1) per turn.
      // Check if a leveled spell can be cast this turn.
      [[nodiscard]] bool canCastLeveledSpell() const noexcept {
        return !leveled_spell_cast_this_turn;
      }

      // Mark that a leveled spell has been cast this turn (if spell level >= 1).
      void markLeveledSpellCast(int spell_level) noexcept {
        if (spell_level >= 1) {
          leveled_spell_cast_this_turn = true;
        }
      }

      // Reset the leveled spell flag at the start of a new turn.
      void resetLeveledSpellCastFlag() noexcept {
        leveled_spell_cast_this_turn = false;
      }

      // Damage multiplier setters (for Python/pybind11 compatibility)
      void set_magic_damage_multiplier(int type_idx, float multiplier) noexcept {
        if (type_idx >= 0 && type_idx < static_cast<int>(magic_damage_multipliers.size())) {
          magic_damage_multipliers[type_idx] = multiplier;
        }
      }

      void set_physical_damage_multiplier(int type_idx, float multiplier) noexcept {
        if (type_idx >= 0 && type_idx < static_cast<int>(physical_damage_multipliers.size())) {
          physical_damage_multipliers[type_idx] = multiplier;
        }
      }

      float get_magic_damage_multiplier(int type_idx) const noexcept {
        if (type_idx >= 0 && type_idx < static_cast<int>(magic_damage_multipliers.size())) {
          return magic_damage_multipliers[type_idx];
        }
        return 1.0f;
      }

      float get_physical_damage_multiplier(int type_idx) const noexcept {
        if (type_idx >= 0 && type_idx < static_cast<int>(physical_damage_multipliers.size())) {
          return physical_damage_multipliers[type_idx];
        }
        return 1.0f;
      }

      // ── Class Resources (Rage, Focus Points, Sorcery Points, etc.) ───────
      std::map<std::string, Resource> resources{};

      // ── Character Identity & Background ──────────────────────────────────
      Background background{BackgroundNone};
      Alignment alignment{TrueNeutral};
      BarbianSubclass barbarian_subclass{BarbianSubclassNone};
      WildHeartRageChoice wild_heart_rage_choice{WildHeartNone};  // Which animal form for Rage of the Wilds
      WildHeartAspect wild_heart_aspect{AspectNone};             // Aspect choice for L6 (Owl/Panther/Salmon)
      WildHeartPower wild_heart_power{WildHeartPowerNone};        // Power of the Wilds choice (L14): Falcon/Lion/Ram, applied on Rage activation
      bool rage_of_gods_used{false};                             // Zealot L14 Rage of the Gods: once per long rest (true once the form has been assumed this rest)
      int brutal_strike_damage_dice{1};    // Brutal Strike damage: 1d10 (L9-16), 2d10 (L17+)
      FighterSubclass fighter_subclass{FighterSubclassNone};     // Fighter subclass choice
      DruidCircle druid_circle{DruidCircleNone};                 // Druid circle choice
      MonkSubclass monk_subclass{MonkSubclassNone};              // Monk subclass choice
      PaladinOath paladin_oath{PaladinOathNone};                 // Paladin oath choice
      WizardSubclass wizard_subclass{WizardSubclassNone};        // Wizard subclass choice
      SorcererSubclass sorcerer_subclass{SorcererSubclassNone};  // Sorcerer subclass choice
      BardCollege bard_subclass{BardCollegeNone};                // Bard college choice
      std::vector<MetamagicOption> metamagic_options;            // 2 @ L2, 4 @ L10, 6 @ L17
      WarlockSubclass warlock_subclass{WarlockSubclassNone};     // Warlock patron choice
      RogueSubclass rogue_subclass{RogueSubclassNone};           // Rogue subclass choice
      ClericSubclass cleric_subclass{ClericSubclassNone};        // Cleric divine domain choice
      BlessedStrike blessed_strike{BlessedStrikeNone};           // Cleric L7 Blessed Strikes choice
      RangerSubclass ranger_subclass{RangerSubclassNone};        // Ranger subclass choice
      HunterPrey hunter_prey{HunterPreyNone};                    // Hunter L3 Hunter's Prey choice
      DefensiveTactics defensive_tactics{DefensiveTacticsNone};  // Hunter L7 Defensive Tactics choice
      PrimalCompanion primal_companion{PrimalCompanionNone};     // Beast Master L3 companion form (re-summon memory)

      // ── Ranger: Hunter's Mark / marked-target rider (Phase 2) ───────────
      // Generic "marked target" on-hit bonus damage (powers Hunter's Mark and Warlock Hex).
      // Set when the mark spell resolves; cleared on concentration drop. hunters_mark_target
      // is a BattleMap agent index (-1 = none).
      int  hunters_mark_target{-1};                              // marked agent index (-1 = no active mark)
      int  hunters_mark_dice{1};                                 // # of rider dice (HM 1d6; Foe Slayer L20 keeps 1 die but d10)
      int  hunters_mark_die_size{6};                             // rider die size (6 = d6; 10 once Foe Slayer)
      int  hunters_mark_damage_type{3};                          // MagicDamage_t (3 = Force for HM; 7 = Psychic for Hex)

      // ── Gloom Stalker (Ranger subclass) — Dread Ambusher ────────────────
      // Initiative Bonus (passive) + the Dreadful Strike class action (arms a one-hit Psychic rider).
      bool dread_ambusher{false};        // +WIS modifier to Initiative rolls (set at GloomStalker L3+)
      int  dreadful_strike_dice{2};      // Dreadful Strike rider: 2 dice (2d6 → 2d8 at L11 Stalker's Flurry)
      int  dreadful_strike_die_size{6};  // 6 = d6; becomes 8 at L11

      // ── Fey Wanderer (Ranger subclass) — Dreadful Strikes (distinct from Gloom's) ──
      // L3: a weapon hit deals +1d4 Psychic (→1d6 at L11), once per turn, no resource.
      bool fey_dreadful_strikes{false};      // set at FeyWanderer L3+
      int  fey_dreadful_strikes_die_size{4}; // 4 = d4; becomes 6 at L11

      // ── Druid Features ────────────────────────────────────────────────
      // Wild Shape / Starry Form state
      bool wild_shape_active{false};
      std::string wild_shape_form_name{};                        // beast name, e.g. "Brown Bear"
      int wild_shape_saved_ac{0};
      int wild_shape_saved_str{0};
      int wild_shape_saved_dex{0};
      int wild_shape_saved_con{0};
      std::vector<Weapon> wild_shape_saved_weapons{};           // original weapons to restore on deactivate

      bool starry_form_active{false};
      int starry_constellation{0};                               // 0=none, 1=Archer, 2=Chalice, 3=Dragon

      // Circle of the Land
      int land_type{0};                                          // 0=none, 1=Arid, 2=Polar, 3=Temperate, 4=Tropical

      // Wrath of the Sea (Circle of the Sea)
      bool wrath_of_sea_active{false};

      // Lunar Radiance (Moon L6): Wild Shape attacks can deal Radiant
      bool lunar_radiance_available{false};                      // set while wild_shape_active + Moon L6+

      // Improved Lunar Radiance (Moon L14): 2d10 Radiant rider once/turn
      bool improved_lunar_radiance_available{false};

      // Primal Strike (Druid L7 Elemental Fury choice)
      bool primal_strike_active{false};
      int primal_strike_damage_type{0};                          // element choice (Cold/Fire/Lightning/Thunder)

      bool is_undead{false};                                     // creature type Undead (Turn Undead target)
      bool is_fiend{false};                                      // creature type Fiend (Divine Smite +1d8 target)
      bool is_vampire{false};                                    // creature type Vampire (Sunlight vulnerability)

      // ── Regeneration (Troll, Vampire, Hydra, …) ──────────────────────────────
      // The creature regains regeneration_amount HP at the start of each of its turns (capped at
      // effectiveMaxHp()), provided it still has at least 1 HP. Regeneration is suppressed for one
      // regen check when the creature takes a damage type in regen_interrupt_damage_types (MagicDamage_t
      // indices, e.g. Troll = {Acid, Fire}, Vampire = {Radiant}): processDamageTaken sets the transient
      // regen_suppressed flag, which beginTurn consumes. The Vampire "in sunlight" interrupt needs no
      // special field — the sunlight block already deals Radiant at turn start, so it sets the same flag.
      int  regeneration_amount{0};                               // HP regained at turn start (0 = no regeneration)
      std::vector<int> regen_interrupt_damage_types{};           // MagicDamage_t indices that suppress the next regen if taken
      bool regen_suppressed{false};                              // transient: set on interrupting damage, consumed at the next beginTurn regen check (NOT serialized)

      // ── Legendary Actions & Resistance ──────────────────────────────────
      int  legendary_resistance_max{0};                          // uses per day (resets on long rest)
      int  legendary_resistance_current{0};                      // remaining uses this day
      int  legendary_actions_max{0};                             // actions per round
      int  legendary_actions_current{0};                         // remaining actions this round (resets at start of creature's turn)
      bool has_legendary_actions{false};                         // gate for legendary action offer window
      bool is_in_lair{false};                                    // affects legendary_resistance/actions counts if different
      std::vector<std::string> legendary_action_names{};         // available actions: ["Bite", "Claw", "Dash", "DashHalf", ...]

      int  weapon_mastery{0};                                    // # of Weapon Mastery properties known (>0 = feature active)
      int  crit_threshold{20};                                   // d20 roll >= this is a critical hit (default 20, Champion lowers it)
      int  superiority_die_size{8};                              // Battle Master: d8 at L3-9, d10 at L10+
      int  psionic_die_size{6};                                  // Psi Warrior: Psionic Energy die size (d6/d8/d10/d12 by level)
      int  bardic_inspiration_die{0};                            // Bard: SIZE of the held Bardic Inspiration die (0 = none; 6/8/10/12). One at a time; persists across turns until used or long rest.
      int  bardic_inspiration_die_size{6};                       // Bard: the die size this bard GRANTS (d6/d8/d10/d12 by level), set in initializeClassResources
      // ── Barbarian L20 Primal Champion ────────────────────────────────────────
      bool primal_champion_applied{false};                       // Primal Champion (L20): +4 STR/CON (capped at 25) applied; idempotent flag
      // ── Monk Phase 0 Features ────────────────────────────────────────────────
      bool monk_body_mind_applied{false};                        // Body and Mind (L20): +4 DEX/WIS (capped at 25) applied; idempotent flag
      int  unarmed_damage_override{-1};                          // Unarmed-strike damage-type override: -1 = none (Bludgeoning default), else a MagicDamage_t value. Set by Monk L6 Empowered Strikes (Force) and Elements L3 Elemental Attunement (chosen element). One field, last activation wins.
      // ── Barbarian L11 Relentless Rage ───────────────────────────────────────
      int  relentless_rage_dc{10};                               // Relentless Rage save DC (10 base, +5 per use in same Rage); reset on rage end
      int  sacred_weapon_bonus{0};                               // Paladin Oath of Devotion: Sacred Weapon attack bonus (0 = inactive)
      int  sacred_weapon_turns{0};                               // Sacred Weapon remaining duration in rounds (decrements at turn start)
      int  corona_of_light_turns{0};                             // Cleric Light Domain (L17): Corona of Light remaining duration in rounds (>0 = enemies in 60ft have Disadvantage on saves vs the caster's Fire/Radiant spells)
      int  innate_sorcery_turns{0};                              // Sorcerer Innate Sorcery: remaining duration in rounds (>0 = active: +1 spell DC, advantage on spell attacks)
      // ── Sorcerer Subclass Features ──────────────────────────────────────────
      bool draconic_hp_applied{false};                          // Draconic L3 Resilience HP bonus applied (idempotent flag); bonus = char_level (3 + (lvl-3))
      int  draconic_affinity_type{-1};                          // Draconic L6 Elemental Affinity: chosen MagicDamage_t index (0-9), -1 = none
      bool draconic_affinity_used_this_turn{false};             // Draconic L6 Elemental Affinity: CHA mod bonus already applied this turn; reset in beginTurn
      int  draconic_affinity_resist_turns{0};                  // Draconic L6 Elemental Affinity: resistance half — rounds remaining (>0 = chosen type has 0.5× multiplier). 1 hour → 600 rounds; ticks in beginTurn; on reaching 0 multiplier restores to 1.0.
      bool dragon_wings_active{false};                          // Draconic L14 Dragon Wings: fly speed granted (= walk speed); false until activated
      int  overchannel_uses{0};                                 // Evoker L14 Overchannel: times used since last Long Rest. 0 = the next use is free; each later use inflicts escalating Necrotic self-damage. Reset to 0 on Long Rest. (Transient per-rest state; not serialized.)
      int  trance_of_order_turns{0};                            // Clockwork L14 Trance of Order: rounds remaining (>0 = active: attacks vs you can't benefit from Advantage + you treat your own d20 of 9-or-lower as a 10 on D20 Tests). 1 min = 10 rounds; ticks in beginTurn.
      int  bastion_ward{0};                                     // Clockwork L6 Bastion of Law: pre-rolled d8 ward pool (= sum of (SP spent)d8). Absorbs damage BEFORE temp_hp at each damage site; decremented as it soaks. Persists until reused (overwrites) or a long rest (cleared in applyLongRest). 0 = no ward.
      int  revelation_in_flesh_turns{0};                        // Aberrant L14 Revelation in Flesh: rounds remaining (>0 = active: fly+hover, swim, truesight 60 ft / see invisible). 10 min = 100 rounds; ticks in beginTurn and reverts the granted speeds/truesight on expiry (and at long rest). 0 = inactive.
      int  revelation_prior_fly{0};                             // Revelation in Flesh: speed_fly snapshot before the grant, restored on expiry
      int  revelation_prior_swim{0};                            // Revelation in Flesh: speed_swim snapshot before the grant, restored on expiry
      int  revelation_prior_truesight{0};                       // Revelation in Flesh: truesight_range snapshot before the grant, restored on expiry
      int  mantle_majesty_turns{0};                              // Bard College of Glamour (L6) — Mantle of Majesty: "unearthly appearance" window in rounds (>0 = may re-cast Command as a Bonus Action with no slot; Command auto-fails for creatures Charmed by this bard). Tied to concentration on "Mantle of Majesty".
      int  majestic_presence_turns{0};                            // Bard College of Glamour (L14) — Unbreakable Majesty: "majestic presence" window in rounds (>0 = negates incoming attacks automatically like Shield, no reaction). Tied to concentration on "Unbreakable Majesty".
      bool majesty_checked_this_turn{false};                      // Unbreakable Majesty: per-turn gate — only check/negate once per turn
      int  majesty_disadv_save_vs{-1};                            // Unbreakable Majesty: success-rider; spell index whose save gets Disadvantage (TODO: full rider impl); -1 = none
      // Wild Magic Surge persistent effects (set by applyWildMagicSurgeEffect, tick at turn start)
      bool shield_active{false};                                 // Shield spell: +5 AC (via ac_temporary_modifications) until start of next turn + Magic Missile immunity
      int  wild_magic_shield_turns{0};                           // Band 2 (spectral shield): +2 AC (via ac_temporary_modifications) + Magic Missile immunity, in rounds
      int  wild_magic_regen_turns{0};                            // Band 3: regain 5 HP at the start of each of your turns, in rounds
      bool wild_magic_skip_next_turn{false};                     // Band 7: skip this agent's next turn
      bool wild_magic_extra_action{false};                       // Band 8: GUI grants one extra action this turn
      int  wild_magic_bonus_cast_turns{0};                       // Band 6: action-cast spells may be cast as a Bonus Action (GUI-enforced), in rounds
      int  wild_magic_teleport_bonus_turns{0};                   // Band 10: may teleport 20 ft as a Bonus Action each turn (GUI-enforced), in rounds
      int fiendish_resilience_type{-1};                          // Fiend L10: chosen damage type (0-9, ≠3), -1 = none
      std::deque<int> portent_dice{};                            // Diviner: portent d20 values, refilled on long rest
      std::vector<int> eldritch_invocations{};                   // Warlock invocation codes (see HAIKU_WARLOCK_PHASE3)
      bool fiendish_vigor_applied{false};                        // Fiendish Vigor (code 6): max-False-Life temp HP granted this combat
      [[nodiscard]] bool hasInvocation(int code) const noexcept {
          return std::find(eldritch_invocations.begin(), eldritch_invocations.end(), code)
                 != eldritch_invocations.end();
      }

      // Clockwork L14 Trance of Order: while active, treat any d20 of 9 or lower as a 10 on the
      // owner's own D20 Tests (attacks/saves). Apply to the KEPT die at each roll site, BEFORE
      // crit/fumble evaluation and gated on !auto_fail (an automatic-fail save must not be floored).
      // A no-op for any creature not a L14+ Clockwork Sorcerer in an active trance.
      [[nodiscard]] int applyTranceFloor(int d20) const noexcept {
          return (character_class == CharacterClass::Sorcerer &&
                  sorcerer_subclass == SorcererSubclass::ClockworkPath &&
                  char_level >= 14 && trance_of_order_turns > 0 && d20 < 10) ? 10 : d20;
      }

      // ── Feats ───────────────────────────────────────────────────────────
      // Canonical feat names a character has taken (e.g. "Tough", "Savage Attacker",
      // "Tavern Brawler", "Alert", "Lucky"). Mirrors the eldritch_invocations pattern.
      // Combat hooks query hasFeat(); one-time stat effects (Tough HP, Alert initiative
      // proficiency, Lucky points) are applied by addFeat() when a feat is first granted.
      std::vector<std::string> feats{};
      [[nodiscard]] bool hasFeat(const std::string& f) const noexcept {
          return std::find(feats.begin(), feats.end(), f) != feats.end();
      }

      // ── Spell Thief (Arcane Trickster Rogue L17) ────────────────────────
      // Spell names this caster currently CANNOT cast because an Arcane Trickster stole them with
      // Spell Thief (the caster failed the INT save). Checked at the top of executeSpell; cleared on
      // a long rest (RAW: the lock lasts 8 hours). The "the AT may now cast the stolen spell once"
      // half is deferred (flavor — needs spell-list mutation the GUI doesn't expose).
      std::vector<std::string> stolen_spell_names{};
      [[nodiscard]] bool spellIsStolen(const std::string& n) const noexcept {
          return std::find(stolen_spell_names.begin(), stolen_spell_names.end(), n)
                 != stolen_spell_names.end();
      }

      // ── Elemental Adept (general feat) ──────────────────────────────────
      // MagicDamage_t indices whose Resistance this caster's spells ignore (and whose damage dice
      // treat a 1 as a 2). The feat may be taken once per element (acid/cold/fire/lightning/thunder),
      // so this is a list. Chosen via the GUI element picker; serialized in the save's `feats` block.
      std::vector<int> elemental_adept_types{};
      [[nodiscard]] bool hasElementalAdeptType(int t) const noexcept {
          return hasFeat("Elemental Adept") &&
                 std::find(elemental_adept_types.begin(), elemental_adept_types.end(), t)
                     != elemental_adept_types.end();
      }

      // ── Lucky (Origin feat) ─────────────────────────────────────────────
      // Luck Points = proficiency bonus, regained on a Long Rest. Spent to grant
      // Advantage on a d20 Test (CombatEngine::spendLuckForAdvantage).
      int luck_points{0};
      int luck_points_max{0};

      // Grant a feat and apply its one-time stat-derived effects. Call AFTER ability
      // scores, level, and prof_bonus are set (the GUI assigns feats at the end of
      // configuration). Restoring from a save sets the `feats` list directly instead —
      // hp_max/luck_points are persisted with the bonus already folded in, so re-applying
      // here would double-count. No-op if the feat is already present.
      void addFeat(const std::string& name) {
          if (hasFeat(name)) return;
          feats.push_back(name);
          if (name == "Tough") {
              const int bonus = 2 * char_level;   // +2 HP per character level
              hp_max += bonus;
              hp_cur += bonus;
          } else if (name == "Alert") {
              initiative_prof = true;             // add prof_bonus to initiative rolls
          } else if (name == "Lucky") {
              luck_points_max = prof_bonus;
              luck_points     = prof_bonus;
          }
      }

      // Helper: get resource by name (returns nullptr if not found)
      [[nodiscard]] Resource* getResource(const std::string& name) noexcept {
        auto it = resources.find(name);
        return (it != resources.end()) ? &it->second : nullptr;
      }

      // Helper: const version
      [[nodiscard]] const Resource* getResource(const std::string& name) const noexcept {
        auto it = resources.find(name);
        return (it != resources.end()) ? &it->second : nullptr;
      }

      // Initialize class resources based on class and level
      // Declared here, implemented in agent.cpp
      void initializeClassResources(CharacterClass cls, int level);

      // Long rest: restore spell slots + all resources
      void restore_resources_long_rest() {
        restore_spell_slots();
        for (auto& [name, res] : resources) {
          res.restore_long_rest();
        }
        luck_points = luck_points_max;   // Lucky feat: Luck Points regained on a Long Rest
      }

      // Short rest: restore some resources (e.g., Focus Points for Monk)
      void restore_resources_short_rest() {
        // Warlock Pact Magic slots recharge on a short rest as well as a long rest.
        if (get_caster_type(character_class) == CasterPact)
          restore_spell_slots();
        for (auto& [name, res] : resources) {
          res.restore_short_rest();
        }
      }

      // Called at end of turn to tick down duration-based resources
      void tick_resource_durations() {
        for (auto& [name, res] : resources) {
          res.tick_duration();
        }
      }

    private:
      // Ability modifier: floor((score - 10) / 2), matching D&D integer rules.
      [[nodiscard]] static int _mod(int score) noexcept {
        int m = (score - 10) / 2;
        if (score < 10 && (score - 10) % 2 != 0) --m; // round toward -∞
        return m;
      }

      [[nodiscard]] int _dc(int score, bool proficient) const noexcept {
        return 8 + (proficient ? prof_bonus : 0) + _mod(score);
      }
    };

    struct Conditions {


      // Conditions:
      bool dashing{false};       // double movement speed
      bool dodging{false};       // attacks against have disadvantage, advantage on DEX saves
      bool disengaging{false};   // does not provoke opportunity attacks
      bool reaction_used{false}; // reaction already used this turn
      bool hidden{false};        // enemies cannot detect; attacks from hiding have advantage
      bool invisible{false};     // enemies cannot see this agent (pierced by Truesight/Blindsight)
      bool invisible_persists_on_action{false}; // Greater Invisibility: does NOT end on attack/cast (else Invisibility ends after the actor attacks/deals damage/casts)
      bool attacked_while_invisible{false}; // set when an attack ends this agent's Invisibility (per-turn); gates Thief Supreme Sneak (Stealth Attack)
      bool incapacitated{false}; // cannot act, movement speed 0
      bool sanctuary_active{false}; // warded by the Sanctuary spell: any creature targeting this one with an attack or damaging spell must make a WIS save or lose the attack/spell. Ends when the warded creature attacks, casts a spell, or deals damage.
      int  sanctuary_dc{0};         // WIS save DC an attacker must beat to target the Sanctuary-warded creature (the caster's spell save DC)
      bool concentrating{false}; // concentrating on a spell; breaks on damage CON save failure
      std::string concentrating_on{}; // name of the spell being concentrated on
      bool has_advantage{false};   // advantage on attack rolls, ability checks, saving throws
      bool has_disadvantage{false}; // disadvantage on attack rolls, ability checks, saving throws
      bool paralyzed{false};     // cannot move, speed 0, auto-fail STR/DEX saves, attacks have advantage and auto-crit within 5ft
      bool blinded{false};       // cannot see; attack rolls against have advantage, own attacks have disadvantage
      bool deafened{false};      // cannot hear; auto-fail ability checks requiring hearing
      bool stunned{false};       // cannot act, auto-fail STR/DEX saves, attacks have advantage
      bool prone{false};         // crawling only, disadvantage on attacks; advantage for attackers within 5ft
      bool charmed{false};       // cannot attack the charmer or target with damaging abilities
      int  charmed_by{-1};       // index of the creature that Charmed this one (-1 = none / unknown source). Set when a spell applies Charmed; used by Mantle of Majesty (Command auto-fails for a creature Charmed by the casting bard).
      bool frightened{false};    // disadvantage on attacks/checks when source in LOS; cannot move closer to source
      bool slipped_this_turn{false}; // slipped on ice/grease this turn; cannot use action/bonus action
      bool restrained{false};     // speed drops to 0, attacks have disadvantage, attacks against have advantage
      bool poisoned{false};      // disadvantage on attack rolls and ability checks
      bool petrified{false};     // incapacitated, speed 0, resistance to all damage (0.5x), immune to poisoned, auto-fail STR/DEX saves, advantage on attacks
      bool gaseous_form{false};  // Gaseous Form / vampire Misty Escape: fly-only (Speed 20), can't attack or cast, Resistance to Bludgeoning/Piercing/Slashing (Immunity if is_vampire), immune to Prone. Session-only transient; endGaseousForm restores the pre-cast speeds + physical multipliers snapshotted in gaseousSnapshots_.
      bool unconscious{false};   // incapacitated, prone, speed 0, attacks have advantage, auto-fail STR/DEX saves, auto-crit within 5ft
      bool dead{false};          // character is dead (permanent until revived by magic)
      int death_save_successes{0}; // successful death saves (0-3); at 3, character stabilizes
      int death_save_failures{0};  // failed death saves (0-3); at 3, character dies
      bool stabilized{false};    // no longer rolling death saves
      bool grappled{false};                 // creature is currently grappled
      int grappler_idx{-1};                 // index of creature doing the grappling (-1 = none)
      int grapple_escape_dc{10};            // DC to escape grapple
      int grapple_range_ft{5};              // range at which grapple is broken if exceeded
      int exhaustion_level{0};              // exhaustion level (0-6; 6 = death)
      bool raging{false};                   // Barbarian is currently in Rage
      bool lion_aura_active{false};         // Wild Heart L14 Lion power: while raging, enemies within 5 ft have Disadvantage attacking anyone but this barbarian (or another lion-active barbarian). Set on Rage activation, cleared on Rage end.
      bool rage_of_gods_active{false};      // Zealot L14 Rage of the Gods: divine-warrior form active (fly+hover, resist Necrotic/Psychic/Radiant, Revivification reaction). Set by activateRageOfTheGods, cleared on Rage end / 0 HP.
      bool world_tree_long_teleport_used{false}; // World Tree L14 Travel along the Tree: the 150-ft (vs 60-ft) teleport upgrade is once per Rage. Reset on Rage activation, cleared on Rage end.
      bool retaliation_available{false};    // Berserker L10 Retaliation: an enemy within 5 ft damaged this barbarian; may spend a reaction to make one melee attack back (set on the DEFENDER).
      int  retaliation_target_idx{-1};      // Berserker L10 Retaliation: index of the creature that damaged this barbarian (the legal Retaliation target).
      bool reckless_attack{false};          // Barbarian declared Reckless Attack this turn
      bool reckless_reroll_available{false}; // Barbarian missed; GUI may offer a post-hoc reckless reroll
      bool riposte_available{false};        // Battle Master was missed by a melee attack; may Riposte (set on the DEFENDER)
      bool sentinel_guard_available{false}; // Sentinel feat (Guardian): an adjacent enemy attacked an ally; a nearby Sentinel may guard (set on the ATTACKER)
      bool colossus_slayer_used{false};     // Hunter L3 Colossus Slayer: +1d8 already applied this turn (once/turn)
      bool horde_breaker_available{false};  // Hunter L3 Horde Breaker: a weapon hit can grant an extra attack vs an adjacent creature (GUI prompt)
      bool horde_breaker_used{false};       // Hunter L3 Horde Breaker already used this turn (once/turn)
      bool superior_prey_used{false};       // Hunter L11 Superior Hunter's Prey: HM-damage splash already applied this turn (once/turn)
      bool bestial_fury_used{false};        // Beast Master L11 Bestial Fury: companion's HM-marked Force splash already applied this turn (once/turn)
      bool fey_dreadful_strikes_used{false}; // Fey Wanderer L3 Dreadful Strikes Psychic rider already applied this turn (once/turn)
      std::vector<int> multiattack_def_hit_by{}; // Hunter L7 Multiattack Defense: indices of creatures that hit me this turn (their other attacks vs me get Disadvantage)
      bool dreadful_strike_armed{false};    // Gloom Stalker Dread Ambusher: next weapon hit this turn deals +Xd6 Psychic (consumed on the hit)
      bool dread_ambusher_used{false};      // Gloom Stalker Dread Ambusher class action already used this turn (once/turn)
      bool sudden_strike_available{false};  // Gloom Stalker L11 Stalker's Flurry: a Dreadful Strike hit grants one free extra attack (GUI prompt)
      bool berserker_frenzy_used{false};    // Berserker Frenzy bonus already applied this turn
      bool vitality_used_this_turn{false};  // World Tree Vitality of the Tree turn-start grant used this turn
      bool branches_speed_zeroed{false};    // World Tree Branches of the Tree: target's Speed is 0 until the end of THIS turn (set on a failed save, cleared in turn())
      bool brutal_strike_used_this_turn{false}; // Brutal Strike effect already used this turn
      bool zealot_divine_fury_used{false};  // Zealot Divine Fury bonus already applied this turn
      bool fanatical_focus_used{false};     // Zealot Fanatical Focus reroll already used this Rage
      bool brutal_strike_available{false};  // Brutal Strike can be used this attack
      bool hamstrung{false};                // Hamstring Blow effect: speed -15ft (expires start of next turn)
      int sundering_target_idx{-1};         // Sundering Blow: +5 to hit vs this target (expires start of next turn)
      bool staggered_next_save{false};      // Staggering Blow: disadvantage on next save
      bool radiant_soul_used{false};        // Celestial L6: Radiant Soul bonus damage already used this turn
      bool sneak_attack_used{false};        // Rogue: Sneak Attack already applied this turn (once per turn)
      bool cunning_strike_available{false}; // Rogue: a qualifying hit can apply Sneak Attack / Cunning Strike this attack
      bool steady_aim{false};               // Rogue L3: Steady Aim grants advantage on the next attack this turn
      bool stunning_strike_available{false}; // Monk: a qualifying unarmed hit can apply Stunning Strike this attack
      bool stunning_strike_used{false};     // Monk: Stunning Strike already applied this turn (once per turn)
      bool open_hand_rider_available{false}; // Monk Open Hand: a Flurry hit can apply a rider (Knockdown/Push/Deny Reaction)
      bool open_hand_rider_used{false};     // Monk Open Hand: rider already applied this turn (once per turn)
      bool quivering_palm_available{false}; // Monk Open Hand L17: an unarmed hit can plant Quivering Palm vibrations this attack
      bool divine_strike_available{false};  // Cleric L7: a weapon hit can apply Divine Strike this attack
      bool divine_strike_used{false};       // Cleric L7: Divine Strike already applied this turn (once per turn)
      bool psionic_strike_available{false}; // Psi Warrior L3: a hit can apply Psionic Strike this attack
      bool psionic_strike_used{false};      // Psi Warrior L3: Psionic Strike already applied this turn (once per turn)
      bool hand_of_harm_available{false};   // Warrior of Mercy L3: a qualifying unarmed hit can apply Hand of Harm this attack
      bool elemental_attunement_move_available{false}; // Warrior of the Elements L3: an unarmed hit while Elemental Attunement is active can push/pull the target 10 ft (per-turn eligibility; the push/pull direction is a player choice)
      bool hand_of_harm_used{false};        // Warrior of Mercy L3: Hand of Harm already used this turn (once; L11 lifts the limit to once per target)
      int  hand_of_harm_last_target{-1};    // Warrior of Mercy L11: index of the last creature struck by Hand of Harm this turn (can't reuse on the same target)
      bool grappler_punch_grab_available{false}; // Grappler feat: an Unarmed-Strike hit (Attack action) can also Grapple this attack
      bool grappler_punch_grab_used{false};      // Grappler feat: Punch-and-Grab already used this turn (once per turn)
      bool divine_smite_available{false};   // Paladin: a melee/unarmed hit can apply Divine Smite this attack
      bool divine_smite_used{false};        // Paladin: Divine Smite already used this turn (bonus action, once per turn)
      bool eldritch_smite_available{false}; // Warlock (Eldritch Smite, inv 15): a pact-weapon hit can expend a pact slot this attack
      bool eldritch_smite_used{false};      // Warlock: Eldritch Smite already used this turn (once per turn)
      bool lifedrinker_used{false};         // Warlock (Lifedrinker, inv 16): bonus necrotic + temp HP already applied this turn (once per turn)
      bool war_magic_used{false};           // Eldritch Knight: War Magic substitution already used this Attack action (once per Attack action; reset when a fresh action-attack sequence seeds — Action Surge permits another)
      int  eldritch_strike_by{-1};          // Eldritch Knight L10: this creature (the target of an EK weapon hit) has disadvantage on its next save vs a spell cast by agent index eldritch_strike_by; -1 = none. One-shot: consumed at the save site (RAW window simplified — see known_limitations)
      bool guided_strike_available{false};  // War Cleric: this missed attack can be nudged to a hit (+10)
      bool restore_balance_miss_available{false}; // Clockwork Sorcerer ally: this disadvantaged miss can have its Disadvantage cancelled (raise d20 → d20_primary)
      bool maneuver_available{false};           // Battle Master: a qualifying hit can apply a Maneuver this attack
      bool maneuver_precision_available{false}; // Battle Master: this missed attack can apply Precision Attack
      // ── Battle Master maneuvers (2024) beyond Trip/Menacing/Pushing/Precision/Riposte ──
      int  goaded_by{-1};        // Goading Attack: this creature's attacks vs anyone other than goaded_by have
                                 //   Disadvantage; cleared at the start of goaded_by's next turn.
      int  distracted_by{-1};    // Distracting Strike: the next attack vs this creature by an attacker other than
                                 //   distracted_by has Advantage (consumed); cleared at start of distracted_by's next turn.
      bool disarmed{false};      // Disarming Attack: this creature dropped its weapon — its weapon attacks resolve as
      int  disarmed_by{-1};      //   improvised Unarmed Strikes until the start of disarmed_by's next turn.
      int  feint_target_idx{-1}; // Feinting Attack: Advantage on your next attack vs this target this turn, and that
                                 //   hit adds a superiority die to damage. Consumed on that attack (reset each turn).
      bool quick_toss_die_pending{false}; // Quick Toss: the next thrown-weapon attack this turn adds a superiority
                                 //   die to its damage (consumed on that attack).
      // (Parry needs no flag — like Uncanny Dodge it is offered live in the OnHit defender window via canParry.)
      // ── Weapon Mastery (2024) ──────────────────────────────────────────────
      bool sapped{false};                   // Sap: disadvantage on this creature's next attack roll
      bool sap_used_this_turn{false};       // Sap: once per turn
      bool slowed{false};                   // Slow: speed -10 ft (consumed at this creature's next turn)
      bool slow_used_this_turn{false};      // Slow: once per turn
      int  vex_target_idx{-1};              // Vex: advantage on this attacker's next attack vs this target
      bool vex_used_this_turn{false};       // Vex: once per turn
      bool push_available{false};           // Push: a hit this attack can push the target 10 ft (GUI prompt)
      bool push_used_this_turn{false};      // Push: once per turn
      bool poison_used_this_turn{false};    // Poison mastery: once per turn
      bool topple_available{false};         // Topple: a hit this attack can force a Prone save (GUI prompt)
      bool topple_used_this_turn{false};    // Topple: once per turn
      // ── Origin feats (per-turn) ─────────────────────────────────────────────
      bool savage_attacker_used_this_turn{false};    // Savage Attacker: damage reroll once per turn
      bool tavern_brawler_push_used_this_turn{false};// Tavern Brawler: Unarmed-Strike push once per turn
      // ── General feats (per-turn) ────────────────────────────────────────────
      bool crusher_push_used_this_turn{false};       // Crusher: Bludgeoning-hit push once per turn
      bool piercer_reroll_used_this_turn{false};     // Piercer: Puncture damage-die reroll once per turn
      bool slasher_slow_used_this_turn{false};       // Slasher: Hamstring −10 ft Speed once per turn
      bool gwm_hew_available{false};   // Great Weapon Master Hew: a melee crit/kill offers a bonus attack (GUI prompt)
      bool battle_magic_available{false};  // Battle Magic (Valor Bard L14+): a Magic action casting a Bard spell offers a bonus weapon attack (GUI prompt)
      // ── General feats — enhanced-crit marks (cross-turn; NOT reset in turn()) ────────
      // Set on the VICTIM by a critical hit; expire at the start of the feat-user's next turn
      // (cleared in CombatEngine::beginTurn for the agent whose index matches *_marked_by).
      bool crusher_marked{false};   // Crusher crit: attack rolls AGAINST this creature have Advantage
      int  crusher_marked_by{-1};   // feat-user index whose next turn clears the mark
      bool slasher_marked{false};   // Slasher crit: THIS creature's attack rolls have Disadvantage
      int  slasher_marked_by{-1};   // feat-user index whose next turn clears the mark
      bool cleave_available{false};         // Cleave: a hit this attack can grant an extra attack (GUI prompt)
      bool cleave_used_this_turn{false};    // Cleave: once per turn
      // ── Two-Weapon Fighting (per-turn) ──────────────────────────────────────
      // The single Light-property off-hand extra attack is one resource per turn. It lands in
      // the Bonus Action by default, or — with the Nick mastery on the off-hand weapon (and the
      // Weapon Mastery feature) — in the Attack action, freeing the Bonus Action. Dual Wielder
      // grants an ADDITIONAL bonus-action off-hand attack (only useful once Nick frees the bonus).
      bool offhand_attack_used{false};      // the per-turn off-hand extra attack has been spent
      // ── Barbarian L10 subclass features ─────────────────────────────────────
      bool zealous_blessing{false};         // Zealot Zealous Presence: grants Advantage on attack rolls and saves until the granter's next turn
      int  zealous_blessing_by{-1};         // index of the Zealot who granted zealous_blessing; cleared in CombatEngine::beginTurn as that Zealot's turn begins (mirrors goaded_by)
      // ── Per-COMBAT marker (NOT reset in turn()) ─────────────────────────────
      bool has_taken_turn_this_combat{false}; // set true at the start of this agent's first turn (CombatEngine::beginTurn); drives Assassin "Assassinate" Advantage vs creatures that haven't acted yet. Reset to false at combat start (GUI _start_combat).
      // ── Monk Phase 0 Features ────────────────────────────────────────────────
      bool uncanny_metabolism_used_this_combat{false}; // L2: restore Focus + heal on initiative roll (once per combat)
      bool superior_defense_active{false};  // L18: currently under Superior Defense resistance (set by action, expires end of turn)
      // ── Warrior of Shadow (Phase 1) ──────────────────────────────────────
      bool shadow_step_advantage{false};    // L6 Shadow Step: next attack this turn has Advantage (consumed on attack)
      bool bonus_reach_available{false};    // L11 Improved Shadow Step: +5 ft reach on next attack (consumed on attack)
      bool cloak_of_shadows_active{false};  // L17 Cloak of Shadows: currently Invisible (set by action, expires on light level change or turn end)
      // ── Warrior of the Elements (Phase 3) ────────────────────────────────
      bool elemental_attunement_active{false}; // L3 Elemental Attunement: active until a short/long rest (the sim doesn't track the 10-min duration). While set: +10 ft unarmed reach and each unarmed hit can push/pull 10 ft. The chosen element lives in Stats.unarmed_damage_override. NOT reset per turn — only at combat start and on rest.
    };

    // ── Construction ───────────────────────────────────────────────────────
    Agent(int x, int y, int z, int size, std::filesystem::path sprite)
      : x_{x}, y_{y}, z_{z}, size_{size}, sprite_{std::move(sprite)}
    {
      if (size_ < 1 || size_ > 6)
	throw std::out_of_range{"Agent size must be between 1 and 6"};
    }

    virtual ~Agent() = default;

    // Non-copyable, movable
    Agent(const Agent&)            = delete;
    Agent& operator=(const Agent&) = delete;
    Agent(Agent&&)                 = default;
    Agent& operator=(Agent&&)      = default;

    // ── Position ───────────────────────────────────────────────────────────
    [[nodiscard]] int  getX() const noexcept { return x_; }
    [[nodiscard]] int  getY() const noexcept { return y_; }
    [[nodiscard]] int  getZ() const noexcept { return z_; }

    void setPosition(int x, int y, int z=0) noexcept { x_ = x; y_ = y; z_=z; }

    // ── Size (grid cells: 1–6) ─────────────────────────────────────────────
    [[nodiscard]] int  getSize()   const noexcept { return size_; }

    // ── Sprite ─────────────────────────────────────────────────────────────
    [[nodiscard]] const std::filesystem::path& getSprite() const noexcept {
      return sprite_;
    }

    void setSprite(std::filesystem::path path) {
      sprite_ = std::move(path);
    }

    // ── Turn lifecycle ────────────────────────────────────────────────────────
    // Resets per-turn conditions then delegates to takeTurn() for input.
    void turn() {
      conditions_.dashing     = false;
      conditions_.dodging     = false;
      conditions_.disengaging = false;
      conditions_.reaction_used = false;
      // Per-turn Barbarian flags. Previously reset only in CombatEngine::runRound,
      // which the GUI never calls — left Brutal Strike/Divine Fury stuck after one use.
      // reckless_attack is a per-turn declaration (D&D 2024): it must be re-declared on each
      // turn, and its downside (enemies have advantage vs you until the start of your next turn)
      // ends here at the start of your turn. The GUI re-prompts to declare it each turn while
      // raging, and Brutal Strike then works on any turn it is declared.
      conditions_.reckless_attack              = false;
      conditions_.reckless_reroll_available    = false;
      conditions_.brutal_strike_used_this_turn = false;
      conditions_.brutal_strike_available      = false;
      conditions_.berserker_frenzy_used        = false;
      conditions_.colossus_slayer_used         = false;
      conditions_.horde_breaker_available      = false;
      conditions_.horde_breaker_used           = false;
      conditions_.superior_prey_used           = false;
      conditions_.bestial_fury_used            = false;
      conditions_.fey_dreadful_strikes_used    = false;
      conditions_.multiattack_def_hit_by.clear();
      conditions_.dreadful_strike_armed        = false;
      conditions_.dread_ambusher_used          = false;
      conditions_.sudden_strike_available      = false;
      conditions_.vitality_used_this_turn      = false;
      conditions_.branches_speed_zeroed        = false;
      conditions_.zealot_divine_fury_used      = false;
      conditions_.radiant_soul_used            = false;
      conditions_.sneak_attack_used            = false;
      conditions_.cunning_strike_available     = false;
      conditions_.attacked_while_invisible     = false;
      conditions_.steady_aim                   = false;
      conditions_.divine_strike_available      = false;
      conditions_.divine_strike_used           = false;
      conditions_.psionic_strike_available     = false;
      conditions_.psionic_strike_used          = false;
      conditions_.hand_of_harm_available       = false;
      conditions_.hand_of_harm_used            = false;
      conditions_.hand_of_harm_last_target     = -1;
      conditions_.elemental_attunement_move_available = false;  // per-turn on-hit eligibility (the active attunement itself persists across turns)
      conditions_.grappler_punch_grab_available = false;
      conditions_.grappler_punch_grab_used      = false;
      conditions_.divine_smite_available       = false;
      conditions_.divine_smite_used            = false;
      conditions_.eldritch_smite_available     = false;
      conditions_.eldritch_smite_used          = false;
      conditions_.lifedrinker_used             = false;
      conditions_.war_magic_used               = false;
      conditions_.guided_strike_available      = false;
      conditions_.restore_balance_miss_available = false;
      conditions_.maneuver_available           = false;
      conditions_.maneuver_precision_available = false;
      conditions_.riposte_available            = false;
      // Per-turn maneuver flags. goaded_by / distracted_by / disarmed[_by] are cross-turn
      // markers cleared in CombatEngine::beginTurn by the maneuvering Fighter's own turn (so
      // they last "until the end of your next turn"); they are NOT reset here.
      conditions_.feint_target_idx             = -1;
      conditions_.quick_toss_die_pending       = false;
      conditions_.sentinel_guard_available     = false;
      // Weapon Mastery per-turn flags. sapped/vex_target_idx are NOT reset here:
      // they are consumed on the next qualifying attack roll (and survive into this
      // turn so a sapped creature's attack still suffers disadvantage). slowed and
      // hamstrung are read by CombatEngine::beginTurn's movement seeding (which runs
      // before this) and cleared here so they apply for exactly one turn.
      conditions_.slowed                       = false;
      conditions_.hamstrung                    = false;
      conditions_.push_available               = false;
      conditions_.topple_available             = false;
      conditions_.cleave_available             = false;
      conditions_.cleave_used_this_turn        = false;
      conditions_.offhand_attack_used          = false;
      // zealous_blessing is NOT reset here: it lasts "until the start of the GRANTING Zealot's
      // next turn", so it is cleared in CombatEngine::beginTurn (tagged via zealous_blessing_by),
      // mirroring goaded_by / distracted_by — not on the buffed creature's own turn.
      conditions_.savage_attacker_used_this_turn     = false;
      conditions_.tavern_brawler_push_used_this_turn = false;
      conditions_.crusher_push_used_this_turn        = false;
      conditions_.piercer_reroll_used_this_turn      = false;
      conditions_.slasher_slow_used_this_turn        = false;
      conditions_.gwm_hew_available                  = false;
      conditions_.battle_magic_available             = false;
      takeTurn();
    }

    /// Override to provide player input or AI decision-making.
    virtual void takeTurn() = 0;

    // ── The four D&D-style turn actions (pure virtual) ─────────────────────

    /// Standard action: attack, cast a spell, dash, etc.
    virtual void action()      = 0;

    /// Dash: double movement speed for 1 turn
    virtual void attack() = 0;
  
    /// Dash: double movement speed for 1 turn
    virtual void dash() = 0;

    /// Disengage: avoid opportunity attacks for 1 turn
    virtual void disengage() = 0;

    /// Dodge: impose disadvantage on attack rolls against this agent, and DEX saves with advantage
    virtual void dodge() = 0;

    /// Hide: attempt to become hidden (Cunning Action for Rogues)
    virtual void hide() = 0;

    /// Bonus action: off-hand attack, cunning action, etc.
    virtual void bonusAction() = 0;

    /// Ground movement: traverse passable cells up to speed_walk feet.
    /// BattleMap enforces wall/obstacle constraints for walk.
    virtual void walk() = 0;

    /// Aerial movement: move up to speed_fly feet, ignoring terrain obstacles.
    /// BattleMap enforces only map-boundary constraints for fly.
    virtual void fly()  = 0;

    /// Reaction: opportunity attack, shield spell, etc.
    virtual void reaction()    = 0;

    // ── Optional: display name for the agent ──────────────────────────────
    [[nodiscard]] virtual std::string_view name() const noexcept = 0;

    // Rename a placed agent in-flight. The name lives in the concrete subclass,
    // so the base is a no-op and ConfiguredAgent overrides it.
    virtual void setName(std::string /*name*/) {}

    // ── Optional: source for the agent (like "Dungeon Master's Guide", "Curse of Strahd", etc)
    [[nodiscard]] virtual std::string_view source() const noexcept = 0;

    // ── Optional: display size for the agent as a string ──────────────────────────────
    [[nodiscard]] virtual std::string_view mob_size() const noexcept = 0;

    // ── Optional: display mob_type for the agent (like Elemental, Monstrosity, etc) 
    [[nodiscard]] virtual std::string_view mob_type() const noexcept = 0;

    // ── Optional: display moral_alignment for the agent (like Chaotic Evil, Lawful Good, etc )
    [[nodiscard]] virtual std::string_view moral_alignment() const noexcept = 0;

    // ── Optional: display habitat for the agent (Arctic, Underdark, etc)
    [[nodiscard]] virtual std::string_view habitat() const noexcept = 0;

    // ── Optional: display treasure for the agent
    [[nodiscard]] virtual std::string_view treasure() const noexcept = 0;

    // ── Optional: display languages for the agent
    [[nodiscard]] virtual std::string_view languages() const noexcept = 0;
    


    
    // -- Get stats and conditions
    [[nodiscard]] Stats& getStats() noexcept { return stats_; }
    [[nodiscard]] const Stats& getStats() const noexcept { return stats_; }
    [[nodiscard]] const Conditions& getConditions() const noexcept { return conditions_; }
    void setStats(const Stats& s) noexcept { stats_ = s; }
    void setConditions(const Conditions& c) noexcept { conditions_ = c; }

    // ── Reaction tracking (one reaction per round) ────────────────────────────
    [[nodiscard]] bool hasUsedReaction() const noexcept { return conditions_.reaction_used; }
    void setReactionUsed(bool used) noexcept { conditions_.reaction_used = used; }

    // ── Advantage / Disadvantage ──────────────────────────────────────────────
    [[nodiscard]] bool hasAdvantage() const noexcept { return conditions_.has_advantage; }
    void setAdvantage(bool adv) noexcept { conditions_.has_advantage = adv; }

    [[nodiscard]] bool hasDisadvantage() const noexcept { return conditions_.has_disadvantage; }
    void setDisadvantage(bool dis) noexcept { conditions_.has_disadvantage = dis; }

    // ── Slipped this turn (prevents action execution) ─────────────────────────
    [[nodiscard]] bool hasSlippedThisTurn() const noexcept { return conditions_.slipped_this_turn; }
    void setSlippedThisTurn(bool slipped) noexcept { conditions_.slipped_this_turn = slipped; }


    // ── Movement ──────────────────────────────────────────────────────────────
    // Seed remaining movement budgets from speed values (call at turn start).
    void initMovement(int walk_ft, int fly_ft = 0,
                      int swim_ft = 0, int burrow_ft = 0) noexcept {
      speed_walk_remaining_   = walk_ft;
      speed_fly_remaining_    = fly_ft;
      speed_swim_remaining_   = swim_ft;
      speed_burrow_remaining_ = burrow_ft;
    }

    // Add feet to each remaining budget (used when a Dash grant is applied).
    void addMovement(int walk_ft, int fly_ft = 0,
                     int swim_ft = 0, int burrow_ft = 0) noexcept {
      speed_walk_remaining_   += walk_ft;
      speed_fly_remaining_    += fly_ft;
      speed_swim_remaining_   += swim_ft;
      speed_burrow_remaining_ += burrow_ft;
    }

    [[nodiscard]] int getWalkRemaining()   const noexcept {
        return std::max(0, speed_walk_remaining_ - (5 * conditions_.exhaustion_level));
    }
    [[nodiscard]] int getFlyRemaining()    const noexcept {
        return std::max(0, speed_fly_remaining_ - (5 * conditions_.exhaustion_level));
    }
    [[nodiscard]] int getSwimRemaining()   const noexcept {
        return std::max(0, speed_swim_remaining_ - (5 * conditions_.exhaustion_level));
    }
    [[nodiscard]] int getBurrowRemaining() const noexcept {
        return std::max(0, speed_burrow_remaining_ - (5 * conditions_.exhaustion_level));
    }

    // Move to grid cell (x, y, z). Distance is Euclidean in cells × 5 ft.
    // All movement types share a pool: spending any type deducts from all others.
    // Returns true and updates position if the move is legal; false otherwise.
    bool walkTo  (int x, int y, int z = 0) noexcept { return _moveTo(x, y, z, speed_walk_remaining_);   }
    bool flyTo   (int x, int y, int z = 0) noexcept { return _moveTo(x, y, z, speed_fly_remaining_);    }
    bool swimTo  (int x, int y, int z = 0) noexcept { return _moveTo(x, y, z, speed_swim_remaining_);   }
    bool burrowTo(int x, int y, int z = 0) noexcept { return _moveTo(x, y, z, speed_burrow_remaining_); }

  protected:
    Stats stats_;
    Conditions conditions_;

  private:
    int                   x_;
    int                   y_;
    int                   z_;
    int                   size_;       // grid footprint (NxN)
    std::filesystem::path sprite_;     // path to the sprite image

    int speed_walk_remaining_   {0};
    int speed_fly_remaining_    {0};
    int speed_swim_remaining_   {0};
    int speed_burrow_remaining_ {0};

    // Deduct ft from every movement type (shared pool), clamping each to 0.
    void _deductMovement(int ft) noexcept {
      auto deduct = [](int& rem, int cost) {
        rem = std::max(0, rem - cost);
      };
      deduct(speed_walk_remaining_,   ft);
      deduct(speed_fly_remaining_,    ft);
      deduct(speed_swim_remaining_,   ft);
      deduct(speed_burrow_remaining_, ft);
    }

    // Core move: check budget, deduct shared pool, update position.
    bool _moveTo(int x, int y, int z, int& type_remaining) noexcept {
      int dist_ft = (std::abs(x_ - x) + std::abs(y_ - y) + std::abs(z_ - z)) * 5;
      if (dist_ft > type_remaining)
        return false;
      _deductMovement(dist_ft);
      setPosition(x, y, z);
      return true;
    }

  };

  // ── Compile-time check that Agent satisfies its own concept ───────────────
  // (Checked against a concrete stub; real check happens on derived classes.)

} // namespace rpg
