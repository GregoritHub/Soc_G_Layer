# Soc G Layer

Full Theory engine continuation. The repaired FT3 recovery gate passed on 12 October 2026: all 751 inherited method identities, 30 FT controls and both positive retention witnesses passed with unchanged source. See `docs/ft/Recovery_Record_20261012.md`.

**FT4, FT5.1, FT5.2 and FT5.3a are accepted.** A paid interruption can now bind exact external A5 replenishment and explicitly restart the same pending autonomous attempt without repricing native work. Next is FT5.3b harder-demand ordering, the frozen ample/scarce grid and the release-policy decision; the parent FT5 gate remains pending.

## Run the recovered engine

The inherited engine remains a read-only, pinned dependency. Obtain the existing recovery attachments `Full_Theory_Checkpoint_FT3_Held.zip` and `FT2_FT3_Approved_Repair_Evidence.zip`, then run:

```sh
python3 tools/prepare_workspace.py --held-archive /absolute/held.zip --repair-evidence /absolute/repairs.zip --output /absolute/new-runtime
cd /absolute/new-runtime
PYTHONPATH=.:baseline/HLE_Rebuild_R21B python3 -m unittest -v tests_ft1.test_historical tests_ft2.test_content
python3 tools/evaluate_ft3.py /absolute/new-ft3-output
```

Use Python 3.12. The script verifies source and archive identities and preserves existing output directories. It never pushes to either source repository. New committed FT modules, tests, contracts and evaluators in this destination are applied over the verified repaired engine.

The exact current plan and continuation handoff are in `operator/` inside `Soc_G_Layer_Recovery_Verification_20261012.zip` (SHA-256 `af1bd163563ecb703ffa77d95508ba4d8269c18b524ee143e8d750a216a42438`). Authorized hosted runs already have private retrieval pointers. Read this destination's run-state rather than the historical publication state inside recovered inputs. No manual download/upload cycle is required for hosted continuation.

## Scope

The recovery checkpoint is reproducible from exact dependencies. A standalone FT9 package and the full FT4–FT9 engine remain unfinished. The bulk recovered-source import was rejected by automatic review and was not performed; only the narrower setup/dependency save was used. Previously denied historical manifest transfers remain untouched.

Preserve the sealed baseline, legacy-r4 default, accepted contracts, failed attempts, exact payments and theoretical boundaries. New dynamics are versioned hypotheses. Passing simulation tests does not validate a psychological theory.
