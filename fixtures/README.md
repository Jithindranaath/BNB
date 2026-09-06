# fixtures/

Real labeled data only. Anything demo/seed is badged DEMO in the UI (rule R2).

- security_testset.json   ~150 known-bad + ~150 known-good BSC tokens, each {address,label,source_url}  (T-032)
- security_results.json    measured precision/recall/FPR/n from running sentry over the test set  (T-032)
- manual_baselines.json    human analyst stopwatch times + written output  (spec.md §3.5, §9)
- gas_units.json           gas units per op, MEASURED on the Anvil fork, with the block  (T-012)
