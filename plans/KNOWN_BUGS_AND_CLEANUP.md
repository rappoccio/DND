# Known Bugs & Cleanup

Running list of latent bugs and cleanup tasks discovered during development that
are not urgent enough to fix inline but should not be forgotten.

---

## ~~`Weapon::attack_bonus` is a dead field the to-hit roll ignores~~ — RESOLVED 2026-07-08

Removed the dead `Weapon::attack_bonus` field entirely: dropped it from `weapon.hpp` and its
`rpg_bindings.cpp` binding, stripped the inert `attack_bonus` keys from `beast_forms.json`,
and cleaned every `test_*.py` usage (deleted the no-op `w.attack_bonus = …` assignments,
removed the `attack_bonus` param from the weapon-factory helpers, deleted `test_combat.py`'s
round-trip test of the field, and rewrote `test_druid.py`'s assertion to check the beast
weapon's name instead). The real flat to-hit field is `w.bonus_hit`. Deletion was
behavior-neutral — the engine never read `attack_bonus`, so no roll outcome changed.
Built + full `test_*.py` run confirmed all green (2026-07-08).

---

## ~~Panel click dispatch is a flat `if` chain — one click can fire several buttons~~ — RESOLVED 2026-07-14

`_handle_events` (`gui/main.py`, the `if not self.combat_active:` panel section) tests every
panel button against the same event with independent `if btn.clicked(event):` statements and
no `continue`. A handler that *blocks* and then *moves the panel rects* therefore lets the
same `MOUSEBUTTONDOWN` be re-matched against buttons that have since slid under the cursor.

This is not hypothetical — it shipped as a live bug: clicking **Generate Dungeon** on a
multi-floor run opened the file browser. `_on_generate_dungeon` blocks for the whole
generation and ends in `_switch_to_page` → `_load_map_png` → `_reposition_panel()`
(main.py:869), and opening the manifest turns on the Floor-nav block, which pushes every
config row down (`shift`, main.py:1084). The stale click then landed on whatever button had
moved into those coordinates, and `Load Lighting` / the Dungeon menu are both still ahead in
the chain. First patched by adding `continue` to the three handlers that block and re-anchor the
panel (Generate Terrain, Generate Dungeon, Dungeon…).

Fixed properly 2026-07-14: the whole panel run is now first-match-wins. A `_claimed` latch plus
a `_hit(btn)` helper sits at the top of the `if not self.combat_active:` block, every
`if self.btn_x.clicked(event):` became `if _hit(self.btn_x):`, and the three ad-hoc `continue`s
are gone. The rect-based ✕ (remove pending agent) hit-test takes the same latch, since a
relayout could otherwise slide a ✕ under a spent click too. The Floor-nav rects are dispatched
earlier in `_handle_events` and already `continue` out, so they were left alone. A click can now
belong to exactly one panel widget, and a future handler that relayouts can't reintroduce this.

---

## ~~`FileBrowser` shows one generic title for seven different jobs~~ — RESOLVED 2026-07-14

`dialogs.py:89` hardcodes the title:

```python
self._title = "Save Layout As" if save_mode else "Open Layout / Select Sprite"
```

so every read-mode use shows **"Open Layout / Select Sprite"** regardless of what is actually
being picked: Load (encounter), Load PCs, Load Terrain, Load Lighting, Dungeon → Open
(manifest), Dungeon → Add Page (map PNG), and right-click → Edit Sprite. Each caller already
passes the correct `extensions` / `name_pattern`, so the *list* is filtered right — only the
heading lies. The name is a leftover from when the browser did just two things.

Cost of the confusion: when the Generate Dungeon bug above wrongly opened the browser, the
title gave no clue which button had really fired, which is most of what made it hard to
diagnose.

**Fixed 2026-07-14:** `FileBrowser.open()` takes a `title=` keyword (defaulting to `""` →
the old generic strings, so any future caller that forgets it still works). All nine call
sites now say what they mean: Save Encounter As, Load Encounter, Load PCs, Save Terrain As,
Load Terrain, Load Lighting, Open Dungeon, Add Page — Select Map Image, Select Sprite.
