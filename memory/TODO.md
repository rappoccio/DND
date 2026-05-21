# D&D 5e Battle Map - To-Do List

## Completed ✓

### Portent Dice (Diviner L3) - COMPLETE
- [x] Implement Portent Dice resource (2 uses at L3, 3 at L14)
- [x] Portent Dice regenerate on long rest
- [x] UI display of available portent dice
- [x] "Use Portent Die" button with context menu
- [x] Per-agent, per-round enforcement (one use per round)
- [x] Integration with advantage/disadvantage rolls
- [x] Spell attack rolls with portent dice
- [x] Test suite (7 tests passing)

### Barbarian Rage (L1 Feature) - COMPLETE
- [x] Rage bonus action button
- [x] Rage initialization as class resource
- [x] Rage damage resistance (0.5x physical damage)
- [x] Combat UI integration
- [x] Rage lifecycle and duration tracking

### Subclass System - COMPLETE
- [x] Subclass selection UI in stats dialog
- [x] Barbarian subclasses: Berserker, WildHeart, WorldTree, Zealot
- [x] Wizard subclasses: Abjurer, Diviner, Evoker, Illusionist
- [x] Subclass persistence (save/load JSON)
- [x] Resource initialization after subclass selection
- [x] Subclass reset when class changes

## In Progress

### Abjurer L3 (Arcane Ward)
- [ ] Implement Arcane Ward resource
- [ ] Ward grants damage reduction
- [ ] Ward breaks when threshold exceeded
- [ ] Integration with class resources system

## Backlog

### Barbarian L6+ Features
- [ ] Berserker L6: Extra Attack
- [ ] Wild Heart L6: Rage of the Wilds improvements
- [ ] WorldTree L6: Branches of the Tree (tree summon) - deferred, needs implementation system
- [ ] Zealot L6: Zealous Presence

### Wizard L6+ Features
- [ ] Abjurer L6: Arcane Deflection (reaction system needed)
- [ ] Diviner L6: Improved Portent (exploit/deny rolls)
- [ ] Evoker L6: Potent Cantrip (damage reduction implementation)
- [ ] Illusionist L6: Illusory Reality (deferred, needs implementation system)

### Known Limitations (Deferred)
- Panther Aspect (climb speed) - requires movement system extension
- Branches of the Tree - requires object placement/summon system
- Illusory Reality - requires implementation system
- Team dynamics (red/blue team for Evoker) - global state tracking needed

## Notes

- Resource initialization must happen AFTER subclass is set (subclass affects which resources are created)
- Portent Dice must be applied after advantage/disadvantage logic, not during
- All class features are in C++; Python UI handles rendering and event dispatching
