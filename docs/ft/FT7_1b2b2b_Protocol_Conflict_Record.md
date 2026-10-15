# FT7.1b2b2b — registered comparison conflict; ruling required

[measured, 2026-10-15 UTC] Read-only review of checkpoint `6f6e40dcc09301d6aeab9fe53932eda1f8a26ef8` establishes a conflict between this new batch's registered comparison and the unchanged route-admission contract. This supersedes the earlier progress record's provisional engineering-continuation status. It is not a two-failure permission stop, a theory contradiction, or a claim that retained reuse is generally impossible. No third gate ran. All 242 members of the second source freeze still match exactly.

## Exact blocked criterion

The protocol requires the original four facets, empty permitted support, unchanged `IntegratedRoutePolicy`, and matched revocation changing retained choice to a completed nonretained route at equal actual movement and consumer spending. `test_revocation_changes_choice_at_matched_main_cost` explicitly requires both branches to complete. The dimensionality amendment explicitly preserves those requirements.

The unchanged policy admits retained reuse only when the current seat covers every required facet. Ordinary, n and cp each require their destination seat to cover those same facets. Support requires a peer in `demand.support_allowed`; that set is empty. Revocation removes the certificate before route admission. These predicates apply equally to canonical and workflow settings.

## Exhaustive structural check

Using unchanged `hle.model_a.fields`, `hle.development_structure.lap/portage`, and `full_theory.route_policy._covered`, a read-only enumeration of all eight origins produced the following seat/dimension pairs. No engine trajectory or accepted test suite was rerun.

| Origin / dimension | Retained covers four facets | Ordinary destination / dimension | n destination / dimension | cp destination / dimension |
| --- | --- | --- | --- | --- |
| 1 / 4 | yes | 5 / 1 | 3 / 2 | 5 / 1 |
| 2 / 3 | no | 1 / 4 | 4 / 1 | 6 / 2 |
| 3 / 2 | no | 7 / 3 | 1 / 4 | 7 / 3 |
| 4 / 1 | no | 3 / 2 | 2 / 3 | 8 / 4 |
| 5 / 1 | no | 6 / 2 | 7 / 3 | 1 / 4 |
| 6 / 2 | no | 2 / 3 | 8 / 4 | 2 / 3 |
| 7 / 3 | no | 8 / 4 | 5 / 1 | 3 / 2 |
| 8 / 4 | yes | 4 / 1 | 6 / 2 | 4 / 1 |

[derived] Only origins 1 and 8 can admit the positive retained route. Neither has an ordinary/n/cp destination covering four facets. With support forbidden and the certificate revoked, only deferral remains. Consequently the same-state revocation branch cannot both complete and match the positive branch's nonzero movement/consumer spending. More wallet, a different TIM, longer execution, or fixing recall truncation does not change this admission proof. Different preparation for only one branch would cease to be the registered matched intervention. A multi-hop extension would change the explicitly preserved route policy.

Reproduce the finite structural check in the prepared runtime:

```python
from hle.model_a import fields
from hle.development_structure import lap, portage
from full_theory.content import FACETS
from full_theory.route_policy import _covered
origins = [s for s in range(1, 9) if _covered(s, FACETS)]
assert origins == [1, 8]
assert all(not _covered(t, FACETS) for s in origins
           for t in (lap(s), portage(s, 'n'), portage(s, 'cp')))
```

The separate observed recall-truncation failure remains open: the positive saved record visited 32 bindings with truncation, and the inherited retention rule honestly rejected it. Repairing that engineering issue alone cannot resolve the comparison conflict. Existing saved records, exact failed source capsules and evidence index remain unchanged.

## Required decision and alternatives

**May the comparison be split: preserve the strict four-facet/no-support case as retained success versus honest deferral, and test matched-cost retained priority on a separately registered lower-facet demand?**

That is a proposed criterion amendment, not an accepted repair or a proven successful fixture. It would preserve the strict-demand negative finding and require actual paid native completion, unchanged source freezes, both settings, exact saved-record audits, all other controls, and an explicit statement that the strict success-versus-deferral contrast is not matched-cost evidence. Its relationship to the FT8 matched-main-cost requirement must be recorded; the strict contrast cannot silently satisfy that requirement. No lower-facet scenario has been executed or declared accepted.

Alternative: retain the exact existing comparison and keep this gate held, unless the author explicitly authorizes a separately versioned route-contract change. No baseline or dimensionality change is proposed. Routine repair authorization remains valid elsewhere, but does not authorize silently removing the registered equal-cost completed-control requirement. The exact FT7.1b2b2b release claim is blocked pending this decision.

FT7.1b2b2a remains accepted at `2bfc3a883bd7aac545f2d93462f2a62e134ae856`: 12 exact methods, 326 predecessor identities and 22 independently audited saved native records. FT7.1b2b2b and its parents remain unaccepted. The lease is released and continuation is paused for this specific protocol ruling. No Dot delivery capability was available; the question is presented in the task conversation.

## Source identities

| Read-only source | SHA256 |
| --- | --- |
| `baseline/HLE_Rebuild_R21B/hle/model_a.py` | `102e9a1592addde75fed2f84da409a815e76657609e9ac25d87381f8455c33b2` |
| `baseline/HLE_Rebuild_R21B/hle/development_structure.py` | `da84dfa6f238e21281d389f63ec5f381d9a4e163786b0820a48d07e4b0dd6323` |
| `full_theory/route_means.py` | `e3e3b4afcf2ffda4027e2db50daf8d99f30aae5ca08568dace946958b5dd3d5b` |
| `full_theory/route_policy.py` | `ef68d90cee55bb5f32a3b0b9d3bc2ded43c36964c4ea689a3f4746b0fe65ed49` |
| `full_theory/retention.py` | `76e604a5a1d8ed7b73b58f391dad74d59e7d2ba868c51f271c14801e8174c29b` |
| `tests_ft7/test_social_reuse.py` | `98d5825db5c4539d6e8b55177e6e756ed8c32df06a0adbc8f34224ec66c30168` |
| `contracts/ft/FT7_1b2b2b_Protocol_v1.json` | `2da7f69807e3a297291c9aa8035598584e69fcbdb3aadb3f5d525af0870f8bc1` |
| `contracts/ft/FT7_1b2b2b_Dimensionality_Amendment_v1.json` | `3a619656574f1ebdab34b226103e5fcfe0a7b78b7cab220d62cd662970006cf9` |
