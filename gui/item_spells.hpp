#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  item_spells.hpp  –  spells cast FROM an item (plans/ENSPELLED_ITEMS_PLAN.md)
//
//  Carried by value on Item, Weapon and Armor, so an item's remaining uses travel
//  with it — to an ally, a chest, the floor, a save file — and dropping and picking
//  it up never refills it (D0). Empty on every ordinary item.
//
//  The authored half comes from items.json / weapons.json / armor.json; the runtime
//  half (attuned, uses_remaining, charges) is saved with the item. Python resolves
//  the spell records (spells.json + spell_overrides); the engine owns cost and state.
// ─────────────────────────────────────────────────────────────────────────────

#include <algorithm>
#include <map>
#include <string>
#include <vector>

namespace rpg {

struct ItemSpells {
    // "99" uses/day = at will (D3), the mob convention: never decremented.
    static constexpr int kAtWill = 99;

    // ── Authored ──────────────────────────────────────────────────────────
    bool requires_attunement{false};   // D5: grants nothing until `attuned`
    int  spell_dc{0};                  // D1: 0 ⇒ the holder's own save DC
    int  spell_attack{0};              // D1: 0 ⇒ the holder's own spell attack bonus

    // Per-spell N/day (D4): uses/day → spell names. Each spell gets its own N uses.
    std::map<int, std::vector<std::string>> spell_groups{};
    // Shared pool (D4): cost per cast → spell names. charges_max 0 ⇒ no pool.
    std::map<int, std::vector<std::string>> charge_spells{};
    int         charges_max{0};
    std::string charges_regain{"long_rest"};

    // D3a: {spell name: {spells.json field: value}} as JSON text. Opaque to the engine —
    // Python applies it when it resolves the catalog record.
    std::string spell_overrides_json{};

    // ── Runtime (saved with the item, not authored) ─────────────────────────
    bool attuned{false};
    std::map<std::string, int> uses_remaining{};   // per spell in spell_groups (not at-will ones)
    int  charges{0};                               // current pool charges

    [[nodiscard]] bool empty() const noexcept {
        return spell_groups.empty() && charge_spells.empty();
    }

    // D5: does this item grant its spells to whoever carries it right now?
    [[nodiscard]] bool active() const noexcept {
        return !empty() && (!requires_attunement || attuned);
    }

    // D7: the item's spell list is the union of both cost models, in authored order.
    [[nodiscard]] std::vector<std::string> spellNames() const {
        std::vector<std::string> out;
        auto add = [&](const std::map<int, std::vector<std::string>>& groups) {
            for (const auto& [_, names] : groups)
                for (const auto& n : names)
                    if (std::find(out.begin(), out.end(), n) == out.end()) out.push_back(n);
        };
        add(spell_groups);
        add(charge_spells);
        return out;
    }

    // Uses/day for a spell in spell_groups; 0 if it isn't in one.
    [[nodiscard]] int usesPerDay(const std::string& spell) const {
        for (const auto& [n, names] : spell_groups)
            if (std::find(names.begin(), names.end(), spell) != names.end()) return n;
        return 0;
    }

    // Fill every N/day spell and the pool to max: a fresh item from the catalog, and the
    // long-rest refill (E2).
    void refill() {
        uses_remaining.clear();
        for (const auto& [n, names] : spell_groups)
            if (n != kAtWill)
                for (const auto& s : names) uses_remaining[s] = n;
        charges = charges_max;
    }
};

}  // namespace rpg
