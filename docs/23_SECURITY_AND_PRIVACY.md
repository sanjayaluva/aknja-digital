# Security and Privacy Specification

Threat model:
- cross-tenant data access;
- prompt injection through client files/websites/issues;
- SSRF and malicious URLs;
- unsafe code execution and supply-chain compromise;
- secrets leakage in logs/prompts/builds;
- upload malware/archive bombs;
- session theft/CSRF/brute force;
- quota exhaustion and resource abuse;
- insecure container/network/volume boundaries;
- unauthorized production changes.

Controls:
- deny-by-default RBAC and tenant-scoped queries;
- MFA for Super Admin; secure cookies, CSRF, session expiry;
- tool gateway with schemas, allow-lists, egress restrictions and approvals;
- sandboxed builds with no production secrets;
- upload type/size limits, malware scanning where available, archive expansion limits;
- SSRF protections: block private/link-local/metadata addresses, validate redirects/DNS;
- secret manager/environment, short-lived scoped credentials, log redaction;
- TLS, least privilege, non-root containers, read-only filesystems where feasible;
- dependency pinning, SBOM, secret and container scans;
- consent, data minimization, retention/deletion and breach response.

Use OWASP ASVS 5.0.0 as a verification reference. Map applicable controls to tests; this package does not certify compliance. India DPDP compliance and legal terms require qualified legal review.
