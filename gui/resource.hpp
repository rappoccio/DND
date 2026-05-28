#pragma once
#include <string>
#include <algorithm>
#include <nlohmann/json.hpp>

namespace rpg {

struct Resource {
  // Identity
  std::string name;  // e.g., "Rage", "Focus Points", "Sorcery Points", "Channel Divinity"

  // Current state
  int current{0};     // current amount available
  int max{0};         // max amount per rest cycle

  // Regeneration rules
  int short_rest_regen{0};  // restored after short rest
  int long_rest_regen{0};   // restored after long rest (or if short_rest_regen=0, restored here)

  // Duration tracking (for limited-time resources like Rage)
  int duration{0};           // duration in turns (0 = permanent resource)
  int duration_remaining{0}; // turns left (only used if duration > 0)

  // Constructor
  Resource() = default;

  Resource(const std::string& n, int mx, int dur = 0)
    : name(n), current(mx), max(mx), duration(dur), duration_remaining(0) {}

  // Queries
  [[nodiscard]] bool isFull() const noexcept { return current >= max; }
  [[nodiscard]] bool isEmpty() const noexcept { return current <= 0; }
  [[nodiscard]] bool isActive() const noexcept {
    return duration > 0 && duration_remaining > 0;
  }

  // Spending a resource (e.g., using a Rage)
  // Returns true if successfully spent, false if not enough
  bool spend(int amount = 1) noexcept {
    if (current < amount) return false;
    current -= amount;
    return true;
  }

  // Gain resource (e.g., from a feature that grants bonus uses)
  void gain(int amount = 1) noexcept {
    current = std::min(current + amount, max);
  }

  // Restore to full (Long Rest)
  void restore_long_rest() noexcept {
    if (long_rest_regen > 0) {
      current = long_rest_regen;
    } else {
      current = max;
    }
    duration_remaining = duration;  // reset duration counter
  }

  // Restore partial (Short Rest)
  void restore_short_rest() noexcept {
    if (short_rest_regen > 0) {
      current = std::min(current + short_rest_regen, max);
    }
    // duration_remaining unchanged on short rest
  }

  // Tick down duration (called each turn)
  void tick_duration() noexcept {
    if (duration > 0 && duration_remaining > 0) {
      duration_remaining--;
    }
  }

  // Reset duration (e.g., when Rage is activated)
  void reset_duration() noexcept {
    duration_remaining = duration;
  }

  // JSON serialization for persistence
  [[nodiscard]] nlohmann::json to_json() const {
    return nlohmann::json{
      {"name", name},
      {"current", current},
      {"max", max},
      {"short_rest_regen", short_rest_regen},
      {"long_rest_regen", long_rest_regen},
      {"duration", duration},
      {"duration_remaining", duration_remaining}
    };
  }

  // JSON deserialization
  static Resource from_json(const nlohmann::json& j) {
    Resource r;
    r.name = j.value("name", "");
    r.current = j.value("current", 0);
    r.max = j.value("max", 0);
    r.short_rest_regen = j.value("short_rest_regen", 0);
    r.long_rest_regen = j.value("long_rest_regen", 0);
    r.duration = j.value("duration", 0);
    r.duration_remaining = j.value("duration_remaining", 0);
    return r;
  }
};

} // namespace rpg
