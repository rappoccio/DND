# Spell Scrolls Plan

The ask (user, 2026-11-10): *"Let's add Spell Scrolls. A consumable item that casts one spell
with a specified Spell Save DC."*

Builds on the enspelled-items mechanism (`plans/ENSPELLED_ITEMS_PLAN.md`, E1–E6): a scroll is
an item carrying `item_spell_groups: {"1": [spell]}` plus a fixed `spell_dc` / `spell_attack`.
Everything that plan built (cost path, D2 slot exemption, DC override, grant/revoke, menu labels,
NPC chooser) applies unchanged.

## Step 0 — decisions (frozen 2026-11-10)

Changes to this set need a dated amendment with a reason, agreed by the user.

| # | Decision |
|---|----------|
| S1 | **One generic catalog entry**, `"Spell Scroll"` in `items.json`, new `ItemType::Scroll`. The spell and DC are chosen when the DM *makes* a scroll (adding it to an inventory, a chest or the floor), not one catalog entry per spell. The made scroll is a full record (`item_spell_groups`, `spell_dc`, `spell_attack`), so it saves, moves and loads like any enspelled item. |
| S2 | **DC and attack default from the 2024 DMG table** by spell level (cantrip–2: DC 13 / +5; 3–4: 15 / +7; 5–6: 17 / +9; 7–8: 18 / +10; 9: 19 / +11) and the DM can edit both. Shown as **Spell Scroll (Fireball), DC 15**. |
| S3 | **Single use, then gone.** Casting spends the one use and deletes the inventory row (C++, in the cost path, so PCs and NPCs both get it). No long-rest refill. No attunement. |
| S4 | **No stacking**: two Fireball scrolls are two rows (the enspelled rule; quantity stays 1). |
| S5 | **Who can read it: the class list, with a DM override.** The spell must be on the class spell list (`spells_raw.json` `classes`) of one of the creature's classes. A per-creature DM tick, *Can read scrolls*, lets classless monsters or edge cases cast from any scroll. A scroll the holder can't read stays in the inventory but isn't offered in the spell menu. |
| S6 | **Cast at the spell's base level** (enspelled D6); casting time and concentration are the spell's own. No material components (the engine doesn't model them anyway). |
| S7 | **Counts as casting a spell** (Counterspell, concentration break and so on apply), and it's exempt from the one-slot-per-turn rule (enspelled D2). |

### Schema (a made scroll, in an inventory / chest / save)

```json
{"name": "Spell Scroll (Fireball)", "type": "Scroll", "action_type": "NoAction",
 "consumable": true, "quantity": 1,
 "item_spell_groups": {"1": ["Fireball"]}, "spell_dc": 15, "spell_attack": 7}
```

## Amendments (2026-11-10, during SS1)

- **A1 (S3, when the row goes):** a spent scroll is erased by `CombatEngine::discard_spent_scrolls`,
  called at the top of `sync_item_spells` (so every E3 hook, including each turn start), not inside
  the cast itself. Conditions, spell effects and terrain effects store the caster's spell *index*, so
  erasing mid-cast would leave them pointing at the wrong spell. A scroll whose spell is still live
  (held concentration, or a condition/effect it made) is kept, uncastable, until that ends. Later
  rows' spell tags are shifted down in C++.
- **A2 (schema):** the made scroll's own `name` is `Spell Scroll (<spell>)` (an `Item` has no
  `label`); `type: "Scroll"` is what marks it. A blank catalog scroll (no spell) is never discarded.
- **A3 (S2, the DM's fields):** one text prompt, `"15 +7"`, rather than two fields. A bare `"17"`
  gives attack 17 − 8 = +9, which is how the DMG table pairs them on every row.

## Steps (after sign-off)

| # | Step | Status |
|---|------|--------|
| SS1 | **Model + engine.** `ItemType::Scroll`; binding; catalog entry; the cost path deletes a spent scroll's row; class-list gate if Q1 says so. Tests: cast uses the scroll's DC and no slot, the row is gone afterwards, save → load keeps an unused scroll, the gate refuses or allows as Q1 decides. | done 2026-11-10 (uncommitted): `Item::Scroll`; `Stats::reads_any_scroll` (bound, saved, snapshot); `discardSpentScrolls` (A1); use_item refuses a scroll; long rest skips scrolls. `helpers`: `SCROLL_DC_TABLE`, `spell_classes` (spells_raw.json + 17 non-SRD extras), `scroll_spell_names`, `can_read_scroll` (EK/AT read Wizard), `make_spell_scroll`, `is_blank_scroll`; the S5 gate in `item_spell_entries`. `items.json` "Spell Scroll". `test_spell_scrolls.py` (8); suite 240/0 |
| SS2 | **Making a scroll (DM).** A spell picker + DC/attack fields (prefilled from S2) wherever Spell Scroll is picked from the catalog: Items dialog, chest contents, Place item. | done 2026-11-10 (uncommitted): `ItemSelectionDialog.finish` hook (every caller of the shared item picker: Items dialog, chest contents, Place item) → `items_play.finish_spell_scroll`: spell picker limited to `scroll_spell_names`, then one prompt "DC +attack" prefilled from the table (A3); `helpers.parse_scroll_dc`. Esc at either step adds nothing. `test_spell_scrolls_gui.py` (5); suite 241/0 |
| SS3 | **Play + NPCs.** Menu label, side panel, player sheet (reuse the E4 helpers); an automated caster carrying a scroll uses it through the existing chooser. Tests. | done 2026-11-10 (uncommitted): menu label `Fear (scroll, DC 15)`; Items-dialog rows, side panel and player sheet show one `DC 15 · +7` line (panel and sheet flag "can't read"; sheet carries `readable`); DM creature menu *Reads any scroll* toggle (offered once a scroll is carried) re-grants at once; `_finish_cast` re-syncs after an item cast, so a spent scroll goes immediately, out of combat too; `make_spell_scroll(dc=…)` alone pairs attack DC − 8 (A3). NPC chooser needed no change. `test_spell_scrolls_play.py` (5); suite 242/0 |
| SS4 | **Live check** by the DM, then `known_limitations.md`. | |
