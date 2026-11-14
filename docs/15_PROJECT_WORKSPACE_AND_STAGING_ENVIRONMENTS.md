# Project Workspace and Reusable Staging Environments

Each project gets an isolated workspace and environment identifier. Staging can be temporary and reused after release evidence is archived.

Provisioning steps:
1. Validate project, approved commit and data classification.
2. Generate unique compose project name and isolated network.
3. Create secrets from secret references; never place secrets in image.
4. Attach project-specific volumes and test DB.
5. Deploy immutable artifact.
6. Configure restricted preview hostname/auth.
7. Run smoke/E2E/visual/security checks.
8. Publish expiring client preview.
9. Capture UAT feedback and approvals.
10. Archive logs, screenshots, test reports and image digest.
11. Stop/remove containers and ephemeral volumes only after retention and approval checks.
12. Keep source, artifacts, evidence and release metadata.

Cleanup must refuse to remove persistent production volumes or unarchived evidence. Use explicit environment labels and allow-list deletion.
