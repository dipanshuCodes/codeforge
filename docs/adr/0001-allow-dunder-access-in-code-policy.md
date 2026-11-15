# 0001: Allow dunder access in the code policy

- **Status:** Accepted
- **Date:** 2026-11-15
- **Decided by:** Dipanshu

## Context

The code policy (`src/codeforge/policy/code_policy.py`) denied every dunder name and dunder
attribute (except `__name__`). That blanket rule also blocked ordinary generated code, such as
classes calling `super().__init__()` or touching `self.__dict__`.

## Decision

Remove the two dunder rules: dunder names and `obj.__attr__` access are no longer denied.
These rules are kept:
- `__builtins__`, `__import__` and the other `DENIED_NAMES`.
- Reflection calls (`getattr`, `globals`, `vars`), including `getattr(x, '__class__')`.
- The import allowlist.

The two unit cases that asserted the removed rules were deleted from
`tests/unit/test_code_policy.py`:
- `().__class__.__bases__[0].__subclasses__()`
- `f.__globals__`

## Consequences

- **Known gap:** introspection escapes now pass the policy gate. For example,
  `().__class__.__bases__[0].__subclasses__()` can reach classes such as `subprocess.Popen`
  without importing them, which gets around the import allowlist. This weakens security
  invariants 4 and 5 (generated code is untrusted; policy before execution).
- The only remaining defences against such code are the sandbox's own layers: a separate
  process, `python -I`, a stripped environment, a temp directory, the audit-hook network block,
  and the timeout and memory limits.
- R2 and R6 demos must not claim that the gate blocks introspection escapes.
- **Narrower alternative, if this is revisited:** allow harmless dunders (`__init__`,
  `__repr__`, `__eq__`, ...) and keep denying the escape routes (`__class__`, `__bases__`,
  `__mro__`, `__subclasses__`, `__globals__`, `__code__`, `__dict__`, `__closure__`,
  `__getattribute__`).
