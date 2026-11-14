# External Compute and Media Pipelines

## Workload classes
- CPU: FFmpeg transcode, thumbnails, audio trim, PDF processing, static builds.
- GPU: speech recognition, image inference, video AI, ML experiments.
- CI/build: unit tests, container builds, platform-specific builds.
- Browser QA: Playwright E2E and screenshot capture.

## Candidate execution
- OCI/local worker for small CPU jobs.
- GitHub Actions for CI within verified included minutes.
- Kaggle/Colab for eligible opportunistic notebook/batch GPU jobs; never treat interactive sessions as durable servers or guaranteed quotas.
- Client-owned or approved paid compute for sustained/heavy workloads.
- Free API endpoints only after plan/privacy/quota verification.

## Job contract
Inputs include content hash, size, format, data classification, client authorization, required output profile, estimated CPU/GPU/storage/network, deadline and checkpoint strategy. Outputs include artifact hash, codec/format, dimensions/duration, validation report, provider usage and provenance.

Do not upload confidential client assets to public notebooks or free providers without written authorization and terms review. Persist checkpoints to approved storage. Validate output integrity and quality before marking complete.
