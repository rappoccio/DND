"""One NPC decision as arrays: the model's input, shared by the dataset writer and the policy.

A decision is what the engine hands a policy: the acting agent, its archetype, and the
``available_macro_actions`` candidates. It becomes

    tokens       (N, TOKEN_DIM)   get_entity_observation's creature tokens, self first
    map          (MAP_DIM,)       its map token
    arch         int              NpcArchetype
    cand         (M, CAND_DIM)    one row per candidate (layout: CAND_FIELDS)
    cand_target  (M,)             the candidate's target as a row of ``tokens``; -1 = none
    legal        (M,)             the engine's legality flag

Bump FEATURE_VERSION whenever a layout changes: a checkpoint records the version it was
trained on and the policy refuses a mismatch.
"""

from __future__ import annotations

import numpy as np

import rpg_battle_map as rpg

FEATURE_VERSION = 1

ENTITY_FIELDS = list(rpg.CombatEngine.entity_observation_fields())
MAP_FIELDS = list(rpg.CombatEngine.map_observation_fields())
TOKEN_DIM = len(ENTITY_FIELDS)
MAP_DIM = len(MAP_FIELDS)
KIND_COUNT = int(rpg.NPC_MACRO_KIND_COUNT)
ARCH_COUNT = 5
KIND_NAMES = [rpg.NpcMacroKind(k).name for k in range(KIND_COUNT)]
ARCH_NAMES = [rpg.NpcArchetype(k).name for k in range(ARCH_COUNT)]
LABEL_NAMES = KIND_NAMES + ["Defer"]          # a label's kind; Defer = the fallback chain

SPELL_FIELDS = ["spell_level", "cantrip", "harm", "heal", "help", "transport",
                "area", "multiple", "radius", "range", "damage", "healing",
                "concentration", "save", "bonus_action"]
CAND_FIELDS = ([f"kind_{n}" for n in KIND_NAMES] +
               ["has_target", "has_spell", "has_cell", "cell_dx", "cell_dy", "cell_dist"] +
               SPELL_FIELDS)
CAND_DIM = len(CAND_FIELDS)

_AREA = {rpg.SpellGeometry.Line, rpg.SpellGeometry.Cone, rpg.SpellGeometry.Sphere,
         rpg.SpellGeometry.Square, rpg.SpellGeometry.Rectangle}


def _avg_dice(rolls) -> float:
    return sum(r.num_dice * (r.die_size + 1) / 2.0 + r.bonus for r in rolls)


def spell_features(sp) -> list[float]:
    heal = sp.healing_type
    return [sp.level / 9.0, float(sp.level <= 0),
            float(sp.type == rpg.SpellType.Harm), float(sp.type == rpg.SpellType.Heal),
            float(sp.type == rpg.SpellType.Help), float(sp.type == rpg.SpellType.Transport),
            float(sp.geometry in _AREA), float(sp.geometry == rpg.SpellGeometry.Multiple),
            sp.radius / 30.0, sp.range / 120.0,
            (_avg_dice(sp.magic_damage_rolls) + _avg_dice(sp.physical_damage_rolls)) / 50.0,
            (heal.num_dice * (heal.die_size + 1) / 2.0 + heal.bonus) / 30.0,
            float(sp.requires_concentration), float(sp.attack_type == rpg.SpellAttack.Save),
            float(sp.casting_time == rpg.CastingTime.BonusAction)]


_NO_SPELL = [0.0] * len(SPELL_FIELDS)


def featurize(eng, bm, idx: int, archetype, actions) -> dict:
    """The decision ``(idx, archetype, actions)`` as the arrays listed in the module doc."""
    obs = eng.get_entity_observation(bm, idx)
    rows = {int(a): r for r, a in enumerate(obs.agent_indices)}
    agents = bm.placed_agents
    me = agents[idx].origin
    spells = agents[idx].spells
    spell_feats: dict[int, list[float]] = {}

    cand = np.zeros((len(actions), CAND_DIM), dtype=np.float32)
    target = np.full(len(actions), -1, dtype=np.int32)
    legal = np.zeros(len(actions), dtype=bool)
    for m, a in enumerate(actions):
        k = int(a.kind)
        row = [0.0] * KIND_COUNT
        row[k] = 1.0
        t = rows.get(int(a.target_agent), -1)
        target[m] = t
        si = int(a.spell_idx)
        cell = a.target_cell
        has_cell = cell.col >= 0 and cell.row >= 0
        dx = (cell.col - me.col) / 20.0 if has_cell else 0.0
        dy = (cell.row - me.row) / 20.0 if has_cell else 0.0
        row += [float(t >= 0), float(si >= 0), float(has_cell), dx, dy,
                max(abs(dx), abs(dy))]
        if 0 <= si < len(spells):
            if si not in spell_feats:
                spell_feats[si] = spell_features(spells[si])
            row += spell_feats[si]
        else:
            row += _NO_SPELL
        cand[m] = row
        legal[m] = bool(a.legal)

    return {"tokens": np.asarray(obs.creature_tokens, dtype=np.float32).reshape(-1, TOKEN_DIM),
            "map": np.asarray(obs.map_token, dtype=np.float32),
            "arch": int(archetype),
            "cand": cand, "cand_target": target, "legal": legal}
