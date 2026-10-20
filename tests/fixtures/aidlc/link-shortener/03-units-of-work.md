# Units of Work — Link Shortener

Each UoW is one buildable feature. One feature per UoW in the AREA spec.

- **UoW-1 — shorten-url**: Create a short link from a long URL. Generate a unique 6-char URL-safe code, store it with the URL, and return the code. (covers US-1)
- **UoW-2 — redirect**: Resolve a short code to its stored URL for redirection; an unknown code is not found. (covers US-2)
- **UoW-3 — visit-count**: Increment a link's visit count on each successful resolve, and expose the current count for a code. (covers US-3)
- **UoW-4 — validate-url**: Reject an input that is not a valid http(s) URL before any link is created. (covers US-4)
