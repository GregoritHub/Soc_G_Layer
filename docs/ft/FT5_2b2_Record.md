# FT5.2b2 — autonomous reserve settlement accepted

[machine-checked] Frozen source `a80537179051f8000c7d518250422656fd2a5c69` passed all 15 prospectively registered FT5.2b2 methods on 13 October 2026 with zero failures/errors, exact method identity, the exact 171-method FT5.2b1/FT5.2a/FT5.1/FT4 predecessor inventory, matching fixtures, the registered source freeze and unchanged source. Prospective protocol commit: `857e00eb8545a5a5c2e37d05045cb6d82f9d02eb`; implementation commit: `07cbf702813c9df9c6261cb2daf0f8db31118943`; protocol SHA-256: `140bc361695644385b56987250c0a2b477b443710b542f39c1cbf88736b6fb45`.

[derived] Autonomous completion now changes reserve only after the realized native traversal is paid, its exact output is consumed by paid same-scope work and the owned demand settles. Actual support traversal yields supported completion; every other settled traversal yields independent completion. Grade-load-v1 derives grade from the realized target seat. Callers cannot supply route, support, grade, completion kind or success.

[machine-checked] Independent audits reconstructed six completion witnesses across the null, load-v1 and grade-load-v1 policies in both content settings, plus one actual paid-work interruption witness. Interruption preserved the unresolved demand, preparation-only interruption was rejected, zero reserve preserved all six routes, reserve effects left native state unchanged and paid preparation reached settlement in both settings.

[evidence] `FT5_2b2_Evidence_20261013.zip`, SHA-256 `798ff23de15931e7b1d50248b334fd319009b14ab4f1ea3d8ade9b054d8a7402`. Retrieve the exact private archive by filename and verify the ZIP CRC and SHA-256. Prepare pinned dependencies per README, then run `PYTHONPATH=.:baseline/HLE_Rebuild_R21B python3 tools/evaluate_ft5_2b2.py /absolute/fresh-output`.

[scope] FT5.2 is accepted as candidate-dynamics integration. FT5.3 still owes sustained depletion, restart, external replenishment, the harder-demand partial order, the preregistered grid and release-policy selection. No C13/TD4 theoretical closure or psychological validation is claimed.

[status] FT5.2b2 and parent FT5.2 accepted; lease released at the verified checkpoint; next eligible batch is FT5.3 depletion and recovery; no current blocker.
