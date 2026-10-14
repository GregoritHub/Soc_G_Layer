# FT6.3a corrected acceptance — local gate passed, publication blocked

The authorized spelling-only protocol correction was frozen at local commit 8d3b215 before exactly one additional acceptance invocation. It changes the registered method spelling from one-factor to one_factor; no test behavior, fixture, denominator, threshold, engine or inherited codec changes. The earlier ordered-tuple evaluator correction is retained.

## Observed result

- Overall evaluator passed: true; exit code 0.
- 14/14 exact registered method identities; zero failures/errors; suite duration 971.744 seconds.
- 180 primary and 48 causal-control paid executions independently reconstructed; 24 discriminating controls.
- All 228 raw evidence records serialized, decoded exactly and passed independent reconstruction again.
- Source unchanged and registered freeze matched; protocol and fixture hashes verified.
- 241 predecessor method identities preserved by the registered predecessor test; they were not all re-executed here.
- Grid digest: 7449c13a386b5737b1090f29e9de7679c767b80ecd68a85aaf1148da98337551. This matches the prior held run, confirming the spelling correction did not change the grid result.

## Preserved evidence and scope

Full evidence: FT6_3a_Corrected_Acceptance_Evidence_20261014.zip. Its exact hash is recorded in FT6_3a_Corrected_Evidence_Index.json. The archive contains raw paid evidence, grid report, exact method inventory, frozen files, logs, summary, correction patch and member hashes.

Earlier archives remain preserved: FT6_3a_Held_Evidence_20261013.zip, SHA-256 015169cfa2158d4a88663307022885f4f88b10d88035a5ca48fdc9c38874430f; FT6_3a_Final_Rerun_Held_Evidence_20261013.zip, SHA-256 a7e959fbaa295942c28ac3aa8a2bc5ba917377ccbf800aaf7050b8b81b4108df. Their failure records are historical, not overwritten.

This is local FT6.3a engineering acceptance only. FT6.3b parent-gate decision, subtype interpretation and FT7–FT9 remain unfinished. No theory register is closed and no psychological validation is claimed.

## Publication blocker

The ruling and lease were saved at d0439ad5e0b887c14ed0d54ceac0a26fee9682f8. Automatic approval review rejected publishing the complete modified evaluator and source-freeze manifest, saying this exceeded approval for correction/hashes/result/status. Read-only verification established that the repository is public and writable, both files already exist publicly, and the 154-entry manifest adds no new metadata keys and changes only three hashes. Review still rejected publication with that evidence. No alternative upload path was used.

The passing implementation remains local and in the private evidence archive. Remote source is still the pre-correction implementation and is not claimed to reproduce this passing result. The remote status/summary can record local acceptance without claiming source publication. Scheduled continuation remains disabled, and the lease is released at the status checkpoint.

## Next action

No additional test run is needed for this accepted frozen artifact. Publish the complete updated tools/evaluate_ft6_3a.py, contracts/ft/FT6_3a_Protocol_v1.json, contracts/ft/FT6_3a_Protocol_v1.sha256 and contracts/ft/FT6_3a_Source_Freeze_v1.json after the publication restriction is resolved; verify remote bytes against this frozen artifact. Then record destination acceptance, release ownership and resume the existing scheduled build at FT6.3b. Preserve the scope and theory boundaries.
