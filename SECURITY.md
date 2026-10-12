# Security policy

Scrybinder runs entirely on your computer. Its local web server listens on `127.0.0.1` only (random port), requires a per-session token cookie (`SameSite=Strict`), checks the `Host` header against DNS rebinding and limits upload sizes. It opens external links only to `scryfall.com` and `www.cardmarket.com` over HTTPS.

If you find a security problem (for example a way for a web page or another local user to reach the server, read your data or run code), please **do not open a public issue**. Report it privately through GitHub's *Security → Report a vulnerability* feature on this repository, or by e-mail to the maintainers listed in the repository profile. You will get an answer within a few days.

Only the latest release is supported with security fixes.
