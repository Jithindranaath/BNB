"""Run harness: observe -> decide -> act -> report, then the receipt.

- computes data_snapshot_hash = sha256(canonical JSON of every input decide() consumed)
- persists the run
- invokes the baseline runner ON THE SAME Observation
- writes the Receipt {agent result, baseline result, advantage delta}

decide() purity is load-bearing here (architecture.md §8). Implemented in T-022.
"""
