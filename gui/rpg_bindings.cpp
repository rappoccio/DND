// ─────────────────────────────────────────────────────────────────────────────
//  rpg_bindings.cpp  –  pybind11 module: exposes C++ RPG types to Python
//
//  Import from Python:
//      import rpg_battle_map as rpg
//
//      bm = rpg.BattleMap("map.png")
//      bm.analyze_grid()
//      bm.detect_walls()
//
//      for w in bm.walls:
//          print(w.a.col, w.a.row, "->", w.b.col, w.b.row)
//
//      cfg = rpg.AgentConfig()
//      cfg.name = "Goblin"; cfg.sprite_path = "goblin.png"
//      cfg.size = 1; cfg.start_col = 2; cfg.start_row = 3
//      bm.add_agent_config(cfg)
//      bm.apply_agent_configs()
// ─────────────────────────────────────────────────────────────────────────────

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>        // std::vector, std::unordered_set → Python list/set
#include <pybind11/operators.h>

#include "battle_map.hpp"
#include "combat.hpp"
#include "map_configs.hpp"
#include "character_class.hpp"
#include "item.hpp"

namespace py = pybind11;
using namespace rpg;

// Helper: convert CellSet → Python list (pybind11 can't auto-convert custom hash sets)
static std::vector<Cell> cellSetToVec(const CellSet& s) {
    return {s.begin(), s.end()};
}

// Python trampoline for CombatDecider interface
struct PyCombatDecider : public CombatDecider {
    using CombatDecider::CombatDecider;
    std::vector<int> chooseBrutalStrike(const BrutalStrikeCtx& ctx) override {
        PYBIND11_OVERRIDE(std::vector<int>, CombatDecider, chooseBrutalStrike, ctx);
    }
    bool chooseReckless(const RecklessCtx& ctx) override {
        PYBIND11_OVERRIDE(bool, CombatDecider, chooseReckless, ctx);
    }
    int chooseOAResponse(const OACtx& ctx) override {
        PYBIND11_OVERRIDE(int, CombatDecider, chooseOAResponse, ctx);
    }
};

PYBIND11_MODULE(rpg_battle_map, m)
{
    m.doc() = "RPG Battle Map – C++ analysis core (grid detection, wall detection, agents)";

    // ── Cell ────────────────────────────────────────────────────────────────
    py::class_<Cell>(m, "Cell")
        .def(py::init<>())
        .def(py::init<int, int>(), py::arg("col"), py::arg("row"))
        .def_readwrite("col", &Cell::col)
        .def_readwrite("row", &Cell::row)
        .def("__eq__",   &Cell::operator==)
        .def("__repr__", [](const Cell& c){
            return "<Cell col=" + std::to_string(c.col)
                 + " row=" + std::to_string(c.row) + ">"; });

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
        // Skill proficiency flags
        .def_readwrite("stealth_prof",    &Agent::Stats::stealth_prof)
        .def_readwrite("perception_prof", &Agent::Stats::perception_prof)
        // Skill bonus methods
        .def("stealth_bonus",       &Agent::Stats::stealthBonus)
        .def("passive_perception",  &Agent::Stats::passivePerception)
        // Class-feature capability flags
        .def_readwrite("num_attacks",          &Agent::Stats::num_attacks)
        .def_readwrite("bonus_attacks_remaining", &Agent::Stats::bonus_attacks_remaining)
        .def_readwrite("bonus_actions_max",       &Agent::Stats::bonus_actions_max)
        .def_readwrite("bonus_actions_remaining", &Agent::Stats::bonus_actions_remaining)
        .def_readwrite("has_cunning_action",   &Agent::Stats::has_cunning_action)
        .def_readwrite("has_offhand_attack",   &Agent::Stats::has_offhand_attack)
        .def_readwrite("can_cast_spell",       &Agent::Stats::can_cast_spell)
        .def_readwrite("spellcasting_ability", &Agent::Stats::spellcasting_ability)
        // Initiative
        .def_readwrite("initiative_prof", &Agent::Stats::initiative_prof)
        .def_property_readonly("initiative_modifier", &Agent::Stats::initiativeModifier)
        // Character Class & Spell Slots
        .def_readwrite("character_class",       &Agent::Stats::character_class)
        .def_readwrite("char_level",            &Agent::Stats::char_level)
        .def_readwrite("spell_slots_max",       &Agent::Stats::spell_slots_max)
        .def_readwrite("spell_slots_remaining", &Agent::Stats::spell_slots_remaining)
        .def_readwrite("darkvision_range",     &Agent::Stats::darkvision_range,
             "Darkvision range in feet (0 = no darkvision). See normally in Darkness within range.")
        .def_readwrite("truesight_range",      &Agent::Stats::truesight_range,
             "Truesight range in feet (0 = no truesight). See normally in all light including magical darkness.")
        .def_readwrite("devilssight_range",    &Agent::Stats::devilssight_range,
             "Devil's Sight range in feet (0 = no devil's sight). See in Darkness and MagicalDarkness within range.")
        .def_readwrite("is_npc", &Agent::Stats::is_npc,
             "True if this agent uses N/day spell system (NPC); false if using spell slots (player).")
        .def_readwrite("leveled_spell_cast_this_turn", &Agent::Stats::leveled_spell_cast_this_turn,
             "D&D 5e rule: only one leveled spell (level >= 1) per turn. Reset at turn start.")
        .def_readwrite("temp_hp", &Agent::Stats::temp_hp,
             "Temporary hit points (absorbs damage before hp_cur).")
        .def_readwrite("magic_damage_multipliers", &Agent::Stats::magic_damage_multipliers,
             "Per-type magic damage multipliers: 0.0=immune, 0.5=resist, 1.0=normal, 2.0=vulnerable.")
        .def_readwrite("physical_damage_multipliers", &Agent::Stats::physical_damage_multipliers,
             "Per-type physical damage multipliers: 0.0=immune, 0.5=resist, 1.0=normal, 2.0=vulnerable.")
        .def("set_class_level", &Agent::Stats::set_class_level,
             py::arg("cls"), py::arg("level"),
             "Set the character class and level. Automatically computes spell_slots_max and updates can_cast_spell.")
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
        .def_readwrite("brutal_strike_damage_dice", &Agent::Stats::brutal_strike_damage_dice,
             "Brutal Strike damage dice count: 1 (L9-16) or 2 (L17+) for 1d10 or 2d10")
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
        .def_readwrite("innate_sorcery_turns", &Agent::Stats::innate_sorcery_turns,
             "Sorcerer Innate Sorcery remaining duration in rounds (>0 = active: +1 spell DC, advantage on spell attacks)")
        .def_readwrite("fighter_subclass", &Agent::Stats::fighter_subclass,
             "Fighter subclass (only valid when character_class == Fighter)")
        .def_readwrite("druid_circle", &Agent::Stats::druid_circle,
             "Druid circle choice (only valid when character_class == Druid)")
        .def_readwrite("monk_subclass", &Agent::Stats::monk_subclass,
             "Monk subclass (only valid when character_class == Monk)")
        .def_readwrite("paladin_oath", &Agent::Stats::paladin_oath,
             "Paladin oath choice (only valid when character_class == Paladin)")
        .def_readwrite("wizard_subclass", &Agent::Stats::wizard_subclass,
             "Wizard subclass (only valid when character_class == Wizard)")
        .def_readwrite("sorcerer_subclass", &Agent::Stats::sorcerer_subclass,
             "Sorcerer subclass (only valid when character_class == Sorcerer)")
        .def_readwrite("metamagic_options", &Agent::Stats::metamagic_options,
             "Sorcerer Metamagic options chosen (2 @ L2, 4 @ L10, 6 @ L17)")
        .def_readwrite("warlock_subclass", &Agent::Stats::warlock_subclass,
             "Warlock patron subclass (only valid when character_class == Warlock)")
        .def_readwrite("rogue_subclass", &Agent::Stats::rogue_subclass,
             "Rogue subclass (only valid when character_class == Rogue)")
        .def_readwrite("cleric_subclass", &Agent::Stats::cleric_subclass,
             "Cleric divine domain (only valid when character_class == Cleric)")
        .def_readwrite("blessed_strike", &Agent::Stats::blessed_strike,
             "Cleric L7 Blessed Strikes choice: DivineStrike or PotentSpellcasting.")
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
        .def_readwrite("weapon_mastery", &Agent::Stats::weapon_mastery,
             "Number of Weapon Mastery properties known (>0 = the feature is active).")
        .def_readwrite("eldritch_invocations", &Agent::Stats::eldritch_invocations,
             "Warlock eldritch invocations (list of invocation codes)")
        .def("has_invocation", &Agent::Stats::hasInvocation,
             "Check if warlock has a specific invocation code")
        .def_readwrite("fiendish_resilience_type", &Agent::Stats::fiendish_resilience_type,
             "Fiend Warlock L10: chosen magic damage type for resistance (0-9, ≠3 Force; -1 = none)")
        .def_readwrite("portent_dice", &Agent::Stats::portent_dice,
             "Diviner Wizard: deque of d20 portent rolls (regenerated on long rest, used with use_portent_die)")
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
        .def_readwrite("hidden",        &Agent::Conditions::hidden)
        .def_readwrite("invisible",     &Agent::Conditions::invisible)
        .def_readwrite("incapacitated", &Agent::Conditions::incapacitated)
        .def_readwrite("paralyzed",     &Agent::Conditions::paralyzed)
        .def_readwrite("blinded",       &Agent::Conditions::blinded)
        .def_readwrite("deafened",      &Agent::Conditions::deafened)
        .def_readwrite("stunned",       &Agent::Conditions::stunned)
        .def_readwrite("charmed",       &Agent::Conditions::charmed)
        .def_readwrite("frightened",    &Agent::Conditions::frightened)
        .def_readwrite("slipped_this_turn", &Agent::Conditions::slipped_this_turn)
        .def_readwrite("restrained",    &Agent::Conditions::restrained)
        .def_readwrite("poisoned",      &Agent::Conditions::poisoned)
        .def_readwrite("petrified",     &Agent::Conditions::petrified)
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
        .def_readwrite("reckless_attack",   &Agent::Conditions::reckless_attack)
        .def_readwrite("berserker_frenzy_used", &Agent::Conditions::berserker_frenzy_used)
        .def_readwrite("zealot_divine_fury_used", &Agent::Conditions::zealot_divine_fury_used)
        .def_readwrite("radiant_soul_used", &Agent::Conditions::radiant_soul_used)
        .def_readwrite("sneak_attack_used", &Agent::Conditions::sneak_attack_used)
        .def_readwrite("cunning_strike_available", &Agent::Conditions::cunning_strike_available)
        .def_readwrite("steady_aim", &Agent::Conditions::steady_aim)
        .def_readwrite("stunning_strike_available", &Agent::Conditions::stunning_strike_available)
        .def_readwrite("stunning_strike_used", &Agent::Conditions::stunning_strike_used)
        .def_readwrite("open_hand_rider_available", &Agent::Conditions::open_hand_rider_available)
        .def_readwrite("open_hand_rider_used", &Agent::Conditions::open_hand_rider_used)
        .def_readwrite("fanatical_focus_used", &Agent::Conditions::fanatical_focus_used)
        .def_readwrite("brutal_strike_available", &Agent::Conditions::brutal_strike_available)
        .def_readwrite("divine_strike_available", &Agent::Conditions::divine_strike_available)
        .def_readwrite("divine_strike_used", &Agent::Conditions::divine_strike_used)
        .def_readwrite("psionic_strike_available", &Agent::Conditions::psionic_strike_available)
        .def_readwrite("psionic_strike_used", &Agent::Conditions::psionic_strike_used)
        .def_readwrite("divine_smite_available", &Agent::Conditions::divine_smite_available)
        .def_readwrite("divine_smite_used", &Agent::Conditions::divine_smite_used)
        .def_readwrite("guided_strike_available", &Agent::Conditions::guided_strike_available)
        .def_readwrite("maneuver_available", &Agent::Conditions::maneuver_available)
        .def_readwrite("maneuver_precision_available", &Agent::Conditions::maneuver_precision_available)
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
        .def_readwrite("save_ability",       &AttackCondition::save_ability)
        .def_readwrite("save_dc_ability",    &AttackCondition::save_dc_ability)
        .def_readwrite("requires_save",      &AttackCondition::requires_save,
             "If true, target gets a save to negate the condition; if false, condition applies automatically.")
        .def_readwrite("on_damage",          &AttackCondition::on_damage,
             "What happens to this condition when the affected creature takes damage:\n"
             "OnDamage.None (default), OnDamage.End (ends immediately), or\n"
             "OnDamage.RepeatSave (repeat the save at Advantage; success ends it).");

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
        .def_readwrite("proficient",       &Weapon::proficient)
        .def_readwrite("off_hand",         &Weapon::off_hand)
        .def_readwrite("two_handed",       &Weapon::two_handed)
        .def_readwrite("mastery",          &Weapon::mastery)
        .def_readwrite("ac_bonus",         &Weapon::ac_bonus)
        .def_readwrite("physical_damage_types", &Weapon::physicalDamageRolls)
        .def_readwrite("magic_damage_types",    &Weapon::magicDamageRolls)
        .def_readwrite("damage_dice",      &Weapon::damage_dice)
        .def_readwrite("damage_dice_count",&Weapon::damage_dice_count)
        .def_readwrite("damage_modifier",  &Weapon::damage_modifier)
        .def_readwrite("attack_bonus",     &Weapon::attack_bonus)
        .def_readwrite("range_short_feet", &Weapon::range_short_feet)
        .def_readwrite("range_long_feet",  &Weapon::range_long_feet)
        .def_readwrite("bonus_hit",        &Weapon::bonus_hit)
        .def_readwrite("bonus_damage",     &Weapon::bonus_damage)
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

    py::enum_<Spell::SpellType_t>(m, "SpellType")
        .value("Harm", Spell::Harm)
        .value("Heal", Spell::Heal)
        .value("Transport", Spell::Transport)
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
        .def_readwrite("requires_concentration", &Spell::requires_concentration,
             "If true, caster must maintain concentration; breaks on damage (CON save).")
        .def_readwrite("moves_with_caster", &Spell::moves_with_caster,
             "Sphere only: the area's center follows the caster (D&D 2024 'Emanation').\n"
             "The persistent effect re-centers on the caster each turn and whenever the caster moves.")
        .def_readwrite("requires_los", &Spell::requires_los,
             "If true, spell requires line of sight to the target or area origin.")
        .def_readwrite("check_los_on_center", &Spell::check_los_on_center,
             "If true, only the spell center needs line of sight (not all affected cells). User configurable.")
        .def_readwrite("requires_sight", &Spell::requires_sight,
             "If true, spell requires target(s) to be visible (not blocked by obscuration).\n"
             "Spells like Hypnotic Pattern, Command, etc. require this.\n"
             "The target is blocked if in MagicalDarkness without Devil's Sight or Heavily Obscured (unless exception applies).")
        .def_readwrite("level", &Spell::level,
             "Spell level: 0 = cantrip (unlimited casts); 1-9 = requires a spell slot of that level.")
        .def_readwrite("upcast_dice_bonus", &Spell::upcast_dice_bonus,
             "Extra dice added to damage when cast at a higher slot level. Calculated as upcast_dice_bonus * (slot_level - spell_level).")
        .def_readwrite("uses_max", &Spell::uses_max,
             "Maximum uses per day for NPCs. 0 = unlimited (use slot system); > 0 = N/day uses.")
        .def_readwrite("uses_remaining", &Spell::uses_remaining,
             "Current remaining uses for the day (for N/day spells).")
        .def_readwrite("resource_name", &Spell::resource_name,
             "Class-feature casting: if non-empty, casting spends this named resource\n"
             "(e.g. 'Channel Divinity') instead of a spell slot. Used by classfeatures.json.")
        .def_readwrite("resource_cost", &Spell::resource_cost,
             "Amount of resource_name spent per cast (default 1).")
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
        .def_readwrite("metamagic",      &SpellAction::metamagic,
             "Sorcerer Metamagic applied to this cast (MetamagicOption; NONE = none).\n"
             "SP cost is deducted in execute_spell. Applied: Careful, Distant, Extended,\n"
             "Heightened, Quickened, Seeking, Transmuted, Twinned. Deferred: Empowered.")
        .def_readwrite("careful_targets", &SpellAction::careful_targets,
             "Careful Spell: allies excluded from this spell's area (up to the caster's CHA mod).")
        .def_readwrite("transmuted_damage_type", &SpellAction::transmuted_damage_type,
             "Transmuted Spell: MagicDamage value to convert the spell's elemental damage into (-1 = none).")
        .def("__repr__", [](const SpellAction& a){
            return "<SpellAction caster=" + std::to_string(a.caster_idx)
                 + " spell=" + std::to_string(a.spell_idx)
                 + " targets=" + std::to_string(a.target_indices.size()) + ">"; });

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
        .def_readonly("removed_condition_ids",     &DropConcentrationResult::removed_condition_ids);

    // ── TurnUndeadResult ─────────────────────────────────────────────────────
    py::class_<TurnUndeadResult>(m, "TurnUndeadResult")
        .def_readonly("valid",       &TurnUndeadResult::valid)
        .def_readonly("save_dc",     &TurnUndeadResult::save_dc)
        .def_readonly("sear_damage", &TurnUndeadResult::sear_damage)
        .def_readonly("turned",      &TurnUndeadResult::turned)
        .def_readonly("resisted",    &TurnUndeadResult::resisted);

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
        .def_readonly("push_distance",      &ManeuverResult::push_distance);

    // ── OpenHandRiderResult ───────────────────────────────────────────────────
    py::class_<OpenHandRiderResult>(m, "OpenHandRiderResult")
        .def_readonly("valid",                   &OpenHandRiderResult::valid)
        .def_readonly("option",                  &OpenHandRiderResult::option)
        .def_readonly("knockdown_save_dc",       &OpenHandRiderResult::knockdown_save_dc)
        .def_readonly("knockdown_save_roll",     &OpenHandRiderResult::knockdown_save_roll)
        .def_readonly("target_knocked_prone",    &OpenHandRiderResult::target_knocked_prone)
        .def_readonly("push_distance",           &OpenHandRiderResult::push_distance)
        .def_readonly("reaction_denied",         &OpenHandRiderResult::reaction_denied);

    // ── FlurryResult (Monk Flurry of Blows) ──────────────────────────────────
    py::class_<FlurryResult>(m, "FlurryResult")
        .def_readonly("attack1",  &FlurryResult::attack1)
        .def_readonly("attack2",  &FlurryResult::attack2)
        .def_readonly("rider1",   &FlurryResult::rider1)
        .def_readonly("rider2",   &FlurryResult::rider2);

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

    py::class_<OACtx>(m, "OACtx")
        .def_readonly("attacker_idx", &OACtx::attacker_idx)
        .def_readonly("target_idx",   &OACtx::target_idx);

    py::class_<CombatDecider, PyCombatDecider>(m, "CombatDecider")
        .def(py::init<>())
        .def("choose_brutal_strike", &CombatDecider::chooseBrutalStrike)
        .def("choose_reckless",      &CombatDecider::chooseReckless)
        .def("choose_oa_response",   &CombatDecider::chooseOAResponse);

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
        .def_readwrite("condition_id",    &ActiveAgentCondition::condition_id)
        .def("__repr__", [](const ActiveAgentCondition& c){
            return "<ActiveAgentCondition '" + c.condition_name
                 + "' on agent[" + std::to_string(c.agent_idx)
                 + "] turns=" + std::to_string(c.turns_remaining) + ">"; });

    // ── AttackResult ─────────────────────────────────────────────────────────
    py::class_<AttackResult>(m, "AttackResult")
        .def(py::init<>())
        .def_readonly("valid",        &AttackResult::valid)
        .def_readonly("d20",          &AttackResult::d20)
        .def_readonly("attack_mod",   &AttackResult::attack_mod)
        .def_readonly("total_roll",   &AttackResult::total_roll)
        .def_readonly("target_ac",    &AttackResult::target_ac)
        .def_readonly("critical",     &AttackResult::critical)
        .def_readonly("fumble",       &AttackResult::fumble)
        .def_readonly("disadvantage", &AttackResult::disadvantage)
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
        .def_readonly("agent_idx", &InitiativeEntry::agent_idx)
        .def_readonly("d20",       &InitiativeEntry::d20)
        .def_readonly("modifier",  &InitiativeEntry::modifier)
        .def_readonly("total",     &InitiativeEntry::total)
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
        .def("__repr__", [](const Attack& a){
            std::string s = "<Attack atk=" + std::to_string(a.attacker_idx)
                 + " tgt=" + std::to_string(a.target_idx)
                 + " wpn=" + std::to_string(a.weapon_idx);
            if (a.is_offhand) s += " offhand";
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

    // ── CombatEngine ──────────────────────────────────────────────────────────
    py::class_<CombatEngine>(m, "CombatEngine")
        .def(py::init<uint32_t>(), py::arg("seed") = 0,
             "Construct with a fixed seed (0 = random).")

        // Static / deterministic helpers
        .def_static("attack_modifier",
                    &CombatEngine::attackModifier,
                    py::arg("weapon"), py::arg("stats"),
                    "Total attack-roll modifier for weapon + attacker stats.")
        .def_static("damage_ability_mod",
                    &CombatEngine::damageAbilityMod,
                    py::arg("weapon"), py::arg("stats"),
                    "Ability modifier added to damage rolls.")
        .def_static("can_attack",
                    &CombatEngine::canAttack,
                    py::arg("weapon"), py::arg("battle_map"),
                    py::arg("atk_origin"), py::arg("atk_size"),
                    py::arg("tgt_origin"), py::arg("tgt_size"),
                    "True iff weapon can reach target with LoS.")
        .def_static("has_disadvantage",
                    &CombatEngine::hasDisadvantage,
                    py::arg("weapon"), py::arg("battle_map"),
                    py::arg("atk_origin"), py::arg("atk_size"),
                    py::arg("tgt_origin"), py::arg("tgt_size"),
                    "True iff the attack should be rolled at disadvantage.")
        .def_static("damage_agent",
                    &CombatEngine::damageAgent,
                    py::arg("battle_map"), py::arg("idx"), py::arg("amount"),
                    "Reduce hp_cur of agent[idx] by amount (clamped to 0). "
                    "Returns new hp_cur.")
        .def_static("heal_agent",
                    &CombatEngine::healAgent,
                    py::arg("battle_map"), py::arg("idx"), py::arg("amount"),
                    "Raise hp_cur of agent[idx] by amount (clamped to hp_max). "
                    "Returns new hp_cur.")
        .def_static("lay_on_hands",
                    &CombatEngine::layOnHands,
                    py::arg("battle_map"), py::arg("caster_idx"), py::arg("target_idx"), py::arg("amount"),
                    "Paladin Lay on Hands: spend from caster's pool to heal target. "
                    "Clamps spend to min(pool_remaining, target_hp_deficit). "
                    "Returns actual HP healed (0 if nothing to heal, -1 if invalid).")
        .def("activate_sacred_weapon",
             &CombatEngine::activateSacredWeapon,
             py::arg("battle_map"), py::arg("idx"),
             "Paladin Oath of Devotion — Sacred Weapon: spend 1 Channel Oath use to add\n"
             "+CHA mod (min +1) to weapon attack rolls for 1 minute (10 rounds). Requires\n"
             "Oath of Devotion and an available Channel Oath use. Returns the bonus granted,\n"
             "or -1 if it could not be activated.")
        .def("activate_innate_sorcery",
             &CombatEngine::activateInnateSorcery,
             py::arg("battle_map"), py::arg("idx"),
             "Sorcerer Innate Sorcery (L1): Bonus Action, spend 1 use to gain +1 spell save\n"
             "DC and advantage on spell attack rolls for 1 minute (10 rounds). Returns True if\n"
             "activated, False otherwise (not a Sorcerer, or no uses left).")
        .def("convert_slot_to_sorcery_points",
             &CombatEngine::convertSlotToSorceryPoints,
             py::arg("battle_map"), py::arg("idx"), py::arg("slot_level"),
             "Font of Magic (L2): convert a remaining spell slot (level 1-9) into that many\n"
             "Sorcery Points (capped at max). Returns the new SP total, or -1 if it could not\n"
             "be done (not a Sorcerer, or no slot of that level).")
        .def("create_spell_slot",
             &CombatEngine::createSpellSlot,
             py::arg("battle_map"), py::arg("idx"), py::arg("slot_level"),
             "Font of Magic (L2): spend Sorcery Points to create a temporary spell slot of\n"
             "level 1-5 (cost 2/3/5/6/7). The slot is cleared at the next long rest. Returns\n"
             "remaining SP, or -1 if it could not be done (not a Sorcerer, or not enough SP).")
        .def_static("metamagic_sp_cost",
                    &CombatEngine::metamagicSpCost,
                    py::arg("option"),
                    "Sorcery Point cost for a Metamagic option (2024 PHB).")
        .def_static("get_rage_damage_bonus",
                    &CombatEngine::getRageDamageBonus,
                    py::arg("level"),
                    "Get Barbarian Rage damage bonus for a given level.")

        // Dice rollers
        .def("roll",              &CombatEngine::roll,            py::arg("sides"), py::arg("modifier") = 0)
        .def("roll_advantage",    &CombatEngine::rollAdvantage,   py::arg("sides"), py::arg("modifier") = 0)
        .def("roll_disadvantage", &CombatEngine::rollDisadvantage,py::arg("sides"), py::arg("modifier") = 0)

        // Core mechanics
        .def("roll_to_hit",
             &CombatEngine::rollToHit,
             py::arg("weapon"), py::arg("attacker_stats"),
             py::arg("target_ac"), py::arg("advantage") = false,
             py::arg("disadvantage") = false, py::arg("exhaustion_level") = 0,
             "Roll d20 + modifier vs AC.  Does not apply damage.")
        .def("resolve_attack",
             &CombatEngine::resolveAttack,
             py::arg("weapon"), py::arg("attacker"), py::arg("target"),
             py::arg("advantage") = false, py::arg("disadvantage") = false,
             py::arg("suppress_positive_mod") = false,
             "Roll to hit, roll damage, and apply damage to target. "
             "Applies Barbarian Rage bonus, temporary HP absorption, etc. "
             "suppress_positive_mod drops a positive ability modifier from damage (Cleave).")

        // High-level
        // Initiative
        .def("roll_initiative",
             &CombatEngine::rollInitiative,
             py::arg("battle_map"),
             "Roll d20 + DEX mod [+ prof_bonus if initiative_prof] for every\n"
             "living agent.  Returns a list of InitiativeEntry sorted highest\n"
             "first.  Call once at combat start; reuse the order each round.")

        .def("execute_action",
             &CombatEngine::executeAction,
             py::arg("battle_map"), py::arg("action"),
             "Validate + execute an Attack; writes HP change to BattleMap.")
        .def("threatening_agents",
             &CombatEngine::threateningAgents,
             py::arg("battle_map"), py::arg("target_idx"), py::arg("reach_cells") = 1,
             "Indices of non-incapacitated agents within reach_cells of target's footprint.")
        .def("available_attacks",
             &CombatEngine::availableAttacks,
             py::arg("battle_map"), py::arg("attacker_idx"),
             "Return all legal (weapon, target) pairs for the attacker.")
        .def("get_battle_observation",
             &CombatEngine::getBattleObservation,
             py::arg("battle_map"), py::arg("attacker_idx"),
             py::arg("target_indices"), py::arg("max_targets") = 8,
             "Fixed-length float vector for NN input (12 + max_targets×14 floats).")

        // Per-agent turn counts
        .def("get_agent_turns",
             &CombatEngine::getAgentTurns,
             py::arg("idx"),
             "Number of turns agent[idx] takes per round (default 1).")
        .def("set_agent_turns",
             &CombatEngine::setAgentTurns,
             py::arg("idx"), py::arg("turns"),
             "Override turn count for agent[idx]. set_agent_turns(idx, 1) "
             "removes the override and restores the default.")
        .def("clear_agent_turns",
             &CombatEngine::clearAgentTurns,
             "Reset every agent to the default of 1 turn per round.")

        // ── Turn lifecycle ────────────────────────────────────────────────
        .def("begin_turn",
             &CombatEngine::beginTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Begin agent's turn: seed movement budgets, reset conditions,\n"
             "reset leveled spell flag, and apply persistent spell effects.")
        .def("end_turn",
             &CombatEngine::endTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "End agent's turn: apply end-of-turn spell effects.")

        // ── Armor & AC calculations ──────────────────────────────────────
        .def("calculate_ac",
             &CombatEngine::calculateAC,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Calculate total AC for agent (base AC + armor + DEX + shield + temp mods).")
        .def("apply_armor_multipliers",
             &CombatEngine::applyArmorMultipliers,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Merge equipped armor damage multipliers into agent stats.\n"
             "Call once at combat start and when armor changes mid-combat.")

        // ── Movement budget ───────────────────────────────────────────────
        .def("get_walk_remaining",
             &CombatEngine::getWalkRemaining,
             py::arg("agent_idx"),
             "Remaining walk movement in feet for agent_idx this turn.")
        .def("get_fly_remaining",
             &CombatEngine::getFlyRemaining,
             py::arg("agent_idx"),
             "Remaining fly movement in feet for agent_idx this turn.")
        .def("get_swim_remaining",
             &CombatEngine::getSwimRemaining,
             py::arg("agent_idx"),
             "Remaining swim movement in feet for agent_idx this turn.")
        .def("get_burrow_remaining",
             &CombatEngine::getBurrowRemaining,
             py::arg("agent_idx"),
             "Remaining burrow movement in feet for agent_idx this turn.")
        .def("spend_walk",
             &CombatEngine::spendWalk,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from walk budget (clamped to 0). Returns amount spent.")
        .def("spend_fly",
             &CombatEngine::spendFly,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from fly budget (clamped to 0). Returns amount spent.")
        .def("spend_swim",
             &CombatEngine::spendSwim,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from swim budget (clamped to 0). Returns amount spent.")
        .def("spend_burrow",
             &CombatEngine::spendBurrow,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from burrow budget (clamped to 0). Returns amount spent.")
        .def("clear_movement",
             &CombatEngine::clearMovement,
             "Clear all movement budgets (call at end of combat).")

        // ── Agent movement (with spell effect checking) ────────────────────
        .def("can_agent_move",
             &CombatEngine::canAgentMove,
             py::arg("battle_map"), py::arg("idx"),
             "Check if agent can move (has Speed > 0, not grappled, etc.).\n"
             "Returns false if any condition reduces speed to 0.")
        .def("move_agent",
             &CombatEngine::moveAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("new_origin"), py::arg("movement_type"),
             "Move agent to a new origin. Returns false if blocked or budget insufficient.\n"
             "On successful move, checks for spell effects at destination and applies them.")
        .def("jump_agent",
             &CombatEngine::jumpAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("new_origin"), py::arg("is_running"),
             "Jump agent to a location (ignores walls, deducts from walk budget).\n"
             "Returns false if distance exceeds jump range.\n"
             "On successful move, checks for spell effects at destination and applies them.")
        .def("teleport_agent",
             &CombatEngine::teleportAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_col"), py::arg("target_row"),
             "Teleport agent to a new location (col, row). Only checks that destination is not blocked by terrain.\n"
             "Returns false if destination is blocked, out of bounds, or agent index invalid.\n"
             "On successful teleport, checks for spell effects at destination and applies them.")
        .def("is_valid_teleport_destination",
             &CombatEngine::isValidTeleportDestination,
             py::arg("battle_map"), py::arg("col"), py::arg("row"),
             "Check if a destination cell is valid for teleportation (in bounds, not blocked by terrain).\n"
             "Returns true if valid, false if out of bounds or blocked.")
        .def("place_teleported_agents",
             &CombatEngine::placeTeleportedAgents,
             py::arg("battle_map"), py::arg("agent_indices"), py::arg("dest_col"), py::arg("dest_row"),
             "Teleport multiple agents and place them in a circular pattern around the destination.\n"
             "Places the first agent at dest_col, dest_row; subsequent agents in expanding circles.\n"
             "Returns the number of agents successfully teleported.")

        .def("set_logger",
             &CombatEngine::setLogger,
             py::arg("logger"),
             py::keep_alive<1, 2>(),
             "Attach a MessageLogger; flush() it after each action to read messages.")

        .def("set_decider",
             &CombatEngine::setDecider,
             py::arg("decider"),
             py::keep_alive<1, 2>(),
             "Set the CombatDecider (GUI=Python subclass, RL/headless=nullptr for defaults).")

        .def("set_safe_targets",
             &CombatEngine::setSafeTargets,
             py::arg("caster_idx"), py::arg("targets"),
             "Set the agent indices fully excluded from caster_idx's AoE spells (Evoker safe targets).")
        .def("get_safe_targets",
             &CombatEngine::getSafeTargets,
             py::arg("caster_idx"),
             "Get the agent indices excluded from caster_idx's AoE spells.")

        // Round execution
        .def("run_round",
             &CombatEngine::runRound,
             py::arg("battle_map"), py::arg("turns"),
             "Execute one combat round from an ordered list of TurnActions.\n"
             "Each entry triggers action(), bonusAction(), walk(), fly() on\n"
             "the acting agent, resolves any weapon Attacks, and calls\n"
             "reaction() on any targeted agent.\n"
             "Returns a list of AttackResult (one per resolved Attack).")

        // Spell mechanics
        .def("execute_spell",
             &CombatEngine::executeSpell,
             py::arg("battle_map"), py::arg("action"),
             "Validate + execute a SpellAction; applies damage/healing to targets\n"
             "and writes HP changes back to BattleMap.\n"
             "Registers persistent effects when spell.duration > 1.")
        .def("drop_concentration",
             &CombatEngine::dropConcentration,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Drop concentration for agent: removes terrain, spell effects, conditions. Returns removed IDs.")
        .def("tick_terrain_for_turn",
             &CombatEngine::tickTerrainForTurn,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Tick the agent's terrain at start of turn; clears concentration if a concentration terrain expired.\n"
             "Returns TerrainTickResult(expired_terrain_ids, concentration).")
        .def("clear_all_concentration",
             &CombatEngine::clearAllConcentration,
             py::arg("battle_map"),
             "Drop concentration for every concentrating agent (e.g. on End Combat).")
        .def("use_magical_cunning",
             &CombatEngine::useMagicalCunning,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Warlock Magical Cunning: recover expended Pact Magic slots (ceil(max/2), or all at L20).\n"
             "Returns True if used; False if unavailable or nothing to recover.")
        .def("use_healing_light",
             &CombatEngine::useHealingLight,
             py::arg("battle_map"), py::arg("healer_idx"), py::arg("target_idx"), py::arg("num_dice"),
             "Celestial Warlock Healing Light (L3+): spend d6 healing dice.\n"
             "Validates healer is Celestial L3+, clamps num_dice to min(num_dice, current, chaMod).\n"
             "Spends dice from resource, rolls that many d6, heals target.\n"
             "Returns HP healed (0 if invalid).")
        .def("spend_resource",
             &CombatEngine::spendResource,
             py::arg("battle_map"), py::arg("idx"), py::arg("name"), py::arg("amount") = 1,
             "Spend a named class resource (e.g. 'War Priest', 'Superiority Dice'); returns True if\n"
             "the agent had >= amount and it was spent. Generic cost helper for extra-attack/maneuver\n"
             "features (the attack itself goes through execute_action).")
        .def("use_turn_undead",
             &CombatEngine::useTurnUndead,
             py::arg("battle_map"), py::arg("caster_idx"),
             "Cleric Turn Undead (Channel Divinity, L2+): each Undead within 30 ft makes a WIS save;\n"
             "failures are Frightened + Incapacitated for 1 minute (ends if the undead takes damage).\n"
             "Sear Undead (L5+) deals WIS-mod d8 Radiant (rolled once) to each failed undead.\n"
             "Spends one Channel Divinity use. Returns a TurnUndeadResult.")
        .def("execute_shove",
             &CombatEngine::executeShove,
             py::arg("battle_map"), py::arg("action"),
             "Execute a shove attempt (bonus action, contested Athletics check).\n"
             "On success: either push 5ft or knock prone based on action.knock_prone.\n"
             "Returns ShoveResult with rolls, success status, and log message.")
        .def("execute_grapple",
             &CombatEngine::executeGrapple,
             py::arg("battle_map"), py::arg("action"),
             "Execute a grapple attempt (contested Athletics vs Athletics/Acrobatics).\n"
             "On success: grapple initiates, escape_dc = 10 + attacker_roll.\n"
             "Returns GrappleResult with rolls, success status, escape_dc, and log message.")
        .def("execute_grapple_escape",
             &CombatEngine::executeGrappleEscape,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Attempt to escape an ongoing grapple (contested STR(Athletics)/DEX(Acrobatics) vs escape_dc).\n"
             "On success: grapple condition is cleared.\n"
             "Returns GrappleEscapeResult with rolls, success status, and log message.")

        // Barbarian Rage lifecycle
        .def("activate_rage",
             &CombatEngine::activateRage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Activate Barbarian Rage: set raging=true, apply 0.5x physical damage multipliers (B/P/S), spend 1 Rage use.")
        .def("extend_rage",
             &CombatEngine::extendRage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Extend active Rage: reset duration_remaining to full duration.")
        .def("end_rage",
             &CombatEngine::endRage,
             py::arg("battle_map"), py::arg("agent_idx"),
             "End Barbarian Rage: set raging=false, restore normal damage multipliers, clear reckless_attack.")
        .def("apply_brutal_strike_effect",
             &CombatEngine::applyBrutalStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("effects"), py::arg("result"),
             "Apply Brutal Strike effects: damage + chosen effects (0=Forceful, 1=Hamstring, 2=Staggering, 3=Sundering).\n"
             "Modifies the AttackResult to include brutal strike damage in damage_breakdown and updates total_damage.")
        .def("apply_cunning_strike_effect",
             &CombatEngine::applyCunningStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("effects"), py::arg("result"),
             "Apply Rogue Sneak Attack + optional Cunning Strike riders after a qualifying hit\n"
             "(conditions.cunning_strike_available). effects: rider codes (0=Poison, 1=Trip, 2=Withdraw,\n"
             "4=KnockOut, 5=Obscure); empty = full Sneak Attack with no rider. Rolls (sneak dice − cost)d6,\n"
             "folds it into the AttackResult and target HP, then applies any rider conditions.")
        .def("apply_divine_strike_effect",
             &CombatEngine::applyDivineStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("radiant"), py::arg("result"),
             "Cleric Blessed Strikes — Divine Strike: after a qualifying weapon hit\n"
             "(conditions.divine_strike_available), add 1d8 (2d8 at L14) Radiant (radiant=True) or\n"
             "Necrotic (False) to the AttackResult and target HP; once per turn.")
        .def("apply_divine_smite_effect",
             &CombatEngine::applyDivineSmiteEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             py::arg("slot_level"), py::arg("result"),
             "Paladin Divine Smite: after a melee/unarmed hit (conditions.divine_smite_available),\n"
             "spend a level-slot_level spell slot as a Bonus Action to add (1+min(slot_level,5))d8\n"
             "Radiant, +1d8 vs Undead/Fiend, to the AttackResult and target HP. Spends the slot +\n"
             "bonus action, sets the leveled-spell + once-per-turn interlocks. Returns Radiant dealt,\n"
             "or -1 if not allowed (no slot/bonus action, already smited, leveled spell already cast).")
        .def("apply_guided_strike_effect",
             &CombatEngine::applyGuidedStrike,
             py::arg("battle_map"), py::arg("action"), py::arg("cleric_idx"), py::arg("result"),
             "War Domain — Guided Strike: a War Cleric L3+ (the attacker, or an ally within 30 ft who\n"
             "also spends a Reaction) expends Channel Divinity to add +10 to a missed attack roll\n"
             "(conditions.guided_strike_available). If it now meets AC, the miss becomes a hit and\n"
             "weapon damage is rolled and applied. Pass the Attack that missed and its AttackResult.")
        .def("apply_push",
             &CombatEngine::applyPush,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "Weapon Mastery — Push: after a qualifying hit (conditions.push_available), shove the\n"
             "target 10 ft straight away from the attacker. Clears the flag; returns feet moved.")
        .def("apply_topple",
             &CombatEngine::applyTopple,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("weapon_idx") = 0,
             "Weapon Mastery — Topple: after a qualifying hit (conditions.topple_available), the target\n"
             "makes a CON save (DC 8 + attack ability mod + prof) or is knocked Prone. Returns a ToppleResult.")
        .def("apply_stunning_strike",
             &CombatEngine::applyStunningStrike,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"),
             "Monk Stunning Strike: after a qualifying unarmed hit (conditions.stunning_strike_available),\n"
             "spend 1 Focus Point and force a CON save (DC 8 + DEX mod + prof) or the target is Stunned.\n"
             "Returns a StunningStrikeResult.")
        .def("apply_psionic_strike_effect",
             &CombatEngine::applyPsionicStrikeEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("result"),
             "Psi Warrior Psionic Strike: after a qualifying hit (conditions.psionic_strike_available),\n"
             "spend one Psionic Energy die and add Force damage (die roll + INT mod) to the AttackResult\n"
             "and the target's HP. Once per turn.")
        .def("apply_protective_field",
             &CombatEngine::applyProtectiveField,
             py::arg("battle_map"), py::arg("defender_idx"), py::arg("damage_taken"),
             "Psi Warrior Protective Field (reaction): spend one Psionic Energy die + the defender's\n"
             "reaction to prevent (die roll + INT mod) damage, capped at damage_taken (modeled as a\n"
             "heal-back). Returns the damage prevented, or -1 if it could not be used.")
        .def("apply_telekinetic_movement",
             &CombatEngine::applyTelekineticMovement,
             py::arg("battle_map"), py::arg("idx"), py::arg("target_idx"),
             "Psi Warrior Telekinetic Movement: spend the once-per-rest use to push a creature up to\n"
             "30 ft straight away from the Psi Warrior. Returns feet moved, or -1 if unavailable.")
        .def("apply_open_hand_rider",
             &CombatEngine::applyOpenHandRider,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("option"),
             "Monk Warrior of the Open Hand: after a qualifying Flurry hit (conditions.open_hand_rider_available),\n"
             "spend 1 Focus Point and apply one of three riders: 0=Knockdown (STR save or Prone),\n"
             "1=Push (5 feet), 2=Deny Reaction. Returns an OpenHandRiderResult.")
        .def("apply_maneuver_effect",
             &CombatEngine::applyManeuverEffect,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("maneuver_type"),
             "Battle Master Maneuver: after a qualifying hit (conditions.maneuver_available),\n"
             "spend 1 Superiority Die and apply one of three riders:\n"
             "0=Trip (STR save or Prone), 1=Menacing (WIS save or Frightened), 2=Pushing (15 ft).\n"
             "Returns a ManeuverResult with save details / push distance.")
        .def("apply_precision_attack_effect",
             &CombatEngine::applyPrecisionAttackEffect,
             py::arg("battle_map"), py::arg("action"), py::arg("result"),
             "Battle Master Precision Attack: after a non-fumble miss (conditions.maneuver_precision_available),\n"
             "spend 1 Superiority Die, add 1d8/d10 to the roll, and recompute the hit.\n"
             "May convert a miss to a hit with full weapon damage. Mutates result in place.")
        .def("execute_flurry_of_blows",
             &CombatEngine::executeFlurryOfBlows,
             py::arg("battle_map"), py::arg("attacker_idx"), py::arg("target_idx"), py::arg("rider_option"),
             "Monk Flurry of Blows: spend 1 Focus Point to make two bonus-action unarmed strikes\n"
             "against the same target, optionally applying an Open Hand rider on each hit.\n"
             "rider_option: -1=None, 0=Knockdown, 1=Push, 2=DenyReaction.\n"
             "Returns a FlurryResult containing both attack results and rider results.")
        .def("consume_bonus_attack",
             &CombatEngine::consumeBonusAttack,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Decrement bonus_attacks_remaining for an agent (Flurry of Blows, Martial Arts, etc).\n"
             "Returns true if more attacks are queued, false if sequence is exhausted.")
        .def("has_bonus_action",
             &CombatEngine::hasBonusAction,
             py::arg("battle_map"), py::arg("agent_idx"),
             "True if the agent still has a bonus action this turn (bonus_actions_remaining > 0).\n"
             "Gate every Bonus Action feature (off-hand attack, Cunning Action, Rage, Healing\n"
             "Word, Divine Smite, etc.) on this before offering it.")
        .def("spend_bonus_action",
             &CombatEngine::spendBonusAction,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Spend one bonus action if available; returns true if spent, false if none remained.")
        .def("reset_bonus_actions",
             &CombatEngine::resetBonusActions,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Refill bonus_actions_remaining = bonus_actions_max (done automatically each turn).")
        .def("can_use_primal_knowledge",
             &CombatEngine::canUsePrimalKnowledge,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("skill_name"),
             "Check if Barbarian can use STR for a skill (Acrobatics/Stealth) while Raging.\n"
             "Returns true if: L3+ Barbarian, Raging, and skill is Acrobatics or Stealth.")

        // ── Diviner Wizard Portent Dice ──────────────────────────────────────
        .def("use_portent_die",
             &CombatEngine::usePortentDie,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("die_index"), py::arg("current_round"),
             "Use a Portent Die on the next roll (for Diviner Wizards).\n"
             "Validates agent is Diviner, has dice, not used this round.\n"
             "Sets pending_portent_die for CombatEngine::roll() to return.\n"
             "Decrements Portent Dice resource.\n"
             "die_index: 0-based index into agent's portent_dice deque.\n"
             "current_round: for per-round enforcement.\n"
             "Returns true on success, false on validation failure.")
        .def("regenerate_portent_dice",
             &CombatEngine::regeneratePortentDice,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Regenerate Portent Dice pool after long rest (for Diviner Wizards).\n"
             "Rolls new d20s and populates agent's portent_dice deque.")
        .def("expend_arcane_ward_slot",
             &CombatEngine::expendArcaneWardSlot,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("slot_level"),
             "Expend a spell slot as bonus action to charge Arcane Ward (for Abjurer Wizards L3+).\n"
             "Adds 2 × slot_level HP to the ward (capped at max = 2 × level + INT mod).\n"
             "slot_level: 1-9 (spell slot level to expend).\n"
             "Returns true on success, false if agent is not Abjurer L3+ or has no ward.")
        .def("apply_long_rest",
             &CombatEngine::applyLongRest,
             py::arg("battle_map"),
             "Apply long rest to all agents: restore spell slots, resources,\n"
             "and regenerate Portent Dice for Diviner Wizards.")
        .def("apply_short_rest",
             &CombatEngine::applyShortRest,
             py::arg("battle_map"),
             "Apply short rest to all agents: restore short-rest resources\n"
             "(Warlock Pact Magic slots, Monk Ki, etc.).")

        .def("tick_effects",
             &CombatEngine::tickEffects,
             py::arg("battle_map"),
             "Apply per-turn damage/healing for active persistent effects;\n"
             "decrement turns_remaining and remove expired effects.")
        .def_property_readonly("active_effects",
             [](const CombatEngine& e) { return e.activeEffects(); },
             "List of ActiveEffect objects currently in play.")
        .def("clear_effects",
             &CombatEngine::clearEffects,
             "Remove all persistent spell effects.")
        .def("concentration_save",
             &CombatEngine::concentrationSave,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("damage_taken"),
             "Check if concentrating agent must save (on damage).\n"
             "Rolls CON save (DC = max(10, damage/2)).\n"
             "Clears concentration on failed save.\n"
             "Returns ConcentrationSaveResult with details.")
        .def("available_castable_spells",
             &CombatEngine::availableCastableSpells,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Returns indices of spells agent_idx can cast this turn.\n"
             "For NPCs: spells with uses_remaining > 0 (and leveled spell check).\n"
             "For players: spells with available slots at spell.level or higher (and leveled spell check).\n"
             "Cantrips (level 0) always included.")
        .def("get_num_targets_for_spell",
             &CombatEngine::getNumTargetsForSpell,
             py::arg("spell"), py::arg("slot_level"), py::arg("caster_level") = -1,
             "Calculate the number of targets for a Multiple geometry spell when cast at given slot level.\n"
             "Formula: spell.num_targets + (slot_level - spell.level) * spell.targets_per_upcast_level\n"
             "For Single geometry: returns 1. For AoE: returns 0.\n"
             "caster_level: character level for special cases like Eldritch Blast (default -1 uses slot level formula)")

        // ── Agent stat and equipment management ─────────────────────────────
        .def("add_agent_config",
             &CombatEngine::addAgentConfig,
             py::arg("battle_map"), py::arg("config"),
             "Queue an agent configuration for later application.")
        .def("apply_agent_configs",
             &CombatEngine::applyAgentConfigs,
             py::arg("battle_map"),
             "Apply all queued agent configs, creating agents on the map.")
        .def("get_agent_stats",
             &CombatEngine::getAgentStats,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the Stats for agent[idx].")
        .def("set_agent_stats",
             &CombatEngine::setAgentStats,
             py::arg("battle_map"), py::arg("idx"), py::arg("stats"),
             "Replace the Stats for agent[idx].")
        .def("get_agent_conditions",
             &CombatEngine::getAgentConditions,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the Conditions for agent[idx].")
        .def("set_agent_conditions",
             &CombatEngine::setAgentConditions,
             py::arg("battle_map"), py::arg("idx"), py::arg("conditions"),
             "Replace the Conditions for agent[idx].")
        .def("apply_paralyzed",
             &CombatEngine::applyParalyzed,
             py::arg("battle_map"), py::arg("idx"),
             "Apply paralyzed condition to agent[idx]: sets paralyzed=true, incapacitated=true, and all movement speeds to 0.")
        .def("apply_poisoned",
             &CombatEngine::applyPoisoned,
             py::arg("battle_map"), py::arg("idx"),
             "Apply poisoned condition to agent[idx]: disadvantage on attack rolls and ability checks.")
        .def("apply_deafened",
             &CombatEngine::applyDeafened,
             py::arg("battle_map"), py::arg("idx"),
             "Apply deafened condition to agent[idx]: cannot hear; auto-fail ability checks requiring hearing.")
        .def("apply_petrified",
             &CombatEngine::applyPetrified,
             py::arg("battle_map"), py::arg("idx"),
             "Apply petrified condition to agent[idx]: incapacitated, speed 0, resistance to all damage (0.5x), immune to poisoned.")
        .def("get_agent_weapons",
             &CombatEngine::getAgentWeapons,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the weapon array [main_hand, off_hand, ranged] for agent[idx].")
        .def("set_agent_weapons",
             &CombatEngine::setAgentWeapons,
             py::arg("battle_map"), py::arg("idx"), py::arg("weapons"),
             "Replace the weapon array [main_hand, off_hand, ranged] for agent[idx].")
        .def("get_agent_armor",
             &CombatEngine::getAgentArmor,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the armor array [helmet, chest, leggings, boots, gloves, cloak] for agent[idx].")
        .def("set_agent_armor",
             &CombatEngine::setAgentArmor,
             py::arg("battle_map"), py::arg("idx"), py::arg("armor"),
             "Replace the armor array for agent[idx].")
        .def("can_equip_armor",
             &CombatEngine::canEquipArmor,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("armor"),
             "Check if agent[agent_idx] meets STR requirement for the given armor piece. "
             "Returns true if armor has no STR requirement or agent meets it.")
        .def("get_agent_spells",
             &CombatEngine::getAgentSpells,
             py::arg("battle_map"), py::arg("idx"),
             "Return a copy of the spell list for agent[idx].")
        .def("set_agent_spells",
             &CombatEngine::setAgentSpells,
             py::arg("battle_map"), py::arg("idx"), py::arg("spells"),
             "Replace the spell list for agent[idx].")
        .def("add_spell_to_agent",
             &CombatEngine::addSpellToAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("spell"),
             "Append a spell to agent[idx]'s spell list.")
        .def("remove_spell_from_agent",
             &CombatEngine::removeSpellFromAgent,
             py::arg("battle_map"), py::arg("idx"), py::arg("spell_idx"),
             "Remove spell at spell_idx from agent[idx]'s list.")
        .def("init_npc_spell_groups",
             &CombatEngine::initNpcSpellGroups,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("groups"),
             "Set is_npc=true on agent and initialize uses_max/uses_remaining from spell groups.\n"
             "groups: dict mapping N (uses/day) -> list of spell names in that group.\n"
             "Call once after set_agent_spells().")

        // ── Agent condition management ──────────────────────────────────────
        .def("add_agent_condition",
             &CombatEngine::addAgentCondition,
             py::arg("battle_map"), py::arg("condition"),
             "Add an active agent condition (e.g., from a spell).\n"
             "Returns the condition_id for later removal.")
        .def_property_readonly("active_agent_conditions",
             [](const CombatEngine& e) { return e.activeAgentConditions(); },
             "List of ActiveAgentCondition objects currently applied to agents.")
        .def("tick_agent_conditions",
             &CombatEngine::tickAgentConditions,
             py::arg("battle_map"),
             "Decrement all active agent condition durations by 1 turn.\n"
             "Remove expired conditions and apply their end-of-life effects.\n"
             "Returns list of expired condition IDs.")
        .def("tick_agent_conditions_for_caster",
             &CombatEngine::tickAgentConditionsForCaster,
             py::arg("battle_map"), py::arg("caster_idx"),
             "Decrement condition durations for conditions cast by the given caster.\n"
             "Duration is counted in the caster's turns, not absolute turns.\n"
             "Returns list of expired condition IDs.")
        .def("remove_agent_condition",
             &CombatEngine::removeAgentCondition,
             py::arg("condition_id"),
             "Explicitly remove an active agent condition by its ID.")

        // ── Prone mechanics ──────────────────────────────────────────────────
        .def("apply_prone",
             &CombatEngine::applyProne,
             py::arg("battle_map"), py::arg("idx"),
             "Apply prone condition to agent[idx].")
        .def("standup",
             &CombatEngine::standup,
             py::arg("battle_map"), py::arg("idx"),
             "Remove prone condition from agent[idx] (costs half movement speed).")

        // ── Hide mechanics ───────────────────────────────────────────────────
        .def("check_hide",
             &CombatEngine::checkHide,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("in_combat"),
             "Attempt Hide action: validate out-of-LOS, roll Stealth vs Perception.\n"
             "If successful, applies hidden condition. Returns HideResult with details.")
        .def("check_hidden_agent_detection",
             &CombatEngine::checkHiddenAgentDetection,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("in_combat"),
             "Check if a hidden agent comes into LOS and is detected by Perception.\n"
             "Returns empty string if still hidden, or detection message if revealed.")
        .def("update_darkness_blinding",
             &CombatEngine::updateDarknessBlinding,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Apply or remove Blinded condition based on agent's location obscuration.\n"
             "Agents in Darkness without darkvision, or MagicalDarkness without devil's sight, become Blinded.")

        // ── Visibility and line of sight ────────────────────────────────────
        .def("compute_visibility",
             &CombatEngine::computeVisibility,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Compute and cache visibility from one agent to all others.\n"
             "Respects perception range (based on stats + lighting modifiers),\n"
             "line-of-sight, and obscuration effects.\n"
             "Results are cached for use by spells/attacks until next turn.")
        .def("get_visibility",
             &CombatEngine::getVisibility,
             py::arg("source_idx"), py::arg("target_idx"),
             "Get the cached visibility level between two agents.\n"
             "Returns Blocked if visibility hasn't been computed for this pair.\n"
             "Call compute_visibility() first to populate the cache.")

        // RNG
        .def("reseed", &CombatEngine::reseed, py::arg("seed"))

        // ── Druid Wild Shape & Starry Form ──────────────────────────────────
        .def("activate_wild_shape", &CombatEngine::activateWildShape,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("beast_name"), py::arg("weapons"), py::arg("beast_forms_path") = "",
             "Activate Druid Wild Shape: spend 1 use, swap to beast form stats, grant Temp HP.\n"
             "For Circle of the Moon: Temp HP = 3×level, AC = max(beast_ac, 13+WIS).\n"
             "For other circles: Temp HP = 1×level, AC = beast_ac.\n"
             "weapons: array of 3 Weapon objects for the beast form.\n"
             "Optional beast_forms_path: if provided, use this path to load beast_forms.json; otherwise try standard locations.")
        .def("deactivate_wild_shape", &CombatEngine::deactivateWildShape,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Deactivate Druid Wild Shape: restore original AC, STR, DEX, CON, and weapons.")
        .def("activate_starry_form", &CombatEngine::activateStarryForm,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("constellation"),
             "Activate Druid Starry Form (Circle of the Stars): spend 1 Wild Shape use.\n"
             "constellation: 1=Archer, 2=Chalice, 3=Dragon.\n"
             "Dragon at L10+: add fly speed. L14+: add B/P/S resistance.")
        .def("deactivate_starry_form", &CombatEngine::deactivateStarryForm,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Deactivate Druid Starry Form: restore fly speed and resistances.")
        .def("activate_wrath_of_sea", &CombatEngine::activateWrathOfSea,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Activate Druid Wrath of the Sea (Circle of the Sea): spend 1 Wild Shape use.\n"
             "At L10+: add fly speed and resistances to Cold/Lightning/Thunder.")
        .def("deactivate_wrath_of_sea", &CombatEngine::deactivateWrathOfSea,
             py::arg("battle_map"), py::arg("agent_idx"),
             "Deactivate Druid Wrath of the Sea: restore fly speed and resistances.")
        .def("apply_dragon_min_roll", &CombatEngine::applyDragonMinRoll,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("d20_roll"),
             "Apply Dragon Constellation min-roll-10 for CON concentration saves.\n"
             "Returns max(d20_roll, 10) if conditions met, else returns d20_roll unchanged.");

    // ── MovementType ─────────────────────────────────────────────────────────
    py::enum_<MovementType>(m, "MovementType")
        .value("Walk",   MovementType::Walk,
               "Ground movement: BFS through passable cells, respects walls.")
        .value("Fly",    MovementType::Fly,
               "Aerial movement: Chebyshev radius, ignores terrain obstacles.")
        .value("Swim",   MovementType::Swim,
               "Aquatic movement: through water terrain.")
        .value("Burrow", MovementType::Burrow,
               "Underground movement: ignores surface obstacles.")
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
        .def_readonly("requires_concentration", &ActiveTerrainEffect::requires_concentration);

    // ── ActiveLightEffect struct ────────────────────────────────────────────
    py::class_<ActiveLightEffect>(m, "ActiveLightEffect")
        .def_readonly("id",                &ActiveLightEffect::id)
        .def_readonly("name",              &ActiveLightEffect::name)
        .def_readonly("cell_indices",      &ActiveLightEffect::cell_indices)
        .def_readonly("light_level",       &ActiveLightEffect::light_level)
        .def_readonly("turns_remaining",   &ActiveLightEffect::turns_remaining)
        .def_readonly("source_agent_idx",  &ActiveLightEffect::source_agent_idx);

    py::class_<ActiveObscurationEffect>(m, "ActiveObscurationEffect")
        .def(py::init<>())
        .def_readwrite("id",                   &ActiveObscurationEffect::id)
        .def_readwrite("source_agent_idx",     &ActiveObscurationEffect::source_agent_idx)
        .def_readwrite("cells",                &ActiveObscurationEffect::cells)
        .def_readwrite("obscuration_level",    &ActiveObscurationEffect::obscuration_level)
        .def_readwrite("turns_remaining",      &ActiveObscurationEffect::turns_remaining)
        .def("__repr__", [](const ActiveObscurationEffect& e){
            std::string level_str;
            switch (e.obscuration_level) {
                case VisibilityLevel::Clear:           level_str = "Clear"; break;
                case VisibilityLevel::Dim:             level_str = "Dim"; break;
                case VisibilityLevel::LightlyObscured: level_str = "LightlyObscured"; break;
                case VisibilityLevel::Dark:            level_str = "Dark"; break;
                case VisibilityLevel::MagicalDark:     level_str = "MagicalDark"; break;
                case VisibilityLevel::Blocked:         level_str = "Blocked"; break;
                default: level_str = "Unknown";
            }
            return "<ActiveObscurationEffect '" + level_str
                 + "' source=" + std::to_string(e.source_agent_idx)
                 + " cells=" + std::to_string(e.cells.size())
                 + " turns=" + std::to_string(e.turns_remaining) + ">"; });

    // ── BattleMap ───────────────────────────────────────────────────────────
    py::class_<BattleMap>(m, "BattleMap")
        .def(py::init<std::string>(),   // accept plain str from Python
             py::arg("map_image_path"))

        // Grid analysis
        .def("analyze_grid",  &BattleMap::analyzeGrid,
             "Detect grid lines; call before detect_walls().")
        .def("detect_walls",  &BattleMap::detectWalls,
             "Detect thick walls and compute disallowed cells via flood fill.")

        // Grid geometry (used by Python renderer to draw overlays)
        .def_property_readonly("grid_cols",       &BattleMap::gridCols)
        .def_property_readonly("grid_rows",       &BattleMap::gridRows)
        .def_property_readonly("cell_pixel_size", &BattleMap::cellPixelSize)
        .def_property_readonly("h_line_positions",&BattleMap::hLinePositions)
        .def_property_readonly("v_line_positions",&BattleMap::vLinePositions)

        // Wall / passability data
        .def_property_readonly("walls", [](const BattleMap& bm) -> std::vector<Wall> {
            return {bm.walls().begin(), bm.walls().end()};
        })
        .def_property_readonly("disallowed_cells", [](const BattleMap& bm){
            return cellSetToVec(bm.disallowedCells());
        })
        .def("is_blocked", &BattleMap::isBlocked,
             py::arg("origin"), py::arg("agent_size"), py::arg("movement_type") = MovementType::Walk)

        // Agent management (core spatial operations only; stat/equipment management moved to CombatEngine)
        .def("clear_agents",       &BattleMap::clearAgents)
        .def("move_agent",         &BattleMap::moveAgent,
             py::arg("idx"), py::arg("new_origin"),
             py::arg("movement_type") = MovementType::Walk,
             "Move placed agent[idx] to new_origin using the given movement type.\n"
             "Returns False if the agent lacks sufficient movement budget.")
        .def("jump_agent",         &BattleMap::jumpAgent,
             py::arg("idx"), py::arg("new_origin"), py::arg("is_running"),
             "Jump placed agent[idx] to new_origin (ignores walls, deducts from walk budget).\n"
             "is_running: True for running jump (up to STR), False for standing jump (up to STR/2).\n"
             "Returns False if out of range or insufficient movement budget.")
        .def("force_move_agent",   &BattleMap::forceMoveAgent,
             py::arg("idx"), py::arg("push_from"), py::arg("push_ft"),
             "Force move agent[idx] away from push_from by up to push_ft.\n"
             "Does not consume movement budget. Stops at walls.\n"
             "Returns number of cells actually moved.")
        .def("set_agent_position", &BattleMap::setAgentPosition,
             py::arg("idx"), py::arg("new_origin"),
             "Directly set agent[idx] position (used for grapple dragging).\n"
             "Returns false if idx invalid or destination out of bounds.")
        .def("remove_agent",       &BattleMap::removeAgent,
             py::arg("idx"),
             "Remove placed agent[idx] from the map.")
        .def("apply_dash",         &BattleMap::applyDash,
             py::arg("idx"),
             "Set dashing condition and add base speeds to remaining movement for agent[idx].")

        // Line-of-sight
        .def("has_line_of_sight",
             &BattleMap::hasLineOfSight,
             py::arg("from_origin"), py::arg("from_size"),
             py::arg("to_origin"),   py::arg("to_size"),
             "Bresenham ray from centre of 'from' agent to centre of 'to' agent.\n"
             "Returns False if any intermediate cell is a wall/obstacle.")

        .def("filter_spell_cells",
             &BattleMap::filterSpellCells,
             py::arg("cells"), py::arg("caster_origin"), py::arg("caster_size"),
             py::arg("spell"), py::arg("center_cell"),
             "Filter spell cells by range and line-of-sight requirements.\n"
             "Respects spell.requires_los and spell.check_los_on_center flags.\n"
             "If check_los_on_center, only the center cell needs LOS (D&D 5e standard).")

        .def("aoe_cells", &BattleMap::aoeCells,
             py::arg("center"), py::arg("spell"), py::arg("caster_origin"),
             "Cells covered by a spell's AoE geometry (Cone/Line use caster_origin as apex).")

        // Attack target cells (melee reach or ranged range, with LoS filter)
        .def("attack_target_cells",
             [](const BattleMap& bm, Cell origin, int agentSize, int rangeFt) {
                 return bm.attackTargetCells(origin, agentSize, rangeFt);
             },
             py::arg("origin"), py::arg("agent_size"), py::arg("range_ft"),
             "Return cells within range_ft feet (Chebyshev from footprint edge)\n"
             "that have line-of-sight from the agent.\n"
             "Use for melee (range_ft = 5/10/15) and ranged (call twice for\n"
             "normal/long zones and subtract).")

        // Movement reach
        .def("reachable_cells",
             [](const BattleMap& bm, Cell origin, int agentSize,
                int speedFt, MovementType type) {
                 return cellSetToVec(bm.reachableCells(origin, agentSize,
                                                       speedFt, type));
             },
             py::arg("origin"), py::arg("agent_size"),
             py::arg("speed_ft"), py::arg("movement_type"),
             "Return a list of Cell origins reachable from origin.\n"
             "Walk: Dijkstra BFS through passable cells.\n"
             "Fly:  Chebyshev radius ignoring terrain.")

        .def_property_readonly("placed_agents", [](const BattleMap& bm){
            auto sp = bm.placedAgents();
            return std::vector<PlacedAgent>(sp.begin(), sp.end());
        })

        // Terrain multipliers (for difficult terrain, spells, etc.)
        .def("get_terrain_multiplier", &BattleMap::getTerrainMultiplier,
             py::arg("cell"), py::arg("movement_type") = MovementType::Walk,
             "Get the movement cost multiplier for a cell (default 1.0).")
        .def("set_terrain_multiplier", &BattleMap::setTerrainMultiplier,
             py::arg("cell"), py::arg("multiplier"),
             "Set the movement cost multiplier for a single cell.")
        .def("set_terrain_multiplier_rect", &BattleMap::setTerrainMultiplierRect,
             py::arg("top_left"), py::arg("width"), py::arg("height"), py::arg("multiplier"),
             "Set the movement cost multiplier for a rectangular region.")
        .def("reset_terrain_multipliers", &BattleMap::resetTerrainMultipliers,
             "Reset all terrain multipliers to 1.0 (default).")

        // Terrain types (Standard, Water, Wall, Chasm)
        .def("get_terrain_type", &BattleMap::getTerrainType,
             py::arg("cell"),
             "Get the terrain type for a cell (Standard, Water, Wall, or Chasm).")
        .def("set_terrain_type", &BattleMap::setTerrainType,
             py::arg("cell"), py::arg("terrain_type"),
             "Set the terrain type for a cell.")

        // Light levels (BrightLight, DimLight, Darkness, MagicalDarkness)
        .def("get_light_level", &BattleMap::getLightLevel,
             py::arg("cell"),
             "Get the light level for a cell (BrightLight, DimLight, Darkness, or MagicalDarkness).")
        .def("set_light_level", &BattleMap::setLightLevel,
             py::arg("cell"), py::arg("light_level"),
             "Set the light level for a cell.")
        .def("reset_light_levels", &BattleMap::resetLightLevels,
             "Reset all light levels to BrightLight (default).")

        // Visibility & Darkvision
        .def("can_see", &BattleMap::canSee,
             py::arg("obs_origin"), py::arg("obs_size"),
             py::arg("darkvision_ft"), py::arg("truesight_ft"), py::arg("devilssight_ft"),
             py::arg("tgt_origin"), py::arg("tgt_size"),
             "Check if observer can see target (D&D 5e vision rules).\n"
             "Returns false = observer is blinded and cannot target.\n"
             "Implements: Truesight (all conditions), Devil's Sight (darkness/magical darkness),\n"
             "Darkvision (disadvantage in pure darkness), Normal vision (blinded in darkness).")
        .def("perception_disadvantage", &BattleMap::perceptionDisadvantage,
             py::arg("obs_origin"), py::arg("obs_size"),
             py::arg("darkvision_ft"), py::arg("truesight_ft"), py::arg("devilssight_ft"),
             py::arg("tgt_origin"), py::arg("tgt_size"),
             "Check if observer has disadvantage on perception vs target.\n"
             "Returns true for: DimLight (normal/devil's sight), Darkness (darkvision only).")

        // Temporary terrain effects (spells, items, etc. with duration)
        .def("place_terrain_effect", &BattleMap::placeTerrainEffect,
             py::arg("name"), py::arg("cells"), py::arg("difficulty"),
             py::arg("turns_remaining"), py::arg("source_agent_idx"),
             py::arg("slip_save_dc") = 10, py::arg("slip_distance_feet") = 5,
             py::arg("spell_idx") = -1, py::arg("requires_concentration") = false,
             "Place a temporary terrain effect covering the given cells.\n"
             "Returns unique effect id (for later removal/metadata).")
        .def("tick_terrain_effects", &BattleMap::tickTerrainEffects,
             py::arg("source_agent_idx"),
             "Decrement turns_remaining for effects from this source.\n"
             "Removes expired effects (turns_remaining <= 0).\n"
             "Returns list of removed effect ids.")
        .def("tick_dm_terrain_effects", &BattleMap::tickDMTerrainEffects,
             "Decrement turns_remaining for DM-placed effects (source_agent_idx == -1).\n"
             "Called at round boundary. Returns list of removed effect ids.")
        .def("remove_terrain_effects_by_source", &BattleMap::removeTerrainEffectsBySource,
             py::arg("source_agent_idx"),
             "Remove all effects sourced from the given agent (concentration drop, death, etc.).\n"
             "Returns list of removed effect ids.")
        .def("remove_terrain_effect", &BattleMap::removeTerrainEffect,
             py::arg("effect_id"),
             "Remove a specific effect by id (manual DM removal).")
        .def("clear_terrain_effects", &BattleMap::clearTerrainEffects,
             "Clear all terrain effects (end of combat).")
        .def_property_readonly("active_terrain_effects", &BattleMap::activeTerrainEffects,
             "Get a copy of all active terrain effects (for rendering).")
        .def("has_active_terrain_effects", &BattleMap::hasActiveTerrainEffects,
             "Check if there are any active terrain effects.")

        // Persistent spell effects (AoE from spells)
        .def_property_readonly("active_spell_effects", &BattleMap::activeSpellEffects,
             "Get all active spell effects from spells cast during combat.")
        .def("add_spell_effect", &BattleMap::addSpellEffect,
             py::arg("effect"),
             "Add a spell effect to the map. Returns effect_id.")
        .def("remove_spell_effect", &BattleMap::removeSpellEffect,
             py::arg("effect_id"),
             "Remove a spell effect by id.")
        .def("clear_spell_effects", &BattleMap::clearSpellEffects,
             "Remove all active spell effects (e.g. on End Combat).")

        // Dynamic light effects (spells, DM-placed lights, etc. with duration)
        .def("apply_base_lighting", &BattleMap::applyBaseLighting,
             py::arg("default_light"), py::arg("sources"),
             "Apply base lighting from map JSON. sources: list[(pixel_x, pixel_y, bright_radius_ft, dim_radius_ft)]")
        .def("update_lighting", &BattleMap::updateLighting,
             "Recompute lightLevel_ from baseLightLevel_ + activeLightEffects_.")
        .def("place_light_effect", &BattleMap::placeLightEffect,
             py::arg("name"), py::arg("cells"), py::arg("light_level"),
             py::arg("turns_remaining"), py::arg("source_agent_idx"),
             "Place a dynamic light effect covering the given cells.\n"
             "Returns unique effect id (for later removal).")
        .def("tick_light_effects", &BattleMap::tickLightEffects,
             py::arg("source_agent_idx"),
             "Decrement turns_remaining for light effects from this source.\n"
             "Removes expired effects (turns_remaining <= 0).\n"
             "Returns list of removed effect ids.")
        .def("tick_dm_light_effects", &BattleMap::tickDmLightEffects,
             "Decrement turns_remaining for DM-placed light effects (source_agent_idx == -1).\n"
             "Returns list of removed effect ids.")
        .def("remove_light_effects_by_source", &BattleMap::removeLightEffectsBySource,
             py::arg("source_agent_idx"),
             "Remove all light effects sourced from the given agent.\n"
             "Returns list of removed effect ids.")
        .def("remove_light_effect", &BattleMap::removeLightEffect,
             py::arg("effect_id"),
             "Remove a specific light effect by id.")
        .def("clear_light_effects", &BattleMap::clearLightEffects,
             "Clear all dynamic light effects.")
        .def_property_readonly("active_light_effects", &BattleMap::activeLightEffects,
             "Get a copy of all active light effects.")
        .def("has_active_light_effects", &BattleMap::hasActiveLightEffects,
             "Check if there are any active light effects.")

        // Obscuration effects (fog clouds, magical darkness, etc.)
        .def_property_readonly("active_obscuration_effects", &BattleMap::activeObscurationEffects,
             "Get all active obscuration effects on the map.")
        .def("add_obscuration_effect", &BattleMap::addObscurationEffect,
             py::arg("effect"),
             "Add an obscuration effect to the map. Returns effect_id.")
        .def("remove_obscuration_effect", &BattleMap::removeObscurationEffect,
             py::arg("effect_id"),
             "Remove an obscuration effect by id.")
        .def("get_obscuration_at_cell", &BattleMap::getObscurationAtCell,
             py::arg("cell"),
             "Get the obscuration level at a specific cell.\n"
             "Returns the highest obscuration level (MagicalDarkness > PartiallyObscured > BrightLight).")
        .def("tick_obscuration_effects", &BattleMap::tickObscurationEffects,
             "Decrement turns_remaining for all obscuration effects.\n"
             "Removes expired effects (turns_remaining <= 0).\n"
             "Returns list of removed effect ids.")
        .def("clear_obscuration_effects", &BattleMap::clearObscurationEffects,
             "Clear all obscuration effects (end of combat).")

        // Map items (weapons on the ground)
        .def("place_item", &BattleMap::placeItem,
             py::arg("cell"), py::arg("weapon"), py::arg("sprite_path") = "",
             "Place a weapon item at a cell. Returns a unique item id.")
        .def("remove_item", &BattleMap::removeItem,
             py::arg("item_id"),
             "Remove the item with the given id from the map.")
        .def("get_items_at_cell", &BattleMap::getItemsAtCell,
             py::arg("cell"),
             "Return list of MapItem at the given cell.")
        .def("get_all_items", &BattleMap::getAllItems,
             "Return list of all MapItem on the map.")
        .def("clear_items", &BattleMap::clearItems,
             "Remove all items from the map.")

        // Expose params so Python can tune detection
        .def_readwrite("params", &BattleMap::params);

    // ── Map Configuration Functions ───────────────────────────────────────
    m.def("apply_terrain_configuration", &applyTerrainConfiguration,
         py::arg("bm"), py::arg("json_path"),
         "Load and apply terrain configuration from a JSON file to the BattleMap.\n"
         "JSON format: {\"terrain_features\": [{\"type\": \"rect|column|row|cell\", ...}]}");

    m.def("apply_spell_effect_configuration", &applySpellEffectConfiguration,
         py::arg("bm"), py::arg("json_path"),
         "Load and apply spell effect configuration from a JSON file to the BattleMap.\n"
         "Loads spells from spells.json in the same directory and creates ActiveSpellEffect instances.\n"
         "JSON format: {\"spell_effects\": [{\"type\": \"rect|sphere|column|row|cell\", \"spell_name\": \"...\", \"remaining_turns\": N, ...}]}");
}
