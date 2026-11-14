# CI/CD and Artifact Management

CI pipeline:
1. checkout exact commit;
2. install pinned dependencies;
3. lint/format/type checks;
4. unit/integration tests;
5. migration validation;
6. secret/dependency/license scans;
7. build container;
8. generate SBOM and image digest;
9. push to approved registry if credentials and quota allow;
10. store test reports and provenance.

Use least-privilege GitHub tokens, protected branches, required reviews, isolated CI secrets and pinned actions by full commit SHA. Do not expose production secrets to pull requests from untrusted branches. Self-hosted runners must be ephemeral or isolated and must not share production credentials.
