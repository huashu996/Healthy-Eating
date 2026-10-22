---
name: healthy-eating-workflow
description: Evidence-preserving local workflow for this repository's diet records, structured analysis, planning, and backup.
---

# Healthy eating project workflow

This is the repository's single project-owned operating contract. It is plain Markdown, not an autonomous agent, model integration, scheduler, or permission grant. The application reads and hashes this file alongside `apps/api/app/diet_policy.json`; changing it changes the planning context. Use the actual schemas and current CLI help rather than inventing fields or bypassing validation.

## 1. Start with the current person's own data

- Initialize an empty private data directory. Never seed personal measurements, preferences, targets, images, or actual intake from another installation.
- Ask the person to enter their own dated profile facts, goals, preferences, restrictions, and activity context. Keep absent information unknown.
- Read `overview`, `targets`, and relevant evidence before proposing a change. Do not infer a medical diagnosis or silently establish a nutrition prescription.
- Verify the active data root. Source code and generic composition references are distinct from private database and asset storage.

## 2. Classify evidence before recording

Separate actual intake, meal corrections, future plans, recipe references, and product labels. A picture, recipe, saved label, or proposed menu alone is not evidence that food was eaten. Do not classify a missing record as fasting or a skipped meal.

For real intake, preserve the reported timestamp, timezone, provenance, and explicit diet date. The supported policy boundary is Asia/Shanghai 07:00. Preserve original day attribution during corrections; do not overwrite historical facts to match a newer target or today's schedule.

## 3. Ingest and analyze explicitly

Use `scripts/diet_cli.py ingest --input` for an authorized structured intake record. A channel/message ID identifies one immutable ingestion request; use the returned record and current version for subsequent operations. Do not invent a new identity to bypass a conflict.

The repository does not recognize photos or call a model. A human or separately authorized integration must provide a structured analysis. Use the `Meal` and `MealVisionOutput` schemas in `apps/api/app/schemas.py`; standalone analysis must also satisfy `AnalysisWrite` in `apps/api/app/external_api.py`. Bind image IDs and hashes to the actual attachments. Do not claim recognition or independent review occurred unless it actually did.

Prefer matching, confirmed product labels with pinned revisions and evidenced quantities; otherwise use traceable food-composition references or explicitly uncertain estimates. Keep estimated ranges, sources, missing values, and uncertainty. Unknown nutrition is not zero. Saving a food label or calculating a portion does not itself create intake.

## 4. Establish targets without fabricated defaults

Use the person's explicitly confirmed dated target when available. `target-set` requires the complete `TargetWrite` envelope, current expected target identity, and a stable idempotency key. Preserve old target versions and explain changes. Do not rewrite past scores using a new target.

A formula estimate is not a prescription. Missing or unsafe inputs should remain a visible limitation, not be replaced with another person's measurements. Target review status is a readout, not an automatic review service. A due review requires actual evidence and an explicit operation; lack of evidence should hold the target rather than force a change.

## 5. Prepare, validate, then publish

1. Read `planning-context` for the intended diet date, including the current policy and skill hashes, profile, target, actual intake, reference libraries, and provenance.
2. Keep plans separate from actual intake. Check the target date's training/rest status, restrictions, confirmed preferences, available foods, and explicit requests. Reuse known information instead of asking the same question repeatedly.
3. Construct a candidate using traceable food/product versions and internally consistent portion calculations. A calorie budget alone is not a food's nutrient content.
4. Review the preceding three diet days where available; distinguish actual intake from earlier recommendations. Missing history is not evidence of excess or deficiency. Do not create cross-day food debts or compensation through skipped meals.
5. Run `validate-plan` on the complete candidate. Numeric validation is not independent human/model review; state which checks were actually completed.
6. Use `publish-candidate` only for a fully validated, authorized candidate satisfying the current context and formal publication constraints. If context changed, reread and revalidate rather than forcing stale writes.

Formal publication and settlement follow the fixed Asia/Shanghai 07:00 policy. Test previews are not promoted into formal menus. Same-day formal results are reused under idempotency rules. Ordinary newly recorded information does not authorize repeatedly replacing a formal menu. Use the dedicated remaining-day or revision interfaces only for an explicit request, preserving prior versions and real intake.

No internal scheduler runs these steps. An external integration must be separately implemented and authorized; a configuration time alone does not schedule execution.

## 6. Interpret scores honestly

Use the current policy's fixed 100-point denominator and preserve its weights and evidence checks. Do not normalize missing components into a perfect score. Display colors are green at 85 or above, yellow at 70 or above, and red below 70; unavailable scores remain unavailable.

Preserve estimate labels, ranges, source references, and the policy version. Never create an empty day's score merely to fill a chart. Scores describe target adherence and food structure, not medical risk, diagnosis, or treatment eligibility.

## 7. Protect private storage and verify changes

After a write, reread the affected record/overview and verify versions and intended effects. On conflict, inspect fresh state; never blindly retry a changed payload under an old idempotency key.

SQLite in `DATA/database/platform.sqlite3` is authoritative. Assets, reference materials, audit files, exports, and backups can contain sensitive health information. Keep them out of Git and public hosting. Local files are not application-encrypted. Do not transmit health data to a new service without the person's authorization.

Mirroring is disabled by default. Local snapshot export is not cloud synchronization, a privacy guarantee, or a complete backup. No proprietary connector is bundled.

Use the CLI `backup` operation for a consistent data backup, keep the matching source/configuration separately, and test `restore` into a new directory. Do not overwrite the active data root or bypass hash verification. Retained history and audit records in backups remain private.

## 中文摘要

此项目只有这一份自有操作约定，不会自行识图、调用模型或定时运行。先填写使用者自己的资料，再明确区分已吃、计划、参考和标签；未知不填零，空白不判禁食。分析必须由人或另行授权的工具提供，按实际模型和版本写入。正式候选先读取当前上下文，再校验并按北京时间 07:00 规则发布；估算和来源必须保留。数据库与附件是私人数据，完整恢复需要数据备份及匹配源码，均不得误传公开仓库。
