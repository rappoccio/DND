# NPC Learning — Implementation Plan

Goal: NPCs that **beat Level 4 by a measured margin**. A transformer *teacher* is trained on
headless simulations, then distilled into one decision tree per archetype. Those trees are
the *students* that run in the engine as difficulty Levels 5/6. Every simulation can be
watched in a GUI **Playback** mode.

This plan supersedes Steps 11–13 of `NPC_AUTOMATION_PLAN.md` (hit-/kill-probability models,
NN training). Levels 1–4 and the "clamp to Level 4 until trained" behaviour stay as they are.

Status: **Step 0 decisions D1–D13 FROZEN 2026-11-09**, including the user-checked role table.
Step 0 Dockerfile edit made; it awaits the user's image rebuild + verification.
Step 1 (trace recorder) committed 4fcba0b; Step 2 (Playback) committed a386c7a (227/0),
live-checked by the user 2026-11-09; Step 3 (arena) committed 2026-11-09 (228/0), with the
party makeup in arena traces and on the Playback HUD. Open: the draw rate and the
generated-party source (Step 3b). Step 4 (archetypes + fallback chain) committed cdac471
(229/0). Step 5 (macro-actions, policy seam, entity observation) implemented 2026-11-09
(230/0), committed 5d42944, awaiting the user's check of the choices flagged in its as-built notes.

---

## Step 0 — decisions (FROZEN 2026-11-09)

| #  | Decision |
| --- | -------- |
| D1 | **Teacher/student.** One shared transformer, conditioned on an archetype token, is trained offline in PyTorch (Python, in the container). Shipped NPCs run **decision trees**, one per archetype, evaluated in C++, with no ML runtime dependency. The transformer never runs at the table. |
| D2 | **Archetypes:** `Melee`, `Ranged`, `Blaster`, `Controller`, `HealerSupport`. Each has a defined **fallback chain** (Step 4). An agent never goes without a decision. |
| D3 | **Action space = Level 4 macro-actions**, each paired with a target (agent or cell). The policy picks *what*; the existing executors (`runWeaponTurn`, `runAoeTurn`, the caster executor, hide, flee, teleport-to-reach) do *how*. No per-cell movement policy in this plan. |
| D4 | **Observation = entity tokens:** one token per visible creature, plus a few map-summary tokens. It is built in C++ and bound to Python. The existing flat `getBattleObservation` is left untouched for compatibility. |
| D5 | **PC driver modes, switchable per run:** `Heuristic` (Level 4 drives the PCs) and `SelfPlay` (a learned policy drives them). `Human` is live play only, and its games are logged for later offline fine-tuning (Step 10). No online learning during a live session. |
| D6 | **Success metric:** the win rate of the Level 5 trees vs Level 4, on a **held-out** scenario set with **paired seeds** (same scenario and seed, swap only the NPC policy). Gate: beat Level 4 by **30 percentage points** (user, 2026-11-09). |
| D7 | **Playback first.** A trace format and a GUI Playback mode land before any training work, so every later step can be watched. Playback replays **recorded visual events + snapshots**; it does **not** re-execute the engine. The checked replay doesn't cover `run_npc_turn`'s internals. |
| D8 | **Determinism.** Simulations are seeded. Tree inference is pure and deterministic, so `test_determinism.py` and the golden stay byte-identical with Levels 5/6 off. Training itself need not be bit-reproducible. |
| D9 | **Brutality is a feature.** No "mercy" term in the reward. The DM picks Level 4 for a gentler table. |
| D10 | **Docker image** gains CPU-only `torch`, `numpy`, `scikit-learn`. The user builds the image; no project script builds it. CPU-only, because Docker on macOS has no GPU path. |
| D11 | **Levels 5/6 split:** Level 5 = trees from the teacher trained against `Heuristic` PCs. Level 6 = trees from the `SelfPlay`-hardened teacher. |
| D12 | **Parties come from saved party files *and* generated PCs.** Generated parties follow the role table below (the five party roles), so the sample set is large and balanced. |
| D13 | **Trace retention:** arena episodes keep a trace for a seeded 1-in-10 sample. Outcomes and summary stats are kept for every episode. GUI combats always write a trace. |

### PC party roles — class/subclass guess (Claude guesses, user checks)

These five **party roles** describe the *PC* side and drive the party generator. They are
separate from the five NPC archetypes in D2.

- **DEF**: defender / meat shield
- **ST**: single-target damage
- **MT**: multiple-target damage
- **CC**: crowd control
- **SUP**: support / healer

Each subclass gets a primary role and an optional secondary one. The generator builds the
**primary** about 75% of the time and the **secondary** about 25%. Each role has its own
build template (spell list, weapons, feats), so a Light Cleric built as CC really carries
control spells. Wizard Illusionist isn't implemented, so it's excluded.

| Class | Subclass | Primary | Secondary | Why (guess) | User check |
| --- | --- | --- | --- | --- | --- |
| Barbarian | Berserker | ST | DEF | Frenzy damage; rage resistances | y |
| Barbarian | Wild Heart | DEF | ST | Bear rage resists nearly everything | y |
| Barbarian | World Tree | DEF | SUP | Vitality of the Tree temp HP to allies; Branches pull | y |
| Barbarian | Zealot | ST | DEF | Divine Fury; very hard to kill | y |
| Bard | Dance | ST | SUP | Unarmored melee skirmisher | y |
| Bard | Glamour | SUP | CC | Mantle of Inspiration; Mantle of Majesty (Command) | y |
| Bard | Lore | CC | SUP | Cutting Words + extra Magical Secrets | y |
| Bard | Valor | SUP | ST | Combat Inspiration; Extra Attack | y |
| Cleric | Life | SUP | DEF | Disciple of Life; heavy armor | y |
| Cleric | Light | MT | CC | Radiance of the Dawn, Fireball; Warding Flare |y |
| Cleric | Trickery | CC | SUP | Hypnotic Pattern / Confusion domain spells | y |
| Cleric | War | ST | DEF | Guided Strike, War Priest; heavy armor | y |
| Cleric | Grave | SUP | ST | Circle of Mortality healing; Path to the Grave | y |
| Druid | Moon | DEF | CC | Wild Shape HP sponge | y |
| Druid | Land | CC | MT | Entangle / Sleet Storm; circle spells add blasts | y |
| Druid | Sea | MT | CC | Wrath of the Sea aura damage + push | y |
| Druid | Stars | SUP | ST | Chalice form healing; Archer form | y |
| Fighter | Champion | ST | DEF | Crit range; durable | y |
| Fighter | Battle Master | ST | CC | Trip / Menacing / Pushing maneuvers | y |
| Fighter | Psi Warrior | DEF | ST | Protective Field |y |
| Fighter | Eldritch Knight | DEF | ST | Shield + heavy armor | y |
| Monk | Open Hand | CC | ST | Topple / push riders; Stunning Strike | y |
| Monk | Mercy | SUP | ST | Hand of Healing | y |
| Monk | Shadow | ST | CC | Shadow Step burst; Darkness | y |
| Monk | Elements | MT | CC | Elemental Burst; elemental pushes | y |
| Paladin | Devotion | DEF | SUP | Aura of Protection; Sacred Weapon | y |
| Paladin | Glory | ST | SUP | Inspiring Smite temp HP | y |
| Paladin | Ancients | DEF | SUP | Aura of Warding | y |
| Paladin | Vengeance | ST | DEF | Vow of Enmity | y |
| Ranger | Beast Master | ST | DEF | Primal Companion as a second body | y |
| Ranger | Fey Wanderer | CC | ST | Beguiling Twist charm/frighten | y |
| Ranger | Gloom Stalker | ST | CC | Dread Ambusher alpha strike | y |
| Ranger | Hunter | ST | MT | Colossus Slayer, or Horde Breaker / Volley | y |
| Rogue | Thief | ST | SUP | Sneak Attack; Fast Hands items | y |
| Rogue | Arcane Trickster | CC | ST | Enchantment/Illusion spells + Sneak Attack | y |
| Rogue | Assassin | ST | — | Assassinate alpha strike | y |
| Rogue | Soulknife | ST | — | Psychic Blades | y |
| Sorcerer | Draconic | MT | ST | Blasts; Elemental Affinity on single-target spells (Draconic Resilience is only near-free Mage Armor, not DEF) | y (corrected by user) |
| Sorcerer | Wild Magic | MT | CC | Blasts + Tides of Chaos | y |
| Sorcerer | Aberrant | CC | MT | Psionic spells | y |
| Sorcerer | Clockwork | SUP | CC | Restore Balance, Bastion of Law | y |
| Warlock | Fiend | MT | ST | Fireball list; Dark One's Blessing | y |
| Warlock | Archfey | CC | SUP | Steps of the Fey; charm/frighten | y |
| Warlock | Great Old One | CC | ST | Psychic Spells; Awakened Mind | y |
| Warlock | Celestial | SUP | MT | Healing Light; Radiant Soul | y |
| Wizard | Abjurer | DEF | CC | Arcane Ward / Projected Ward | y |
| Wizard | Diviner | CC | SUP | Portent forces failed saves | y |
| Wizard | Evoker | MT | ST | Sculpt Spells, Potent Cantrip | y |

**Party templates**, drawn in these proportions:
- 50%: balanced 4, picking primary or secondary as ( DEF | ST, ST | MT, MT | CC | SUP, SUP).
- 30%: random 4 out of primary DEF, ST, MT, CC, SUP, no duplicates
- 20%: skewed, e.g. two DEF, no SUP, or a double caster. This guards against the policy overfitting to textbook parties.

Levels are drawn across all four tiers. A party's level and the mob CR budget come from
the 2024 encounter-difficulty table.

---

## Steps

### Step 0 — Dockerfile + plan freeze
- Add one `pip install` layer to the `Dockerfile`, pinned, CPU wheel index for torch:
  ```dockerfile
  RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 \
   && pip install --no-cache-dir numpy==2.1.3 scikit-learn==1.5.2
  ```
  Kept as a separate layer after the apt/pip layer, so the base layers stay cached.
  Expect roughly +700 MB of image size.
- **The user rebuilds `rpg_map`.** Verification, in the container:
  `docker run --rm rpg_map -c "python3 -c 'import torch, sklearn, numpy; print(torch.__version__, sklearn.__version__)'"`,
  then `./test.sh`. The suite must be unchanged; no code has changed yet.
- D1–D13 and the role table frozen 2026-11-09. The 75/25 primary/secondary split was
  accepted as proposed; the party-template proportions are the user's revision above.

### Step 1 — Simulation trace format + recorder
- New `gui/sim_trace.py`: a JSONL trace. The header holds the map path, the agents JSON
  (inline), the seed, the policy per side, and the PC mode. Then one record per turn: actor,
  round, the display snapshot taken before the turn (the same data `_npc_anim_snapshot`
  takes), the serialized `take_npc_visual_events()` list, and the combat-log lines. A
  footer holds the outcome.
- Visual events need a JSON round-trip, `to_dict` / `from_dict`. This may be done in Python
  or as a binding, whichever is smaller.
- The GUI writes a trace for every combat, next to `replay_log.txt` (and likewise
  untracked). Human turns record as snapshot + log only.
- Test: record → load → identical event stream (`tests/test_sim_trace.py`).
- **Implemented 2026-11-09 (226/0).** As built: the event round-trip is in
  Python (`event_to_dict` / `event_from_dict`, every field, kinds as strings pinned to
  `NpcVisualEvent.Kind`); loaded events are `TraceEvent`s with the engine's attribute
  names, so `_npc_anim_start` takes them unchanged. The GUI writes `gui/sim_trace.jsonl`
  (gitignored). Three additions to the format above:
  - `spawned` on a turn record: the agent records of summons/reinforcements placed since
    the last record. Header + all `spawned`, in order, is the raw agent list.
  - A prelude record (`actor: -1`) holds log lines written before the first turn.
  - Human turns also carry their move events (the `record_moves` slides), since Playback
    would otherwise teleport those tokens.
  A fight restored from a save opens a fresh trace lazily, with `resumed: true`.

### Step 2 — GUI Playback mode
- **Load Playback…** from the menu → a read-only board. The controls are play/pause,
  step one turn, step back one turn, a speed slider (½×–8×), and a round/turn scrubber.
- Each turn is fed through the existing `_npc_anim_start(events, snapshot, on_done)`. Step
  back = re-seed from that turn's snapshot. No engine calls, no autosave, nothing writes to
  the save, and nothing reaches the player server.
- A HUD line shows the round, the actor, the actor's archetype + chosen macro-action (once
  Step 5 records it), and the policy per side.
- Verified headlessly through `tests/gui_driver.py` (load a trace, step, PNG).
- **Implemented 2026-11-09 (227/0).** As built, in `gui/playback.py` + small hooks in `main.py`:
  - **Table menu → Load Playback…** opens a `.jsonl` trace. Refused mid-combat or while an
    animation plays; an unreadable trace, a missing map image or a roster that won't place
    is refused with a flash and leaves the scene untouched.
  - **The DM's scene is set aside, not reloaded.** Entering stashes `bm`, `combat`, the map
    surfaces, the index-keyed metadata and the view flags by reference and builds the
    trace's board in fresh objects (a bare `CombatEngine`, so the checked replay log is not
    touched). Exit puts the same objects back. The test checks identity, the board, the
    window size, the roster's ownership and that no file in the scene folder changed.
  - While Playback is up, `run()` skips net submits, the NPC drive, the fog reveal, the
    net pump and push; `_handle_events` hands Playback every event but a resize (Quit
    leaves Playback first, so its prompt and terrain save are the DM's scene's).
  - Controls: Back / Play-Pause / Step, a 5-stop speed slider (½× 1× 2× 4× 8×, scales the
    animation clock via `App._npc_anim_speed`), a scrubber with round ticks, the turn's
    log lines, Exit. Keys: Space, ←/→, +/−, Esc. HUD line on the map: round, actor,
    driver, policy per side; a gold ring marks the actor.
  - After the last turn the board shows that turn's events folded over its snapshot.
  - **Format addition:** the header now records `manual_grid`; an older trace falls back
    to grid auto-detection.
  - **Not drawn:** the trace has no terrain, so doors, painted walls, lights and spell
    effects don't show; it's the map image, its grid and the tokens. A later format
    version can add the terrain doc to the header if wanted.

### Step 3 — Headless arena
- New `gui/arena.py` (CLI + importable). `run_episode(scenario, seed, npc_policy,
  pc_mode)` → outcome + optional trace.
- **Scenario generator:** a party (from saved PC files) vs a mob mix drawn from
  `DND2024_MonsterStats.json` by CR budget and archetype mix, on a map from `maps/`. Train
  and held-out sets are split by a scenario-hash, not by seed.
- **Reaction windows auto-resolve headless.** This was flagged as FUTURE WORK in
  `NPC_AUTOMATION_PLAN.md`. A parked decision is answered by the side's policy (Level 4
  rules for now), so episodes never block.
- **PC modes** `Heuristic` / `SelfPlay` (D5); `SelfPlay` stubs to `Heuristic` until Step 7.
- **Benchmark:** turns/sec and episodes/hour on one core, plus `--jobs N` process
  parallelism. That throughput sizes Steps 6–7.
- A round cap ends the episode as a draw.
- Test: a fixed scenario + seed gives an identical outcome twice.
- **Implemented 2026-11-09 (228/0).** As built, in `gui/arena.py` + `tests/test_arena.py`:
  - **Board loading.** A headless `App` is used **only as the loader** (`_load_map_png`,
    `_load_terrain`, `_load_agents`, so spells, class features, armor and NPC spell groups
    load exactly as in the GUI). It is built on a temp copy of a tiny map, so nothing is
    written beside `maps/`. Each episode gets a bare `CombatEngine(seed)`.
  - **Fight loop.** The fight is an engine-only loop that mirrors the GUI's turn chain.
    Both sides run through `run_npc_turn`: NPCs at the policy's level, PCs at Level 4.
    Reactions are answered by `auto_reaction`, which takes the first option the engine
    offers; Vitality of the Tree targets the most-wounded ally within 10 ft.
  - **Not modelled** (human-driven in the GUI today): legendary actions, Keeper of Souls,
    Tides of Chaos on initiative, and Thief's Reflexes.
  - **Scenarios.** A party is drawn from a saved party source: an agents file, a single-PC
    file, or a campaign `pcs/` directory. The default is the tracked
    `maps/TestDNDMap_agents.json` party. Mobs are drawn from the bestiary by the SRD 5.2 XP
    budget (party level × Low/Moderate/High × party size) in a melee/ranged/caster mix.
    The groups are placed 6–12 cells' walk apart in the map's largest open region.
  - **Split.** Held out = sha256 of (map, terrain, each creature's name/side/cell) mod 5 == 0.
  - **Outcome.** Each episode reports the winner (`pc`/`npc`/None) and the reason
    (`victory`/`round_cap`, plus `stuck`/`no_initiative` as guards), along with rounds,
    turns, reactions, creatures standing, HP fraction per side, and timings.
  - **Round cap and traces.** The round cap defaults to 20. Traces are kept for a seeded
    1-in-10 sample (`--trace-dir`), or for every episode with `--trace-all`, and an arena
    trace opens in Playback.
  - **CLI.** `python3 gui/arena.py run|bench --episodes N --jobs N --split train|heldout
    --npc-policy levelK --pc-mode Heuristic|SelfPlay --out x.jsonl --trace-dir d/`.
  - **Benchmark** (container, 18 cores): one core runs ~0.04 s/episode, about 86k
    episodes/hour and ~12,900 turns/s inside fights. `--jobs 4` runs ~122k episodes/hour.
    About 80% of an episode is board loading (map analysis), the obvious thing to cache if
    Step 7 needs more.
  - **Engine fix found by the arena.** An automated *PC* cast leveled spells with
    `slot_level = 0`, which charged the spell's own level. With no slot at that level, the
    cast was free: a Warlock with only 5th-level pact slots cast Command 18 times in one
    fight. Fixed in `combat_turn.cpp` (`npcCastSlotLevel`): an automated PC now pays the
    lowest slot at or above the spell's level, and the teleport-to-reach path pays it too.
    NPCs are unchanged, so the determinism golden is unchanged.
  - **Open, for the user:** about 35% of episodes are draws at the 20-round cap. They are
    slow grinds, not stalemates: in 54 of 55 sampled draws the mobs had lost more than 10%
    of their HP. Ranged (kiting) mixes are over-represented, and the one tracked party is
    weak (its Rogue is at −2 to hit). Raise the cap, add parties, or score draws by HP
    before Step 9's win-rate gate.
  - **Not yet built:** D12's *generated* parties (the role-table generator: build templates
    per class/subclass/role across four tiers). It plugs in as another party source; it
    is proposed as Step 3b.

### Step 4 — Archetypes + fallbacks
- `enum class NpcArchetype { Melee, Ranged, Blaster, Controller, HealerSupport }`, plus
  `npcClassifyArchetype`. It refines the existing `NpcRole`: Caster splits on which Level 4
  planner the kit can feed (AoE → Blaster, control spells → Controller, heals/buffs →
  HealerSupport). Ties go by spell-slot weight. A per-agent DM override is optional.
- **Fallback chain**, applied at turn time and recorded in the trace:
  1. The tree's top macro-action, if it is legal and actionable now.
  2. The next-ranked actionable macro-action from the same tree (the leaves store a ranked
     list, not a single choice).
  3. The archetype's secondary role, e.g. Blaster with no slots → Ranged, Controller →
     Blaster → Ranged, HealerSupport → Controller → Ranged, Ranged with no ammo/LOS →
     Melee.
  4. The Level 4 resolver.
  5. `Simple`.
- No model file present → Level 4 for the whole run, with the existing one-time log line.
- Tests: classification fixtures per archetype; each fallback rung is forced and observed.
- **Implemented 2026-11-09 (229/0, uncommitted).** As built, in `combat_turn.cpp` +
  `tests/test_npc_archetypes.py`:
  - **Classifier.** `npcClassifyArchetype`: Melee/Ranged carry over from `NpcRole`. A Caster
    tallies its *known* combat-relevant spells (not just castable ones, so the archetype
    doesn't flicker as slots drain) with the planners' own predicates: AoE blast →
    Blaster, `control_priority` → Controller, HP heal or Help buff → HealerSupport. The
    largest tally wins, ties go by summed spell level, then Blaster → Controller →
    HealerSupport. A caster feeding none of the three (single-target damage only) is
    **Ranged**, which is what Level 4 already runs it as.
  - **Chain.** `npcDecide` returns an `NpcDecision` (archetype, rung, strategy);
    `resolveStrategy` is now `npcDecide(...).strategy`, and Levels 1–4 are the old code
    moved unchanged into `resolveHeuristicStrategy`. Every rung uses one test,
    `npcStrategyActionable`, which probes the executors' own planners. Ranged needs a ranged
    weapon and LOS to an enemy (the engine tracks no ammo). Rung 3 walks the archetype's
    strategies, then its secondaries': Melee {Simple}, Ranged {Hide (only with stealth
    tools), Range}, Blaster {AoE}, Controller {Control}, HealerSupport {Heal, Support}.
    Every chain ends Ranged → Melee. Rung 4 is taken only when Level 4's pick is
    actionable; rung 5 is unconditional Simple.
  - **Stand-in model.** Until Step 8 there are no trees, so a model is a ranked strategy
    list per archetype (`set_npc_archetype_model`), what a tree leaf will hold. Strategies
    stand in for Step 5's macro-actions. No model at all → Level 4 exactly, rung
    `Heuristic`. Some models, but none for this archetype → the chain starts at rung 3.
    Models live in memory only (no file format yet), and are not in a snapshot.
  - **Recorded.** `runNpcTurn` keeps the fresh turn's decision (`last_npc_decision`; reset
    at every fresh turn, so a corpse/Flee/Forcecage turn reports none). The GUI and the
    arena write it on the turn record as `decision: {level, archetype, rung, strategy}`;
    the Playback HUD shows `· Blaster: PreferAOE (rung 3 archetype)`.
  - **Not built:** the optional per-agent DM archetype override (it needs an agent-file
    field and a panel widget). Postponed by the user 2026-11-09. Determinism golden unchanged.
  - **User-checked 2026-11-09:** the stand-in model, "an archetype without a model starts
    at rung 3", and "owning a ranged weapon is the ammo test" are all accepted.

### Step 5 — Macro-action space + entity observation (C++)
- `availableMacroActions(bm, idx)` returns a list of `{kind, target_agent, target_cell,
  spell_idx}` built from the Level 4 planners: Attack, Kite, AoE, Control, Heal, Support,
  Hide, Dash, Disengage, Dodge, Flee, plus a legality mask.
- `executeMacroAction(bm, idx, action)` routes into the existing executors and keeps the
  park/resume contract (`NpcTurnState`).
- `getEntityObservation(bm, idx)` returns one fixed-width token per creature (self
  first). Each token holds: side, archetype, HP fraction, temp HP, AC, a speed/reach/range
  summary, a condition bitset, concentration, spell slots by tier, key resources, position
  relative to the actor, LOS, cover, whether it threatens the actor, and whether the actor
  threatens it. Map tokens summarize the local cover/chokepoint density.
- A new `NpcAutomationStrategy::Policy` dispatches through a pluggable C++ policy interface;
  trees implement it in Step 8, and Python can drive it from the arena.
- Every macro-action choice goes into the trace and the Playback HUD.
- Determinism golden unchanged.
- **Implemented 2026-11-09 (230/0), committed 5d42944.** As built, in `combat_turn.cpp` (+ types in
  `combat_types.hpp`, the interface in `combat.hpp`, bindings) and `tests/test_npc_macro_actions.py`:
  - **Kinds.** `NpcMacroKind` has 11 values: Attack, Kite, AoE, Control, Heal, Support, Hide, Dash,
    Disengage, Dodge, Flee. `NpcMacroAction` is `{kind, target_agent, target_cell, spell_idx, legal}`.
  - **Candidates.** `available_macro_actions` lists every candidate in a fixed order (kind, then
    spell, then target), each flagged `legal`; `macro_action_mask` gives one bool per kind. Attack,
    Kite and Dash get one candidate per enemy in play. AoE and Control get one per castable spell ×
    enemy (an area must net at least one enemy). Heal and Support get one per castable spell ×
    self/ally. Hide, Disengage, Dodge and Flee get one each. An actor that can't act has nothing legal.
  - **Execution.** `execute_macro_action` routes into the existing executors. Attack is the Simple
    turn and Kite the PreferRange turn, each with the target forced (`NpcStrategyPolicy::forced_target`).
    Hide is the PreferHide turn with its own targeting. AoE, Control, Heal and Support run
    `runAoeTurn` / `runCasterTurn` on a forced plan (`npcForcedAoePlan` / `npcForcedCastPlan`). Dash,
    Disengage, Dodge and Flee run a small new move-only executor. Park/resume is unchanged: a
    parked Policy turn stamps its macro on `NpcTurnState` (`has_macro`, `macro`, serialized), and
    the resume runs that macro again without asking the policy.
  - **Policy seam.** A C++ `NpcPolicy::rank(engine, bm, agent, archetype, actions) → indices` (Step 8's
    trees implement it). `set_npc_policy(callable)` wraps a Python callable. The new
    `NpcAutomationStrategy::Policy` (9) is used at Levels 5/6 once a policy is installed: the first
    legal index is rung 1 if it is the top one, rung 2 otherwise. Nothing legal → the Step 4 chain
    from rung 3. A policy replaces the Step 4 stand-in models. At Level 0 the Policy strategy field
    asks the policy too, and with none it fights Simple. An exception raised by the policy reaches
    the caller of `run_npc_turn` / `npc_decide`. `Policy` is not in the GUI's strategy menu.
  - **Recorded.** `NpcDecision` gains `has_macro`, `macro` and `macro_text`. The trace's `decision` gains
    `macro: {kind, target, cell, spell, text}`. The Playback HUD shows
    `· Melee: Attack → Goblin (rung 1 tree)`.
  - **Labels for Step 6.** `npc_heuristic_macro_action` gives Level 4's choice as the best-matching
    candidate.
  - **Observation.** `get_entity_observation` returns `agent_indices`, `creature_tokens` (55 floats each;
    names from `entity_observation_fields()`) and an 8-float `map_token` (`map_observation_fields()`).
  - **Arena.** `--npc-policy l4-macro` installs a Python policy that picks Level 4's own label, and
    `random-macro` installs a seeded random legal pick. Both run at Level 5.
  - **Parity check** (300 episodes each, same scenarios + seeds): `level4` NPCs win 26.0%, `l4-macro`
    25.7%, and 252/300 paired fights end the same. `random-macro` wins 7.3%. The macro path
    reproduces Level 4, and the choice of macro-action matters.
  - **For the user to check:**
    1. *A forced target is never swapped.* An Attack/Kite on an enemy it can't reach this turn Dashes
       toward it. Level 4 instead retargets to whoever it can reach. This is most of the 48 paired
       divergences above.
    2. *Casts are legal out of range.* The executor closes the distance first, as Level 4 does. Heal
       is legal on any ally below max HP; Level 4's 50% threshold is its own judgment, not a rule.
    3. *Tokens cover every creature in play, with a `perceived` flag.* The plan said "one token per
       visible creature". Dropping hidden/invisible enemies would leave Attack candidates with no
       token to point at, so they are flagged instead. The dead are left out.
    4. *"Cover" is `exposure`.* The engine has no half/¾-cover model, so a token carries the share of
       its creature's standing enemies that have line of sight to it.
    5. *One map token*, not several: wall density at radius 2 and 5, a corridor measure, the share of a
       full move's square that is reachable, and nearby/total enemy and ally counts.
    6. *Hide is one candidate* with PreferHide's own targeting, not one per enemy.
  - **Not built:** the Playback HUD shows a macro only for Policy turns; it shows no Level 4 label
    on heuristic turns. Step 6's dataset writer calls `npc_heuristic_macro_action` itself.

### Step 6 — Imitation baseline (behavior cloning of Level 4)
- `gui/ml/` (new): the dataset writer, an entity transformer (about 4 layers, d=128,
  archetype token, masked softmax over macro-actions), and the training loop.
- Labels: the macro-action Level 4 chose, recorded through Step 5's mapping.
- **Gate:** ≥ 90% top-1 agreement on held-out data, **and** win rate vs Level 4 within ±3
  points. This proves the pipeline, not intelligence.
- **Code written 2026-11-09; not trained (user: "Don't train yet") and the suite not yet run.**
  As built, in `gui/ml/` + `tests/test_ml_bc.py`:
  - `dataset.py`: arena episodes with the NPCs on `l4-macro`; each decision is featurized
    (`features.py`) and labelled with Level 4's candidate → npz shards in `ml_runs/` (gitignored),
    tagged by scenario split. 6000 episodes → 235k decisions in 53 s on 16 jobs.
  - **Defer.** ~8.5% of decisions have Level 4 choosing a turn no legal candidate matches (e.g.
    Simple with no targetable enemy); `l4-macro` then hands the turn to the Step 4 chain. These
    get the label Defer, and the model has a Defer output that does the same (policy returns
    `[]`). Decisions with nothing legal at all aren't stored. *For the user to check.*
  - `model.py`: [archetype, map, creatures…] pre-norm encoder (4 layers, d=128); each candidate
    scored from its features + its target's token + self + archetype; masked softmax + Defer.
  - `train.py` (held-out top-1 per kind/archetype, best epoch kept), `policy.py` (arena
    `--npc-policy bc --model x.pt`, one-thread inference), `gate.py` (both gate numbers, paired
    held-out seeds, 95% CI on the win-rate difference).

### Step 7 — Reinforcement learning (PPO)
- Start from the Step 6 weights. Reward: +1 win / −1 loss / 0 draw, plus a small
  HP-weighted damage-dealt-minus-taken term per round. Team reward is shared across the
  NPC side.
- `pc_mode=Heuristic` first. `SelfPlay` then trains a PC-side policy against a pool of
  past NPC snapshots, so it doesn't overfit to one opponent.
- Checkpoints are evaluated on the held-out set each epoch, and Playback traces of
  sampled episodes are saved for watching.

### Step 8 — Distill to per-archetype trees
- For each archetype, fit a `DecisionTreeClassifier` (depth-capped, about 8–12) on
  (engineered features → teacher's ranked actions). Features come from the entity tokens,
  aggregated: nearest enemy by threat, lowest-HP ally, count of enemies in the AoE
  template, the concentrating enemy, and so on.
- Export to JSON (`gui/npc_models/<archetype>.json`); the C++ evaluator loads it. Trees
  are diff-able and DM-readable, and a `tools/print_tree.py` renders them as if/then text.
- Report the win-rate gap between tree and teacher per archetype.

### Step 9 — Levels 5/6 + evaluation tournament
- Level 5 = trees distilled from the `Heuristic`-PC teacher. Level 6 = trees distilled
  from the `SelfPlay`-hardened teacher.
- `tools/tournament.py`: paired-seed held-out evaluation → win rate per level pair, broken
  down by archetype mix and CR, with confidence intervals.
- **Gate (D6):** Level 5 beats Level 4 by ≥ X points.
- GUI: Levels 5/6 become selectable without clamping once model files exist.

### Step 10 — Learning from human play (later)
- Live sessions with a "log for training" toggle append `Human`-mode trajectories. An
  offline fine-tune → redistill → tournament gate cycle runs before any new trees ship.

---

## Open items for review
1. ~~X in D6~~ → 30 points (D6).
2. ~~Level 5/6 split~~ → keep it (D11).
3. ~~Scenario sources~~ → both (D12); the role table above is awaiting the user's check.
4. ~~Trace retention~~ → 1-in-10 sample (D13).
5. ~~Party template proportions and the 75/25 split~~ → 75/25 accepted; templates revised by the user.
