# Public-source response evidence

The HTTP client records `visible_challenge`, `challenge_script_marker`, `challenge_badge`,
`request_detail_markup`, HTTP status, origin, endpoint category, capture time and an allowlist
of response headers (Content-Type, Date, Retry-After). It stores neither response bodies nor
script contents, form values, cookies or challenge tokens in those diagnostics.

`visible_challenge` means recognizable challenge text or a non-hidden challenge container/iframe
in the **static HTML**. It is not independent browser-rendering verification. Explicitly hidden
content, scripts, styles, templates, form values and reCAPTCHA branding badges are excluded.
External CSS and JavaScript can affect actual rendering. Script or badge presence alone cannot
establish that a user encountered a challenge.

HTTP 401/403, recognized F5 rejection, explicit denial or visible challenge raises
`AdapterReviewRequired`. The client then stops further transport calls to that origin for its
remaining lifetime, including cached lookups and calls queued behind the rate limiter. Skipped
requests have null HTTP/challenge observations and link to the original `blocking_evidence`;
they do not claim the skipped page displayed a challenge. This stop is scoped to the client,
not a permanent or city-wide assertion, and is not a distributed persistent challenge gate.

Script-only responses continue to the adapter. Complot requires matching request identity,
a valid submission date, expected detail containers and actual detail content. Missing, empty,
changed or mismatched details become `detail_missing`, `parser_mismatch` or `identity_mismatch`,
with the captured HTTP evidence attached. The existing public summary is retained as a partial
record, with permit verification `unknown`, and the work unit requires review. Legacy search
HTML with no identifiable rows also requires review. Invalid discovery JSON is not an empty
successful search. Structured empty autocomplete results still cannot verify a run-level zero:
the runner retains its existing `zero_not_verified` guard.

Valid details record `parser_result=parsed`; the unchanged validator then checks already
collected payloads before persistence. Its passing consistency check does not independently
prove city coverage. Unknown permits remain explicit in the database and workbook; the zero
count of verified permits does not claim no permits exist.

The preceding 429 implementation is preserved: server Retry-After, adaptive cooldown and
shared source coordination are unchanged. Offline fixtures test a second call during cooldown
without allowing another transport request.

## Validation and boundaries

Run from `worker/`: `python -m pytest -q` and `python -m ruff check heterscan tests`.
The new fixtures are synthetic and use MockTransport. No live municipal source or CAPTCHA
service is accessed, no token is reused and no terms are accepted.

Local code validation does not authorize a scan or clear any city acceptance gate. A future
Rehovot source check needs explicit authorization, a fresh no-active-run/cooldown preflight
and an already documented permitted route. Stop on a challenge/block; preserve historical
evidence and keep unavailable data partial/unknown.

Offline inventory, original-file hashes and Hebrew findings:
[2026-10-02 local evidence review](../outputs/captcha-classification-2026-10-02T19-20-59Z/VERIFICATION_HE.md).
