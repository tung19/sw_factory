# Testing Posture — Link Shortener

Each statement below is one acceptance criterion, tagged to the UoW it tests
(Given / When / Then — observable and testable).

## UoW-1 — shorten-url
- UoW-1: Given a valid URL `https://example.com/a/very/long/path`, When it is shortened, Then a 6-character URL-safe code is returned and stored against that URL.
- UoW-1: Given the same URL is shortened twice, When codes are generated, Then each code is unique (no collision reuse).

## UoW-2 — redirect
- UoW-2: Given a code that was created for `https://example.com`, When the code is resolved, Then the original URL `https://example.com` is returned.
- UoW-2: Given a code that was never created, When it is resolved, Then the result is "not found" (no redirect).

## UoW-3 — visit-count
- UoW-3: Given a freshly created link, When it has never been resolved, Then its visit count is 0.
- UoW-3: Given a link resolved 3 times, When its count is read, Then the count is 3.

## UoW-4 — validate-url
- UoW-4: Given the input `not-a-url`, When shortening is attempted, Then it is rejected and no link is created.
- UoW-4: Given the input `ftp://example.com`, When shortening is attempted, Then it is rejected (only http/https allowed).
