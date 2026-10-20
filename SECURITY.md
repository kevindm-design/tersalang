# Security

Do not open a public issue for a vulnerability. Report it privately through GitHub: on the repository's **Security** tab, choose **Report a vulnerability** (https://github.com/kevindm-design/tersalang/security/advisories/new). Include the `tersa version` output, the command you ran, and a program or task that shows the problem.

You should get a reply within seven days. Fixes go into the latest release; there are no back-ported fixes for older versions.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Older | No |

## Scope

The reference interpreter is not a sandbox. Grants such as `--allow FileRead` are ordinary checks in the evaluator, not an operating-system boundary, so running an untrusted program with a grant it should not have is not a vulnerability.

These are in scope:

- An attempt that changes its harness score other than by solving the task, for example by reading hidden tests, reaching hidden code, or forging the result the parent reads.
- A program that escapes `setrlimit` or bubblewrap isolation in `tersa harness run`, where the host provides them (`docs/harness.md`).
- A program that, without any grant, reads or writes files, opens network connections, or runs host code.
