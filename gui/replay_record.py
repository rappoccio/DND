#!/usr/bin/env python3
"""
Replay recording support for deterministic, *checked* combat regression.

RecordingCombat transparently wraps a CombatEngine and records every
state-mutating engine call (method name + serialized args + a snapshot of the
resulting engine state) to a JSONL event log. replay.py re-runs those events
against a freshly-seeded engine and asserts each recorded snapshot is
reproduced, so any recorded combat becomes a reproducible bug regression.

The snapshot logic lives here (engine_snapshot) so the recorder and the checker
agree on exactly what state is compared.
"""

import json


# ── Shared state snapshot ───────────────────────────────────────────────────
# Per agent: [name, hp_cur, temp_hp, col, row, dead, prone, concentrating]
def engine_snapshot(engine, bm):
    snap = []
    agents = bm.placed_agents
    for i in range(len(agents)):
        st = engine.get_agent_stats(bm, i)
        co = engine.get_agent_conditions(bm, i)
        snap.append([agents[i].name, st.hp_cur, st.temp_hp,
                     agents[i].origin.col, agents[i].origin.row,
                     int(co.dead), int(co.prone), int(co.concentrating)])
    return snap


_SNAP_FIELDS = ["name", "hp_cur", "temp_hp", "col", "row", "dead", "prone", "concentrating"]


def diff_snapshots(expected, actual):
    """Return a list of human-readable mismatch strings (empty if identical)."""
    diffs = []
    if len(expected) != len(actual):
        diffs.append(f"agent count: expected {len(expected)}, got {len(actual)}")
        return diffs
    for i, (e, a) in enumerate(zip(expected, actual)):
        for f, ev, av in zip(_SNAP_FIELDS, e, a):
            if ev != av:
                who = e[0] if e else f"agent {i}"
                diffs.append(f"agent {i} ({who}).{f}: expected {ev}, got {av}")
    return diffs


# ── Recording wrapper ───────────────────────────────────────────────────────
class RecordingCombat:
    """Transparent CombatEngine wrapper that logs every mutating call + snapshot.

    Non-recorded methods/attributes pass straight through, so this is a drop-in
    replacement for the engine on the Python side.
    """

    # Engine methods that mutate engine/BattleMap state and must replay in order.
    # NOTE: set_agent_conditions is intentionally excluded — its Conditions arg is
    # large/awkward to serialize and is used for out-of-band DM/long-rest edits;
    # the one combat-relevant use (Reckless Attack) is logged via log_event("reckless").
    _RECORDED = {
        "execute_action", "execute_spell", "move_agent",
        "begin_turn", "end_turn", "tick_agent_conditions_for_caster",
        "tick_terrain_for_turn", "activate_rage", "end_rage",
        "apply_brutal_strike_effect", "execute_shove", "execute_grapple",
        "execute_grapple_escape", "drop_concentration", "clear_all_concentration",
        "set_safe_targets",
    }

    def __init__(self, engine, rpg_module):
        object.__setattr__(self, "_engine", engine)
        object.__setattr__(self, "_rpg", rpg_module)
        object.__setattr__(self, "_bm", None)
        object.__setattr__(self, "_log_path", None)

    # — recording control —
    def start_recording(self, log_path, bm):
        object.__setattr__(self, "_bm", bm)
        object.__setattr__(self, "_log_path", log_path)

    def stop_recording(self):
        object.__setattr__(self, "_log_path", None)

    def log_event(self, event, **fields):
        """Record a semantic event outside the wrapped methods (e.g. 'reckless')."""
        if not self._log_path or self._bm is None:
            return
        self._append({"event": event, "args": [fields], "snap": engine_snapshot(self._engine, self._bm)})

    # — transparent delegation with logging for recorded methods —
    def __getattr__(self, name):
        attr = getattr(self._engine, name)
        if name not in self._RECORDED or not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            result = attr(*args, **kwargs)
            if self._log_path and self._bm is not None:
                self._append({"event": name,
                              "args": self._serialize_args(args),
                              "snap": engine_snapshot(self._engine, self._bm)})
            return result
        return wrapped

    # — internals —
    def _append(self, entry):
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except IOError:
            pass

    def _serialize_args(self, args):
        out = []
        for a in args:
            if a is self._bm or type(a).__name__ == "BattleMap":
                continue  # bm is reconstructed on replay, not serialized
            out.append(self._ser(a))
        return out

    def _ser(self, a):
        if isinstance(a, bool) or isinstance(a, (int, float, str)) or a is None:
            return a
        if isinstance(a, (list, tuple)):
            return [self._ser(x) for x in a]
        tn = type(a).__name__
        if tn == "Cell":
            return {"_cell": [a.col, a.row]}
        if tn == "Attack":
            return {"_attack": [a.attacker_idx, a.target_idx, a.weapon_idx, a.is_offhand]}
        if tn == "SpellAction":
            return {"_spell": [a.caster_idx, a.spell_idx, a.slot_level,
                               list(a.target_indices), a.aoe_col, a.aoe_row]}
        if tn == "ShoveAction":
            return {"_shove": [a.attacker_idx, a.target_idx, a.knock_prone]}
        if tn == "GrappleAction":
            return {"_grapple": [a.attacker_idx, a.target_idx]}
        if tn == "AttackResult":
            return {"_result": None}  # out-param; a fresh one is made on replay
        if hasattr(a, "name"):  # enum (e.g. MovementType)
            return {"_enum": [tn, a.name]}
        return {"_repr": repr(a)}


# ── Replay-side arg reconstruction ──────────────────────────────────────────
def reconstruct_arg(s, rpg):
    if isinstance(s, list):
        return [reconstruct_arg(x, rpg) for x in s]
    if not isinstance(s, dict):
        return s
    if "_cell" in s:
        return rpg.Cell(*s["_cell"])
    if "_attack" in s:
        ai, ti, wi, off = s["_attack"]
        a = rpg.Attack(ai, ti, wi); a.is_offhand = off
        return a
    if "_spell" in s:
        ci, si, sl, tgts, ac, ar = s["_spell"]
        a = rpg.SpellAction()
        a.caster_idx = ci; a.spell_idx = si; a.slot_level = sl
        a.target_indices = tgts; a.aoe_col = ac; a.aoe_row = ar
        return a
    if "_shove" in s:
        ai, ti, kp = s["_shove"]
        a = rpg.ShoveAction(); a.attacker_idx = ai; a.target_idx = ti; a.knock_prone = kp
        return a
    if "_grapple" in s:
        ai, ti = s["_grapple"]
        a = rpg.GrappleAction(); a.attacker_idx = ai; a.target_idx = ti
        return a
    if "_result" in s:
        return rpg.AttackResult()
    if "_enum" in s:
        tn, name = s["_enum"]
        return getattr(getattr(rpg, _ENUM_PY_NAME.get(tn, tn)), name)
    return s  # dict of fields (semantic event payload)


# C++ enum type name -> Python binding name (extend as needed)
_ENUM_PY_NAME = {"MovementType": "MovementType"}
