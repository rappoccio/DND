// ─────────────────────────────────────────────────────────────────────────────
//  bind_types.cpp  –  pybind11 bindings for plain value types, enums, and results
// ─────────────────────────────────────────────────────────────────────────────
//
//  Everything that isn't CombatEngine or BattleMap: Cell/Wall/Door/AgentConfig,
//  Stats/Conditions/Weapon/Armor/Item/Spell, every *Result struct, every enum
//  (CharacterClass, subclasses, SaveAbility, …), CombatDecider (+ its Python
//  trampoline), and the small BattleMap-adjacent value types (MovementType,
//  DetectionParams, TerrainType/Difficulty, VisibilityLevel, ActiveTerrainEffect,
//  ActiveLightEffect) that don't warrant their own TU.
//
//  Split out of rpg_bindings.cpp (COMBAT_REFACTOR_PLAN.md R1) — mechanical move
//  only, no binding behavior changed.
//
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>        // std::vector, std::unordered_set → Python list/set
#include <pybind11/functional.h> // std::function ↔ Python callable (NPC render-attack hook)
#include <pybind11/operators.h>

#include "battle_map.hpp"
#include "combat.hpp"
#include "combat_internal.hpp"   // footprintDistance — shared with the combat_*.cpp TUs
#include "map_configs.hpp"
#include "character_class.hpp"
#include "item.hpp"
#include "bindings_internal.hpp"

namespace py = pybind11;
using namespace rpg;

// Python trampoline for CombatDecider interface
struct PyCombatDecider : public CombatDecider {
    using CombatDecider::CombatDecider;
    // PYBIND11_OVERRIDE_NAME (not _OVERRIDE) so the C++ camelCase methods dispatch to the
    // snake_case Python methods the bindings expose (e.g. choose_reaction). Plain _OVERRIDE
    // would look up the camelCase name and silently fall back to the C++ base (= no reaction).
    std::vector<int> chooseBrutalStrike(const BrutalStrikeCtx& ctx) override {
        PYBIND11_OVERRIDE_NAME(std::vector<int>, CombatDecider, "choose_brutal_strike", chooseBrutalStrike, ctx);
    }
    bool chooseReckless(const RecklessCtx& ctx) override {
        PYBIND11_OVERRIDE_NAME(bool, CombatDecider, "choose_reckless", chooseReckless, ctx);
    }
    ReactionResponse chooseReaction(const ReactionCtx& ctx) override {
        PYBIND11_OVERRIDE_NAME(ReactionResponse, CombatDecider, "choose_reaction", chooseReaction, ctx);
    }
};

void bindTypes(py::module_& m) {
    py::class_<Cell>(m, "Cell")
        .def(py::init<>())
        .def(py::init<int, int>(), py::arg("col"), py::arg("row"))
        .def(py::init([](int col, int row, int z){ return Cell{col, row, z}; }),
             py::arg("col"), py::arg("row"), py::arg("z"))
        .def_readwrite("col", &Cell::col)
        .def_readwrite("row", &Cell::row)
        .def_readwrite("z",   &Cell::z)  // FLOOR at the global layer only; engine cells stay z=0
        .def("__eq__",   &Cell::operator==)
        .def("__repr__", [](const Cell& c){
            return "<Cell col=" + std::to_string(c.col)
                 + " row=" + std::to_string(c.row)
                 + " z=" + std::to_string(c.z) + ">"; });

    // ── Geometry helpers (single source of truth, shared with the combat engine) ──
    // Chebyshev gap (in CELLS) between two NxN footprints — 0 if their cells are
    // adjacent/overlapping. The same formula the engine uses for reach/adjacency, so
    // Python callers must not re-derive it. Multiply by 5 for feet.
    m.def("footprint_distance", &footprintDistance,
          py::arg("a"), py::arg("size_a"), py::arg("b"), py::arg("size_b"),
          "Chebyshev distance in cells between two square footprints (origin + size).");

    // ── Wall ────────────────────────────────────────────────────────────────
    py::class_<Wall>(m, "Wall")
        .def(py::init<>())
        .def_readwrite("a", &Wall::a)
        .def_readwrite("b", &Wall::b)
        .def("__repr__", [](const Wall& w){
            return "<Wall ("
                 + std::to_string(w.a.col) + "," + std::to_string(w.a.row)
                 + ")->("
                 + std::to_string(w.b.col) + "," + std::to_string(w.b.row) + ")>"; });

    // ── Door ────────────────────────────────────────────────────────────────
    py::class_<Door>(m, "Door")
        .def(py::init<>())
        .def_readwrite("id",          &Door::id)
        .def_readwrite("cells",       &Door::cells,
             "The doorway cells this door occupies (1..4). Source of truth for placement.")
        .def_property_readonly("cell", &Door::anchor,
             "Anchor cell (the first occupied cell). Back-compat single-cell accessor.")
        .def_readwrite("open",        &Door::open)
        .def_readwrite("locked",      &Door::locked)
        .def_readwrite("lock_dc",     &Door::lock_dc)
        .def_readwrite("break_dc",    &Door::break_dc,
             "DC of the Strength (Athletics) check to force the door off its frame.")
        .def_readwrite("broken",      &Door::broken,
             "Smashed off its frame: permanently open, cannot be closed or (re)locked.")
        .def_readwrite("arcane_lock", &Door::arcane_lock)
        .def_readwrite("arcane_suppressed_turns", &Door::arcane_suppressed_turns)
        .def("__repr__", [](const Door& d){
            Cell a = d.anchor();
            return "<Door #" + std::to_string(d.id) + " ("
                 + std::to_string(a.col) + "," + std::to_string(a.row) + ") x"
                 + std::to_string(d.cells.size()) + " "
                 + (d.broken ? "broken" : (d.open ? "open" : "closed"))
                 + (d.locked ? " locked" : "")
                 + (d.arcane_lock ? " arcane" : "") + ">"; });

    // ── AgentConfig ─────────────────────────────────────────────────────────
    py::class_<AgentConfig>(m, "AgentConfig")
        .def(py::init<>())
        .def_readwrite("name",       &AgentConfig::name)
        .def_property("sprite_path",
            [](const AgentConfig& t){ return t.spritePath.string(); },
            [](AgentConfig& t, const std::string& s){ t.spritePath = s; })
        .def_readwrite("size",       &AgentConfig::size)
        .def_readwrite("start_col",  &AgentConfig::startCol)
        .def_readwrite("start_row",  &AgentConfig::startRow)
        .def_readwrite("stats",      &AgentConfig::stats)
        .def("__repr__", [](const AgentConfig& t){
            return "<AgentConfig name='" + t.name
                 + "' size=" + std::to_string(t.size)
                 + " at (" + std::to_string(t.startCol)
                 + "," + std::to_string(t.startRow) + ")>"; });

    // ── PlacedAgent (read-only view) ────────────────────────────────────────
    py::class_<PlacedAgent>(m, "PlacedAgent")
        .def_property_readonly("origin",      [](const PlacedAgent& p){ return p.origin; })
        .def_property_readonly("name",        [](const PlacedAgent& p){ return std::string(p.agent->name()); })
        .def_property_readonly("size",        [](const PlacedAgent& p){ return p.agent->getSize(); })
        .def_property_readonly("sprite_path", [](const PlacedAgent& p){ return p.agent->getSprite().string(); })
        .def_property_readonly("x",           [](const PlacedAgent& p){ return p.agent->getX(); })
        .def_property_readonly("y",           [](const PlacedAgent& p){ return p.agent->getY(); })
        // Summoning (read-only view; mutate via BattleMap.set_agent_* methods)
        .def_property_readonly("summoner_idx",      [](const PlacedAgent& p){ return p.summoner_idx; })
        .def_property_readonly("summon_spell",      [](const PlacedAgent& p){ return p.summon_spell; })
        .def_property_readonly("removed_from_play", [](const PlacedAgent& p){ return p.removed_from_play; })
        .def_property_readonly("faction",           [](const PlacedAgent& p){ return p.faction; })
        // Delegate actions back to C++
        .def("turn",       [](PlacedAgent& p){ p.agent->turn(); })
        .def("action",     [](PlacedAgent& p){ p.agent->action(); })
        .def("attack",     [](PlacedAgent& p){ p.agent->attack(); })
        .def("dash",       [](PlacedAgent& p){ p.agent->dash(); })
        .def("disengage",  [](PlacedAgent& p){ p.agent->disengage(); })
        .def("dodge",      [](PlacedAgent& p){ p.agent->dodge(); })
        .def("hide",       [](PlacedAgent& p){ p.agent->hide(); })
        .def("bonus_action",[](PlacedAgent& p){ p.agent->bonusAction(); })
        .def("walk",       [](PlacedAgent& p){ p.agent->walk(); })
        .def("fly",        [](PlacedAgent& p){ p.agent->fly();  })
        .def("reaction",   [](PlacedAgent& p){ p.agent->reaction(); })
        .def_property_readonly("conditions",
            [](const PlacedAgent& p) -> const Agent::Conditions& { return p.agent->getConditions(); },
            py::return_value_policy::reference_internal)
        // Movement budget
        .def("init_movement",
            [](PlacedAgent& p, int walk, int fly, int swim, int burrow){
                p.agent->initMovement(walk, fly, swim, burrow); },
            py::arg("walk_ft"), py::arg("fly_ft") = 0,
            py::arg("swim_ft") = 0, py::arg("burrow_ft") = 0)
        .def_property_readonly("walk_remaining",
            [](const PlacedAgent& p){ return p.agent->getWalkRemaining(); })
        .def_property_readonly("fly_remaining",
            [](const PlacedAgent& p){ return p.agent->getFlyRemaining(); })
        .def_property_readonly("swim_remaining",
            [](const PlacedAgent& p){ return p.agent->getSwimRemaining(); })
        .def_property_readonly("burrow_remaining",
            [](const PlacedAgent& p){ return p.agent->getBurrowRemaining(); })
        .def("walk_to",   [](PlacedAgent& p, int x, int y, int z){ return p.agent->walkTo(x, y, z); },
            py::arg("x"), py::arg("y"), py::arg("z") = 0)
        .def("fly_to",    [](PlacedAgent& p, int x, int y, int z){ return p.agent->flyTo(x, y, z); },
            py::arg("x"), py::arg("y"), py::arg("z") = 0)
        .def("swim_to",   [](PlacedAgent& p, int x, int y, int z){ return p.agent->swimTo(x, y, z); },
            py::arg("x"), py::arg("y"), py::arg("z") = 0)
        .def("burrow_to", [](PlacedAgent& p, int x, int y, int z){ return p.agent->burrowTo(x, y, z); },
            py::arg("x"), py::arg("y"), py::arg("z") = 0)
        .def_property_readonly("weapons",
            [](const PlacedAgent& p) { return std::vector<Weapon>(p.weapons.begin(), p.weapons.end()); })
        .def_property_readonly("spells",
            [](const PlacedAgent& p) -> std::vector<Spell> { return p.spells; })
        .def_property_readonly("items",
            [](const PlacedAgent& p) -> std::vector<Item> { return p.items; })
        .def_property_readonly("stats",
            [](PlacedAgent& p) -> Agent::Stats { return p.agent->getStats(); })
        .def("set_advantage", [](PlacedAgent& p, bool adv){ p.agent->setAdvantage(adv); },
             py::arg("advantage"), "Set whether the agent has advantage on rolls.")
        .def("has_advantage", [](const PlacedAgent& p){ return p.agent->hasAdvantage(); },
             "Get whether the agent has advantage on rolls.")
        .def("set_disadvantage", [](PlacedAgent& p, bool dis){ p.agent->setDisadvantage(dis); },
             py::arg("disadvantage"), "Set whether the agent has disadvantage on rolls.")
        .def("has_disadvantage", [](const PlacedAgent& p){ return p.agent->hasDisadvantage(); },
             "Get whether the agent has disadvantage on rolls.")
        .def("__repr__", [](const PlacedAgent& p){
            return "<PlacedAgent '" + std::string(p.agent->name())
                 + "' size=" + std::to_string(p.agent->getSize())
                 + " at (" + std::to_string(p.origin.col)
                 + "," + std::to_string(p.origin.row) + ")>"; });

    // ── Resource (class features: Rage, Ki, Sorcery Points, etc.) ──────────
    py::class_<Resource>(m, "Resource")
        .def(py::init<>())
        .def(py::init<const std::string&, int>(), py::arg("name"), py::arg("max"))
        .def(py::init<const std::string&, int, int>(), py::arg("name"), py::arg("max"), py::arg("duration"))
        .def_readwrite("name", &Resource::name)
        .def_readwrite("current", &Resource::current)
        .def_readwrite("max", &Resource::max)
        .def_readwrite("short_rest_regen", &Resource::short_rest_regen)
        .def_readwrite("long_rest_regen", &Resource::long_rest_regen)
        .def_readwrite("duration", &Resource::duration)
        .def_readwrite("duration_remaining", &Resource::duration_remaining)
        .def("is_full", &Resource::isFull,
             "Check if resource is at maximum.")
        .def("is_empty", &Resource::isEmpty,
             "Check if resource is depleted.")
        .def("is_active", &Resource::isActive,
             "Check if duration-based resource is still active (duration_remaining > 0).")
        .def("spend", &Resource::spend,
             py::arg("amount") = 1,
             "Spend from resource. Returns True if successful, False if not enough.")
        .def("gain", &Resource::gain,
             py::arg("amount") = 1,
             "Gain resource (capped at max).")
        .def("restore_long_rest", &Resource::restore_long_rest,
             "Restore resource after a long rest.")
        .def("restore_short_rest", &Resource::restore_short_rest,
             "Restore resource after a short rest.")
        .def("tick_duration", &Resource::tick_duration,
             "Tick down duration by 1 turn.")
        .def("reset_duration", &Resource::reset_duration,
             "Reset duration_remaining to its maximum.")
        .def("__repr__", [](const Resource& r){
            return "<Resource '" + r.name
                 + "' " + std::to_string(r.current)
                 + "/" + std::to_string(r.max) + ">"; });

    // ── Stats (nested inside Agent) ──────────────────────────────────────────
    py::class_<Agent::Stats>(m, "Stats")
        .def(py::init<>())
        .def_static("from_json_string", &Agent::Stats::fromJsonString,
                    py::arg("json_str"),
                    "Create Stats from a JSON string (e.g., from DND2024_MonsterStats.json).")
        // Ability scores
        .def_readwrite("str",        &Agent::Stats::str)
        .def_readwrite("dex",        &Agent::Stats::dex)
        .def_readwrite("con",        &Agent::Stats::con)
        .def_readwrite("intel",      &Agent::Stats::intel)
        .def_readwrite("wis",        &Agent::Stats::wis)
        .def_readwrite("cha",        &Agent::Stats::cha)
        // Combat
        .def_readwrite("hp_max",          &Agent::Stats::hp_max)
        .def_readwrite("hp_cur",          &Agent::Stats::hp_cur)
        .def_readwrite("base_ac",         &Agent::Stats::base_ac)
        .def_readwrite("ac_temporary_modifications", &Agent::Stats::ac_temporary_modifications)
        .def_readwrite("speed_walk",   &Agent::Stats::speed_walk)
        .def_readwrite("speed_swim",   &Agent::Stats::speed_swim)
        .def_readwrite("speed_climb",  &Agent::Stats::speed_climb)
        .def_readwrite("speed_fly",    &Agent::Stats::speed_fly)
        .def_readwrite("speed_burrow", &Agent::Stats::speed_burrow)
        .def_readwrite("prof_bonus",      &Agent::Stats::prof_bonus)
        // Saving throw proficiency flags (one per ability)
        .def_readwrite("save_prof_str",   &Agent::Stats::save_prof_str)
        .def_readwrite("save_prof_dex",   &Agent::Stats::save_prof_dex)
        .def_readwrite("save_prof_con",   &Agent::Stats::save_prof_con)
        .def_readwrite("save_prof_intel", &Agent::Stats::save_prof_intel)
        .def_readwrite("save_prof_wis",   &Agent::Stats::save_prof_wis)
        .def_readwrite("save_prof_cha",   &Agent::Stats::save_prof_cha)
        // Scoped saving-throw Advantage bitmask (Phase 0.3): bit (1<<SaveAbility_t) => Advantage on
        // that ability's saves. Set/cleared by "Advantage on X saves" buffs like Haste.
        .def_readwrite("save_advantage_mask", &Agent::Stats::save_advantage_mask)
        .def_readwrite("blessed", &Agent::Stats::blessed)   // Bless: +1d4 to attacks & saves
        .def_readwrite("baned", &Agent::Stats::baned)       // Bane:  -1d4 to attacks & saves
        // Haste (Phase 2): +2 AC, Adv on DEX saves, doubled Speed, one extra limited action/turn.
        .def_readwrite("hasted", &Agent::Stats::hasted)
        .def_readwrite("haste_speed_bonus", &Agent::Stats::haste_speed_bonus)
        .def_readwrite("haste_action_available", &Agent::Stats::haste_action_available)
        // Aid (Phase 3): the +HP maximum currently granted (stored for an exact teardown).
        .def_readwrite("aid_hp_bonus", &Agent::Stats::aid_hp_bonus)
        // Tier 1 spell buffs / debuffs (SPELL_IMPLEMENTATION_PLAN.md)
        .def_readwrite("longstrider_bonus",       &Agent::Stats::longstrider_bonus)
        .def_readwrite("expeditious_retreat",     &Agent::Stats::expeditious_retreat)
        .def_readwrite("attackers_disadvantage",  &Agent::Stats::attackers_disadvantage)
        .def_readwrite("has_foresight",           &Agent::Stats::has_foresight)
        .def_readwrite("barkskin_ac_bonus",       &Agent::Stats::barkskin_ac_bonus)
        .def_readwrite("enfeebled",               &Agent::Stats::enfeebled)
        .def_readwrite("size_damage_dice",        &Agent::Stats::size_damage_dice)
        .def_readwrite("immune_charm",            &Agent::Stats::immune_charm)
        .def_readwrite("mind_blank_psychic_saved",&Agent::Stats::mind_blank_psychic_saved)
        .def_readwrite("regenerate_saved",        &Agent::Stats::regenerate_saved)
        // Skill proficiency flags
        .def_readwrite("stealth_prof",    &Agent::Stats::stealth_prof)
        .def_readwrite("perception_prof", &Agent::Stats::perception_prof)
        .def_readwrite("sleight_of_hand_prof",      &Agent::Stats::sleight_of_hand_prof)
        .def_readwrite("sleight_of_hand_expertise", &Agent::Stats::sleight_of_hand_expertise)
        .def_readwrite("athletics_prof",            &Agent::Stats::athletics_prof)
        .def_readwrite("athletics_expertise",       &Agent::Stats::athletics_expertise)
        // Skill bonus methods
        .def("stealth_bonus",       &Agent::Stats::stealthBonus)
        .def("passive_perception",  &Agent::Stats::passivePerception)
        .def("sleight_of_hand",     &Agent::Stats::sleightOfHand)
        .def("athletics",           &Agent::Stats::athletics)
        // Class-feature capability flags
        .def_readwrite("num_attacks",          &Agent::Stats::num_attacks)
        .def_readwrite("multiattack",          &Agent::Stats::multiattack)
        .def_readwrite("bonus_attacks_remaining", &Agent::Stats::bonus_attacks_remaining)
        .def_readwrite("bonus_actions_max",       &Agent::Stats::bonus_actions_max)
        .def_readwrite("bonus_actions_remaining", &Agent::Stats::bonus_actions_remaining)
        .def_readwrite("has_cunning_action",   &Agent::Stats::has_cunning_action)
        .def_readwrite("has_offhand_attack",   &Agent::Stats::has_offhand_attack)
        .def_readwrite("can_cast_spell",       &Agent::Stats::can_cast_spell)
        .def_readwrite("has_sentinel",             &Agent::Stats::has_sentinel)
        .def_readwrite("has_branches_of_the_tree", &Agent::Stats::has_branches_of_the_tree)
        .def_readwrite("spellcasting_ability", &Agent::Stats::spellcasting_ability)
        // Initiative
        .def_readwrite("initiative_prof", &Agent::Stats::initiative_prof)
        .def_property_readonly("initiative_modifier", &Agent::Stats::initiativeModifier)
        // Character Class & Spell Slots. Multiclassing (MULTICLASSING_PLAN.md):
        // class_levels is the source of truth. character_class/char_level stay
        // read/WRITE for back-compat (existing code + tests assign them directly as
        // `stats.character_class = X; stats.char_level = N`), but each write routes
        // through a compat setter that keeps class_levels in sync for the single-
        // class case those scalars describe. Multiclass callers use
        // set_class_level() (single-class reset) or add_class_level() (add one class).
        .def_property("character_class",
             [](const Agent::Stats& s) { return s.character_class; },
             [](Agent::Stats& s, CharacterClass c) { s.setPrimaryClassMirror(c); },
             "Primary class (lowest-enum class with levels), mirror of class_levels.\n"
             "Writing it makes that class the SOLE class (single-class reset, level preserved);\n"
             "use set_class_level()/add_class_level() for multiclass. Prefer has_class()/class_level() to read.")
        .def_property("char_level",
             [](const Agent::Stats& s) { return s.char_level; },
             [](Agent::Stats& s, int n) { s.setCharLevelMirror(n); },
             "Total character level, mirror of total_level(). Writing it sets the (single)\n"
             "primary class's level; multiclass callers use set_class_level()/add_class_level().")
        .def_property_readonly("class_levels",
             [](const Agent::Stats& s) {
                 std::vector<int> v(static_cast<std::size_t>(NumCharacterClass), 0);
                 for (int c = 1; c < static_cast<int>(NumCharacterClass); ++c)
                     v[static_cast<std::size_t>(c)] =
                         s.classLevel(static_cast<CharacterClass>(c));
                 return v;
             },
             "Per-class levels indexed by the CharacterClass enum (list of ints; 0 = no levels).")
        .def("has_class", &Agent::Stats::hasClass, py::arg("cls"),
             "True if the creature has any levels in class cls.")
        .def("class_level", &Agent::Stats::classLevel, py::arg("cls"),
             "This creature's level in class cls (0 if it lacks the class).")
        .def("total_level", &Agent::Stats::totalLevel,
             "Sum of all class levels (proficiency/feat cadence; mirrored by char_level).")
        .def_readwrite("spell_slots_max",       &Agent::Stats::spell_slots_max)
        .def_readwrite("spell_slots_remaining", &Agent::Stats::spell_slots_remaining)
        .def_readwrite("darkvision_range",     &Agent::Stats::darkvision_range,
             "Darkvision range in feet (0 = no darkvision). See normally in Darkness within range.")
        .def_readwrite("truesight_range",      &Agent::Stats::truesight_range,
             "Truesight range in feet (0 = no truesight). See normally in all light including magical darkness.")
        .def_readwrite("devilssight_range",    &Agent::Stats::devilssight_range,
             "Devil's Sight range in feet (0 = no devil's sight). See in Darkness and MagicalDarkness within range.")
        .def_readwrite("blindsight_range",     &Agent::Stats::blindsight_range,
             "Blindsight range in feet (0 = none). Pierces the Invisible condition within range.")
        .def_readwrite("is_npc", &Agent::Stats::is_npc,
             "True if this agent uses N/day spell system (NPC); false if using spell slots (player).")
        .def_readwrite("leveled_spell_cast_this_turn", &Agent::Stats::leveled_spell_cast_this_turn,
             "D&D 5e rule: only one leveled spell (level >= 1) per turn. Reset at turn start.")
        .def_readwrite("temp_hp", &Agent::Stats::temp_hp,
             "Temporary hit points (absorbs damage before hp_cur).")
        .def_readwrite("available_hit_points", &Agent::Stats::available_hit_points,
             "Mirror of temp_hp: a non-negative reduction to the HP maximum (vampiric drain, etc.).\n"
             "effective_max_hp = max(0, hp_max - available_hit_points); cleared on a long rest.")
        .def_property_readonly("effective_max_hp", &Agent::Stats::effectiveMaxHp,
             "Usable HP maximum after any reduction: max(0, hp_max - available_hit_points).")
        .def_readwrite("rage_thp_source_idx", &Agent::Stats::rage_thp_source_idx,
             "Index of the Barbarian whose Rage granted the current temp HP (World Tree Vitality of the\n"
             "Tree), or -1 for any other source. endRage clears temp HP tagged with the ending Barbarian.")
        .def_readwrite("magic_damage_multipliers", &Agent::Stats::magic_damage_multipliers,
             "Per-type magic damage multipliers: 0.0=immune, 0.5=resist, 1.0=normal, 2.0=vulnerable.")
        .def_readwrite("physical_damage_multipliers", &Agent::Stats::physical_damage_multipliers,
             "Per-type physical damage multipliers: 0.0=immune, 0.5=resist, 1.0=normal, 2.0=vulnerable.")
        .def("set_class_level", &Agent::Stats::set_class_level,
             py::arg("cls"), py::arg("level"),
             "Set the character class and level (SINGLE-CLASS RESET: clears any other class\n"
             "levels first). Automatically computes spell_slots_max and the class mirrors.")
        .def("add_class_level", &Agent::Stats::add_class_level,
             py::arg("cls"), py::arg("level"),
             "Additively set one class's level (multiclass entry point). Unlike set_class_level\n"
             "this does NOT clear the other classes. Recomputes the character_class/char_level mirrors.")
        .def("compute_multiclass_slots", &Agent::Stats::computeMulticlassSlots,
             "Phase 3: the combined leveled-slot array for this creature's full mix of\n"
             "spellcasting classes (single-class → that class's own table; 2+ casters →\n"
             "combined caster level on the full-caster table). Warlock Pact Magic is a\n"
             "separate pool: a Warlock-only caster returns its pact table; a Warlock's\n"
             "levels are ignored when other caster classes are present. Third-caster\n"
             "(EK/AT) contribution requires the subclass to be set.")
        .def("restore_spell_slots", &Agent::Stats::restore_spell_slots,
             "Restore spell_slots_remaining to their maximum (Long Rest).")
        .def("pact_slot_level", &Agent::Stats::pact_slot_level,
             "Warlock Pact Magic: the single slot level (1-5) the pact slots occupy, or 0 if none.")
        // D&D 5e leveled spell per-turn rule
        .def("can_cast_leveled_spell", &Agent::Stats::canCastLeveledSpell,
             "Check if a leveled spell (level >= 1) can be cast this turn.")
        .def("mark_leveled_spell_cast", &Agent::Stats::markLeveledSpellCast,
             py::arg("spell_level"),
             "Mark that a leveled spell has been cast this turn (if spell_level >= 1).")
        .def("reset_leveled_spell_cast_flag", &Agent::Stats::resetLeveledSpellCastFlag,
             "Reset the leveled spell flag at the start of a new turn.")
        // Class resources (Rage, Ki, Sorcery Points, etc.)
        .def("get_resource", py::overload_cast<const std::string&>(&Agent::Stats::getResource),
             py::arg("name"), py::return_value_policy::reference,
             "Get a resource by name (e.g., 'Rage', 'Ki'). Returns None if not found.")
        .def("initialize_class_resources", &Agent::Stats::initializeClassResources,
             py::arg("cls"), py::arg("level"),
             "Initialize resources for a class at a given level (Rage for Barbarian, Ki for Monk, etc.)")
        .def("initialize_multiclass_resources", &Agent::Stats::initializeMulticlassResources,
             "Initialize resources for ALL classes in class_levels (multiclass merge): "
             "accumulates each class's resources; Extra Attack does not stack.")
        .def("restore_resources_long_rest", &Agent::Stats::restore_resources_long_rest,
             "Restore all resources and spell slots after a long rest.")
        .def("restore_resources_short_rest", &Agent::Stats::restore_resources_short_rest,
             "Restore resources that are restored on short rest (e.g., Ki for Monk).")
        .def("tick_resource_durations", &Agent::Stats::tick_resource_durations,
             "Tick down duration counters for all duration-based resources (call at end of turn).")
        .def_readwrite("resources", &Agent::Stats::resources,
             "Map of class resources by name (e.g., {'Rage': Resource(...), 'Ki': Resource(...)})")
        .def("set_magic_damage_multiplier", &Agent::Stats::set_magic_damage_multiplier,
             py::arg("type_idx"), py::arg("multiplier"),
             "Set magic damage multiplier: 0.0=immune, 0.5=resist, 1.0=normal, 2.0=vulnerable")
        .def("set_physical_damage_multiplier", &Agent::Stats::set_physical_damage_multiplier,
             py::arg("type_idx"), py::arg("multiplier"),
             "Set physical damage multiplier: 0.0=immune, 0.5=resist, 1.0=normal, 2.0=vulnerable")
        .def("get_magic_damage_multiplier", &Agent::Stats::get_magic_damage_multiplier,
             py::arg("type_idx"),
             "Get magic damage multiplier for a type")
        .def("get_physical_damage_multiplier", &Agent::Stats::get_physical_damage_multiplier,
             py::arg("type_idx"),
             "Get physical damage multiplier for a type")
        // Spell Save DCs (computed read-only: 8 + mod [+ prof_bonus if proficient])
        .def_property_readonly("spell_save_dc_str",   &Agent::Stats::spellSaveDcStr)
        .def_property_readonly("spell_save_dc_dex",   &Agent::Stats::spellSaveDcDex)
        .def_property_readonly("spell_save_dc_con",   &Agent::Stats::spellSaveDcCon)
        .def_property_readonly("spell_save_dc_intel", &Agent::Stats::spellSaveDcIntel)
        .def_property_readonly("spell_save_dc_wis",   &Agent::Stats::spellSaveDcWis)
        .def_property_readonly("spell_save_dc_cha",   &Agent::Stats::spellSaveDcCha)
        // Character identity & background
        .def_readwrite("background", &Agent::Stats::background,
             "Character background (Acolyte, Criminal, etc.)")
        .def_readwrite("alignment", &Agent::Stats::alignment,
             "Character alignment (LawfulGood, TrueNeutral, etc.)")
        .def_readwrite("barbarian_subclass", &Agent::Stats::barbarian_subclass,
             "Barbarian subclass (only valid when character_class == Barbarian)")
        .def_readwrite("wild_heart_rage_choice", &Agent::Stats::wild_heart_rage_choice,
             "Wild Heart Rage of the Wilds choice (Bear/Eagle/Wolf); set before activateRage()")
        .def_readwrite("wild_heart_aspect", &Agent::Stats::wild_heart_aspect,
             "Wild Heart L6 Aspect choice (Owl/Panther/Salmon); set before combat or at long rest")
        .def_readwrite("wild_heart_power", &Agent::Stats::wild_heart_power,
             "Wild Heart L14 Power of the Wilds choice (Falcon/Lion/Ram); set before activateRage()")
        .def_readwrite("rage_of_gods_used", &Agent::Stats::rage_of_gods_used,
             "Zealot L14 Rage of the Gods: True once the divine form has been assumed this long rest")
        .def_readwrite("brutal_strike_damage_dice", &Agent::Stats::brutal_strike_damage_dice,
             "Brutal Strike damage dice count: 1 (L9-16) or 2 (L17+) for 1d10 or 2d10")
        .def_readwrite("primal_champion_applied", &Agent::Stats::primal_champion_applied,
             "Barbarian L20 Primal Champion: +4 STR/CON (capped at 25) applied (idempotent flag)")
        .def_readwrite("relentless_rage_dc", &Agent::Stats::relentless_rage_dc,
             "Barbarian L11 Relentless Rage save DC (base 10, +5 per use in same Rage; reset on rage end)")
        .def_readwrite("crit_threshold", &Agent::Stats::crit_threshold,
             "d20 roll >= this is a critical hit (default 20, Champion lowers it to 19/18)")
        .def_readwrite("superiority_die_size", &Agent::Stats::superiority_die_size,
             "Battle Master: superiority die size (8 at L3-9, 10 at L10+)")
        .def_readwrite("psionic_die_size", &Agent::Stats::psionic_die_size,
             "Psi Warrior: Psionic Energy die size (d6 L3, d8 L5, d10 L11, d12 L17)")
        .def_readwrite("sacred_weapon_bonus", &Agent::Stats::sacred_weapon_bonus,
             "Paladin Oath of Devotion: Sacred Weapon attack-roll bonus (0 = inactive)")
        .def_readwrite("sacred_weapon_turns", &Agent::Stats::sacred_weapon_turns,
             "Sacred Weapon remaining duration in rounds (decrements at turn start)")
        .def_readwrite("vow_of_enmity_target", &Agent::Stats::vow_of_enmity_target,
             "Paladin Oath of Vengeance L3 Vow of Enmity: sworn target agent index (-1 = none)")
        .def_readwrite("vow_of_enmity_turns", &Agent::Stats::vow_of_enmity_turns,
             "Vow of Enmity remaining duration in rounds (decrements at turn start; 0 = inactive)")
        .def_readwrite("avenging_angel_turns", &Agent::Stats::avenging_angel_turns,
             "Paladin Oath of Vengeance L20 Avenging Angel: remaining duration in rounds "
             "(>0 = Fly 60 + hover and a Frightful Aura in the Aura of Protection)")
        .def_readwrite("undying_sentinel_used", &Agent::Stats::undying_sentinel_used,
             "Paladin Oath of the Ancients L15 Undying Sentinel: 1/long-rest drop-to-1-HP used (reset on long rest)")
        .def_readwrite("elder_champion_turns", &Agent::Stats::elder_champion_turns,
             "Paladin Oath of the Ancients L20 Elder Champion: remaining duration in rounds "
             "(>0 = regen 10/turn; enemies in aura have Disadvantage on saves vs your spells/CD)")
        .def_readwrite("living_legend_turns", &Agent::Stats::living_legend_turns,
             "Paladin Oath of Glory L20 Living Legend: remaining duration in rounds "
             "(>0 = save-reroll reaction + once/turn Unerring Strike miss→hit)")
        .def_readwrite("corona_of_light_turns", &Agent::Stats::corona_of_light_turns,
             "Cleric Light Domain (L17) Corona of Light remaining duration in rounds (>0 = enemies in 60ft "
             "have Disadvantage on saves vs the caster's Fire/Radiant spells)")
        .def_readwrite("innate_sorcery_turns", &Agent::Stats::innate_sorcery_turns,
             "Sorcerer Innate Sorcery remaining duration in rounds (>0 = active: +1 spell DC, advantage on spell attacks)")
        .def_readwrite("draconic_hp_applied", &Agent::Stats::draconic_hp_applied,
             "Draconic L3 Resilience HP bonus applied (idempotent flag); bonus = 3 + max(0, level-3)")
        .def_readwrite("draconic_affinity_type", &Agent::Stats::draconic_affinity_type,
             "Draconic L6 Elemental Affinity: chosen MagicDamage_t index (0-9), -1 = none")
        .def_readwrite("draconic_affinity_used_this_turn", &Agent::Stats::draconic_affinity_used_this_turn,
             "Draconic L6 Elemental Affinity: CHA mod bonus already applied this turn (reset in beginTurn)")
        .def_readwrite("draconic_affinity_resist_turns", &Agent::Stats::draconic_affinity_resist_turns,
             "Draconic L6 Elemental Affinity: rounds remaining for 0.5x resistance to chosen type "
             "(1 hour = 600 rounds; ticks in beginTurn; 0 = inactive)")
        .def_readwrite("dragon_wings_active", &Agent::Stats::dragon_wings_active,
             "Draconic L14 Dragon Wings: fly speed = walk speed is active")
        .def_readwrite("overchannel_uses", &Agent::Stats::overchannel_uses,
             "Evoker L14 Overchannel: times used since last Long Rest (0 = next use is free). "
             "Escalating Necrotic self-damage kicks in from the 2nd use. Reset to 0 on Long Rest.")
        .def_readwrite("trance_of_order_turns", &Agent::Stats::trance_of_order_turns,
             "Clockwork L14 Trance of Order window in rounds (>0 = active: attacks vs you lose "
             "Advantage + you floor your own d20s to 10; ticks in beginTurn)")
        .def_readwrite("bastion_ward", &Agent::Stats::bastion_ward,
             "Clockwork L6 Bastion of Law: pre-rolled d8 ward pool absorbing damage before temp HP "
             "(decremented as it soaks; cleared on a long rest)")
        .def_readwrite("revelation_in_flesh_turns", &Agent::Stats::revelation_in_flesh_turns,
             "Aberrant L14 Revelation in Flesh window in rounds (>0 = active: fly+hover, swim, "
             "truesight 60 ft / see invisible; ticks in beginTurn, reverts on expiry)")
        .def_readwrite("revelation_prior_fly", &Agent::Stats::revelation_prior_fly)
        .def_readwrite("revelation_prior_swim", &Agent::Stats::revelation_prior_swim)
        .def_readwrite("revelation_prior_truesight", &Agent::Stats::revelation_prior_truesight)
        .def_readwrite("mantle_majesty_turns", &Agent::Stats::mantle_majesty_turns,
             "Bard College of Glamour (L6) Mantle of Majesty 'unearthly appearance' window in rounds "
             "(>0 = may re-cast Command as a Bonus Action with no slot; tied to concentration)")
        .def_readwrite("majestic_presence_turns", &Agent::Stats::majestic_presence_turns,
             "Bard College of Glamour (L14) Unbreakable Majesty 'majestic presence' window in rounds "
             "(>0 = melee attacks against the bard trigger Psychic damage + a CHA save; tied to concentration)")
        .def_readwrite("shield_active", &Agent::Stats::shield_active,
             "Shield spell active: +5 AC (in ac_temporary_modifications) until start of next turn + MM immunity")
        .def_readwrite("wild_magic_shield_turns", &Agent::Stats::wild_magic_shield_turns,
             "Wild Magic Surge band 2 (spectral shield): rounds of +2 AC + Magic Missile immunity left")
        .def_readwrite("wild_magic_regen_turns", &Agent::Stats::wild_magic_regen_turns,
             "Wild Magic Surge band 3: rounds of 'regain 5 HP at the start of your turn' left")
        .def_readwrite("wild_magic_skip_next_turn", &Agent::Stats::wild_magic_skip_next_turn,
             "Wild Magic Surge band 7: this agent's next turn is skipped")
        .def_readwrite("wild_magic_extra_action", &Agent::Stats::wild_magic_extra_action,
             "Wild Magic Surge band 8: GUI grants one extra action this turn")
        .def_readwrite("wild_magic_bonus_cast_turns", &Agent::Stats::wild_magic_bonus_cast_turns,
             "Wild Magic Surge band 6: rounds left where action-cast spells may be cast as a Bonus Action (GUI-enforced)")
        .def_readwrite("wild_magic_teleport_bonus_turns", &Agent::Stats::wild_magic_teleport_bonus_turns,
             "Wild Magic Surge band 10: rounds left where the agent may teleport 20 ft as a Bonus Action (GUI-enforced)")
        .def_readwrite("fighter_subclass", &Agent::Stats::fighter_subclass,
             "Fighter subclass (only valid when character_class == Fighter)")
        .def_readwrite("druid_circle", &Agent::Stats::druid_circle,
             "Druid circle choice (only valid when character_class == Druid)")
        .def_readwrite("monk_subclass", &Agent::Stats::monk_subclass,
             "Monk subclass (only valid when character_class == Monk)")
        .def_readwrite("monk_body_mind_applied", &Agent::Stats::monk_body_mind_applied,
             "Monk L20 Body and Mind: +4 DEX/WIS (capped at 25) applied (idempotent flag)")
        .def_readwrite("unarmed_damage_override", &Agent::Stats::unarmed_damage_override,
             "Unarmed-strike damage-type override: -1 = none (Bludgeoning default), else a MagicDamage_t "
             "value. Set by Monk L6 Empowered Strikes (Force=3) and Elements L3 Elemental Attunement "
             "(chosen Acid/Cold/Fire/Lightning/Thunder).")
        .def_readwrite("paladin_oath", &Agent::Stats::paladin_oath,
             "Paladin oath choice (only valid when character_class == Paladin)")
        .def_readwrite("wizard_subclass", &Agent::Stats::wizard_subclass,
             "Wizard subclass (only valid when character_class == Wizard)")
        .def_readwrite("sorcerer_subclass", &Agent::Stats::sorcerer_subclass,
             "Sorcerer subclass (only valid when character_class == Sorcerer)")
        .def_readwrite("bard_subclass", &Agent::Stats::bard_subclass,
             "Bard college (only valid when character_class == Bard)")
        .def_readwrite("metamagic_options", &Agent::Stats::metamagic_options,
             "Sorcerer Metamagic options chosen (2 @ L2, 4 @ L10, 6 @ L17)")
        .def_readwrite("warlock_subclass", &Agent::Stats::warlock_subclass,
             "Warlock patron subclass (only valid when character_class == Warlock)")
        .def_readwrite("rogue_subclass", &Agent::Stats::rogue_subclass,
             "Rogue subclass (only valid when character_class == Rogue)")
        .def_readwrite("ranger_subclass", &Agent::Stats::ranger_subclass,
             "Ranger subclass (only valid when character_class == Ranger)")
        .def_readwrite("hunter_prey", &Agent::Stats::hunter_prey,
             "Hunter L3 Hunter's Prey choice (Colossus Slayer / Horde Breaker)")
        .def_readwrite("defensive_tactics", &Agent::Stats::defensive_tactics,
             "Hunter L7 Defensive Tactics choice (Escape the Horde / Multiattack Defense)")
        .def_readwrite("primal_companion", &Agent::Stats::primal_companion,
             "Beast Master L3 Primal Companion form (Land / Sea / Sky); remembered for re-summon")
        .def_readwrite("hunters_mark_target", &Agent::Stats::hunters_mark_target,
             "Ranger/Warlock marked-target agent index for Hunter's Mark / Hex (-1 = none)")
        .def_readwrite("hunters_mark_dice", &Agent::Stats::hunters_mark_dice,
             "Number of marked-target rider dice")
        .def_readwrite("hunters_mark_die_size", &Agent::Stats::hunters_mark_die_size,
             "Marked-target rider die size (6=d6 Hunter's Mark, 10=d10 Foe Slayer)")
        .def_readwrite("hunters_mark_damage_type", &Agent::Stats::hunters_mark_damage_type,
             "Marked-target rider MagicDamage_t (3=Force HM, 7=Psychic Hex)")
        .def_readwrite("dread_ambusher", &Agent::Stats::dread_ambusher,
             "Gloom Stalker: add WIS modifier to Initiative rolls (Dread Ambusher Initiative Bonus)")
        .def_readwrite("dreadful_strike_dice", &Agent::Stats::dreadful_strike_dice,
             "Gloom Stalker Dreadful Strike rider dice (2d6 → 2d8 at L11)")
        .def_readwrite("dreadful_strike_die_size", &Agent::Stats::dreadful_strike_die_size,
             "Gloom Stalker Dreadful Strike die size (6=d6, 8 at L11 Stalker's Flurry)")
        .def_readwrite("fey_dreadful_strikes", &Agent::Stats::fey_dreadful_strikes,
             "Fey Wanderer L3 Dreadful Strikes: weapon hit adds Psychic once/turn")
        .def_readwrite("fey_dreadful_strikes_die_size", &Agent::Stats::fey_dreadful_strikes_die_size,
             "Fey Wanderer Dreadful Strikes die size (4=d4, 6 at L11)")
        .def_readwrite("cleric_subclass", &Agent::Stats::cleric_subclass,
             "Cleric divine domain (only valid when character_class == Cleric)")
        .def_readwrite("blessed_strike", &Agent::Stats::blessed_strike,
             "Cleric L7 Blessed Strikes choice: DivineStrike or PotentSpellcasting.")
        .def_readwrite("divine_intervention_lock", &Agent::Stats::divine_intervention_lock,
             "Greater Divine Intervention (Cleric L20) recharge lock: remaining Long Rests before\n"
             "the DI resource refills again (0 = normal). Set to 2d4 when Wish is chosen.")
        // Druid Features
        .def_readwrite("wild_shape_active", &Agent::Stats::wild_shape_active,
             "True when Druid is in an active Wild Shape form.")
        .def_readwrite("wild_shape_form_name", &Agent::Stats::wild_shape_form_name,
             "Beast form name (e.g., 'Brown Bear') when wild_shape_active is true.")
        .def_readwrite("wild_shape_saved_ac", &Agent::Stats::wild_shape_saved_ac,
             "Saved AC before entering Wild Shape (to restore on exit).")
        .def_readwrite("wild_shape_saved_str", &Agent::Stats::wild_shape_saved_str,
             "Saved STR before entering Wild Shape.")
        .def_readwrite("wild_shape_saved_dex", &Agent::Stats::wild_shape_saved_dex,
             "Saved DEX before entering Wild Shape.")
        .def_readwrite("wild_shape_saved_con", &Agent::Stats::wild_shape_saved_con,
             "Saved CON before entering Wild Shape.")
        .def_readwrite("starry_form_active", &Agent::Stats::starry_form_active,
             "True when Circle of the Stars Druid is in Starry Form.")
        .def_readwrite("starry_constellation", &Agent::Stats::starry_constellation,
             "Starry Form constellation choice: 0=none, 1=Archer, 2=Chalice, 3=Dragon.")
        .def_readwrite("land_type", &Agent::Stats::land_type,
             "Circle of the Land type: 0=none, 1=Arid, 2=Polar, 3=Temperate, 4=Tropical.")
        .def_readwrite("wrath_of_sea_active", &Agent::Stats::wrath_of_sea_active,
             "True when Circle of the Sea Wrath of the Sea is active.")
        .def_readwrite("lunar_radiance_available", &Agent::Stats::lunar_radiance_available,
             "Circle of the Moon L6+ feature: Wild Shape attacks can deal Radiant damage.")
        .def_readwrite("improved_lunar_radiance_available", &Agent::Stats::improved_lunar_radiance_available,
             "Circle of the Moon L14+ feature: Improved Lunar Radiance rider available.")
        .def_readwrite("primal_strike_active", &Agent::Stats::primal_strike_active,
             "Druid L7 Primal Strike rider is active.")
        .def_readwrite("primal_strike_damage_type", &Agent::Stats::primal_strike_damage_type,
             "Primal Strike elemental damage type choice.")
        .def_readwrite("is_undead", &Agent::Stats::is_undead,
             "Creature type is Undead (a valid Turn Undead target).")
        .def_readwrite("is_fiend", &Agent::Stats::is_fiend,
             "Creature type is Fiend (takes Divine Smite's +1d8, like Undead).")
        .def_readwrite("is_celestial", &Agent::Stats::is_celestial,
             "Creature type is Celestial (a Magic Circle / Hallow warded type).")
        .def_readwrite("is_elemental", &Agent::Stats::is_elemental,
             "Creature type is Elemental (a Magic Circle / Hallow warded type).")
        .def_readwrite("is_fey", &Agent::Stats::is_fey,
             "Creature type is Fey (a Magic Circle / Hallow warded type).")
        .def_readwrite("is_aberration", &Agent::Stats::is_aberration,
             "Creature type is Aberration (a Hallow / Glyph of Warding warded type).")
        .def_readwrite("is_vampire", &Agent::Stats::is_vampire,
             "Creature type is Vampire (takes 20 radiant damage at turn start in Sunlight).")
        .def_readwrite("magic_resistance", &Agent::Stats::magic_resistance,
             "Magic Resistance trait: Advantage on saving throws against spells and other magical effects.")
        .def_readwrite("cant_heal", &Agent::Stats::cant_heal,
             "Derived: true while a prevents_healing condition is active (Pit Fiend poison). Blocks "
             "healAgent + Regeneration. Set/recomputed by the condition lifecycle — not authored.")
        .def_readwrite("death_burst_spell", &Agent::Stats::death_burst_spell,
             "Name of a spell in this creature's own list that detonates centered on it when it "
             "drops to 0 HP (Balor Death Throes). Empty = no burst.")
        .def_readwrite("regeneration_amount", &Agent::Stats::regeneration_amount,
             "Regeneration: HP regained at the start of each turn (0 = none). Capped at effective max HP.")
        .def_readwrite("regen_interrupt_damage_types", &Agent::Stats::regen_interrupt_damage_types,
             "Regeneration: MagicDamage_t indices that suppress the next regen if taken "
             "(e.g. Troll = [Acid, Fire], Vampire = [Radiant]). Assign a whole list; do not append in place.")
        .def_readwrite("regen_suppressed", &Agent::Stats::regen_suppressed,
             "Regeneration: transient flag — true means the next turn's regen is skipped. Set by the "
             "engine on interrupting damage / Sunlight; consumed at turn start. Not normally serialized.")
        .def_readwrite("legendary_resistance_max", &Agent::Stats::legendary_resistance_max,
             "Legendary Resistance uses per day (resets on a Long Rest).")
        .def_readwrite("legendary_resistance_current", &Agent::Stats::legendary_resistance_current,
             "Legendary Resistance uses remaining today.")
        .def_readwrite("legendary_actions_max", &Agent::Stats::legendary_actions_max,
             "Legendary Actions available per round (resets at the start of the creature's turn).")
        .def_readwrite("legendary_actions_current", &Agent::Stats::legendary_actions_current,
             "Legendary Actions remaining this round.")
        .def_readwrite("has_legendary_actions", &Agent::Stats::has_legendary_actions,
             "Gate: this creature may take Legendary Actions after other creatures' turns.")
        .def_readwrite("is_in_lair", &Agent::Stats::is_in_lair,
             "Creature is in its lair (uses the in-lair legendary counts).")
        .def_readwrite("legendary_action_names", &Agent::Stats::legendary_action_names,
             "Available Legendary Action option names (e.g. ['Bite','Claw','Dash','DashHalf']).")
        .def_readwrite("weapon_mastery", &Agent::Stats::weapon_mastery,
             "Number of Weapon Mastery properties known (>0 = the feature is active).")
        .def_readwrite("eldritch_invocations", &Agent::Stats::eldritch_invocations,
             "Warlock eldritch invocations (list of invocation codes)")
        .def("has_invocation", &Agent::Stats::hasInvocation,
             "Check if warlock has a specific invocation code")
        .def_readwrite("feats", &Agent::Stats::feats,
             "Feats taken (list of canonical names, e.g. 'Tough', 'Savage Attacker', "
             "'Tavern Brawler', 'Alert', 'Lucky'). Set directly when restoring a save.")
        .def("has_feat", &Agent::Stats::hasFeat, py::arg("name"),
             "Check whether the character has the named feat")
        .def("add_feat", &Agent::Stats::addFeat, py::arg("name"),
             "Grant a feat and apply its one-time stat effects (Tough HP, Alert initiative "
             "proficiency, Lucky points). Call after ability scores/level/prof_bonus are set. "
             "On reload, set `feats` directly instead — bonuses are already folded into hp_max/luck_points.")
        .def_readwrite("stolen_spell_names", &Agent::Stats::stolen_spell_names,
             "Spell names this caster currently can't cast because an Arcane Trickster stole them "
             "(Spell Thief, L17). Cleared on a long rest. Round-trips in save/load.")
        .def_readwrite("elemental_adept_types", &Agent::Stats::elemental_adept_types,
             "MagicDamage_t indices (Acid=0,Cold=1,Fire=2,Lightning=4,Thunder=9) whose Resistance this "
             "caster's Elemental Adept ignores (and whose spell dice treat a 1 as a 2). One entry per "
             "element the feat was taken for; chosen via the GUI element picker, serialized in the save.")
        .def("has_elemental_adept_type", &Agent::Stats::hasElementalAdeptType, py::arg("type"),
             "True if the caster has Elemental Adept covering MagicDamage_t `type`.")
        .def_readwrite("irresistible_offense_ability", &Agent::Stats::irresistible_offense_ability,
             "Boon of Irresistible Offense: which score the boon boosted (0=STR, 1=DEX). "
             "Overwhelming Strike reads this ability's live full score for its natural-20 bonus damage.")
        .def_readwrite("luck_points", &Agent::Stats::luck_points,
             "Lucky feat: current Luck Points (spent for Advantage; regained on a Long Rest)")
        .def_readwrite("luck_points_max", &Agent::Stats::luck_points_max,
             "Lucky feat: maximum Luck Points (= proficiency bonus)")
        .def_readwrite("boon_of_fate_used", &Agent::Stats::boon_of_fate_used,
             "Boon of Fate (epic boon): whether the 1/rest Improve Fate use is spent "
             "(reset on short/long rest and at initiative). Available == has feat and not used.")
        .def_readwrite("fiendish_resilience_type", &Agent::Stats::fiendish_resilience_type,
             "Fiend Warlock L10: chosen magic damage type for resistance (0-9, ≠3 Force; -1 = none)")
        .def_readwrite("portent_dice", &Agent::Stats::portent_dice,
             "Diviner Wizard: deque of d20 portent rolls (regenerated on long rest, used with use_portent_die)")
        .def_readwrite("bardic_inspiration_die", &Agent::Stats::bardic_inspiration_die,
             "Bard: SIZE of the held Bardic Inspiration die (0 = none; 6/8/10/12). "
             "Granted with grant_bardic_die, spent with use_bardic_die.")
        .def_readwrite("bardic_inspiration_die_size", &Agent::Stats::bardic_inspiration_die_size,
             "Bard: the die size this bard GRANTS (d6/d8/d10/d12), set by level in initialize_class_resources.")
        .def("__repr__", [](const Agent::Stats& s){
            return "<Stats STR=" + std::to_string(s.str)
                 + " DEX=" + std::to_string(s.dex)
                 + " CON=" + std::to_string(s.con)
                 + " INT=" + std::to_string(s.intel)
                 + " WIS=" + std::to_string(s.wis)
                 + " CHA=" + std::to_string(s.cha)
                 + " HP=" + std::to_string(s.hp_cur) + "/" + std::to_string(s.hp_max)
                 + " AC=" + std::to_string(s.base_ac) + ">"; });

    // ── Conditions (nested inside Agent) ────────────────────────────────────
    py::class_<Agent::Conditions>(m, "Conditions")
        .def(py::init<>())
        .def_readwrite("dashing",       &Agent::Conditions::dashing)
        .def_readwrite("dodging",       &Agent::Conditions::dodging)
        .def_readwrite("disengaging",   &Agent::Conditions::disengaging)
        .def_readwrite("reaction_used", &Agent::Conditions::reaction_used)
        .def_readwrite("reactions_denied", &Agent::Conditions::reactions_denied,
             "Balor Lightning Blade: the creature can take NO reaction (incl. opportunity attacks) "
             "until the source's next turn. Distinct from reaction_used so the target's own beginTurn "
             "reset can't restore reactions early. Session-only; cleared via the DenyReactions teardown.")
        .def_readwrite("battle_magic_available", &Agent::Conditions::battle_magic_available,
             "Battle Magic (Valor Bard L14+): set after casting a Bard spell via the Magic action; "
             "enables a bonus-action weapon attack. Reset at the start of the agent's turn.")
        .def_readwrite("hidden",        &Agent::Conditions::hidden)
        .def_readwrite("invisible",     &Agent::Conditions::invisible)
        .def_readwrite("invisible_persists_on_action", &Agent::Conditions::invisible_persists_on_action)
        .def_readwrite("sanctuary_active", &Agent::Conditions::sanctuary_active)
        .def_readwrite("sanctuary_dc",     &Agent::Conditions::sanctuary_dc)
        .def_readwrite("incapacitated", &Agent::Conditions::incapacitated)
        .def_readwrite("paralyzed",     &Agent::Conditions::paralyzed)
        .def_readwrite("blinded",       &Agent::Conditions::blinded)
        .def_readwrite("deafened",      &Agent::Conditions::deafened)
        .def_readwrite("stunned",       &Agent::Conditions::stunned)
        .def_readwrite("charmed",       &Agent::Conditions::charmed)
        .def_readwrite("charmed_by",    &Agent::Conditions::charmed_by,
             "Index of the creature that Charmed this one (-1 = none). Used by Mantle of Majesty.")
        .def_readwrite("frightened",    &Agent::Conditions::frightened)
        .def_readwrite("slipped_this_turn", &Agent::Conditions::slipped_this_turn)
        .def_readwrite("restrained",    &Agent::Conditions::restrained)
        .def_readwrite("netted",        &Agent::Conditions::netted,
             "Restrained by a thrown Net: lasts until escape_net succeeds (no duration).")
        .def_readwrite("net_escape_dc", &Agent::Conditions::net_escape_dc,
             "DC of the STR (Athletics) check to break out of the Net (10 for a standard Net).")
        .def_readwrite("burning",       &Agent::Conditions::burning,
             "Burning [Hazard]: 1d4 Fire at the start of each of its turns until extinguish_burning.")
        .def_readwrite("poisoned",      &Agent::Conditions::poisoned)
        .def_readwrite("petrified",     &Agent::Conditions::petrified)
        .def_readwrite("gaseous_form",  &Agent::Conditions::gaseous_form)
        .def_readwrite("prone",         &Agent::Conditions::prone)
        .def_readwrite("unconscious",   &Agent::Conditions::unconscious)
        .def_readwrite("dead",          &Agent::Conditions::dead)
        .def_readwrite("death_save_successes", &Agent::Conditions::death_save_successes)
        .def_readwrite("death_save_failures",  &Agent::Conditions::death_save_failures)
        .def_readwrite("stabilized",    &Agent::Conditions::stabilized)
        .def_readwrite("concentrating",    &Agent::Conditions::concentrating)
        .def_readwrite("concentrating_on", &Agent::Conditions::concentrating_on)
        .def_readwrite("has_advantage",   &Agent::Conditions::has_advantage)
        .def_readwrite("has_disadvantage", &Agent::Conditions::has_disadvantage)
        .def_readwrite("grappled",       &Agent::Conditions::grappled)
        .def_readwrite("grappler_idx",   &Agent::Conditions::grappler_idx)
        .def_readwrite("grapple_escape_dc", &Agent::Conditions::grapple_escape_dc)
        .def_readwrite("grapple_range_ft",  &Agent::Conditions::grapple_range_ft)
        .def_readwrite("exhaustion_level",  &Agent::Conditions::exhaustion_level)
        .def_readwrite("raging",            &Agent::Conditions::raging)
        .def_readwrite("lion_aura_active",  &Agent::Conditions::lion_aura_active)
        .def_readwrite("rage_of_gods_active", &Agent::Conditions::rage_of_gods_active)
        .def_readwrite("world_tree_long_teleport_used", &Agent::Conditions::world_tree_long_teleport_used)
        .def_readwrite("retaliation_available", &Agent::Conditions::retaliation_available)
        .def_readwrite("retaliation_target_idx", &Agent::Conditions::retaliation_target_idx)
        .def_readwrite("reckless_attack",   &Agent::Conditions::reckless_attack)
        .def_readwrite("reckless_reroll_available", &Agent::Conditions::reckless_reroll_available)
        .def_readwrite("riposte_available", &Agent::Conditions::riposte_available)
        .def_readwrite("sentinel_guard_available", &Agent::Conditions::sentinel_guard_available)
        .def_readwrite("soul_of_vengeance_available", &Agent::Conditions::soul_of_vengeance_available)
        .def_readwrite("inspiring_smite_used", &Agent::Conditions::inspiring_smite_used)
        .def_readwrite("unerring_strike_used", &Agent::Conditions::unerring_strike_used)
        .def_readwrite("peerless_aim_used", &Agent::Conditions::peerless_aim_used)
        .def_readwrite("peerless_aim_available", &Agent::Conditions::peerless_aim_available)
        .def_readwrite("blink_steps_available", &Agent::Conditions::blink_steps_available)
        .def_readwrite("berserker_frenzy_used", &Agent::Conditions::berserker_frenzy_used)
        .def_readwrite("colossus_slayer_used", &Agent::Conditions::colossus_slayer_used)
        .def_readwrite("horde_breaker_available", &Agent::Conditions::horde_breaker_available)
        .def_readwrite("horde_breaker_used", &Agent::Conditions::horde_breaker_used)
        .def_readwrite("superior_prey_used", &Agent::Conditions::superior_prey_used)
        .def_readwrite("bestial_fury_used", &Agent::Conditions::bestial_fury_used)
        .def_readwrite("fey_dreadful_strikes_used", &Agent::Conditions::fey_dreadful_strikes_used)
        .def_readwrite("multiattack_def_hit_by", &Agent::Conditions::multiattack_def_hit_by)
        .def_readwrite("dreadful_strike_armed", &Agent::Conditions::dreadful_strike_armed)
        .def_readwrite("dread_ambusher_used", &Agent::Conditions::dread_ambusher_used)
        .def_readwrite("sudden_strike_available", &Agent::Conditions::sudden_strike_available)
        .def_readwrite("vitality_used_this_turn", &Agent::Conditions::vitality_used_this_turn)
        .def_readwrite("branches_speed_zeroed", &Agent::Conditions::branches_speed_zeroed)
        .def_readwrite("forcecaged", &Agent::Conditions::forcecaged)
        .def_readwrite("forcecage_dc", &Agent::Conditions::forcecage_dc)
        .def_readwrite("forcecage_sealed", &Agent::Conditions::forcecage_sealed)
        .def_readwrite("zealot_divine_fury_used", &Agent::Conditions::zealot_divine_fury_used)
        .def_readwrite("radiant_soul_used", &Agent::Conditions::radiant_soul_used)
        .def_readwrite("sneak_attack_used", &Agent::Conditions::sneak_attack_used)
        .def_readwrite("has_taken_turn_this_combat", &Agent::Conditions::has_taken_turn_this_combat)
        .def_readwrite("cunning_strike_available", &Agent::Conditions::cunning_strike_available)
        .def_readwrite("attacked_while_invisible", &Agent::Conditions::attacked_while_invisible)
        .def_readwrite("steady_aim", &Agent::Conditions::steady_aim)
        .def_readwrite("stunning_strike_available", &Agent::Conditions::stunning_strike_available)
        .def_readwrite("stunning_strike_used", &Agent::Conditions::stunning_strike_used)
        .def_readwrite("open_hand_rider_available", &Agent::Conditions::open_hand_rider_available)
        .def_readwrite("open_hand_rider_used", &Agent::Conditions::open_hand_rider_used)
        .def_readwrite("quivering_palm_available", &Agent::Conditions::quivering_palm_available)
        .def_readwrite("fleet_step_used", &Agent::Conditions::fleet_step_used)
        .def_readwrite("fanatical_focus_used", &Agent::Conditions::fanatical_focus_used)
        .def_readwrite("brutal_strike_available", &Agent::Conditions::brutal_strike_available)
        .def_readwrite("divine_strike_available", &Agent::Conditions::divine_strike_available)
        .def_readwrite("divine_strike_used", &Agent::Conditions::divine_strike_used)
        .def_readwrite("psionic_strike_available", &Agent::Conditions::psionic_strike_available)
        .def_readwrite("psionic_strike_used", &Agent::Conditions::psionic_strike_used)
        .def_readwrite("hand_of_harm_available", &Agent::Conditions::hand_of_harm_available)
        .def_readwrite("hand_of_harm_used", &Agent::Conditions::hand_of_harm_used)
        .def_readwrite("hand_of_harm_last_target", &Agent::Conditions::hand_of_harm_last_target)
        .def_readwrite("elemental_attunement_active", &Agent::Conditions::elemental_attunement_active,
             "Monk Elements L3 Elemental Attunement active (until short/long rest): +10 ft unarmed reach + push/pull rider")
        .def_readwrite("elemental_attunement_move_available", &Agent::Conditions::elemental_attunement_move_available,
             "Monk Elements L3: an unarmed hit this turn can push/pull the target 10 ft (per-turn eligibility)")
        .def_readwrite("grappler_punch_grab_available", &Agent::Conditions::grappler_punch_grab_available)
        .def_readwrite("grappler_punch_grab_used", &Agent::Conditions::grappler_punch_grab_used)
        .def_readwrite("divine_smite_available", &Agent::Conditions::divine_smite_available)
        .def_readwrite("divine_smite_used", &Agent::Conditions::divine_smite_used)
        .def_readwrite("eldritch_smite_available", &Agent::Conditions::eldritch_smite_available)
        .def_readwrite("eldritch_smite_used", &Agent::Conditions::eldritch_smite_used)
        .def_readwrite("lifedrinker_used", &Agent::Conditions::lifedrinker_used)
        .def_readwrite("war_magic_used", &Agent::Conditions::war_magic_used)
        .def_readwrite("eldritch_strike_by", &Agent::Conditions::eldritch_strike_by)
        .def_readwrite("guided_strike_available", &Agent::Conditions::guided_strike_available)
        .def_readwrite("restore_balance_miss_available", &Agent::Conditions::restore_balance_miss_available)
        .def_readwrite("maneuver_available", &Agent::Conditions::maneuver_available)
        .def_readwrite("maneuver_precision_available", &Agent::Conditions::maneuver_precision_available)
        .def_readwrite("goaded_by", &Agent::Conditions::goaded_by)
        .def_readwrite("distracted_by", &Agent::Conditions::distracted_by)
        .def_readwrite("disarmed", &Agent::Conditions::disarmed)
        .def_readwrite("disarmed_by", &Agent::Conditions::disarmed_by)
        .def_readwrite("feint_target_idx", &Agent::Conditions::feint_target_idx)
        .def_readwrite("quick_toss_die_pending", &Agent::Conditions::quick_toss_die_pending)
        .def_readwrite("hamstrung", &Agent::Conditions::hamstrung)
        .def_readwrite("sundering_target_idx", &Agent::Conditions::sundering_target_idx)
        .def_readwrite("staggered_next_save", &Agent::Conditions::staggered_next_save)
        .def_readwrite("sapped", &Agent::Conditions::sapped)
        .def_readwrite("slowed", &Agent::Conditions::slowed)
        .def_readwrite("vex_target_idx", &Agent::Conditions::vex_target_idx)
        .def_readwrite("push_available", &Agent::Conditions::push_available)
        .def_readwrite("topple_available", &Agent::Conditions::topple_available)
        .def_readwrite("cleave_available", &Agent::Conditions::cleave_available)
        .def_readwrite("cleave_used_this_turn", &Agent::Conditions::cleave_used_this_turn)
        .def_readwrite("offhand_attack_used", &Agent::Conditions::offhand_attack_used)
        .def_readwrite("savage_attacker_used_this_turn", &Agent::Conditions::savage_attacker_used_this_turn)
        .def_readwrite("tavern_brawler_push_used_this_turn", &Agent::Conditions::tavern_brawler_push_used_this_turn)
        .def_readwrite("crusher_push_used_this_turn", &Agent::Conditions::crusher_push_used_this_turn)
        .def_readwrite("piercer_reroll_used_this_turn", &Agent::Conditions::piercer_reroll_used_this_turn)
        .def_readwrite("slasher_slow_used_this_turn", &Agent::Conditions::slasher_slow_used_this_turn)
        .def_readwrite("gwm_hew_available", &Agent::Conditions::gwm_hew_available)
        .def_readwrite("zealous_blessing", &Agent::Conditions::zealous_blessing)
        .def_readwrite("zealous_blessing_by", &Agent::Conditions::zealous_blessing_by)
        .def_readwrite("crusher_marked", &Agent::Conditions::crusher_marked)
        .def_readwrite("crusher_marked_by", &Agent::Conditions::crusher_marked_by)
        .def_readwrite("slasher_marked", &Agent::Conditions::slasher_marked)
        .def_readwrite("slasher_marked_by", &Agent::Conditions::slasher_marked_by)
        .def_readwrite("uncanny_metabolism_used_this_combat", &Agent::Conditions::uncanny_metabolism_used_this_combat,
             "Monk L2 Uncanny Metabolism: Focus Points restoration used this combat (once per combat)")
        .def_readwrite("superior_defense_active", &Agent::Conditions::superior_defense_active,
             "Monk L18 Superior Defense: currently under Resistance to all damage except Force (expires end of turn)")
        .def_readwrite("shadow_step_advantage", &Agent::Conditions::shadow_step_advantage,
             "Warrior of Shadow L6 Shadow Step: next weapon attack has Advantage (consumed on attack)")
        .def_readwrite("bonus_reach_available", &Agent::Conditions::bonus_reach_available,
             "Warrior of Shadow L11 Improved Shadow Step: +5 ft reach on next attack (consumed on attack)")
        .def_readwrite("cloak_of_shadows_active", &Agent::Conditions::cloak_of_shadows_active,
             "Warrior of Shadow L17 Cloak of Shadows: currently Invisible (expires on light level change)")
        .def("__repr__", [](const Agent::Conditions& c){
            std::string s = "<Conditions";
            if (c.dashing)       s += " dashing";
            if (c.dodging)       s += " dodging";
            if (c.disengaging)   s += " disengaging";
            if (c.hidden)        s += " hidden";
            if (c.invisible)     s += " invisible";
            if (c.incapacitated) s += " incapacitated";
            if (c.paralyzed)     s += " paralyzed";
            if (c.blinded)       s += " blinded";
            if (c.stunned)       s += " stunned";
            if (c.charmed)       s += " charmed";
            if (c.frightened)    s += " frightened";
            if (c.grappled)      s += " grappled";
            if (c.unconscious)   s += " unconscious";
            if (c.dead)          s += " dead";
            if (c.stabilized)    s += " stabilized";
            if (c.death_save_successes > 0 || c.death_save_failures > 0)
                s += std::format(" deaths({}/{})", c.death_save_successes, c.death_save_failures);
            if (c.slipped_this_turn) s += " slipped_this_turn";
            return s + ">"; });

    // ── Creature-type bitmask (Magic Circle / Hallow warded types) ─────────────
    // Bit flags — a ward's mask and a creature's creatureTypeMask() are OR-combined ints, so
    // these are exposed with arithmetic enabled (rpg.CreatureType.Fiend | rpg.CreatureType.Fey).
    py::enum_<CreatureTypeBit>(m, "CreatureType", py::arithmetic())
        .value("Aberration", CT_Aberration)
        .value("Celestial",  CT_Celestial)
        .value("Elemental",  CT_Elemental)
        .value("Fey",        CT_Fey)
        .value("Fiend",      CT_Fiend)
        .value("Undead",     CT_Undead);

    // ── Damage type enums ─────────────────────────────────────────────────────
    py::enum_<MagicDamage_t>(m, "MagicDamage")
        .value("Acid",      MagicDamage_t::Acid)
        .value("Cold",      MagicDamage_t::Cold)
        .value("Fire",      MagicDamage_t::Fire)
        .value("Force",     MagicDamage_t::Force)
        .value("Lightning", MagicDamage_t::Lightning)
        .value("Necrotic",  MagicDamage_t::Necrotic)
        .value("Poison",    MagicDamage_t::Poison)
        .value("Psychic",   MagicDamage_t::Psychic)
        .value("Radiant",   MagicDamage_t::Radiant)
        .value("Thunder",   MagicDamage_t::Thunder);

    py::enum_<PhysicalDamage_t>(m, "PhysicalDamage")
        .value("Bludgeoning", PhysicalDamage_t::Bludgeoning)
        .value("Piercing",    PhysicalDamage_t::Piercing)
        .value("Slashing",    PhysicalDamage_t::Slashing);

    // ── WeaponType ────────────────────────────────────────────────────────────
    py::enum_<WeaponType>(m, "WeaponType")
        .value("Melee",  WeaponType::Melee,  "Close-quarters weapon.")
        .value("Ranged", WeaponType::Ranged, "Projectile weapon.")
        .export_values();

    // ── WeaponMastery (2024) ────────────────────────────────────────────────────
    py::enum_<WeaponMastery>(m, "WeaponMastery")
        .value("None",   WeaponMastery::None)
        .value("Cleave", WeaponMastery::Cleave)
        .value("Graze",  WeaponMastery::Graze)
        .value("Nick",    WeaponMastery::Nick)
        .value("Poison",  WeaponMastery::Poison)
        .value("Push",    WeaponMastery::Push)
        .value("Sap",    WeaponMastery::Sap)
        .value("Slow",   WeaponMastery::Slow)
        .value("Topple", WeaponMastery::Topple)
        .value("Vex",    WeaponMastery::Vex)
        .export_values();

    // ── Attack Condition ──────────────────────────────────────────────────────
    py::class_<AttackCondition>(m, "AttackCondition")
        .def(py::init<>())
        .def_readwrite("condition_name",     &AttackCondition::condition_name)
        .def_readwrite("condition_duration", &AttackCondition::condition_duration)
        .def_readwrite("push_ft",            &AttackCondition::push_ft)
        .def_readwrite("save_repeat_turns",  &AttackCondition::save_repeat_turns)
        .def_readwrite("save_at_end_of_turn", &AttackCondition::save_at_end_of_turn,
             "If true, the periodic save is rolled at the END of the affected creature's turn\n"
             "(endTurn) rather than the start — Hold Person / Hold Monster RAW. The creature is\n"
             "still barred from acting on the intervening turn; a success frees it next turn.")
        .def_readwrite("contested",          &AttackCondition::contested,
             "Grappled rider: true = contested Athletics check; false = grapple lands automatically on hit.")
        .def_readwrite("escape_dc",          &AttackCondition::escape_dc,
             "Grappled rider: fixed escape DC override; 0 = compute 10 + STR mod + proficiency.")
        .def_readwrite("save_ability",       &AttackCondition::save_ability)
        .def_readwrite("save_dc_ability",    &AttackCondition::save_dc_ability)
        .def_readwrite("requires_save",      &AttackCondition::requires_save,
             "If true, target gets a save to negate the condition; if false, condition applies automatically.")
        .def_readwrite("on_damage",          &AttackCondition::on_damage,
             "What happens to this condition when the affected creature takes damage:\n"
             "OnDamage.None (default), OnDamage.End (ends immediately), or\n"
             "OnDamage.RepeatSave (repeat the save at Advantage; success ends it).")
        .def_readwrite("curse_kind",          &AttackCondition::curse_kind,
             "Vistani Curse kind installed on apply: 0=none, 1=vulnerability, 2=weakness\n"
             "(save disadvantage), 3=affliction (Blinded/Deafened/Both).")
        .def_readwrite("kickback_dice",       &AttackCondition::kickback_dice,
             "Vistani Curse kickback: number of dice of psychic damage to the caster when the curse ends.")
        .def_readwrite("kickback_die_size",   &AttackCondition::kickback_die_size,
             "Vistani Curse kickback die size (e.g. 6 → d6).")
        .def_readwrite("kickback_damage_type", &AttackCondition::kickback_damage_type,
             "Vistani Curse kickback damage type (MagicDamage; default Psychic).")
        .def_readwrite("dot_dice",            &AttackCondition::dot_dice,
             "Damage-over-time rider: number of dice taken at the start of each turn (0 = no DoT).")
        .def_readwrite("dot_die_size",        &AttackCondition::dot_die_size,
             "DoT die size (e.g. 6 → d6).")
        .def_readwrite("dot_flat_bonus",      &AttackCondition::dot_flat_bonus,
             "Flat damage added to each DoT tick after the dice.")
        .def_readwrite("dot_damage_type",     &AttackCondition::dot_damage_type,
             "DoT damage type (MagicDamage; default Poison).")
        .def_readwrite("prevents_healing",    &AttackCondition::prevents_healing,
             "If true, the creature can't regain HP while this condition is active (Pit Fiend poison).");

    py::enum_<OnDamage_t>(m, "OnDamage")
        .value("None", OnDamage_t::None)
        .value("End", OnDamage_t::End)
        .value("RepeatSave", OnDamage_t::RepeatSave);

    // ── Weapon ────────────────────────────────────────────────────────────────
    py::class_<Weapon>(m, "Weapon")
        .def(py::init<>())
        .def_readwrite("name",             &Weapon::name)
        .def_readwrite("type",             &Weapon::type)
        .def_readwrite("reach_ft",         &Weapon::reach_ft)
        .def_readwrite("normal_range_ft",  &Weapon::normal_range_ft)
        .def_readwrite("long_range_ft",    &Weapon::long_range_ft)
        .def_readwrite("finesse",          &Weapon::finesse)
        .def_readwrite("thrown",           &Weapon::thrown)
        .def_readwrite("quantity",         &Weapon::quantity,
                       "Copies of this weapon carried (javelins/daggers/darts come in bundles). "
                       "Each THROW spends one and lays it on the ground; 0 = all thrown away.")
        .def_readwrite("sprite_path",      &Weapon::sprite_path,
                       "Icon drawn when this weapon lies on the map as a MapItem.")
        .def_readwrite("returns_after_throw", &Weapon::returns_after_throw,
                       "Thrown, but comes straight back: never spent, never lands on the ground "
                       "(Soulknife Psychic Blade, returning magic weapons).")
        .def_readwrite("pact_weapon",      &Weapon::pact_weapon)
        .def_readwrite("psychic_blade",    &Weapon::psychic_blade)
        .def_readwrite("proficient",       &Weapon::proficient)
        .def_readwrite("off_hand",         &Weapon::off_hand)
        .def_readwrite("two_handed",       &Weapon::two_handed)
        .def_readwrite("heavy",            &Weapon::heavy)
        .def_readwrite("light",            &Weapon::light)
        .def_readwrite("is_shield",        &Weapon::is_shield)
        .def_readwrite("auto_hit_if_grappled", &Weapon::auto_hit_if_grappled)
        .def_readwrite("save_for_damage",  &Weapon::save_for_damage)
        .def_readwrite("save_for_damage_ability", &Weapon::save_for_damage_ability)
        .def_readwrite("auto_use_when_grappling", &Weapon::auto_use_when_grappling)
        .def_readwrite("permanently_armed", &Weapon::permanently_armed)
        .def_readwrite("mastery",          &Weapon::mastery)
        .def_readwrite("ac_bonus",         &Weapon::ac_bonus)
        .def_readwrite("physical_damage_types", &Weapon::physicalDamageRolls)
        .def_readwrite("magic_damage_types",    &Weapon::magicDamageRolls)
        .def_readwrite("damage_dice",      &Weapon::damage_dice)
        .def_readwrite("damage_dice_count",&Weapon::damage_dice_count)
        .def_readwrite("damage_modifier",  &Weapon::damage_modifier)
        .def_readwrite("range_short_feet", &Weapon::range_short_feet)
        .def_readwrite("range_long_feet",  &Weapon::range_long_feet)
        .def_readwrite("bonus_hit",        &Weapon::bonus_hit)
        .def_readwrite("bonus_damage",     &Weapon::bonus_damage)
        .def_readwrite("uses_max",         &Weapon::uses_max,
            "Limited-use cap (N/day attacks). 0 = unlimited; > 0 = N uses, refilled on a long rest.")
        .def_readwrite("uses_remaining",   &Weapon::uses_remaining,
            "Current remaining uses for a N/day weapon.")
        .def_readwrite("recharge_min",     &Weapon::recharge_min,
            "Recharge threshold: 0 = no recharge; 5 ⇒ (Recharge 5–6); 6 ⇒ (Recharge 6). When spent the\n"
            "weapon is `expended` until a d6 ≥ recharge_min at the owner's turn start restores it.")
        .def_readwrite("expended",         &Weapon::expended,
            "True when a recharge weapon has been spent and is waiting on its recharge roll.")
        .def_readwrite("conditions",       &Weapon::conditions)
        .def_readwrite("condition_rider",  &Weapon::condition_rider)
        .def("__repr__", [](const Weapon& w){
            std::string dmg_str;
            if (!w.physicalDamageRolls.empty()) {
                dmg_str = std::to_string(w.physicalDamageRolls[0].num_dice) +
                         "d" + std::to_string(w.physicalDamageRolls[0].die_size);
            } else if (!w.magicDamageRolls.empty()) {
                dmg_str = std::to_string(w.magicDamageRolls[0].num_dice) +
                         "d" + std::to_string(w.magicDamageRolls[0].die_size);
            } else {
                dmg_str = "0d0";
            }
            return "<Weapon '" + w.name + "' "
                 + (w.type == WeaponType::Melee ? "Melee" : "Ranged")
                 + " " + dmg_str + ">"; });

    // ── MapItem ───────────────────────────────────────────────────────────
    py::class_<MapItem>(m, "MapItem")
        .def(py::init<>())
        .def_readwrite("id",          &MapItem::id)
        .def_readwrite("cell",        &MapItem::cell)
        .def_readwrite("weapon",      &MapItem::weapon)
        .def_readwrite("sprite_path", &MapItem::sprite_path)
        .def("__repr__", [](const MapItem& mi){
            return "<MapItem id=" + std::to_string(mi.id)
                 + " '" + mi.weapon.name + "'"
                 + " at (" + std::to_string(mi.cell.col)
                 + "," + std::to_string(mi.cell.row) + ")>"; });

    // ── Armor ─────────────────────────────────────────────────────────────
    py::class_<Armor>(m, "Armor")
        .def(py::init<>())
        .def_readwrite("name",                      &Armor::name)
        .def_readwrite("description",               &Armor::description)
        .def_readwrite("ac_bonus",                  &Armor::ac_bonus)
        .def_readwrite("ac_base",                   &Armor::ac_base)
        .def_readwrite("dex_mod_cap",               &Armor::dex_mod_cap)
        .def_readwrite("grants_disadvantage",       &Armor::grants_disadvantage)
        .def_readwrite("magic_damage_multipliers",  &Armor::magic_damage_multipliers)
        .def_readwrite("physical_damage_multipliers", &Armor::physical_damage_multipliers)
        .def_readwrite("damage_reduction",          &Armor::damage_reduction)
        .def_readwrite("requires_strength",         &Armor::requires_strength)
        .def_readwrite("str_requirement",           &Armor::str_requirement)
        .def("__repr__", [](const Armor& a){
            return "<Armor '" + a.name + "' AC+" + std::to_string(a.ac_bonus) + " DR" + std::to_string(a.damage_reduction) + ">"; });

    // ── Spell enums ──────────────────────────────────────────────────────────
    py::enum_<Spell::Geometry_t>(m, "SpellGeometry")
        .value("Single",    Spell::Single)
        .value("Line",      Spell::Line)
        .value("Cone",      Spell::Cone)
        .value("Sphere",    Spell::Sphere)
        .value("Square",    Spell::Square)
        .value("Rectangle", Spell::Rectangle)
        .value("Multiple",  Spell::Multiple)
        .export_values();

    py::enum_<NpcRole>(m, "NpcRole")
        .value("Melee",  NpcRole::Melee)
        .value("Ranged", NpcRole::Ranged)
        .value("Caster", NpcRole::Caster);

    py::enum_<NpcAutomationStrategy>(m, "NpcAutomationStrategy")
        .value("Simple",             NpcAutomationStrategy::Simple)
        .value("PreferTargetCaster", NpcAutomationStrategy::PreferTargetCaster)
        .value("PreferAOE",          NpcAutomationStrategy::PreferAOE)
        .value("PreferRange",        NpcAutomationStrategy::PreferRange)
        .value("PreferHide",         NpcAutomationStrategy::PreferHide)
        .value("NoOp",               NpcAutomationStrategy::NoOp)
        .value("PreferControl",      NpcAutomationStrategy::PreferControl)
        .value("PreferHeal",         NpcAutomationStrategy::PreferHeal)
        .value("PreferSupport",      NpcAutomationStrategy::PreferSupport)
        .export_values();

    py::enum_<NpcConcealRoute>(m, "NpcConcealRoute")
        .value("RouteA", NpcConcealRoute::RouteA)
        .value("RouteB", NpcConcealRoute::RouteB)
        .value("RouteC", NpcConcealRoute::RouteC)
        .value("RouteD", NpcConcealRoute::RouteD)
        .export_values();

    // NPC turn playback: one entry of the visual event stream an automated turn records
    // (drained via CombatEngine.take_npc_visual_events, replayed by the GUI as an animation).
    auto nve = py::class_<NpcVisualEvent>(m, "NpcVisualEvent",
        "One visual event recorded during an automated NPC turn: a Move (token route), an\n"
        "Announce (action text to scroll above the actor), or an Outcome (flash text +\n"
        "hp_after/died for the animation-synced HP bar and corpse removal).");
    py::enum_<NpcVisualEvent::Kind>(nve, "Kind")
        .value("Move",     NpcVisualEvent::Move)
        .value("Announce", NpcVisualEvent::Announce)
        .value("Outcome",  NpcVisualEvent::Outcome)
        .export_values();
    nve.def_readonly("kind",       &NpcVisualEvent::kind,       "Kind as int: 0=Move, 1=Announce, 2=Outcome")
       .def_readonly("agent_idx",  &NpcVisualEvent::agent_idx,  "Move/Announce: the actor; Outcome: the affected target (flash anchor)")
       .def_readonly("target_idx", &NpcVisualEvent::target_idx, "Announce only: the action's target (-1 = none/area)")
       .def_readonly("path",       &NpcVisualEvent::path,       "Move only: route actually taken (origin..dest cells, inclusive)")
       .def_readonly("text",       &NpcVisualEvent::text,       "Announce: action sentence; Outcome: flash text (Hit (7)/Miss/Saved/Failed)")
       .def_readonly("good",       &NpcVisualEvent::good,       "Outcome only: green flash (Hit/Saved) vs red (Miss/Failed), the FLASH_GOOD/BAD convention")
       .def_readonly("hp_after",   &NpcVisualEvent::hp_after,   "Outcome only: target hp_cur after the action (-1 = no HP sync from this event)")
       .def_readonly("died",       &NpcVisualEvent::died,       "Outcome only: target died/was removed by this action");

    // NPC attack analysis: the pre-attack probability report an automated turn logs (and tests verify).
    py::class_<NpcAttackAnalysis>(m, "NpcAttackAnalysis",
        "Probability analysis for one NPC-automation weapon attack: chance to hit, chance a hit\n"
        "drops the target to 0 HP, and the estimated advantage/disadvantage state used. An estimate:\n"
        "core to-hit math + dominant condition-driven adv/dis; exotic feat riders are not modeled.")
        .def_readonly("p_hit",            &NpcAttackAnalysis::p_hit,            "P(attack hits), crit auto-hit and nat-1 auto-miss included")
        .def_readonly("p_drop_given_hit", &NpcAttackAnalysis::p_drop_given_hit, "P(target drops to 0 HP | hit), exact damage distribution vs hp_cur + temp_hp")
        .def_readonly("advantage",        &NpcAttackAnalysis::advantage,        "estimated roll state: attack made at Advantage")
        .def_readonly("disadvantage",     &NpcAttackAnalysis::disadvantage,     "estimated roll state: attack made at Disadvantage");

    py::enum_<Spell::SpellType_t>(m, "SpellType")
        .value("Harm", Spell::Harm)
        .value("Heal", Spell::Heal)
        .value("Transport", Spell::Transport)
        .value("Help", Spell::Help)
    ;

    py::enum_<Spell::CastingTime_t>(m, "CastingTime")
        .value("Action", Spell::Action)
        .value("BonusAction", Spell::BonusAction)
        .value("Reaction", Spell::Reaction)
        .export_values();

    py::enum_<Spell::SpellAttack_t>(m, "SpellAttack")
        .value("AttackRoll", Spell::AttackRoll)
        .value("Save",       Spell::Save)
        .value("Automatic",  Spell::Automatic)
        .export_values();

    py::enum_<Spell::SpellSchool_t>(m, "SpellSchool")
        .value("NONE",        Spell::SchoolNone)
        .value("Abjuration",  Spell::Abjuration)
        .value("Conjuration", Spell::Conjuration)
        .value("Divination",  Spell::Divination)
        .value("Enchantment", Spell::Enchantment)
        .value("Evocation",   Spell::Evocation)
        .value("Illusion",    Spell::Illusion)
        .value("Necromancy",  Spell::Necromancy)
        .value("Transmutation", Spell::Transmutation)
        .export_values();

    py::enum_<SaveAbility_t>(m, "SaveAbility")
        .value("Strength", SaveStr)
        .value("Dexterity", SaveDex)
        .value("Constitution", SaveCon)
        .value("Intelligence", SaveInt)
        .value("Wisdom", SaveWis)
        .value("Charisma", SaveCha)
        .value("SaveStr", SaveStr)
        .value("SaveDex", SaveDex)
        .value("SaveCon", SaveCon)
        .value("SaveInt", SaveInt)
        .value("SaveWis", SaveWis)
        .value("SaveCha", SaveCha)
        .value("SaveSpellcasterMod", SaveSpellcasterMod)
        .export_values();

    // ── Skill Enum (18 D&D skills) ────────────────────────────────────────────
    py::enum_<Skill>(m, "Skill")
        .value("Acrobatics", Acrobatics)
        .value("AnimalHandling", AnimalHandling)
        .value("Arcana", Arcana)
        .value("Athletics", Athletics)
        .value("Deception", Deception)
        .value("History", History)
        .value("Insight", Insight)
        .value("Intimidation", Intimidation)
        .value("Investigation", Investigation)
        .value("Medicine", Medicine)
        .value("Nature", Nature)
        .value("Perception", Perception)
        .value("Performance", Performance)
        .value("Persuasion", Persuasion)
        .value("Religion", Religion)
        .value("SleigtOfHand", SleigtOfHand)
        .value("Stealth", Stealth)
        .value("Survival", Survival)
        .export_values();

    // ── Background Enum (16 2024 PHB backgrounds) ────────────────────────────
    py::enum_<Background>(m, "Background")
        .value("NONE", BackgroundNone)
        .value("Acolyte", Acolyte)
        .value("Artisan", Artisan)
        .value("Charlatan", Charlatan)
        .value("Criminal", Criminal)
        .value("Entertainer", Entertainer)
        .value("Farmer", Farmer)
        .value("Guard", Guard)
        .value("Guide", Guide)
        .value("Hermit", Hermit)
        .value("Merchant", Merchant)
        .value("Noble", Noble)
        .value("Sage", Sage)
        .value("Sailor", Sailor)
        .value("Scribe", Scribe)
        .value("Soldier", Soldier)
        .value("Wayfarer", Wayfarer)
        .export_values();

    // ── Alignment Enum (9 alignments) ────────────────────────────────────────
    py::enum_<Alignment>(m, "Alignment")
        .value("NONE", AlignmentNone)
        .value("LawfulGood", LawfulGood)
        .value("LawfulNeutral", LawfulNeutral)
        .value("LawfulEvil", LawfulEvil)
        .value("NeutralGood", NeutralGood)
        .value("TrueNeutral", TrueNeutral)
        .value("NeutralEvil", NeutralEvil)
        .value("ChaoticGood", ChaoticGood)
        .value("ChaoticNeutral", ChaoticNeutral)
        .value("ChaoticEvil", ChaoticEvil)
        .export_values();

    // ── Barbarian Subclass Enum (2024 D&D) ──────────────────────────────────
    py::enum_<BarbianSubclass>(m, "BarbianSubclass")
        .value("NONE", BarbianSubclassNone)
        .value("Berserker", BerserkerPath)
        .value("WildHeart", WildHeartPath)
        .value("WorldTree", WorldTreePath)
        .value("Zealot", ZealotPath)
        .export_values();

    py::enum_<WildHeartRageChoice>(m, "WildHeartRageChoice")
        .value("NONE", WildHeartNone)
        .value("Bear", BearForm)
        .value("Eagle", EagleForm)
        .value("Wolf", WolfForm)
        .export_values();

    py::enum_<WildHeartAspect>(m, "WildHeartAspect")
        .value("NONE", AspectNone)
        .value("Owl", OwlAspect)
        .value("Panther", PantherAspect)
        .value("Salmon", SalmonAspect)
        .export_values();

    py::enum_<WildHeartPower>(m, "WildHeartPower")
        .value("NONE", WildHeartPowerNone)
        .value("Falcon", FalconPower)
        .value("Lion", LionPower)
        .value("Ram", RamPower)
        .export_values();

    // ── Fighter Subclass Enum (2024 D&D) ──────────────────────────────────
    py::enum_<FighterSubclass>(m, "FighterSubclass")
        .value("NONE", FighterSubclassNone)
        .value("Champion", ChampionPath)
        .value("BattleMaster", BattleMasterPath)
        .value("PsiWarrior", PsiWarriorPath)
        .value("EldritchKnight", EldritchKnightPath)
        .export_values();

    // ── Druid Circle Enum (2024 D&D) ────────────────────────────────────
    py::enum_<DruidCircle>(m, "DruidCircle")
        .value("NONE", DruidCircleNone)
        .value("CircleOfMoon", CircleOfMoon)
        .value("CircleOfLand", CircleOfLand)
        .value("CircleOfSea", CircleOfSea)
        .value("CircleOfStars", CircleOfStars)
        .value("CircleOfSpores", CircleOfSpores)
        .value("CircleOfWildfire", CircleOfWildfire)
        .export_values();

    // ── Monk Subclass Enum (2024 D&D) ────────────────────────────────────
    py::enum_<MonkSubclass>(m, "MonkSubclass")
        .value("NONE", MonkSubclassNone)
        .value("WarriorOfTheOpenHand", WarriorOfTheOpenHandPath)
        .value("WarriorOfMercy", WarriorOfMercyPath)
        .value("WarriorOfShadow", WarriorOfShadowPath)
        .value("WarriorOfFourElements", WarriorOfFourElementsPath)
        .export_values();

    // ── Paladin Oath Enum (2024 D&D) ────────────────────────────────────
    py::enum_<PaladinOath>(m, "PaladinOath")
        .value("NONE", PaladinOathNone)
        .value("OathOfDevotion", OathOfDevotionPath)
        .value("OathOftheMountedWarrior", OathOftheMountedWarriorPath)
        .value("OathOfRedemption", OathOfRedemptionPath)
        .value("OathOfVengeance", OathOfVengeancePath)
        .value("OathOfAncients", OathOfAncientsPath)
        .value("OathOfGlory", OathOfGloryPath)
        .export_values();

    // ── Ranger Subclass Enum (2024 D&D) ──────────────────────────────────────
    py::enum_<RangerSubclass>(m, "RangerSubclass")
        .value("NONE", RangerSubclassNone)
        .value("Hunter", HunterPath)
        .value("BeastMaster", BeastMasterPath)
        .value("FeyWanderer", FeyWandererPath)
        .value("GloomStalker", GloomStalkerPath)
        .export_values();

    // ── Hunter subclass feature choices (2024 D&D) ───────────────────────────
    py::enum_<HunterPrey>(m, "HunterPrey")
        .value("NONE", HunterPreyNone)
        .value("ColossusSlayer", ColossusSlayer)
        .value("HordeBreaker", HordeBreaker)
        .export_values();
    py::enum_<DefensiveTactics>(m, "DefensiveTactics")
        .value("NONE", DefensiveTacticsNone)
        .value("EscapeTheHorde", EscapeTheHorde)
        .value("MultiattackDefense", MultiattackDefense)
        .export_values();
    py::enum_<PrimalCompanion>(m, "PrimalCompanion")
        .value("NONE", PrimalCompanionNone)
        .value("Land", PrimalLand)
        .value("Sea", PrimalSea)
        .value("Sky", PrimalSky)
        .export_values();

    // ── Wizard Subclass Enum (2024 D&D) ──────────────────────────────────────
    py::enum_<WizardSubclass>(m, "WizardSubclass")
        .value("NONE", WizardSubclassNone)
        .value("Abjurer", AbjurerPath)
        .value("Diviner", DivinierPath)
        .value("Evoker", EvokerPath)
        .value("Illusionist", IllusionistPath)
        .export_values();

    // ── Sorcerer Subclass Enum (2024 D&D) ────────────────────────────────────
    py::enum_<SorcererSubclass>(m, "SorcererSubclass")
        .value("NONE", SorcererSubclassNone)
        .value("Aberrant", AberrantPath)
        .value("Clockwork", ClockworkPath)
        .value("Draconic", DraconicPath)
        .value("WildMagic", WildMagicPath)
        .export_values();

    // ── Bard College (Subclass) Enum (2024 D&D) ──────────────────────────────
    py::enum_<BardCollege>(m, "BardCollege")
        .value("NONE", BardCollegeNone)
        .value("Dance", DancePath)
        .value("Glamour", GlamourPath)
        .value("Lore", LorePath)
        .value("Valor", ValorPath)
        .export_values();

    // ── Sorcerer Metamagic Options (2024 D&D) ────────────────────────────────
    py::enum_<MetamagicOption>(m, "MetamagicOption")
        .value("NONE", MetamagicNone)
        .value("Careful", MetamagicCareful)
        .value("Distant", MetamagicDistant)
        .value("Empowered", MetamagicEmpowered)
        .value("Extended", MetamagicExtended)
        .value("Heightened", MetamagicHeightened)
        .value("Quickened", MetamagicQuickened)
        .value("Seeking", MetamagicSeeking)
        .value("Subtle", MetamagicSubtle)
        .value("Transmuted", MetamagicTransmuted)
        .value("Twinned", MetamagicTwinned)
        .export_values();

    // ── Warlock Subclass (Patron) Enum (2024 D&D) ────────────────────────────
    py::enum_<WarlockSubclass>(m, "WarlockSubclass")
        .value("NONE", WarlockSubclassNone)
        .value("Archfey", ArchfeyPath)
        .value("Celestial", CelestialPath)
        .value("Fiend", FiendPath)
        .value("GreatOldOne", GreatOldOnePath)
        .export_values();

    py::enum_<RogueSubclass>(m, "RogueSubclass")
        .value("NONE", RogueSubclassNone)
        .value("ArcaneTrickster", ArcaneTricksterPath)
        .value("Assassin", AssassinPath)
        .value("Soulknife", SoulknifePath)
        .value("Thief", ThiefPath)
        .export_values();

    py::enum_<ClericSubclass>(m, "ClericSubclass")
        .value("NONE", ClericSubclassNone)
        .value("LifeDomain", LifeDomain)
        .value("LightDomain", LightDomain)
        .value("TrickeryDomain", TrickeryDomain)
        .value("WarDomain", WarDomain)
        .export_values();

    py::enum_<BlessedStrike>(m, "BlessedStrike")
        .value("NONE", BlessedStrikeNone)
        .value("DivineStrike", BlessedStrikeDivineStrike)
        .value("PotentSpellcasting", BlessedStrikePotentSpellcasting)
        .export_values();

    // ── Origin Struct ────────────────────────────────────────────────────────
    py::class_<Origin>(m, "Origin")
        .def(py::init<>())
        .def_readwrite("background", &Origin::background)
        .def_readwrite("ability_increases", &Origin::ability_increases)
        .def_readwrite("origin_feat", &Origin::origin_feat)
        .def_readwrite("skill_proficiencies", &Origin::skill_proficiencies);

    // ── Character Class & Caster Type ─────────────────────────────────────────
    py::enum_<CharacterClass>(m, "CharacterClass")
        .value("None",      CharacterClass::CharClassNone)
        .value("Barbarian", CharacterClass::Barbarian)
        .value("Fighter",   CharacterClass::Fighter)
        .value("Monk",      CharacterClass::Monk)
        .value("Rogue",     CharacterClass::Rogue)
        .value("Bard",      CharacterClass::Bard)
        .value("Cleric",    CharacterClass::Cleric)
        .value("Druid",     CharacterClass::Druid)
        .value("Sorcerer",  CharacterClass::Sorcerer)
        .value("Wizard",    CharacterClass::Wizard)
        .value("Paladin",   CharacterClass::Paladin)
        .value("Ranger",    CharacterClass::Ranger)
        .value("Warlock",   CharacterClass::Warlock)
        .export_values();

    py::enum_<CasterType>(m, "CasterType")
        .value("None", CasterType::CasterNone)
        .value("Full", CasterType::CasterFull)
        .value("Half", CasterType::CasterHalf)
        .value("Pact", CasterType::CasterPact)
        .export_values();

    // Free functions for class/spell slot logic
    m.def("compute_class_slots", &rpg::compute_class_slots,
          py::arg("character_class"), py::arg("level"),
          "Compute spell slots for a character class at a given level. Returns array of 9 ints (one per spell level).");
    m.def("get_caster_type", &rpg::get_caster_type,
          py::arg("character_class"),
          "Get the caster type (None/Full/Half/Pact) for a character class.");

    // ── MagicDamageRoll ───────────────────────────────────────────────────────
    py::class_<MagicDamageRoll>(m, "MagicDamageRoll")
        .def(py::init<>())
        .def_readwrite("type", &MagicDamageRoll::type)
        .def_readwrite("num_dice", &MagicDamageRoll::num_dice)
        .def_readwrite("die_size", &MagicDamageRoll::die_size)
        .def_readwrite("bonus", &MagicDamageRoll::bonus,
             "Fixed damage bonus added after rolling dice (e.g., 1d4+1 has bonus=1)");

    // ── PhysicalDamageRoll ────────────────────────────────────────────────────
    py::class_<PhysicalDamageRoll>(m, "PhysicalDamageRoll")
        .def(py::init<>())
        .def_readwrite("type", &PhysicalDamageRoll::type)
        .def_readwrite("num_dice", &PhysicalDamageRoll::num_dice)
        .def_readwrite("die_size", &PhysicalDamageRoll::die_size)
        .def_readwrite("bonus", &PhysicalDamageRoll::bonus,
             "Fixed damage bonus added after rolling dice");

    // ── HealingRoll ────────────────────────────────────────────────────────────
    py::class_<HealingRoll>(m, "HealingRoll")
        .def(py::init<>())
        .def_readwrite("num_dice", &HealingRoll::num_dice)
        .def_readwrite("die_size", &HealingRoll::die_size)
        .def_readwrite("bonus", &HealingRoll::bonus,
             "Fixed healing bonus added after rolling dice (e.g., 1d4+1 has bonus=1)");

    // ── Item (a carried consumable — potions + thrown flasks; catalog in items.json) ──
    py::enum_<Item::ItemType_t>(m, "ItemType")
        .value("Heal",   Item::Heal)
        .value("Thrown", Item::Thrown)
        .export_values();

    py::enum_<Item::ItemAction_t>(m, "ItemAction")
        .value("Action",            Item::Action)
        .value("BonusAction",       Item::BonusAction)
        .value("NoAction",          Item::NoAction)
        .value("AttackReplacement", Item::AttackReplacement)
        .export_values();

    py::class_<Item>(m, "Item")
        .def(py::init<>())
        .def_readwrite("name",        &Item::name)
        .def_readwrite("description", &Item::description)
        .def_readwrite("type",        &Item::type)
        .def_readwrite("action_type", &Item::action_type)
        .def_readwrite("range",       &Item::range,
             "Reach in feet for administering a Heal item to another creature (0 = self only); "
             "the throwing range for a Thrown item.")
        .def_readwrite("healing",     &Item::healing,
             "HealingRoll (num_dice/die_size/bonus) restored by a Heal item.")
        .def_readwrite("damage",      &Item::damage,
             "MagicDamageRoll thrown by a Thrown item (num_dice 0 = no damage, e.g. a Net).")
        .def_readwrite("save_ability", &Item::save_ability,
             "Ability the target saves with vs a Thrown item (DEX for all four SRD items).")
        .def_readwrite("condition_applied", &Item::condition_applied,
             "Condition applied on a failed save: 'Burning' or 'Restrained' ('' = none).")
        .def_readwrite("only_vs_fiend_undead", &Item::only_vs_fiend_undead,
             "Holy Water: no effect on anything but a Fiend or an Undead.")
        .def_readwrite("max_target_size", &Item::max_target_size,
             "Net: largest size (footprint in cells) it can catch; bigger creatures auto-succeed. 0 = no limit.")
        .def_readwrite("escape_dc",   &Item::escape_dc,
             "Net: DC of the STR (Athletics) check to break free.")
        .def_readwrite("quantity",    &Item::quantity)
        .def_readwrite("consumable",  &Item::consumable)
        .def_readwrite("sprite_path", &Item::sprite_path)
        .def("__repr__", [](const Item& it){
            const bool thrown = (it.type == Item::Thrown);
            const int n  = thrown ? it.damage.num_dice : it.healing.num_dice;
            const int d  = thrown ? it.damage.die_size : it.healing.die_size;
            const int b  = thrown ? it.damage.bonus    : it.healing.bonus;
            return "<Item '" + it.name + "' x" + std::to_string(it.quantity)
                 + " " + std::to_string(n) + "d" + std::to_string(d) + "+"
                 + std::to_string(b) + ">"; });

    // ── Spell ─────────────────────────────────────────────────────────────────
    py::class_<Spell>(m, "Spell")
        .def(py::init<>())
        .def_readwrite("name",                 &Spell::name)
        .def_readwrite("type",                 &Spell::type)
        .def_readwrite("geometry",             &Spell::geometry)
        .def_readwrite("attack_type",          &Spell::attack_type)
        .def_readwrite("save_ability",         &Spell::save_ability)
        .def_readwrite("school",               &Spell::school,
             "Spell school: Abjuration, Conjuration, Divination, Enchantment, Evocation, Illusion, Necromancy, Transmutation.")
        .def_readwrite("casting_time",         &Spell::casting_time,
             "Casting time: Action, BonusAction, or Reaction.")
        .def_readwrite("range",                &Spell::range)
        .def_readwrite("radius",               &Spell::radius)
        .def_readwrite("width",                &Spell::width)
        .def_readwrite("length",               &Spell::length)
        .def_readwrite("duration",             &Spell::duration)
        .def_readwrite("magic_damage_rolls",   &Spell::magic_damage_rolls)
        .def_readwrite("physical_damage_rolls",&Spell::physical_damage_rolls)
        .def_readwrite("healing_type",         &Spell::healing_type,
             "Healing dice: num_dice d die_size + bonus (for Heal-type spells).")
        .def_readwrite("terrain_difficulty",   &Spell::terrain_difficulty,
             "Terrain difficulty applied by this spell (Normal = no terrain effect).\n"
             "The duration is the same as spell.duration (in rounds).")
        .def_readwrite("slip_save_dc",         &Spell::slip_save_dc,
             "Slipping terrain: DEX save DC.")
        .def_readwrite("slip_distance_feet",   &Spell::slip_distance_feet,
             "Slipping terrain: feet moved before a save is required.")
        .def_readwrite("light_level",           &Spell::light_level,
             "Light effect level created by this spell (VisibilityLevel enum value, -1 = no light effect).\n"
             "E.g., 6 = Sunlight (Daylight spell), 0 = Clear/BrightLight (Light spell).")
        .def_readwrite("requires_concentration", &Spell::requires_concentration,
             "If true, caster must maintain concentration; breaks on damage (CON save).")
        .def_readwrite("moves_with_caster", &Spell::moves_with_caster,
             "Sphere only: the area's center follows the caster (D&D 2024 'Emanation').\n"
             "The persistent effect re-centers on the caster each turn and whenever the caster moves.")
        .def_readwrite("requires_los", &Spell::requires_los,
             "If true, spell requires line of sight to the target or area origin.")
        .def_readwrite("selective_targeting", &Spell::selective_targeting,
             "Harm AoE that intrinsically affects only 'creatures of your choosing'\n"
             "(e.g. Radiance of the Dawn): the caster's allies (same faction + claimed\n"
             "neutrals) are auto-spared from the area without any Evoker/Careful feature.")
        .def_readwrite("grants_advantage_aura", &Spell::grants_advantage_aura,
             "Advantage emanation: while this spell's persistent area is active, the caster\n"
             "and its same-faction allies within `radius` ft of the caster have Advantage on\n"
             "attack rolls and saving throws. Continuous and caster-following; ends when the\n"
             "effect is removed (concentration drop / duration expiry). Pair with geometry=\n"
             "Sphere, moves_with_caster=True, duration>1.")
        .def_readwrite("check_los_on_center", &Spell::check_los_on_center,
             "If true, only the spell center needs line of sight (not all affected cells). User configurable.")
        .def_readwrite("requires_sight", &Spell::requires_sight,
             "If true, spell requires target(s) to be visible (not blocked by obscuration).\n"
             "Spells like Hypnotic Pattern, Command, etc. require this.\n"
             "The target is blocked if in MagicalDarkness without Devil's Sight or Heavily Obscured (unless exception applies).")
        .def_readwrite("opens_doors", &Spell::opens_doors,
             "If true (Knock), casting at a door cell removes a mundane lock, suppresses an\n"
             "Arcane Lock, and opens the door. Detected by this flag, not the spell name.")
        .def_readwrite("dispels_magic", &Spell::dispels_magic,
             "If true (Dispel Magic), casting at a target ends ongoing spells/conditions on it\n"
             "(auto for level <= slot; ability check vs DC 10+level otherwise). Flag, not name.")
        .def_readwrite("level", &Spell::level,
             "Spell level: 0 = cantrip (unlimited casts); 1-9 = requires a spell slot of that level.")
        .def_readwrite("upcast_dice_bonus", &Spell::upcast_dice_bonus,
             "Extra dice added to damage when cast at a higher slot level. Calculated as upcast_dice_bonus * (slot_level - spell_level).")
        .def_readwrite("uses_max", &Spell::uses_max,
             "Maximum uses per day for NPCs. 0 = unlimited (use slot system); > 0 = N/day uses.")
        .def_readwrite("uses_remaining", &Spell::uses_remaining,
             "Current remaining uses for the day (for N/day spells).")
        .def_readwrite("recharge_min", &Spell::recharge_min,
             "Recharge threshold for breath-weapon spells: 0 = no recharge; 5 ⇒ (Recharge 5–6);\n"
             "6 ⇒ (Recharge 6). When cast the spell is `expended` until a d6 ≥ recharge_min at the\n"
             "caster's turn start restores it.")
        .def_readwrite("expended", &Spell::expended,
             "True when a recharge spell has been cast and is waiting on its recharge roll.")
        .def_readwrite("resource_name", &Spell::resource_name,
             "Class-feature casting: if non-empty, casting spends this named resource\n"
             "(e.g. 'Channel Divinity') instead of a spell slot. Used by classfeatures.json.")
        .def_readwrite("resource_cost", &Spell::resource_cost,
             "Amount of resource_name spent per cast (default 1).")
        .def_readwrite("instant_kill_threshold", &Spell::instant_kill_threshold,
             "Power Word Kill: a creature whose current HP <= this dies outright (no damage\n"
             "roll, no death saves). Above the threshold the spell deals its normal damage.\n"
             "0 = disabled.")
        .def_readwrite("condition_hp_threshold", &Spell::condition_hp_threshold,
             "Power Word Stun: the spell's conditions take hold only if the target's current\n"
             "HP <= this. 0 = no gate (conditions always apply).")
        .def_readwrite("hp_pool", &Spell::hp_pool,
             "Power Word Fortify / Mass Heal: a shared pool of HP distributed among every\n"
             "affected creature instead of rolling per-target healing dice. 0 = disabled.")
        .def_readwrite("pool_is_temp_hp", &Spell::pool_is_temp_hp,
             "When true the hp_pool grants Temporary HP (Power Word Fortify) rather than\n"
             "restoring current HP (Mass Heal).")
        .def_readwrite("heal_to_full", &Spell::heal_to_full,
             "Power Word Heal: the target regains all its Hit Points (healed to its HP\n"
             "maximum) instead of rolling healing_type dice.")
        .def_readwrite("revives_dead", &Spell::revives_dead,
             "Raise Dead / Revivify: this heal can restore a true-dead corpse. Clears the\n"
             "target's `dead` condition before reviving, and drives the GUI corpse-pick mode.")
        .def_readwrite("animates_dead", &Spell::animates_dead,
             "Animate Dead (Divine Intervention D3): targets a corpse and raises an undead\n"
             "servant from it. Engine ignores it; drives the GUI corpse-pick + spawn resolve.")
        .def_readwrite("binds_creature", &Spell::binds_creature,
             "Planar Binding (Divine Intervention D3): on a failed Charisma save the target is\n"
             "bound to the caster's team. Engine ignores it; drives the GUI control-transfer resolve.")
        .def_readwrite("creates_movement_ward", &Spell::creates_movement_ward,
             "Magic Circle / Hallow (Divine Intervention D4): places a creature-type movement ward\n"
             "at the aimed center. The warded types + direction ride on SpellAction\n"
             "(ward_creature_mask / ward_traps); radius comes from `radius`.")
        .def_readwrite("ward_blocks_living", &Spell::ward_blocks_living,
             "Antilife Shell: places a caster-anchored emanation (radius `radius`) that no living\n"
             "creature can cross (only Undead may pass). Reuses the movement-ward terrain effect\n"
             "with ward_all_living instead of a creature-type mask.")
        .def_readwrite("creates_wall_terrain", &Spell::creates_wall_terrain,
             "Wall of Stone: an oriented Rectangle wall (aimed with a second point like Wall of\n"
             "Fire) whose cells become solid Wall terrain for the duration, then restore. Reuses\n"
             "the terrain-effect lifecycle with the place_terrain_effect sets_wall flag.")
        .def_readwrite("ends_conditions", &Spell::ends_conditions,
             "Restorative Heal: condition names ended on each healed target (e.g. Power\n"
             "Word Heal ends Charmed/Frightened/Paralyzed/Poisoned/Stunned).")
        .def_readwrite("teleportation_spell", &Spell::teleportation_spell,
             "If true, this spell enables teleporting agents (Misty Step, Dimension Door, Teleport).")
        .def_readwrite("max_teleport_targets", &Spell::max_teleport_targets,
             "Max number of agents (incl. caster) that can teleport (0 = not a teleport spell).\n"
             "Misty Step=1, Dimension Door=2, Teleport=9.")
        .def_readwrite("teleport_range_ft", &Spell::teleport_range_ft,
             "Range in feet for teleportation destination.\n"
             "Misty Step=30, Dimension Door=500, Teleport=3000.")
        .def_readwrite("num_targets", &Spell::num_targets,
             "For Multiple geometry: base number of targets/projectiles at spell level.")
        .def_readwrite("targets_per_upcast_level", &Spell::targets_per_upcast_level,
             "For Multiple geometry: additional targets per upcast level above base.")
        .def_readwrite("effects_on_begin_turn", &Spell::effects_on_begin_turn,
             "If true, apply spell effects to agents in area at the start of their turn.")
        .def_readwrite("effects_on_end_turn", &Spell::effects_on_end_turn,
             "If true, apply spell effects to agents in area at the end of their turn.")
        .def_readwrite("conditions", &Spell::conditions,
             "List of AttackCondition objects applied to targets (includes name, duration, save rules).")
        .def("__repr__", [](const Spell& s){
            return "<Spell '" + s.name + "'>"; });

    // ── SpellAction ───────────────────────────────────────────────────────────
    py::class_<SpellAction>(m, "SpellAction")
        .def(py::init<>())
        .def_readwrite("caster_idx",     &SpellAction::caster_idx)
        .def_readwrite("spell_idx",      &SpellAction::spell_idx)
        .def_readwrite("slot_level",     &SpellAction::slot_level,
             "For player upcasting: spell slot level used (1-9); 0 = base level / NPC mode")
        .def_readwrite("target_indices", &SpellAction::target_indices)
        .def_readwrite("aoe_col",        &SpellAction::aoe_col)
        .def_readwrite("aoe_row",        &SpellAction::aoe_row)
        .def_readwrite("aoe_col2",       &SpellAction::aoe_col2,
             "Endpoint column for oriented Rectangle 'wall' spells (-1 = unset).")
        .def_readwrite("aoe_row2",       &SpellAction::aoe_row2,
             "Endpoint row for oriented Rectangle 'wall' spells (-1 = unset).")
        .def_readwrite("metamagic",      &SpellAction::metamagic,
             "Sorcerer Metamagic applied to this cast (MetamagicOption; NONE = none).\n"
             "SP cost is deducted in execute_spell. Applied: Careful, Distant, Empowered,\n"
             "Extended, Heightened, Quickened, Seeking, Transmuted, Twinned. Subtle = flavor only.")
        .def_readwrite("metamagic2",     &SpellAction::metamagic2,
             "Second Metamagic option on the same cast (MetamagicOption; NONE = none). Honored only\n"
             "when one of the pair is Seeking (the option that stacks) or the caster has Sorcery\n"
             "Incarnate (Sorcerer L7 with Innate Sorcery active); otherwise execute_spell logs and\n"
             "ignores it, spending no SP. A duplicate of `metamagic` is ignored (never paid twice).")
        .def_readwrite("careful_targets", &SpellAction::careful_targets,
             "Careful Spell: allies excluded from this spell's area (up to the caster's CHA mod).")
        .def_readwrite("transmuted_damage_type", &SpellAction::transmuted_damage_type,
             "Transmuted Spell: MagicDamage value to convert the spell's elemental damage into (-1 = none).")
        .def_readwrite("damage_type_override", &SpellAction::damage_type_override,
             "Cast-time element choice (Chromatic Orb, Sorcerous Burst): MagicDamage value to set this\n"
             "cast's damage type to (-1 = use the spell's stored type). Rewrites every damage roll's type.")
        .def_readwrite("chromatic_leap_targets", &SpellAction::chromatic_leap_targets,
             "Chromatic Orb leap chain (GUI picker): ordered creatures the orb should leap to on\n"
             "matching d8s, consumed one per leap. Each is validated (within 30 ft of the previous\n"
             "hop, living non-ally, not already hit); empty/invalid entries fall back to nearest enemy.")
        .def_readwrite("free_cast", &SpellAction::free_cast,
             "Free cast: when true, executeSpell does not expend a spell slot (the caller still\n"
             "charges the action economy). Used for Mantle of Majesty's slot-free Command casts.")
        .def_readwrite("command_word", &SpellAction::command_word,
             "Command spell word (only read for the Command spell): 0=Drop, 1=Flee, 2=Grovel,\n"
             "3=Halt, 4=Approach. -1 = unspecified → engine defaults to Halt.")
        .def_readwrite("curse_choice", &SpellAction::curse_choice,
             "Vistani Curse sub-choice (only read for curse spells): vulnerability → encoded damage\n"
             "type (0..9 magic, 100+i physical); weakness → SaveAbility value; affliction →\n"
             "0=Blinded, 1=Deafened, 2=Both. -1 = unspecified.")
        .def_readwrite("overchannel", &SpellAction::overchannel,
             "Overchannel (Evoker Wizard L14): request maximum damage on this cast. Honored only for\n"
             "an Evoker L14+ casting a damaging spell of effective level 1-5; first use per Long Rest\n"
             "is free, later uses inflict escalating Necrotic self-damage. Default false.")
        .def_readwrite("dispel_condition_ids", &SpellAction::dispel_condition_ids,
             "Dispel Magic picker selection: ActiveAgentCondition ids to end (see dispel_spell_effect_ids).")
        .def_readwrite("dispel_spell_effect_ids", &SpellAction::dispel_spell_effect_ids,
             "Dispel Magic picker selection: ActiveSpellEffect ids to end.")
        .def_readwrite("ward_creature_mask", &SpellAction::ward_creature_mask,
             "Magic Circle / Hallow: OR of rpg creature-type bits this cast wards (chosen in GUI).")
        .def_readwrite("ward_traps", &SpellAction::ward_traps,
             "Magic Circle reverse mode: False keeps warded types OUT, True traps them IN.")
        .def_readwrite("forcecage_sealed", &SpellAction::forcecage_sealed,
             "Forcecage form: False = Cage (20-ft barred, attacks/spells pass through); True = Box\n"
             "(10-ft solid, two-way seal — occupant can't act out and can't be targeted from outside).")
        .def_readwrite("dispel_terrain_ids", &SpellAction::dispel_terrain_ids,
             "Dispel Magic picker selection: ActiveTerrainEffect ids to end. When any of these three\n"
             "lists is non-empty, a dispels_magic cast ends ONLY the chosen effects (grouped by source\n"
             "spell, one roll each) instead of everything on the aimed creature/cell.")
        .def("__repr__", [](const SpellAction& a){
            return "<SpellAction caster=" + std::to_string(a.caster_idx)
                 + " spell=" + std::to_string(a.spell_idx)
                 + " targets=" + std::to_string(a.target_indices.size()) + ">"; });

    // ── DispelCandidate (Dispel Magic picker) ─────────────────────────────────
    py::class_<DispelCandidate>(m, "DispelCandidate")
        .def_readonly("label",            &DispelCandidate::label,
             "Spell/condition name shown in the picker.")
        .def_readonly("owner_idx",        &DispelCandidate::owner_idx,
             "Agent index of the caster who created the effect (-1 = unknown).")
        .def_readonly("level",            &DispelCandidate::level,
             "Effective level: auto-ends if <= slot, else the check is DC 10 + level.")
        .def_readonly("owner_is_ally",    &DispelCandidate::owner_is_ally,
             "True if the effect's owner is an ally of the dispelling caster (buff-on-ally hint).")
        .def_readonly("spell_key",        &DispelCandidate::spell_key,
             "Grouping spell_idx for concentration cleanup (-1 = ungrouped).")
        .def_readonly("condition_ids",    &DispelCandidate::condition_ids)
        .def_readonly("spell_effect_ids", &DispelCandidate::spell_effect_ids)
        .def_readonly("terrain_ids",      &DispelCandidate::terrain_ids)
        .def("__repr__", [](const DispelCandidate& c){
            return "<DispelCandidate '" + c.label + "' lvl=" + std::to_string(c.level)
                 + (c.owner_is_ally ? " ally" : " enemy") + ">"; });

    // ── SpellTargetResult ─────────────────────────────────────────────────────
    py::class_<SpellTargetResult>(m, "SpellTargetResult")
        .def(py::init<>())
        .def_readonly("target_idx",    &SpellTargetResult::target_idx)
        .def_readonly("saved",         &SpellTargetResult::saved)
        .def_readonly("hit",           &SpellTargetResult::hit)
        .def_readonly("d20",           &SpellTargetResult::d20)
        .def_readonly("attack_mod",    &SpellTargetResult::attack_mod)
        .def_readonly("total_roll",    &SpellTargetResult::total_roll)
        .def_readonly("target_ac",     &SpellTargetResult::target_ac)
        .def_readonly("critical",      &SpellTargetResult::critical)
        .def_readonly("dice_results",  &SpellTargetResult::dice_results)
        .def_readonly("damage_mod",    &SpellTargetResult::damage_mod)
        .def_readonly("total_damage",  &SpellTargetResult::total_damage)
        .def_readonly("total_healing", &SpellTargetResult::total_healing)
        .def_readonly("hp_before",     &SpellTargetResult::hp_before)
        .def_readonly("hp_after",      &SpellTargetResult::hp_after)
        .def_readonly("target_down",   &SpellTargetResult::target_down)
        .def_readonly("save_d20",      &SpellTargetResult::save_d20)
        .def_readonly("save_mod",      &SpellTargetResult::save_mod)
        .def_readonly("save_dc",       &SpellTargetResult::save_dc)
        .def_readonly("log_message",   &SpellTargetResult::log_message)
        .def_readonly("concentration_checked", &SpellTargetResult::concentration_checked)
        .def_readonly("concentration_lost",    &SpellTargetResult::concentration_lost)
        .def_readonly("push_ft_applied",       &SpellTargetResult::push_ft_applied)
        .def("__repr__", [](const SpellTargetResult& r){
            return "<SpellTargetResult tgt=" + std::to_string(r.target_idx)
                 + (r.hit ? " HIT" : " MISS")
                 + " dmg=" + std::to_string(r.total_damage)
                 + " heal=" + std::to_string(r.total_healing) + ">"; });

    // ── SpellResult ───────────────────────────────────────────────────────────
    py::class_<SpellResult>(m, "SpellResult")
        .def(py::init<>())
        .def_readonly("valid",                      &SpellResult::valid)
        .def_readonly("spell_idx",                  &SpellResult::spell_idx)
        .def_readonly("spell_name",                 &SpellResult::spell_name)
        .def_readonly("attack_type",                &SpellResult::attack_type)
        .def_readonly("target_results",             &SpellResult::target_results)
        .def_readonly("concentration_replaced",     &SpellResult::concentration_replaced)
        .def_readonly("prev_concentration_spell",   &SpellResult::prev_concentration_spell)
        .def_readonly("terrain_effect_ids",         &SpellResult::terrain_effect_ids,
             "IDs of terrain effects placed by this spell (for Python render cache).")
        .def_readonly("light_effect_ids",           &SpellResult::light_effect_ids,
             "IDs of light effects placed by this spell (for Python render cache).")
        .def_readonly("cast_as_bonus_action",       &SpellResult::cast_as_bonus_action,
             "Metamagic Quickened: this cast was made as a Bonus Action.")
        .def("__repr__", [](const SpellResult& r){
            if (!r.valid) return std::string("<SpellResult invalid>");
            return "<SpellResult '" + r.spell_name + "' "
                 + std::to_string(r.target_results.size()) + " target(s)>"; });

    // ── DropConcentrationResult ──────────────────────────────────────────────
    py::class_<DropConcentrationResult>(m, "DropConcentrationResult")
        .def_readonly("dropped",                   &DropConcentrationResult::dropped)
        .def_readonly("spell_name",                &DropConcentrationResult::spell_name)
        .def_readonly("removed_terrain_ids",       &DropConcentrationResult::removed_terrain_ids)
        .def_readonly("removed_spell_effect_ids",  &DropConcentrationResult::removed_spell_effect_ids)
        .def_readonly("removed_condition_ids",     &DropConcentrationResult::removed_condition_ids)
        .def_readonly("dismissed_summons",         &DropConcentrationResult::dismissed_summons);

    // ── TurnUndeadResult ─────────────────────────────────────────────────────
    py::class_<TurnUndeadResult>(m, "TurnUndeadResult")
        .def_readonly("valid",       &TurnUndeadResult::valid)
        .def_readonly("save_dc",     &TurnUndeadResult::save_dc)
        .def_readonly("sear_damage", &TurnUndeadResult::sear_damage)
        .def_readonly("turned",      &TurnUndeadResult::turned)
        .def_readonly("resisted",    &TurnUndeadResult::resisted);

    // ── PreserveLifeResult (Life Domain Channel Divinity) ────────────────────
    py::class_<PreserveLifeResult>(m, "PreserveLifeResult")
        .def_readonly("valid",   &PreserveLifeResult::valid)
        .def_readonly("pool",    &PreserveLifeResult::pool)
        .def_readonly("spent",   &PreserveLifeResult::spent)
        .def_readonly("healed",  &PreserveLifeResult::healed)
        .def_readonly("amounts", &PreserveLifeResult::amounts);

    // ── ToppleResult ─────────────────────────────────────────────────────────
    py::class_<ToppleResult>(m, "ToppleResult")
        .def_readonly("valid",     &ToppleResult::valid)
        .def_readonly("save_dc",   &ToppleResult::save_dc)
        .def_readonly("save_roll", &ToppleResult::save_roll)
        .def_readonly("toppled",   &ToppleResult::toppled);

    // ── StunningStrikeResult ──────────────────────────────────────────────────
    py::class_<StunningStrikeResult>(m, "StunningStrikeResult")
        .def_readonly("valid",     &StunningStrikeResult::valid)
        .def_readonly("save_dc",   &StunningStrikeResult::save_dc)
        .def_readonly("save_roll", &StunningStrikeResult::save_roll)
        .def_readonly("stunned",   &StunningStrikeResult::stunned);

    // ── ManeuverResult (Battle Master Maneuvers) ─────────────────────────────
    py::class_<ManeuverResult>(m, "ManeuverResult")
        .def_readonly("valid",              &ManeuverResult::valid)
        .def_readonly("maneuver_type",      &ManeuverResult::maneuver_type)
        .def_readonly("save_dc",            &ManeuverResult::save_dc)
        .def_readonly("save_roll",          &ManeuverResult::save_roll)
        .def_readonly("condition_applied",  &ManeuverResult::condition_applied)
        .def_readonly("push_distance",      &ManeuverResult::push_distance)
        .def_readonly("extra_damage",       &ManeuverResult::extra_damage)
        .def_readonly("extra_target_down",  &ManeuverResult::extra_target_down);

    // ── OpenHandRiderResult ───────────────────────────────────────────────────
    py::class_<OpenHandRiderResult>(m, "OpenHandRiderResult")
        .def_readonly("valid",                   &OpenHandRiderResult::valid)
        .def_readonly("option",                  &OpenHandRiderResult::option)
        .def_readonly("knockdown_save_dc",       &OpenHandRiderResult::knockdown_save_dc)
        .def_readonly("knockdown_save_roll",     &OpenHandRiderResult::knockdown_save_roll)
        .def_readonly("target_knocked_prone",    &OpenHandRiderResult::target_knocked_prone)
        .def_readonly("push_distance",           &OpenHandRiderResult::push_distance)
        .def_readonly("reaction_denied",         &OpenHandRiderResult::reaction_denied);

    // ── HandOfHealingResult (Monk Warrior of Mercy) ──────────────────────────
    py::class_<HandOfHealingResult>(m, "HandOfHealingResult")
        .def_readonly("valid",             &HandOfHealingResult::valid)
        .def_readonly("amount_healed",     &HandOfHealingResult::amount_healed)
        .def_readonly("condition_cleared", &HandOfHealingResult::condition_cleared)
        .def_readonly("cleared_condition", &HandOfHealingResult::cleared_condition);

    // ── UseItemResult (CombatEngine::use_item) ───────────────────────────────
    py::class_<UseItemResult>(m, "UseItemResult")
        .def_readonly("valid",         &UseItemResult::valid)
        .def_readonly("amount_healed", &UseItemResult::amount_healed)
        .def_readonly("item_name",     &UseItemResult::item_name)
        .def_readonly("consumed",      &UseItemResult::consumed)
        .def_readonly("save_dc",       &UseItemResult::save_dc)
        .def_readonly("save_roll",     &UseItemResult::save_roll)
        .def_readonly("saved",         &UseItemResult::saved,
             "Thrown item: the target made its save (or auto-succeeded). The flask is spent either way.")
        .def_readonly("damage_dealt",  &UseItemResult::damage_dealt)
        .def_readonly("no_effect",     &UseItemResult::no_effect,
             "Thrown item: splashed harmlessly (Holy Water on a creature that is neither Fiend nor Undead).")
        .def_readonly("condition_applied", &UseItemResult::condition_applied);

    // ── EscapeNetResult (CombatEngine::escape_net) ───────────────────────────
    py::class_<EscapeNetResult>(m, "EscapeNetResult")
        .def_readonly("valid", &EscapeNetResult::valid)
        .def_readonly("dc",    &EscapeNetResult::dc)
        .def_readonly("d20",   &EscapeNetResult::d20)
        .def_readonly("total", &EscapeNetResult::total)
        .def_readonly("freed", &EscapeNetResult::freed);

    // ── FlurryResult (Monk Flurry of Blows) ──────────────────────────────────
    py::class_<FlurryResult>(m, "FlurryResult")
        .def_readonly("attack1",  &FlurryResult::attack1)
        .def_readonly("attack2",  &FlurryResult::attack2)
        .def_readonly("attack3",  &FlurryResult::attack3)
        .def_readonly("rider1",   &FlurryResult::rider1)
        .def_readonly("rider2",   &FlurryResult::rider2)
        .def_readonly("rider3",   &FlurryResult::rider3);

    // ── TerrainTickResult ────────────────────────────────────────────────────
    py::class_<TerrainTickResult>(m, "TerrainTickResult")
        .def_readonly("expired_terrain_ids", &TerrainTickResult::expired_terrain_ids)
        .def_readonly("concentration",       &TerrainTickResult::concentration);

    // ── CombatDecider interface ──────────────────────────────────────────────
    py::class_<BrutalStrikeCtx>(m, "BrutalStrikeCtx")
        .def_readonly("attacker_idx", &BrutalStrikeCtx::attacker_idx)
        .def_readonly("target_idx",   &BrutalStrikeCtx::target_idx)
        .def_readonly("level",        &BrutalStrikeCtx::level);

    py::class_<RecklessCtx>(m, "RecklessCtx")
        .def_readonly("attacker_idx", &RecklessCtx::attacker_idx);

    // ── Reaction system ─────────────────────────────
    py::enum_<ReactionWindow>(m, "ReactionWindow")
        .value("LeftReach",         ReactionWindow::LeftReach)
        .value("OnHit",             ReactionWindow::OnHit)
        .value("OnMiss",            ReactionWindow::OnMiss)
        .value("OnDeclareCast",     ReactionWindow::OnDeclareCast)
        .value("OnD20Seen",         ReactionWindow::OnD20Seen)
        .value("OnSaveFail",        ReactionWindow::OnSaveFail)
        .value("OnTurnStartNearby", ReactionWindow::OnTurnStartNearby)
        .value("OnAllyAttacked",    ReactionWindow::OnAllyAttacked);

    py::enum_<ReactionOption::Kind>(m, "ReactionOptionKind")
        .value("Skip",    ReactionOption::Skip)
        .value("Weapon",  ReactionOption::Weapon)
        .value("Spell",   ReactionOption::Spell)
        .value("Feature", ReactionOption::Feature);

    py::class_<ReactionOption>(m, "ReactionOption")
        .def_readonly("kind",    &ReactionOption::kind)
        .def_readonly("index",   &ReactionOption::index)
        .def_readonly("label",   &ReactionOption::label)
        .def_readonly("feature", &ReactionOption::feature);

    py::class_<ReactionCtx>(m, "ReactionCtx")
        .def_readonly("window",      &ReactionCtx::window)
        .def_readonly("reactor_idx", &ReactionCtx::reactor_idx)
        .def_readonly("source_idx",  &ReactionCtx::source_idx)
        .def_readonly("options",     &ReactionCtx::options)
        .def_readonly("d20_value",   &ReactionCtx::d20_value)
        .def_readonly("spell_idx",   &ReactionCtx::spell_idx)
        .def_readonly("damage",      &ReactionCtx::damage);

    py::class_<ReactionResponse>(m, "ReactionResponse")
        .def(py::init<>())
        .def_readwrite("option",     &ReactionResponse::option)
        .def_readwrite("target_idx", &ReactionResponse::target_idx);

    py::enum_<FlowStatus>(m, "FlowStatus")
        .value("Completed",        FlowStatus::Completed)
        .value("AwaitingDecision", FlowStatus::AwaitingDecision);

    py::class_<PendingDecision>(m, "PendingDecision")
        .def_readonly("active", &PendingDecision::active)
        .def_readonly("ctx",    &PendingDecision::ctx);

    py::class_<CombatDecider, PyCombatDecider>(m, "CombatDecider")
        .def(py::init<>())
        .def("choose_brutal_strike", &CombatDecider::chooseBrutalStrike)
        .def("choose_reckless",      &CombatDecider::chooseReckless)
        .def("choose_reaction",      &CombatDecider::chooseReaction);

    // ── ShoveAction / ShoveResult ────────────────────────────────────────────
    py::class_<ShoveAction>(m, "ShoveAction")
        .def(py::init<>())
        .def_readwrite("attacker_idx", &ShoveAction::attacker_idx)
        .def_readwrite("target_idx",   &ShoveAction::target_idx)
        .def_readwrite("knock_prone",  &ShoveAction::knock_prone);

    py::class_<ShoveResult>(m, "ShoveResult")
        .def(py::init<>())
        .def_readonly("valid",            &ShoveResult::valid)
        .def_readonly("success",          &ShoveResult::success)
        .def_readonly("attacker_roll",    &ShoveResult::attacker_roll)
        .def_readonly("defender_roll",    &ShoveResult::defender_roll)
        .def_readonly("push_ft_applied",  &ShoveResult::push_ft_applied)
        .def_readonly("knocked_prone",    &ShoveResult::knocked_prone)
        .def_readonly("log_message",      &ShoveResult::log_message)
        .def("__repr__", [](const ShoveResult& r){
            if (!r.valid) return std::string("<ShoveResult invalid>");
            return "<ShoveResult " + (r.success ? std::string("success")
                                                 : std::string("failed"))
                 + " atk=" + std::to_string(r.attacker_roll)
                 + " def=" + std::to_string(r.defender_roll) + ">"; });

    // ── PickLockResult (Sleight of Hand vs a door's lock DC) ───────────────────
    py::class_<PickLockResult>(m, "PickLockResult")
        .def_readonly("valid",       &PickLockResult::valid)
        .def_readonly("success",     &PickLockResult::success)
        .def_readonly("roll",        &PickLockResult::roll)
        .def_readonly("total",       &PickLockResult::total)
        .def_readonly("dc",          &PickLockResult::dc)
        .def_readonly("log_message", &PickLockResult::log_message)
        .def("__repr__", [](const PickLockResult& r){
            if (!r.valid) return std::string("<PickLockResult invalid>");
            return "<PickLockResult " + (r.success ? std::string("success")
                                                   : std::string("failed"))
                 + " total=" + std::to_string(r.total)
                 + " dc=" + std::to_string(r.dc) + ">"; });

    // ── BreakDoorResult (Strength/Athletics vs a door's break DC) ──────────────
    py::class_<BreakDoorResult>(m, "BreakDoorResult")
        .def_readonly("valid",       &BreakDoorResult::valid)
        .def_readonly("success",     &BreakDoorResult::success)
        .def_readonly("roll",        &BreakDoorResult::roll)
        .def_readonly("total",       &BreakDoorResult::total)
        .def_readonly("dc",          &BreakDoorResult::dc)
        .def_readonly("log_message", &BreakDoorResult::log_message)
        .def("__repr__", [](const BreakDoorResult& r){
            if (!r.valid) return std::string("<BreakDoorResult invalid>");
            return "<BreakDoorResult " + (r.success ? std::string("success")
                                                    : std::string("failed"))
                 + " total=" + std::to_string(r.total)
                 + " dc=" + std::to_string(r.dc) + ">"; });

    // ── GrappleAction / GrappleResult / GrappleEscapeResult ────────────────────
    py::class_<GrappleAction>(m, "GrappleAction")
        .def(py::init<>())
        .def_readwrite("attacker_idx", &GrappleAction::attacker_idx)
        .def_readwrite("target_idx",   &GrappleAction::target_idx);

    py::class_<GrappleResult>(m, "GrappleResult")
        .def(py::init<>())
        .def_readonly("valid",            &GrappleResult::valid)
        .def_readonly("success",          &GrappleResult::success)
        .def_readonly("attacker_roll",    &GrappleResult::attacker_roll)
        .def_readonly("defender_roll",    &GrappleResult::defender_roll)
        .def_readonly("escape_dc",        &GrappleResult::escape_dc)
        .def_readonly("log_message",      &GrappleResult::log_message)
        .def("__repr__", [](const GrappleResult& r){
            if (!r.valid) return std::string("<GrappleResult invalid>");
            return "<GrappleResult " + (r.success ? std::string("success")
                                                   : std::string("failed"))
                 + " atk=" + std::to_string(r.attacker_roll)
                 + " def=" + std::to_string(r.defender_roll)
                 + " dc=" + std::to_string(r.escape_dc) + ">"; });

    py::class_<GrappleEscapeResult>(m, "GrappleEscapeResult")
        .def(py::init<>())
        .def_readonly("valid",            &GrappleEscapeResult::valid)
        .def_readonly("success",          &GrappleEscapeResult::success)
        .def_readonly("escape_roll",      &GrappleEscapeResult::escape_roll)
        .def_readonly("escape_dc",        &GrappleEscapeResult::escape_dc)
        .def_readonly("log_message",      &GrappleEscapeResult::log_message)
        .def("__repr__", [](const GrappleEscapeResult& r){
            if (!r.valid) return std::string("<GrappleEscapeResult invalid>");
            return "<GrappleEscapeResult " + (r.success ? std::string("success")
                                                        : std::string("failed"))
                 + " roll=" + std::to_string(r.escape_roll)
                 + " dc=" + std::to_string(r.escape_dc) + ">"; });

    // ── ActiveEffect ──────────────────────────────────────────────────────────
    py::class_<ActiveEffect>(m, "ActiveEffect")
        .def(py::init<>())
        .def_readwrite("caster_idx",      &ActiveEffect::caster_idx)
        .def_readwrite("target_idx",      &ActiveEffect::target_idx)
        .def_readwrite("spell",           &ActiveEffect::spell)
        .def_readwrite("turns_remaining", &ActiveEffect::turns_remaining)
        .def("__repr__", [](const ActiveEffect& e){
            return "<ActiveEffect '" + e.spell.name
                 + "' caster=" + std::to_string(e.caster_idx)
                 + " tgt=" + std::to_string(e.target_idx)
                 + " turns=" + std::to_string(e.turns_remaining) + ">"; });

    // ── ActiveSpellEffect ────────────────────────────────────────────────────
    py::class_<ActiveSpellEffect>(m, "ActiveSpellEffect")
        .def(py::init<>())
        .def_readwrite("caster_idx",      &ActiveSpellEffect::caster_idx)
        .def_readwrite("spell_idx",       &ActiveSpellEffect::spell_idx)
        .def_readwrite("spell",           &ActiveSpellEffect::spell)
        .def_readwrite("cells",           &ActiveSpellEffect::cells)
        .def_readwrite("turns_remaining", &ActiveSpellEffect::turns_remaining)
        .def_readwrite("effect_id",       &ActiveSpellEffect::effect_id)
        .def_readwrite("cast_level",      &ActiveSpellEffect::cast_level)
        .def("__repr__", [](const ActiveSpellEffect& e){
            return "<ActiveSpellEffect '" + e.spell.name
                 + "' caster=" + std::to_string(e.caster_idx)
                 + " cells=" + std::to_string(e.cells.size())
                 + " turns=" + std::to_string(e.turns_remaining) + ">"; });

    // ── ConcentrationSaveResult ───────────────────────────────────────────────
    py::class_<ConcentrationSaveResult>(m, "ConcentrationSaveResult")
        .def(py::init<>())
        .def_readonly("checked",            &ConcentrationSaveResult::checked)
        .def_readonly("save_d20",           &ConcentrationSaveResult::save_d20)
        .def_readonly("save_dc",            &ConcentrationSaveResult::save_dc)
        .def_readonly("con_mod",            &ConcentrationSaveResult::con_mod)
        .def_readonly("passed",             &ConcentrationSaveResult::passed)
        .def_readonly("concentration_lost", &ConcentrationSaveResult::concentration_lost)
        .def_readonly("spell_name",         &ConcentrationSaveResult::spell_name);

    // ── TurnStartResult ────────────────────────────────────────────────────────
    py::class_<TurnStartResult>(m, "TurnStartResult")
        .def(py::init<>())
        .def_readwrite("turn_skipped",       &TurnStartResult::turn_skipped)
        .def_readwrite("skip_reason",        &TurnStartResult::skip_reason)
        .def_readwrite("save_roll_message",  &TurnStartResult::save_roll_message)
        .def("__repr__", [](const TurnStartResult& r){
            if (r.turn_skipped) {
                return std::string("<TurnStartResult SKIPPED: ") + r.skip_reason + ">";
            }
            return std::string("<TurnStartResult turn proceeds>");
        });

    // ── HideResult ────────────────────────────────────────────────────────────
    py::class_<HideResult>(m, "HideResult")
        .def(py::init<>())
        .def_readonly("valid",              &HideResult::valid)
        .def_readonly("stealth_d20",        &HideResult::stealth_d20)
        .def_readonly("stealth_total",      &HideResult::stealth_total)
        .def_readonly("hidden",             &HideResult::hidden)
        .def_readonly("log_message",        &HideResult::log_message)
        .def("__repr__", [](const HideResult& r){
            if (!r.valid) return std::string("<HideResult invalid>");
            return "<HideResult " + (r.hidden ? std::string("hidden")
                                              : std::string("spotted"))
                 + " stealth=" + std::to_string(r.stealth_total) + ">"; });

    // ── ActiveAgentCondition ──────────────────────────────────────────────────
    py::class_<ActiveAgentCondition>(m, "ActiveAgentCondition")
        .def(py::init<>())
        .def_readwrite("agent_idx",      &ActiveAgentCondition::agent_idx)
        .def_readwrite("caster_idx",     &ActiveAgentCondition::caster_idx)
        .def_readwrite("spell_idx",      &ActiveAgentCondition::spell_idx)
        .def_readwrite("condition_name", &ActiveAgentCondition::condition_name)
        .def_readwrite("turns_remaining", &ActiveAgentCondition::turns_remaining)
        .def_readwrite("next_save_turn",  &ActiveAgentCondition::next_save_turn)
        .def_readwrite("save_ability",    &ActiveAgentCondition::save_ability)
        .def_readwrite("save_dc",         &ActiveAgentCondition::save_dc)
        .def_readwrite("save_repeat_turns", &ActiveAgentCondition::save_repeat_turns)
        .def_readwrite("save_at_end_of_turn", &ActiveAgentCondition::save_at_end_of_turn)
        .def_readwrite("condition_id",    &ActiveAgentCondition::condition_id)
        .def_readwrite("cast_level",      &ActiveAgentCondition::cast_level)
        .def_readwrite("on_damage",       &ActiveAgentCondition::on_damage)
        // ── Delayed / stored effect (Quivering Palm, Delayed Blast Fireball, …) ──
        .def_readwrite("delayed_trigger",      &ActiveAgentCondition::delayed_trigger)
        .def_readwrite("delay_dice",           &ActiveAgentCondition::delay_dice)
        .def_readwrite("delay_die_size",       &ActiveAgentCondition::delay_die_size)
        .def_readwrite("delay_flat_bonus",     &ActiveAgentCondition::delay_flat_bonus)
        .def_readwrite("delay_damage_type",    &ActiveAgentCondition::delay_damage_type)
        .def_readwrite("delay_requires_save",  &ActiveAgentCondition::delay_requires_save)
        .def_readwrite("delay_half_on_save",   &ActiveAgentCondition::delay_half_on_save)
        .def_readwrite("delay_drop_to_zero",   &ActiveAgentCondition::delay_drop_to_zero)
        .def_readwrite("delay_auto_on_expire", &ActiveAgentCondition::delay_auto_on_expire)
        .def_readwrite("delay_label",          &ActiveAgentCondition::delay_label)
        // ── Damage-over-time / no-heal rider (generic; Pit Fiend poison) ─────────
        .def_readwrite("dot_dice",             &ActiveAgentCondition::dot_dice)
        .def_readwrite("dot_die_size",         &ActiveAgentCondition::dot_die_size)
        .def_readwrite("dot_flat_bonus",       &ActiveAgentCondition::dot_flat_bonus)
        .def_readwrite("dot_damage_type",      &ActiveAgentCondition::dot_damage_type)
        .def_readwrite("prevents_healing",     &ActiveAgentCondition::prevents_healing)
        // ── Caster "kickback" on condition end (Vistani Curse) ──────────────────
        .def_readwrite("kickback_dice",        &ActiveAgentCondition::kickback_dice)
        .def_readwrite("kickback_die_size",    &ActiveAgentCondition::kickback_die_size)
        .def_readwrite("kickback_damage_type", &ActiveAgentCondition::kickback_damage_type)
        // ── Vistani Curse effect state ──────────────────────────────────────────
        .def_readwrite("curse_disadv_ability", &ActiveAgentCondition::curse_disadv_ability,
             "SaveAbility value made to roll at Disadvantage by a Curse of Weakness (-1 = none).")
        .def_readwrite("curse_vuln_type_code", &ActiveAgentCondition::curse_vuln_type_code,
             "Encoded damage type made vulnerable by a Curse of Vulnerability: 0..9 magic, 100+i\n"
             "physical (-1 = none).")
        .def_readwrite("curse_vuln_prev_mult", &ActiveAgentCondition::curse_vuln_prev_mult,
             "Target's prior damage multiplier for the cursed type, restored when the curse ends.")
        .def("__repr__", [](const ActiveAgentCondition& c){
            return "<ActiveAgentCondition '" + c.condition_name
                 + "' on agent[" + std::to_string(c.agent_idx)
                 + "] turns=" + std::to_string(c.turns_remaining) + ">"; });

    // ── AttackResult ─────────────────────────────────────────────────────────
    py::class_<WildMagicSurgeResult>(m, "WildMagicSurgeResult")
        .def(py::init<>())
        .def_readonly("d100_roll",   &WildMagicSurgeResult::d100_roll)
        .def_readonly("effect",      &WildMagicSurgeResult::effect,
             "Surge table band 1-10 (0 = no surge / not a L3+ Wild Magic Sorcerer).")
        .def_readonly("description", &WildMagicSurgeResult::description)
        .def("__repr__", [](const WildMagicSurgeResult& r){
            return "<WildMagicSurge d100=" + std::to_string(r.d100_roll)
                 + " effect=" + std::to_string(r.effect) + ">";
        });

    py::class_<WildMagicSurgeOffer>(m, "WildMagicSurgeOffer")
        .def(py::init<>())
        .def_readonly("surged",         &WildMagicSurgeOffer::surged,
             "Did a surge actually trigger this cast?")
        .def_readonly("options",        &WildMagicSurgeOffer::options,
             "Candidate surge bands 1-10 (1 normally; 2 with Controlled Chaos at L14).")
        .def_readonly("can_choose_any", &WildMagicSurgeOffer::can_choose_any,
             "Tamed Surge (L18): the caller may pick ANY band 1-10, not just the rolled one(s).")
        .def_readonly("tides_expended", &WildMagicSurgeOffer::tides_expended,
             "Pass back to resolve_wild_magic_surge so it recharges Tides of Chaos.")
        .def("__repr__", [](const WildMagicSurgeOffer& o){
            return "<WildMagicSurgeOffer surged=" + std::string(o.surged ? "1" : "0")
                 + " n_options=" + std::to_string(o.options.size())
                 + " any=" + std::string(o.can_choose_any ? "1" : "0") + ">";
        });

    py::class_<AttackResult>(m, "AttackResult")
        .def(py::init<>())
        .def_readonly("valid",        &AttackResult::valid)
        .def_readonly("d20",          &AttackResult::d20)
        .def_readonly("d20_primary",  &AttackResult::d20_primary)
        .def_readonly("attack_mod",   &AttackResult::attack_mod)
        .def_readonly("total_roll",   &AttackResult::total_roll)
        .def_readonly("target_ac",    &AttackResult::target_ac)
        .def_readonly("critical",     &AttackResult::critical)
        .def_readonly("fumble",       &AttackResult::fumble)
        .def_readonly("disadvantage", &AttackResult::disadvantage)
        .def_readonly("advantage",    &AttackResult::advantage)
        .def_readonly("hit",          &AttackResult::hit)
        .def_readonly("dice_results",          &AttackResult::dice_results)
        .def_readonly("damage_mod",            &AttackResult::damage_mod)
        .def_readonly("total_damage",          &AttackResult::total_damage)
        .def_readonly("damage_breakdown",      &AttackResult::damage_breakdown)
        .def_readonly("physical_damage_types", &AttackResult::physical_damage_types)
        .def_readonly("magic_damage_types",    &AttackResult::magic_damage_types)
        .def_readonly("hp_before",             &AttackResult::hp_before)
        .def_readonly("hp_after",     &AttackResult::hp_after)
        .def_readonly("target_down",  &AttackResult::target_down)
        .def_readonly("push_ft_applied", &AttackResult::push_ft_applied)
        .def_readonly("weapon_thrown",   &AttackResult::weapon_thrown,
                      "The weapon was THROWN: it is out of the thrower's hand (hit or miss).")
        .def_readonly("thrown_item_id",  &AttackResult::thrown_item_id,
                      "MapItem id the thrown weapon became on the ground (-1 = none).")
        .def("__repr__", [](const AttackResult& r){
            if (!r.valid) return std::string("<AttackResult invalid>");
            std::string s = "<AttackResult d20=" + std::to_string(r.d20)
                          + " mod=" + std::to_string(r.attack_mod)
                          + " vs AC=" + std::to_string(r.target_ac)
                          + (r.hit ? " HIT dmg=" + std::to_string(r.total_damage)
                                   : " MISS")
                          + ">";
            return s; });

    // ── InitiativeEntry ───────────────────────────────────────────────────────
    py::class_<InitiativeEntry>(m, "InitiativeEntry")
        .def(py::init<>())
        // Writable so the GUI can synthesize an entry for a mid-combat summon
        // (shares the summoner's `total`, inserted immediately after the summoner).
        .def_readwrite("agent_idx", &InitiativeEntry::agent_idx)
        .def_readwrite("d20",       &InitiativeEntry::d20)
        .def_readwrite("modifier",  &InitiativeEntry::modifier)
        .def_readwrite("total",     &InitiativeEntry::total)
        .def("__repr__", [](const InitiativeEntry& e){
            return "<InitiativeEntry agent=" + std::to_string(e.agent_idx)
                 + " d20=" + std::to_string(e.d20)
                 + " mod=" + std::to_string(e.modifier)
                 + " total=" + std::to_string(e.total) + ">"; });

    // ── Attack ──────────────────────────────────────────────────────────
    py::class_<Attack>(m, "Attack")
        .def(py::init<>())
        .def(py::init<int,int,int>(),
             py::arg("attacker_idx"), py::arg("target_idx"),
             py::arg("weapon_idx") = 0)
        .def_readwrite("attacker_idx", &Attack::attacker_idx)
        .def_readwrite("target_idx",   &Attack::target_idx)
        .def_readwrite("weapon_idx",   &Attack::weapon_idx)
        .def_readwrite("is_offhand",   &Attack::is_offhand)
        .def_readwrite("no_ability_damage", &Attack::no_ability_damage)
        .def_readwrite("attack_slot",  &Attack::attack_slot)
        .def_readwrite("opportunity",  &Attack::opportunity)
        .def_readwrite("thrown",       &Attack::thrown,
                       "THROW this weapon (needs Weapon.thrown): the attack reaches long_range_ft, "
                       "and the weapon leaves the thrower's hand to land on the ground as a MapItem.")
        .def("__repr__", [](const Attack& a){
            std::string s = "<Attack atk=" + std::to_string(a.attacker_idx)
                 + " tgt=" + std::to_string(a.target_idx)
                 + " wpn=" + std::to_string(a.weapon_idx);
            if (a.is_offhand) s += " offhand";
            if (a.thrown)     s += " thrown";
            return s + ">"; });

    // ── TurnActions ───────────────────────────────────────────────────────────
    py::class_<TurnActions>(m, "TurnActions")
        .def(py::init<>())
        .def(py::init([](int agent_idx,
                         std::vector<Attack>      attacks,
                         std::vector<Attack>      bonus_attacks,
                         std::vector<SpellAction> spell_actions,
                         std::vector<SpellAction> bonus_spells) {
            TurnActions t;
            t.agent_idx     = agent_idx;
            t.attacks       = std::move(attacks);
            t.bonus_attacks = std::move(bonus_attacks);
            t.spell_actions = std::move(spell_actions);
            t.bonus_spells  = std::move(bonus_spells);
            return t;
        }),
        py::arg("agent_idx"),
        py::arg("attacks")       = std::vector<Attack>{},
        py::arg("bonus_attacks") = std::vector<Attack>{},
        py::arg("spell_actions") = std::vector<SpellAction>{},
        py::arg("bonus_spells")  = std::vector<SpellAction>{})
        .def_readwrite("agent_idx",     &TurnActions::agent_idx)
        .def_readwrite("attacks",       &TurnActions::attacks)
        .def_readwrite("bonus_attacks", &TurnActions::bonus_attacks)
        .def_readwrite("spell_actions", &TurnActions::spell_actions)
        .def_readwrite("bonus_spells",  &TurnActions::bonus_spells)
        .def("__repr__", [](const TurnActions& t){
            std::string s = "<TurnActions agent=" + std::to_string(t.agent_idx);
            if (!t.attacks.empty())
                s += " attacks=" + std::to_string(t.attacks.size());
            if (!t.bonus_attacks.empty())
                s += " bonus_attacks=" + std::to_string(t.bonus_attacks.size());
            if (!t.spell_actions.empty())
                s += " spell_actions=" + std::to_string(t.spell_actions.size());
            if (!t.bonus_spells.empty())
                s += " bonus_spells=" + std::to_string(t.bonus_spells.size());
            return s + ">"; });

    // ── MessageLogger ──────────────────────────────────────────────────────────
    py::class_<MessageLogger>(m, "MessageLogger")
        .def(py::init<>())
        .def("log", &MessageLogger::log, py::arg("message"),
             "Log a single message.")
        .def("flush", &MessageLogger::flush,
             "Return all buffered messages and clear the buffer.")
        .def("set_file", &MessageLogger::setFile, py::arg("path"),
             "Optional: open a log file for debug output.");
    py::enum_<MovementType>(m, "MovementType")
        .value("Walk",   MovementType::Walk,
               "Ground movement: BFS through passable cells, respects walls.")
        .value("Fly",    MovementType::Fly,
               "Aerial movement: Chebyshev radius, ignores terrain obstacles.")
        .value("Swim",   MovementType::Swim,
               "Aquatic movement: through water terrain.")
        .value("Burrow", MovementType::Burrow,
               "Underground movement: ignores surface obstacles.")
        .value("Jump",   MovementType::Jump,
               "Jumping: clears Water and Chasm terrain but is blocked by walls.")
        .export_values();

    // ── DetectionParams ─────────────────────────────────────────────────────
    py::class_<BattleMap::DetectionParams>(m, "DetectionParams")
        .def(py::init<>())
        .def_readwrite("canny_low",            &BattleMap::DetectionParams::cannyLow)
        .def_readwrite("canny_high",           &BattleMap::DetectionParams::cannyHigh)
        .def_readwrite("hough_threshold",      &BattleMap::DetectionParams::houghThreshold)
        .def_readwrite("min_line_length",      &BattleMap::DetectionParams::minLineLength)
        .def_readwrite("max_line_gap",         &BattleMap::DetectionParams::maxLineGap)
        // Primary wall method: cells darker than this threshold (0–255) are obstacles
        .def_readwrite("dark_cell_threshold",  &BattleMap::DetectionParams::darkCellThreshold)
        // Secondary wall method: detect thick lines drawn between cells (opt-in)
        .def_readwrite("detect_edge_walls",    &BattleMap::DetectionParams::detectEdgeWalls)
        .def_readwrite("wall_min_px",          &BattleMap::DetectionParams::wallMinPx)
        .def_readwrite("flood_fill",           &BattleMap::DetectionParams::floodFill)
        .def_readwrite("flood_seed",           &BattleMap::DetectionParams::floodSeed);

    // ── TerrainType enum ────────────────────────────────────────────────────
    py::enum_<TerrainType>(m, "TerrainType")
        .value("Standard", TerrainType::Standard)
        .value("Water",    TerrainType::Water)
        .value("Wall",     TerrainType::Wall)
        .value("Chasm",    TerrainType::Chasm)
        .export_values();

    // ── TerrainDifficulty enum ──────────────────────────────────────────────
    py::enum_<TerrainDifficulty>(m, "TerrainDifficulty")
        .value("Normal",    TerrainDifficulty::Normal)
        .value("Halved",    TerrainDifficulty::Halved)
        .value("Quartered", TerrainDifficulty::Quartered)
        .value("Slipping",  TerrainDifficulty::Slipping)
        .export_values();

    // ── VisibilityLevel enum (unified for all vision/light) ──────────────────
    py::enum_<VisibilityLevel>(m, "VisibilityLevel")
        .value("Clear",            VisibilityLevel::Clear,
               "Fully visible (BrightLight area, normal vision)")
        .value("Dim",              VisibilityLevel::Dim,
               "Lightly obscured but visible (DimLight area)")
        .value("LightlyObscured",  VisibilityLevel::LightlyObscured,
               "Obscured by fog/shadows (disadvantage on perception/attacks)")
        .value("Dark",             VisibilityLevel::Dark,
               "Heavily obscured / Darkness (needs darkvision to see)")
        .value("MagicalDark",      VisibilityLevel::MagicalDark,
               "Impenetrable / MagicalDarkness (needs devil's sight to see)")
        .value("Blocked",          VisibilityLevel::Blocked,
               "Cannot see at all (blocked by walls, full cover, etc.)")
        .value("Sunlight",         VisibilityLevel::Sunlight,
               "Sunlight: a bright-light category that behaves like Clear for vision, tracked "
               "separately so vampire features (Sunlight Sensitivity) can detect it.")
        .value("HeavilyObscured",  VisibilityLevel::HeavilyObscured,
               "Fog/smoke/dense foliage: the effectively-Blinded state, but the non-magical, "
               "light-independent kind that darkvision AND devil's sight do NOT pierce (only "
               "Truesight/Blindsight do) and that bright light cannot dispel. Distinct from Dark "
               "(Darkness, pierced by darkvision) and MagicalDark (pierced by devil's sight).")
        .export_values();

    // ── ActiveTerrainEffect struct ───────────────────────────────────────────
    py::class_<ActiveTerrainEffect>(m, "ActiveTerrainEffect")
        .def_readonly("id",                &ActiveTerrainEffect::id)
        .def_readonly("name",              &ActiveTerrainEffect::name)
        .def_readonly("cell_indices",      &ActiveTerrainEffect::cell_indices)
        .def_readonly("difficulty",        &ActiveTerrainEffect::difficulty)
        .def_readonly("turns_remaining",   &ActiveTerrainEffect::turns_remaining)
        .def_readonly("source_agent_idx",  &ActiveTerrainEffect::source_agent_idx)
        .def_readonly("spell_idx",         &ActiveTerrainEffect::spell_idx)
        .def_readonly("cast_level",        &ActiveTerrainEffect::cast_level)
        .def_readonly("requires_concentration", &ActiveTerrainEffect::requires_concentration)
        .def_readonly("anchor_agent_idx",  &ActiveTerrainEffect::anchor_agent_idx)
        .def_readonly("anchor_radius_ft",  &ActiveTerrainEffect::anchor_radius_ft)
        .def_readonly("spares_source_allies", &ActiveTerrainEffect::spares_source_allies)
        .def_readonly("ward_creature_mask", &ActiveTerrainEffect::ward_creature_mask,
             "Magic Circle / Hallow: OR of warded creature-type bits (0 = not a movement ward).")
        .def_readonly("ward_traps",        &ActiveTerrainEffect::ward_traps,
             "Movement ward direction: False keeps warded types out, True traps them inside.")
        .def_readonly("ward_all_living",   &ActiveTerrainEffect::ward_all_living,
             "Antilife Shell: True if this ward blocks any non-Undead mover (by 'alive?').")
        .def_readonly("sets_wall",         &ActiveTerrainEffect::sets_wall,
             "Wall of Stone: True if this effect turns its cells into solid Wall terrain.");

    // ── ActiveLightEffect struct ────────────────────────────────────────────
    py::class_<ActiveLightEffect>(m, "ActiveLightEffect")
        .def_readonly("id",                &ActiveLightEffect::id)
        .def_readonly("name",              &ActiveLightEffect::name)
        .def_readonly("cell_indices",      &ActiveLightEffect::cell_indices)
        .def_readonly("light_level",       &ActiveLightEffect::light_level)
        .def_readonly("turns_remaining",   &ActiveLightEffect::turns_remaining)
        .def_readonly("source_agent_idx",  &ActiveLightEffect::source_agent_idx)
        .def_readonly("see_through_agent_idx", &ActiveLightEffect::see_through_agent_idx)
        .def_readonly("anchor_agent_idx",  &ActiveLightEffect::anchor_agent_idx)
        .def_readonly("anchor_radius_ft",  &ActiveLightEffect::anchor_radius_ft);

}
