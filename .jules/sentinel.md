# Sentinel Journal 🛡️

Sentinel is a security-focused agent who protects the codebase from vulnerabilities and security risks.

## Mission
Identify and fix security issues or add security enhancements to make the application more secure.

## 2025-05-14 - [Initial Assessment]
**Vulnerability:** Telemetry sanitization bypasses and directory syscall overhead.
**Learning:** Existing path redaction failed on paths with spaces; generic secrets (passwords/tokens) were not redacted; nested dictionary keys and tuples were ignored; redundant mkdir syscalls in telemetry hot path.
**Prevention:** Use more robust regex for paths with spaces; implement generic secret detection; ensure recursive sanitization covers keys and tuples; cache directory existence checks.

## 2025-05-16 - [Consolidated Work]
**Vulnerability:** Redundant effort on telemetry redaction.
**Learning:** A concurrent PR (#115) was already consolidating telemetry redaction review.
**Prevention:** Always check for overlapping PRs or issue tracks to avoid duplicate effort on the same security module.

## 2025-05-16 - [Env Probe Security]
**Enhancement:** Reducing `shell=True` footprint in `env_probe.py`.
**Reasoning:** While currently quoted, using `shell=True` for a large set of system probes increases the risk of command injection if future probes include unquoted external input.
**Prevention:** Prefer `shell=False` with argument lists; only use `shell=True` for complex shell-native scripts (loops/pipes) with strictly controlled input.
