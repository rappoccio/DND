#!/usr/bin/env python3
"""
Combat Replay Utility

Automatically replays a recorded combat encounter using the replay_log.txt file.
This allows for deterministic reproduction of bugs and intermittent issues.

Usage:
    python replay.py <map_image> [replay_log.txt]
"""

import sys
import os
import json
import re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import rpg_battle_map as rpg
except ImportError:
    print("ERROR: rpg_battle_map module not found. Run cmake to build it first.")
    sys.exit(1)

from agent_loader import load_agents_from_json


class CombatReplayer:
    """Replays combat encounters from a replay log."""

    def __init__(self, map_image_path, replay_log_path="replay_log.txt"):
        self.map_image_path = map_image_path
        self.replay_log_path = replay_log_path
        self.bm = None
        self.combat = None
        self.seed = None
        self.actions = []
        self.combat_log = []

    def load_replay_log(self):
        """Load and parse the replay log file."""
        if not os.path.exists(self.replay_log_path):
            print(f"ERROR: Replay log not found: {self.replay_log_path}")
            return False

        with open(self.replay_log_path, "r") as f:
            lines = f.readlines()

        # Parse header
        in_actions = False
        for line in lines:
            line = line.strip()
            if not line or line.startswith("==="):
                if "ACTIONS" in line:
                    in_actions = True
                continue

            if line.startswith("SEED:"):
                self.seed = int(line.split(":")[1].strip())
                print(f"[REPLAY] Loaded seed: {self.seed}")
            elif line.startswith("INITIATIVE:"):
                # Parse initiative
                init_str = line.split(":", 1)[1].strip()
                print(f"[REPLAY] Initiative: {init_str}")
            elif in_actions and line.startswith("{"):
                try:
                    action = json.loads(line)
                    self.actions.append(action)
                except json.JSONDecodeError:
                    print(f"WARNING: Failed to parse action: {line}")

        print(f"[REPLAY] Loaded {len(self.actions)} actions")
        return True

    def setup_combat(self):
        """Set up the battle map and combat engine."""
        print(f"[REPLAY] Loading map: {self.map_image_path}")
        self.bm = rpg.BattleMap(self.map_image_path)

        # Create combat engine with the same seed before loading agents
        if self.seed is None:
            print("ERROR: No seed found in replay log")
            return False

        self.combat = rpg.CombatEngine(self.seed)
        print(f"[REPLAY] Created CombatEngine with seed: {self.seed}")

        # Load agents from the map JSON file using shared loader
        map_base = os.path.splitext(self.map_image_path)[0]
        agents_json_path = map_base + "_agents.json"

        if not load_agents_from_json(agents_json_path, self.bm, self.combat, sprites_dir=""):
            print(f"WARNING: Could not load agents from: {agents_json_path}")
            return False

        print(f"[REPLAY] Loaded {len(self.bm.placed_agents)} agents")
        return True

    def replay_actions(self):
        """Execute all actions in sequence."""
        print(f"\n[REPLAY] Starting action replay...")

        for i, action in enumerate(self.actions):
            action_type = action.get("action")
            print(f"\n[REPLAY] Action {i+1}/{len(self.actions)}: {action_type}")

            if action_type == "attack":
                self._replay_attack(action)
            elif action_type == "move":
                self._replay_move(action)
            elif action_type == "spell":
                self._replay_spell(action)
            else:
                print(f"WARNING: Unknown action type: {action_type}")

        print(f"\n[REPLAY] Replay complete!")

    def _replay_attack(self, action):
        """Replay an attack action."""
        atk_idx = action.get("attacker_idx")
        tgt_idx = action.get("target_idx")
        weapon_idx = action.get("weapon_idx", 0)
        slot = action.get("slot")

        agents = self.bm.placed_agents
        atk_name = agents[atk_idx].name if 0 <= atk_idx < len(agents) else "?"
        tgt_name = agents[tgt_idx].name if 0 <= tgt_idx < len(agents) else "?"

        print(f"  {atk_name} attacks {tgt_name} with weapon[{weapon_idx}] ({slot})")

        atk = rpg.Attack(atk_idx, tgt_idx, weapon_idx)
        atk.is_offhand = (slot == "bonus")
        result = self.combat.execute_action(self.bm, atk)

        if result.valid:
            if result.hit:
                print(f"  ✓ HIT! Damage: {result.total_damage}")
            else:
                print(f"  ✗ MISS (rolled {result.total_roll} vs AC {result.target_ac})")
        else:
            print(f"  ✗ INVALID attack")

    def _replay_move(self, action):
        """Replay a move action."""
        agent_idx = action.get("agent_idx")
        col = action.get("col")
        row = action.get("row")
        move_type_str = action.get("move_type", "Walk")

        # Parse MovementType
        move_type = getattr(rpg.MovementType, move_type_str, rpg.MovementType.Walk)

        agents = self.bm.placed_agents
        agent_name = agents[agent_idx].name if 0 <= agent_idx < len(agents) else "?"

        print(f"  {agent_name} moves to ({col},{row}) via {move_type_str}")

        cell = rpg.Cell(col, row)
        success = self.combat.move_agent(self.bm, agent_idx, cell, move_type)

        if success:
            print(f"  ✓ Moved successfully")
        else:
            print(f"  ✗ Movement blocked")

    def _replay_spell(self, action):
        """Replay a spell action."""
        caster_idx = action.get("caster_idx")
        spell_idx = action.get("spell_idx")
        slot = action.get("slot")
        targets = action.get("targets", [])

        agents = self.bm.placed_agents
        caster_name = agents[caster_idx].name if 0 <= caster_idx < len(agents) else "?"

        spells = self.combat.get_agent_spells(self.bm, caster_idx)
        spell_name = spells[spell_idx].name if 0 <= spell_idx < len(spells) else "?"

        target_names = [agents[t].name if 0 <= t < len(agents) else "?" for t in targets]
        print(f"  {caster_name} casts {spell_name} on {target_names}")

        spell_action = rpg.SpellAction()
        spell_action.caster_idx = caster_idx
        spell_action.spell_idx = spell_idx
        spell_action.slot_level = 0  # Assume base level
        spell_action.target_indices = targets

        result = self.combat.execute_spell(self.bm, spell_action)

        if result.valid:
            print(f"  ✓ Spell cast successfully")
        else:
            print(f"  ✗ Spell cast failed")

    def run(self):
        """Run the full replay."""
        print("=" * 60)
        print("COMBAT REPLAY UTILITY")
        print("=" * 60)

        if not self.load_replay_log():
            return False

        if not self.setup_combat():
            return False

        self.replay_actions()
        return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python replay.py <map_image> [replay_log.txt]")
        print("Example: python replay.py maps/MyMap.png replay_log.txt")
        sys.exit(1)

    map_image = sys.argv[1]
    replay_log = sys.argv[2] if len(sys.argv) > 2 else "replay_log.txt"

    replayer = CombatReplayer(map_image, replay_log)
    success = replayer.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
