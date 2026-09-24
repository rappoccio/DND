"""The session roster: principals, credentials, and the one authorization chokepoint.

Implemented from the frozen schema in ``plans/MULTIPLAYER_PLAN.md`` Step 0.4. Nothing
here may be changed without a dated amendment in that document.

The shape of the thing, in one paragraph: a **principal** is a person at the table and
persists across runs in ``<base>_session.json``; a **credential** is the bearer token a
principal presents on a request and dies with the process; a **seat** is a principal's
place at the table; a **token** is a creature on the map. Ownership of a token is stored
once and only once — in the agent record's ``controller`` field, which rides along in
``<base>_agents.json`` (constraint A1). This module never persists agent indices, because
``_save_agents`` drops summons and tombstoned agents and renumbers what is left, so any
index written to disk is basis-dependent and silently wrong on the next load.

Session-scoping is free rather than arithmetic: the credential signing key is generated in
memory at construction and never written anywhere (A5), so every credential minted by a
previous run is unverifiable by this one.
"""

from __future__ import annotations

import base64
import enum
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, replace
from typing import Callable, Iterable

from atomic_io import atomic_write_json

# The DM console's principal id. A token whose controller is this (the default for every
# agent record) is DM-driven. It is a reserved id: a player can never be minted with it.
DM_PRINCIPAL_ID = "dm"

# The party's faction id, duplicated from gui/constants.py so this module stays importable
# without the GUI (the headless tests and, later, the net thread both rely on that).
PC_FACTION = 2

PROTOCOL_VERSION = 1

# NN7: the autosave ring depth, configurable per session, clamped to this range.
MIN_AUTOSAVE_SLOTS = 1
MAX_AUTOSAVE_SLOTS = 5
DEFAULT_AUTOSAVE_SLOTS = 3

# How long a freshly minted credential is nominally good for. Credentials die with the
# process regardless (A3), so this only bounds a long-running session; the field exists
# from day one because M8 needs the slot (A4).
CREDENTIAL_TTL_SECONDS = 12 * 3600

# Join codes avoid 0/O and 1/I/L: they get read aloud across a table.
_JOIN_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_JOIN_CODE_LEN = 6


class Role(enum.Enum):          # a role is not an identity (A8). Read ONLY inside
    DM     = "dm"               # authorize() — no call site may branch on it.
    PLAYER = "player"           # a PLAYER owning zero tokens is a spectator.


@dataclass(frozen=True)
class AuthBlock:                # A4: the slot M8 fills, present from day one
    method:  str = "join_code"  # v1 only ever writes "join_code"; later "oidc" / "password"
    subject: str | None = None  # the IdP's subject id, when there is one


@dataclass(frozen=True)
class Principal:                # PERSISTED in <base>_session.json, survives restarts
    id:           str           # "p_7f3a…" opaque + stable; the ONLY thing agents reference
    display_name: str           # a label. Never a key, never compared, never persisted
    role:         Role          #   anywhere but here (A1)
    auth:         AuthBlock = AuthBlock()


@dataclass(frozen=True)
class Credential:               # IN MEMORY ONLY. Dies with the process (A3/A5).
    kid:          str           # key id, so a single credential can be revoked
    principal_id: str
    exp:          float         # populated even though lifetime is session-scoped (A4)


class Action(enum.Enum):
    # reads
    VIEW_SESSION      = "view_session"       # may connect / receive any view at all
    VIEW_TOKEN_VITALS = "view_token_vitals"  # hp numbers + conditions
    VIEW_TOKEN_SHEET  = "view_token_sheet"   # full stat block, resources, slots
    VIEW_DM_CHANNEL   = "view_dm_channel"    # private notes, enemy stat blocks, whole map
    # writes
    CONTROL_TOKEN     = "control_token"      # act as this creature
    ANSWER_PROMPT     = "answer_prompt"      # submit a response to a live prompt
    DM_COMMAND        = "dm_command"         # takeover, kick, reveal, force-advance,
                                             #   rotate join code, restore an autosave slot


@dataclass(frozen=True)
class TokenTarget:
    """A LIVE agent index. Safe to hold precisely because it never reaches disk (A1)."""
    agent_idx: int


@dataclass(frozen=True)
class PromptTarget:
    prompt_id: str


# Step 0.4 writes this as `None | TokenTarget | PromptTarget`; the operands are reordered
# only because `None | cls` is a TypeError at runtime. The type is unchanged.
Target = TokenTarget | PromptTarget | None


@dataclass(frozen=True)
class TokenInfo:
    """The slice of an agent record authorization needs. Built on the pygame thread from
    ``bm.placed_agents`` and handed over by value — the roster never holds a ``BattleMap``
    reference, so it cannot violate NN1 even by accident."""
    agent_idx:  int
    controller: str
    faction:    int


class SessionRoster:
    """Principals, credentials, ownership, and ``authorize()`` — the single chokepoint.

    Every read projection and every state-changing submission passes through
    ``authorize()`` (NN6). No call site does its own check, and no call site branches on
    ``Role``; that enum is read here and nowhere else (A8).
    """

    def __init__(self, join_code: str | None = None,
                 autosave_slots: int = DEFAULT_AUTOSAVE_SLOTS):
        # The signing key: process-local, never serialized. Regenerating it invalidates
        # every outstanding credential at once, which is A5's panic button.
        self._signing_key: bytes = secrets.token_bytes(32)
        self.join_code: str = join_code or self.generate_join_code()
        self.autosave_slots: int = _clamp_slots(autosave_slots)
        self._principals: dict[str, Principal] = {}
        # In-memory only: credentials die with the process, so a revocation list on disk
        # would only ever list ids that can no longer be presented.
        self._revoked_kids: set[str] = set()
        # Ownership cache. Derived from the agent records, never persisted, rebuilt by
        # sync_tokens() on load and on any roster or agent-list change.
        self._tokens: dict[int, TokenInfo] = {}
        self._owned: dict[str, list[int]] = {}
        # Installed by the prompt bus in M1: prompt_id -> (owner principal id, is_live).
        # Kept as a hook so authorize() keeps Step 0.4's exact frozen signature while the
        # liveness check NN4 needs still has a source of truth.
        self.prompt_lookup: Callable[[str], tuple[str | None, bool]] | None = None
        # The DM always has a seat, even in a brand-new session with no file behind it.
        self._principals[DM_PRINCIPAL_ID] = Principal(
            id=DM_PRINCIPAL_ID, display_name="DM", role=Role.DM, auth=AuthBlock())

    # ── Principals ──────────────────────────────────────────────────────────

    @property
    def principals(self) -> list[Principal]:
        """Every seated principal, DM first, then players in insertion order."""
        return list(self._principals.values())

    def players(self) -> list[Principal]:
        return [p for p in self._principals.values() if p.role is Role.PLAYER]

    def get(self, principal_id: str) -> Principal | None:
        return self._principals.get(principal_id)

    def display_name(self, principal_id: str) -> str:
        """A label for the UI. Falls back to the raw id so an orphaned controller is
        visible to the DM rather than silently rendering as the DM's own token."""
        p = self._principals.get(principal_id)
        return p.display_name if p else principal_id

    def add_principal(self, display_name: str, role: Role = Role.PLAYER,
                      auth: AuthBlock | None = None) -> Principal:
        """Mint a new seat. The id is opaque and random — never derived from the display
        name, which is a label the DM can change at any time (A1)."""
        pid = _new_principal_id()
        while pid in self._principals:          # astronomically unlikely; cheap to rule out
            pid = _new_principal_id()
        p = Principal(id=pid, display_name=display_name.strip() or pid,
                      role=role, auth=auth or AuthBlock())
        self._principals[pid] = p
        self._rebuild_ownership()
        return p

    def rename_principal(self, principal_id: str, display_name: str) -> None:
        p = self._principals.get(principal_id)
        if p is None:
            return
        self._principals[principal_id] = replace(p, display_name=display_name)

    def remove_principal(self, principal_id: str) -> None:
        """Unseat a principal. The DM's seat cannot be removed. Tokens they controlled are
        NOT rewritten here — an unknown controller loads as DM-controlled (A1), which is
        the harmless outcome, and the DM can reassign at leisure."""
        if principal_id == DM_PRINCIPAL_ID:
            return
        self._principals.pop(principal_id, None)
        self._rebuild_ownership()

    # ── Credentials ─────────────────────────────────────────────────────────

    def generate_join_code(self) -> str:
        """A fresh join code. An invite that mints a credential, never an identity (A2):
        one table-wide code is safe because each join mints a distinct principal."""
        return "".join(secrets.choice(_JOIN_CODE_ALPHABET) for _ in range(_JOIN_CODE_LEN))

    def rotate_join_code(self) -> str:
        self.join_code = self.generate_join_code()
        return self.join_code

    def check_join_code(self, code: str) -> bool:
        """Constant-time compare, case-insensitive: the code is typed by a human."""
        return hmac.compare_digest((code or "").strip().upper(), self.join_code.upper())

    def mint_credential(self, principal_id: str,
                        ttl_seconds: float = CREDENTIAL_TTL_SECONDS) -> str | None:
        """Issue a bearer credential for a seated principal. Returns the wire string, or
        None if the principal has no seat. The credential is signed, not encrypted — it
        carries no secret, only a claim this process can verify."""
        if principal_id not in self._principals:
            return None
        return self.encode_credential(Credential(kid=secrets.token_hex(8),
                                                 principal_id=principal_id,
                                                 exp=time.time() + ttl_seconds))

    def encode_credential(self, cred: Credential) -> str:
        """The wire form of a credential: the three claims, then a signature over them."""
        payload = f"{cred.kid}.{cred.principal_id}.{cred.exp:.0f}"
        return f"{payload}.{self._sign(payload)}"

    def verify_credential(self, credential: str,
                          now: float | None = None) -> Principal | None:
        """Steps 3–5 of the request order: verify the signature, the expiry and the
        revocation list, then resolve to a Principal. Returns None on any failure — the
        caller turns that into a 401 and never learns which check failed."""
        if not credential:
            return None
        parts = credential.split(".")
        if len(parts) != 4:
            return None
        kid, principal_id, exp_str, sig = parts
        payload = f"{kid}.{principal_id}.{exp_str}"
        if not hmac.compare_digest(sig, self._sign(payload)):
            return None                                   # forged or minted by a dead run
        try:
            exp = float(exp_str)
        except ValueError:
            return None
        if (now if now is not None else time.time()) >= exp:
            return None
        if kid in self._revoked_kids:                     # A5: runs even while empty
            return None
        return self._principals.get(principal_id)         # unseated since minting ⇒ None

    def credential_kid(self, credential: str) -> str | None:
        """The key id inside a credential, for revoking exactly one of them."""
        parts = (credential or "").split(".")
        return parts[0] if len(parts) == 4 else None

    def revoke_kid(self, kid: str) -> None:
        self._revoked_kids.add(kid)

    def revoke_credential(self, credential: str) -> None:
        kid = self.credential_kid(credential)
        if kid:
            self._revoked_kids.add(kid)

    def revoke_all(self) -> None:
        """A5's panic button: a new signing key invalidates every credential at once,
        without needing to have kept a list of them."""
        self._signing_key = secrets.token_bytes(32)
        self._revoked_kids.clear()

    def _sign(self, payload: str) -> str:
        mac = hmac.new(self._signing_key, payload.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode("ascii").rstrip("=")

    # ── Ownership (derived, never stored twice) ─────────────────────────────

    def sync_tokens(self, tokens: Iterable[TokenInfo]) -> None:
        """Refresh the ownership cache from the live agent records.

        Called on the pygame thread after a load and after any roster or agent-list
        change. A controller naming a principal with no seat is folded to the DM here
        (A1): the token stays playable and nobody is silently handed someone else's
        creature."""
        self._tokens = {t.agent_idx: t for t in tokens}
        self._rebuild_ownership()

    def _rebuild_ownership(self) -> None:
        owned: dict[str, list[int]] = {}
        for idx, t in sorted(self._tokens.items()):
            pid = t.controller if t.controller in self._principals else DM_PRINCIPAL_ID
            owned.setdefault(pid, []).append(idx)
        self._owned = owned

    def controlled_by(self, principal_id: str) -> list[int]:
        """Live agent indices this principal controls. A1: ``controller`` on the agent
        record is the sole persisted truth; this is a cache, rebuilt on load and on any
        roster or agent-list change. Never persisted — indices are basis-dependent."""
        return list(self._owned.get(principal_id, ()))

    def controller_of(self, agent_idx: int) -> str:
        """The principal id controlling this token, folding an unknown id to the DM."""
        t = self._tokens.get(agent_idx)
        if t is None or t.controller not in self._principals:
            return DM_PRINCIPAL_ID
        return t.controller

    def owns(self, principal_id: str, agent_idx: int) -> bool:
        return self.controller_of(agent_idx) == principal_id

    # ── The one authorization chokepoint (NN6) ──────────────────────────────

    def authorize(self, principal: Principal | None,
                  action: Action, target: Target = None) -> bool:
        """The single policy decision in a request. Returns a plain bool: denial *reasons*
        belong to the middleware's audit log (A9), and the user-facing "why is this greyed
        out" string is ``ActionMenu.disabled_reason`` (M2), which is a rules question and
        not an authorization one.

        Entitlement is not visibility: this answers what a principal may know *if* they
        could perceive the creature at all. ``GameView`` (M3) then applies fog on top.
        Both must pass; neither substitutes for the other."""
        # The unauthenticated caller is denied everything, without exception. POST /join is
        # the one pre-auth route and does not call here.
        if principal is None:
            return False
        # A principal whose seat is gone (unseated mid-session, or a stale record) is
        # denied everything, even while holding a signature-valid credential.
        seated = self._principals.get(principal.id)
        if seated is None or seated != principal:
            return False

        is_dm = seated.role is Role.DM

        if action is Action.VIEW_SESSION:
            return True                       # seated at all ⇒ may connect. Spectators included.

        if action is Action.VIEW_DM_CHANNEL or action is Action.DM_COMMAND:
            return is_dm

        if action is Action.VIEW_TOKEN_VITALS:
            if is_dm:
                return True
            if not isinstance(target, TokenTarget):
                return False
            # Party members' hit points are table information: a player reads any
            # PC_FACTION token's vitals, owned or not.
            t = self._tokens.get(target.agent_idx)
            return self.owns(seated.id, target.agent_idx) or (t is not None and t.faction == PC_FACTION)

        if action is Action.VIEW_TOKEN_SHEET:
            if is_dm:
                return True
            return isinstance(target, TokenTarget) and self.owns(seated.id, target.agent_idx)

        if action is Action.CONTROL_TOKEN:
            if is_dm:
                return True                   # NN4: always, for any token, with no handoff
            return isinstance(target, TokenTarget) and self.owns(seated.id, target.agent_idx)

        if action is Action.ANSWER_PROMPT:
            if not isinstance(target, PromptTarget):
                return False
            if is_dm:
                return True                   # NN4: the DM answers any prompt at any time
            # The prompt bus (M1) owns prompt state; the roster must not reach into it, so
            # it asks through the hook. With no bus installed there are no live prompts,
            # and a player is denied — the safe direction.
            if self.prompt_lookup is None:
                return False
            owner, live = self.prompt_lookup(target.prompt_id)
            return bool(live) and owner == seated.id

        return False                          # closed enum: an unhandled action denies

    # ── Persistence ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """The on-disk shape. No seats list (A1), no credentials and no signing key
        (A3/A5) — the only ownership record on disk is each agent's ``controller``."""
        return {
            "protocol_version": PROTOCOL_VERSION,
            "join_code":      self.join_code,
            "autosave_slots": self.autosave_slots,
            "principals": [
                {"id": p.id,
                 "display_name": p.display_name,
                 "role": p.role.value,
                 "auth": {"method": p.auth.method, "subject": p.auth.subject}}
                for p in self._principals.values()
            ],
            # A5: reserved slot; the live list is in-memory, since credentials die with
            # the process and a persisted kid could never be presented again.
            "revoked": [],
        }

    @classmethod
    def from_dict(cls, doc: dict) -> "SessionRoster":
        r = cls(join_code=str(doc.get("join_code") or "") or None,
                autosave_slots=int(doc.get("autosave_slots", DEFAULT_AUTOSAVE_SLOTS)))
        for rec in doc.get("principals", []):
            if not isinstance(rec, dict):
                continue
            pid = str(rec.get("id") or "").strip()
            if not pid:
                continue
            auth_rec = rec.get("auth") or {}
            auth = AuthBlock(method=str(auth_rec.get("method", "join_code")),
                             subject=auth_rec.get("subject"))
            # An unrecognised role loads as a player: the failure that matters is handing
            # someone DM powers, never withholding them from the person at the keyboard.
            try:
                role = Role(str(rec.get("role", "player")))
            except ValueError:
                role = Role.PLAYER
            if pid == DM_PRINCIPAL_ID:
                role = Role.DM
            r._principals[pid] = Principal(id=pid,
                                           display_name=str(rec.get("display_name") or pid),
                                           role=role, auth=auth)
        r._rebuild_ownership()
        return r

    def save(self, path: str) -> None:
        """Write the session file atomically (NN7) — see ``atomic_io``."""
        atomic_write_json(path, self.to_dict())

    @classmethod
    def load(cls, path: str) -> "SessionRoster":
        """Read a session file, or return a fresh roster when there is none. A malformed
        file is treated as absent: a table with a corrupt roster still has a DM, and the
        alternative is a console that refuses to start."""
        try:
            with open(path) as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(doc, dict):
            return cls()
        return cls.from_dict(doc)


def _clamp_slots(n: int) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return DEFAULT_AUTOSAVE_SLOTS
    return max(MIN_AUTOSAVE_SLOTS, min(MAX_AUTOSAVE_SLOTS, n))


def _new_principal_id() -> str:
    # 14 characters total, which fits libstdc++'s small-string buffer — PlacedAgent copies
    # this id around on the game thread (summon inheritance), and a non-allocating copy is
    # a free win there.
    return "p_" + secrets.token_hex(6)


def tokens_from_battle_map(bm) -> list[TokenInfo]:
    """Build the ownership snapshot from a live BattleMap. MUST be called on the pygame
    thread (NN1) — reading a pybind11 accessor is a C++ call, and the GIL does not protect
    C++ invariants mid-mutation. The result is plain Python data and is safe to hand on."""
    return [TokenInfo(agent_idx=i, controller=pt.controller, faction=pt.faction)
            for i, pt in enumerate(bm.placed_agents)
            if not pt.removed_from_play]
