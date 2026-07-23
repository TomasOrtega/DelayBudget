# Security policy

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x | Yes |
| 0.x | No |

Security fixes are released for the latest 1.x version. Older releases may
receive a fix when the change is low risk, but this is not guaranteed.

## Reporting a vulnerability

Do not include sensitive exploit details in a public issue. Use GitHub private
vulnerability reporting when available. Otherwise contact `@TomasOrtega`
through GitHub and request a private reporting channel.

Please include the affected version, impact, reproduction steps, and any
suggested mitigation. Non-sensitive correctness bugs may be reported normally.

## Threat surface

The core library operates only on caller-provided identifiers and integer
timestamps. It performs no network access and reads no notification content.

The CLI parses untrusted JSON Lines and writes output files. Relevant reports
include denial of service, path handling, parser differentials, unexpected
partial output, and violations of a documented scheduling guarantee.

Platform adapters are separate security boundaries and require their own
permission review, timer analysis, data-retention policy, and threat model.
