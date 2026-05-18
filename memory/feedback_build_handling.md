---
name: User handles all builds
description: Do not attempt C++ builds or docker operations; user manages compilation
type: feedback
originSessionId: 5d137bad-b42c-4631-af40-e332b3ff2d1c
---
User builds the C++ extension themselves. Do not attempt:
- Running `cmake` commands
- Using `bash build.sh`
- Docker operations
- Any `ninja` or compiler invocations

**Why:** User has their own build environment and preferences. Builds can create artifacts with ownership/permission issues that interfere with their workflow.

**How to apply:** When C++ changes are made, document what changed and let user know they can now build. Never proactively attempt compilation.
