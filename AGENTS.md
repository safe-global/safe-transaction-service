# AGENTS.md

## How Codex Uses This File
Codex will read `AGENTS.md` for project-specific guidance, workflows, and conventions.
It is the preferred place to capture shared context and expectations.

## Indexer Architecture (Summary)
This repository includes multiple indexers under `safe_transaction_service/history/indexers/`.

### Base Classes
- `ethereum_indexer.py`
  - Orchestrates block range selection and indexing flow.
  - Shared helpers:
    - `_is_processed(...)` / `_mark_processed(...)`
    - `_prefetch_ethereum_txs(...)`
  - `element_already_processed_checker` is centralized here.
- `events_indexer.py`
  - Base for event-driven indexers using `eth_getLogs`.
  - Shared helpers:
    - `_filter_not_processed_log_receipts(...)`
    - `_mark_log_receipts_processed(...)`

### Concrete Indexers
- `safe_events_indexer.py`
  - Used on L2 networks. Builds InternalTx-like records from events.
  - Supports conditional indexing with allow/block lists.
- `internal_tx_indexer.py`
  - Used on L1 networks. Uses `trace_filter`/`trace_block`.
  - Filters traces to relevant ones and skips errored txs.
  - Only inserts `EthereumTx` when relevant traces exist.
- `erc20_events_indexer.py`
  - Indexes ERC20/ERC721 transfers.
  - Only inserts `EthereumTx` when there are new (not-yet-processed) logs.
- `proxy_factory_indexer.py`
  - Indexes Safe `ProxyCreation` events, inserts `SafeContract`.

### Key Behavioral Constraints (Must Preserve)
- L1 uses `InternalTxIndexer` and L2 uses `SafeEventsIndexer`. They do not run in parallel.
- Internal traces are matched only by `SafeMasterCopy` addresses (no other address list).
- `EthereumTx` should not exist without at least one related table row.
- Do not index errored transactions.

## Recent Refactors & Conventions
- Reused helpers in `EthereumIndexer` for processed-element checks and EthereumTx prefetching.
- Event indexers use shared helpers to filter/mark processed log receipts.
- `InternalTxIndexer` filters to relevant traces at trace-level and re-checks `InternalTx.is_relevant` before insert.
- `is_relevant_trace(...)` must remain consistent with `InternalTx.is_relevant`.

## Testing
- `Virtualenv` available at `.venv`
- Use `pytest` (no parameters). It should auto-detect configuration.
