# Git Strategy

## 1. Purpose

Use lightweight trunk-based development to complete Phase 0 and later PoC tasks while keeping `main` reviewable and usable.

Create one short-lived branch per Phase 0 roadmap task. Merge a task only after its acceptance evidence is recorded, and mark the corresponding roadmap item complete in the same branch.

## 2. Main Branch

`main` is the integration branch and should remain in a coherent state.

- Branch from the latest `main`.
- Keep branches limited to one roadmap task or one explicitly added contingency task.
- Do not maintain a long-running shared `phase0` branch.
- Do not mark a roadmap task `[x]` until its acceptance condition is supported by committed evidence.
- Update affected documentation and `docs/roadmap.md` before merging.

## 3. Phase 0 Branches

Recommended branches:

```text
phase0/forecast-contract
phase0/covariate-smoke-test
phase0/natural-language-smoke-test
phase0/probabilistic-adapter-smoke-test
phase0/datasource-smoke-test
phase0/data-catalog
phase0/decision-record
```

The three capability smoke tests may proceed independently. Static workbook adoption should precede the final data catalog, and the Phase 0 decision record should be completed last.

## 4. Branch Completion Contract

A Phase 0 branch is ready to merge when:

1. the roadmap task has been executed;
2. the commands, inputs, dependency versions, and relevant environment constraints are recorded;
3. results and unsupported cases are captured as durable repository evidence;
4. applicable tests or smoke checks pass;
5. unknowns and limitations are documented rather than inferred;
6. the affected roadmap item is updated accurately; and
7. the staged diff passes whitespace and repository checks.

## 5. Evidence Layout

Prefer reproducible checks and concise findings over screenshots or transient terminal logs.

Suggested locations:

```text
tests/smoke/
  test_covariate_support.py
  test_natural_language.py
  test_probabilistic_adapters.py

docs/findings/
  covariate_support.md
  natural_language.md
  probabilistic_adapters.md
  datasource_selection.md
```

Small deterministic fixtures may be committed when needed. Do not commit:

- credentials or `.env` files;
- downloaded raw datasets unless they are the explicitly adopted, provenance-recorded source artifact;
- model weights or caches;
- virtual environments;
- machine-specific generated files; or
- large transient logs.

Record the command needed to reproduce a result, the tested package or source revision, and enough output to support the conclusion.

## 6. Commit Policy

Keep commits focused on a decision or independently reviewable result. A branch will commonly contain:

1. smoke-test or research scaffolding;
2. the reproducible result and supporting evidence; and
3. documentation plus roadmap updates.

Every commit message must follow the Lore Commit Protocol.

```text
<intent line: why the change was made, not what changed>

<optional concise body: constraints and approach rationale>

Constraint: <external constraint that shaped the decision>
Rejected: <alternative considered> | <reason for rejection>
Confidence: <low|medium|high>
Scope-risk: <narrow|moderate|broad>
Directive: <forward-looking warning for future modifiers>
Tested: <what was verified>
Not-tested: <known gaps in verification>
```

Lead with intent. Use trailers only when they preserve useful decision context. Use `Rejected:` to prevent repeated investigation and `Directive:` for warnings to future contributors.

Do not combine unrelated Phase 0 tasks in one commit merely because they were performed together.

## 7. Merge Policy

Use pull requests for capability, datasource, and architecture decisions, even when the repository has one active contributor. The pull request preserves the evidence and rationale that led to the decision.

Prefer squash merges for exploratory branches so `main` receives one concise decision record. Use a regular merge only when preserving multiple independently meaningful commits improves the history.

Before merging:

- update the branch from `main`;
- rerun the relevant smoke checks;
- inspect the complete diff;
- verify that no credentials or large generated artifacts are staged; and
- confirm that the roadmap status matches the committed evidence.

Delete the remote task branch after a successful merge.

## 8. Recommended Merge Order

1. Forecast contract and scope.
2. Covariate-support smoke test.
3. Natural-language capability smoke test.
4. Probabilistic-adapter smoke test.
5. Datasource smoke test and static workbook adoption.
6. Initial data catalog.
7. Phase 0 decision record and exit review.

Items 2–4 may be developed in parallel, but each should merge independently. Items 5–7 are sequential because downstream decisions depend on earlier findings.

## 9. Custom Covariate Adapter Contingency

If the Phase 0 smoke test finds no native TimeCopilot integration that satisfies the PoC covariate requirement:

1. finish and merge the native-support findings first;
2. add custom-adapter implementation and validation to `docs/roadmap.md`;
3. create a separate branch:

   ```text
   phase0/custom-covariate-adapter
   ```

4. implement and test the adapter without rewriting the original native-support evidence; and
5. record the adapter contract, supported covariate classes, validation behavior, and known limitations.

Keeping the contingency separate preserves the distinction between observed TimeCopilot behavior and project-specific remediation.

## 10. Phase 0 Completion

The `phase0/decision-record` branch performs the final exit review. It should:

- confirm every Phase 0 roadmap item is `[x]`;
- summarize native covariate support and any custom-adapter decision;
- identify at least one adapter that supplies the required probabilistic output;
- record the verified natural-language execution path and its LLM requirements;
- record the selected static World Bank Pink Sheet workbook datasource;
- confirm that the initial data catalog exists;
- summarize unresolved capability, datasource, and environment limitations; and
- update the roadmap so Phase 1 becomes active.

After the completion branch is merged and `main` is verified, create an annotated checkpoint tag:

```bash
git tag -a phase0-complete -m "Phase 0 capability and data decisions verified"
git push origin phase0-complete
```

The tag marks a reproducible decision boundary. Do not create it while any Phase 0 exit condition remains unresolved.

## 11. Repository Protection

When multiple contributors are active, protect `main` with required pull requests and passing checks. For a solo PoC, continue to use pull requests for the capability smoke tests and final decision record because these contain assumptions that may need later review.

Force pushes to `main` and history-rewriting merges are prohibited. If a merged finding changes, record the correction in a new commit rather than rewriting the original evidence.
