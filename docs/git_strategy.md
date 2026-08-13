# Git Strategy

## Purpose

Use lightweight trunk-based development. Keep `main` coherent and each change small, reviewable, and reproducible.

## Branches

Create a short-lived branch from the latest `main` for each roadmap task or focused change.

Use descriptive names such as:

```text
feature/monthly-target-pipeline
fix/publication-lag-alignment
docs/covariate-contract
research/model-adapter-support
```

Do not combine unrelated work or maintain long-running shared branches.

## Commits

Keep each commit focused on one decision or independently reviewable result. Every commit message must follow the Lore Commit Protocol:

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

Lead with intent. Use trailers only when they preserve useful decision context. Use `Rejected:` for alternatives that should not be retried without new evidence and `Directive:` for warnings to future contributors.

## Evidence and Safety

Record the commands, inputs, dependency versions, results, and known limitations needed to reproduce a decision. Prefer tests and concise repository findings over screenshots or transient logs.

Do not commit:

- credentials or `.env` files;
- model weights, caches, virtual environments, or machine-specific files;
- large transient logs;
- downloaded data unless the project adopts it as a provenance-recorded source artifact.

## Review and Merge

Before merging:

- update the branch from `main`;
- run relevant tests and repository checks;
- inspect the complete diff for secrets and unintended files;
- update affected documentation and `docs/roadmap.md`;
- confirm that completed roadmap items have acceptance evidence.

Use a pull request for material code, datasource, capability, or architecture decisions. Prefer squash merges unless preserving separate commits improves the history. Delete the task branch after merging.

Do not force-push or rewrite `main`. Record corrections in new commits.

## Checkpoints

Use annotated tags for verified project milestones. Create a tag only after the milestone is merged to `main` and its acceptance conditions pass.
