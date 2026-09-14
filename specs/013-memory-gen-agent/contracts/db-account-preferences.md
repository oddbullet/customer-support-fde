# Contract: `db.update_account_preferences`

**Module**: `src/customer_support_fde/db.py`

**Signature**:

```python
def update_account_preferences(
    account_number: str,
    preferences: str,
    path: Path | str | None = None,
) -> None:
    ...
```

## Behavior

1. Resolve the database path via the existing `_resolve_path(path)` helper (same as every other
   `db.py` function).
2. Normalize `account_number` via the existing `normalize_account_number` helper — same
   normalization `get_account` already applies, so a value taken from `SupportState` (already
   normalized when it was first looked up/created) round-trips unchanged.
3. Open a connection via the existing `_connect` helper.
4. Execute, inside a `with conn:` transaction (same pattern as `create_account`):
   ```sql
   UPDATE accounts SET preferences = ? WHERE account_number = ?
   ```
5. If the statement's `rowcount` is `0`, raise `OrderStoreError` — the caller (`memory_gen_node`)
   is only ever expected to call this for an account that already exists (created or looked up
   earlier in the same conversation), so no matching row indicates an invariant violation, not a
   normal "account not found" case that should be silently ignored.
6. On any `sqlite3.Error`, raise `OrderStoreError` with the same remediation-hint message style
   already used by `create_account`/`get_account`/etc.
7. Always close the connection in a `finally` block (same convention as every other `db.py`
   function).
8. Returns `None` on success.

## Error contract

| Condition | Result |
|---|---|
| `account_number` does not match any row | `OrderStoreError` |
| Underlying `sqlite3.Error` (e.g. locked database, disk I/O failure) | `OrderStoreError`, wrapping the original exception per existing style |
| Success | Returns `None`; `accounts.preferences` for that row now equals `preferences` |

## Callers

Only `memory_gen_node` (`nodes/memory_gen_node.py`) calls this function, and only after its own
`try/except Exception` guard (contracts/memory-gen-node.md) — so an `OrderStoreError` raised here
is caught there, logged, and never propagates out of the node.
