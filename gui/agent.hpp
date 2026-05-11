#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <concepts>
#include <filesystem>
#include <string>
#include <string_view>
#include <map>
#include <vector>
#include <nlohmann/json.hpp>
#include "character_class.hpp"

namespace rpg {


  // Some global structs to specify the types of damage allowed. 
  enum MagicDamage_t{Acid=0,Cold,Fire,Force,Lightning,Necrotic,Poison,Psychic,Radiant,Thunder,NumMagicDamage_t};
  enum PhysicalDamage_t{Bludgeoning=0,Piercing,Slashing,NumPhysicalDamage_t};

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
      int ac{10};
      int speed_walk{30};  // total walking speed in feet
      int speed_swim{0};   // total swimming speed in feet (0 = cannot swim)
      int speed_fly{0};    // total flying speed in feet   (0 = cannot fly)
      int speed_burrow{0}; // total burrowing speed in feet (0 = cannot burrow)
      int speed_walk_remaining{30}; // remaining walking speed in feet
      int speed_swim_remaining{0};  // remaining swimming speed in feet
      int speed_fly_remaining{0};   // remaining flying speed in feet
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

      // ── Spellcasting ──────────────────────────────────────────────────
      // 0=STR 1=DEX 2=CON 3=INT 4=WIS 5=CHA — drives spell attack rolls and
      // save DCs.  Matches Spell::SaveAbility_t ordinal values.
      int spellcasting_ability{5};   // default CHA

      // ── Class-feature capability flags ───────────────────────────────
      // Controls which action/bonus-action buttons are shown in the GUI.
      int  num_attacks{1};             // weapon attacks per Action (Extra Attack feature)
      bool has_cunning_action{false};  // Rogue: Dash/Disengage/Hide as bonus action
      bool has_offhand_attack{false};  // TWF / light weapon: off-hand bonus attack
      bool can_cast_spell{false};      // spellcaster: Cast Spell action/bonus action

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

      // ── NPC Spell System ────────────────────────────────────────────────
      // When true: use N/day system (Spell::uses_remaining); when false: use spell slots
      bool is_npc{false};

      // ── D&D 5e Turn-Based Spell Limits ─────────────────────────────────
      // D&D 5e rule: only one leveled spell (level >= 1) can be cast per turn
      // (cantrips and action-economy actions don't count).
      bool leveled_spell_cast_this_turn{false};  // reset at start of agent's turn

      // Initiative modifier: DEX mod [+ prof_bonus if initiative_prof].
      // CombatEngine::rollInitiative() adds a d20 on top of this.
      [[nodiscard]] int initiativeModifier() const noexcept {
	return _mod(dex) + (initiative_prof ? prof_bonus : 0);
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

      // Default constructor (uses struct field defaults defined above)
      Stats() = default;

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
        ac = std::stoi(j["AC"].get<std::string>());

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
      bool invisible{false};     // enemies cannot see this agent
      bool incapacitated{false}; // cannot act, movement speed 0
      bool concentrating{false}; // concentrating on a spell; breaks on damage CON save failure
      std::string concentrating_on{}; // name of the spell being concentrated on
      bool has_advantage{false};   // advantage on attack rolls, ability checks, saving throws
      bool has_disadvantage{false}; // disadvantage on attack rolls, ability checks, saving throws
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
    


    
    // -- Get conditions
    [[nodiscard]] const Conditions& getConditions() const noexcept { return conditions_; }
    void setConditions(const Conditions& c) noexcept { conditions_ = c; }

    // ── Reaction tracking (one reaction per round) ────────────────────────────
    [[nodiscard]] bool hasUsedReaction() const noexcept { return conditions_.reaction_used; }
    void setReactionUsed(bool used) noexcept { conditions_.reaction_used = used; }

    // ── Advantage / Disadvantage ──────────────────────────────────────────────
    [[nodiscard]] bool hasAdvantage() const noexcept { return conditions_.has_advantage; }
    void setAdvantage(bool adv) noexcept { conditions_.has_advantage = adv; }

    [[nodiscard]] bool hasDisadvantage() const noexcept { return conditions_.has_disadvantage; }
    void setDisadvantage(bool dis) noexcept { conditions_.has_disadvantage = dis; }

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

    [[nodiscard]] int getWalkRemaining()   const noexcept { return speed_walk_remaining_;   }
    [[nodiscard]] int getFlyRemaining()    const noexcept { return speed_fly_remaining_;    }
    [[nodiscard]] int getSwimRemaining()   const noexcept { return speed_swim_remaining_;   }
    [[nodiscard]] int getBurrowRemaining() const noexcept { return speed_burrow_remaining_; }

    // Move to grid cell (x, y, z). Distance is Euclidean in cells × 5 ft.
    // All movement types share a pool: spending any type deducts from all others.
    // Returns true and updates position if the move is legal; false otherwise.
    bool walkTo  (int x, int y, int z = 0) noexcept { return _moveTo(x, y, z, speed_walk_remaining_);   }
    bool flyTo   (int x, int y, int z = 0) noexcept { return _moveTo(x, y, z, speed_fly_remaining_);    }
    bool swimTo  (int x, int y, int z = 0) noexcept { return _moveTo(x, y, z, speed_swim_remaining_);   }
    bool burrowTo(int x, int y, int z = 0) noexcept { return _moveTo(x, y, z, speed_burrow_remaining_); }

  protected:
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
