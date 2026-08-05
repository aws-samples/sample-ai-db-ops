# Security Policy

## Reporting a Vulnerability

If you discover a potential security issue in this project, we ask that you
notify AWS Security via our
[vulnerability reporting page](https://aws.amazon.com/security/vulnerability-reporting/)
or directly at [aws-security@amazon.com](mailto:aws-security@amazon.com).

Please do **not** create a public GitHub issue for security vulnerabilities.

## Scope and Intent

This repository contains **sample code** intended to demonstrate how to build
an AI-assisted database operations assistant on AWS. It is provided for
educational and proof-of-concept purposes and is **not** intended for
production use as-is.

Before deploying any part of this sample, review and harden it for your
environment, including but not limited to:

- Restricting IAM permissions to the minimum required (least privilege).
- Managing all credentials through AWS Secrets Manager or an equivalent; never
  hardcode secrets. All account-specific values in this sample are read from
  environment variables (see `ui/.env.local.example` and `config.yaml`).
- Enabling encryption at rest and in transit for all data stores.
- Reviewing and constraining any database write/administrative operations the
  assistant is permitted to perform.

## Supported Versions

As sample code tied to a proof of concept, this repository does not follow a
formal versioned support lifecycle. Fixes are applied to the primary branch.
