"""NPC learning (NPC_LEARNING_PLAN.md Steps 6+): the dataset writer, the entity transformer,
its training loops (behaviour cloning, PPO), and the policy that runs a checkpoint in the arena.

    features.py   one decision → arrays (entity tokens, map token, archetype, candidates)
    dataset.py    arena episodes under Level 4's own labels → npz shards
    model.py      the entity transformer that scores candidate macro-actions
    train.py      behaviour cloning on the shards; held-out top-1 agreement
    policy.py     a checkpoint as an arena / engine policy (set_npc_policy)
    gate.py       Step 6's gate: agreement and paired win rate vs Level 4
    ppo.py        Step 7: PPO from the BC weights; Heuristic and SelfPlay runs, held-out eval

Everything here runs in the container (torch is in the rpg_map image since Step 0).
"""
