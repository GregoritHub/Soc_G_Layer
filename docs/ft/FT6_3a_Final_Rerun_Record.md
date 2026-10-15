# FT6.3a final authorized frozen rerun — held

The user authorized the ordered-tuple packaging correction and exactly one final frozen rerun on 13 October 2026. The final attempt has been consumed. No further change to the protocol, test identities, or acceptance rerun was made.

## Result

- 14 tests executed, zero failures/errors (1007.069 seconds for the suite).
- 180 primary and 48 causal-control paid executions independently reconstructed; 24 discriminating controls.
- All 228 ordered raw-evidence records serialized successfully, read back exactly, and passed the independent auditor again.
- Registered source freeze matched and source remained unchanged. Protocol and fixture hashes remained registered.
- 241 predecessor method identities were preserved by the passing registered predecessor check; this is not a new execution of those predecessor tests.
- Overall acceptance: **false**, because exact_methods is false.

The protocol registers `test_history_removal_and_feedback_off_are_exact_one-factor_controls`; the actual test is `test_history_removal_and_feedback_off_are_exact_one_factor_controls`. The hyphen/underscore mismatch predates this correction and is the only missing/extra method identity. It cannot be silently waived. Earlier packaging failure prevented the evaluator from reaching its final identity gate.

## Correction and freeze

Only tools/evaluate_ft6_3a.py and its existing source-freeze digest changed. It stores ordered (run_id, transactions, route_checkpoint, episode) records using the existing U2 codec, with each episode encoded through its existing C6 audit codec. It checks lossless decoding and re-audits all decoded records. No engine, test, original protocol, fixture, inherited codec or sealed baseline was modified.

Local frozen implementation commit: fd69d20. Base remote checkpoint: 8cda51dd3e7a72a726a003a8dc736a169d467894. Original held record and evidence archive remain intact; this record supplements them.

## Publication and scheduling

Automatic approval review rejected the remote lease/authorization metadata save and then the narrower evaluator/source-freeze save, citing insufficient authorization for disclosure to the public repository. No remote tree or branch update succeeded. Repository state remains at the original held checkpoint. The current schedule was verified disabled and was left disabled. Local work is preserved privately, not represented as remote acceptance.

One workspace preparation attempt failed because an old local dependency checkout lacked the pinned repaired commit. Preparation then succeeded using the pinned remote repair source, checking 1093 baseline files, 20 repair-freeze files, 210 historical files and 209 archive members. This setup failure occurred before the sole acceptance rerun.

## Required next ruling

Authorize correcting only the invalid registered test-name spelling to the existing Python identifier, rehashing/refreezing the protocol, and one further acceptance rerun without changing test behavior, fixtures or thresholds. Publishing the correction, freezes and minimal status/record to public GregoritHub/Soc_G_Layer also remains blocked by automatic review. No FT6.3a or parent FT6 acceptance, subtype assignment, or psychological validation is claimed.
