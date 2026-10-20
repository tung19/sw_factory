# Password strength checker

A tiny library that rates how strong a password is, so a signup form can give the
user instant feedback.

Expose one pure function `rate(password)` that returns `"weak"`, `"medium"`, or
`"strong"`:

- Shorter than 8 characters → **weak**.
- 8+ characters with at least one letter AND one digit (but not strong) → **medium**.
- 12+ characters with at least one letter, one digit, AND one symbol → **strong**.
- 8+ characters but missing a digit (e.g. letters only) → **weak**.
- An empty or non-string input is invalid → throw an error.
