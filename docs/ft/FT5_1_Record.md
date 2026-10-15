# FT5.1 — integer reserve accounting state accepted

[machine-checked] Frozen source `b054f467fc0508e4eb954fe9208613e43115c036` passed all 16 prospectively registered FT5.1 methods on 12 October 2026 with zero failures/errors, exact method identity, the exact 130-method FT4 predecessor inventory, matching fixtures, the registered source freeze and unchanged source. Prospective protocol commit: `3a972c13aeb70f5a453af11c598c4a0c8595b37c`; protocol SHA-256: `1940827a7e0666a561aadf4d54bbcece8cfecdc4fab51553547d9c1d86995a69`; source-freeze SHA-256: `6a43f4d6f7a931c1bda5765c7e9ed43a14f28fc3565e3f4a2011f8970a9d0543`.

[derived] Reserve is now an actor-owned exact integer in `0..8`, independent of facet charge, native energy/time wallets, elapsed time, TIM, dimensionality, closure and capability state. The ledger freezes the null, load-v1 and grade-load-v1 admission, independent/support completion, once-per-attempt interruption and finite-token replenishment arithmetic. Zero reserve leaves the demand pending and records preparation rather than forbidding a route.

[machine-checked] An auditor that imports no reserve runtime independently reconstructed every event and rejected changed balance, preparation and token history. Duplicate demand, attempt, token and receipt identities are rejected. Canonical and workflow FT4 engines, wallets, TIM maps and retained-reuse checkpoints remained byte-identical while their separate reserve ledgers changed. A pre-freeze isolation test used the wrong fixture attribute path and errored; only that test path was corrected, and the failed output is preserved with the evidence.

[evidence] `FT5_1_Evidence_20261012.zip`, SHA-256 `e5610ef183e23b03f0a5c7cda18afb76ca76c3fcfc26cc1ca901a2558c525b30`. Retrieve the exact private archive by filename and verify the ZIP CRC and SHA-256. Prepare pinned dependencies per README, then run `PYTHONPATH=.:baseline/HLE_Rebuild_R21B python3 tools/evaluate_ft5_1.py /absolute/fresh-output`.

[scope] FT5.1 accepts only the accounting-state contract. Its provisional A5 receipt records do not establish actual native paid uptake. FT5.2 must bind preparation and replenishment to committed native work and integrate candidate dynamics; FT5.3 retains depletion/recovery and the frozen grid. No reserve policy is elected for release, C13/TD4 remains open, and no claim about people is made.

[status] FT5.1 accepted; lease released at the verified checkpoint; next eligible batch is FT5.2 paid native binding and candidate dynamics; no current blocker.
