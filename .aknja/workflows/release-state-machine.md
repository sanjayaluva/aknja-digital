# Release State Machine

`LOCAL → CI → TESTED_BUILD → STAGING_DEPLOYED → SMOKE_TESTED → QA_VERIFIED → UAT_PENDING → UAT_ACCEPTED → BACKUP_VERIFIED → RELEASE_APPROVED → PRODUCTION_DEPLOYED → POST_DEPLOY_VERIFIED`.

Failure at any gate moves release to `BLOCKED` or `ROLLBACK_REQUIRED`. A release approval is bound to project, environment, target, commit SHA, image digest, migration set, configuration version, payload hash, approver, expiry and nonce. Staging success never automatically authorizes production.
