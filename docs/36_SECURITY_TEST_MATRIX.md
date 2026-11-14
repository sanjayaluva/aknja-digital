# Security Test Matrix

- Auth: brute force, session expiry, MFA, password reset, CSRF.
- Authorization: horizontal/vertical access, tenant ID tampering, object-level access.
- Input: SQL injection, XSS, template injection, path traversal.
- SSRF: loopback/private/link-local/cloud metadata, redirects, DNS rebinding.
- Uploads: MIME mismatch, oversized file, archive bomb, malicious document.
- AI: prompt injection in files/webpages, tool argument injection, secret exfiltration attempts.
- Containers: root user, exposed socket, privileged mode, writable host mounts, network isolation.
- Supply chain: dependency vulnerabilities, pinned images, SBOM, secret scanning.
- Operations: audit tampering, approval replay, expired approval, payload mismatch, emergency stop.
Map applicable controls to OWASP ASVS 5.0.0 and record test evidence. This matrix is not a certification.
