# Complot recovery — local implementation, 6 October 2026

This change is not deployed and has no new production run. Historical data is unchanged.

The scan window still filters **application submission date**, inclusively. Permit dates
are evidence associated with those applications and may be outside the window. A query
for permits issued in January needs a separate discovery strategy including older
applications; this change does not implement that strategy.

`public_search_url` remains a display URL. Its `#request/...` fragment is executed by the
municipal SPA, not sent to an HTTP server. Substituting that URL into `httpx.get()` would
fetch the shell and cannot be treated as successful detail collection.

An operator may configure `public_detail_url_template` plus
`public_detail_route_evidence` **only after documenting the ordinary public HTTP request**
on an accessible municipal route. The template must contain `{request_number}`, use HTTPS,
have the same host as `public_search_url`, and have no fragment or credentials. Optional
`{site_id}` is supported. Invalid configuration preserves the summary and requires review;
it never falls back to DLL after a failed public detail request. Do not insert a guessed
endpoint. The current live cities have no such endpoint configured; their existing shared
DLL transport is preserved and explicitly identified in diagnostics. This addition prepares
an auditable route choice; it does not prove access or recover production permits by itself.

Any challenge or source block still uses the existing `PublicHttpClient` stop rules.
No session/challenge token, spoofed header, browser fingerprint, proxy or CAPTCHA service
is added. The preserved Herzliya tab remains challenged, so municipal endpoint verification
and a controlled live run are pending human recovery.

Complot issuance now requires an explicit current permit number and issue date. Blank,
zero and dash numbers are unknown. Only exact permit field labels are used; previous permit
fields, approval decisions, deposits and event dates cannot prove issuance. The validator
uses the same rule. This does not change Jerusalem's separately verified source rules.

Short numeric autocomplete labels (at least five digits) receive candidate request units
as well as prefix units where appropriate. Exact public number search must confirm each
candidate; a hint is never saved as an application by discovery alone. This adds requests
and must be measured in the controlled pilot. Capped pages containing long identifiers
continue beyond the configured final digit. Raw labels and the configured length survive
in review diagnostics. These guards do not independently certify exhaustive coverage.

Partial summaries retain field provenance and the actual fetch URL, requested identifier,
detail failure and date basis. Detail records retain raw fields, source provenance and
separate identity/detail/status/permit/coverage scopes. Summary building-file/land fields
are retained when absent from details. Conflicting nonempty duplicate fields require review.

`tests/fixtures/complot_recovery.json` contains minimal **reconstructed** markup inputs
from preserved JSON/AX evidence, with source-file hashes. It is not an HTTP response capture
or fresh source validation. Six offline cases cover Herzliya 20260010/38/11/15, Eilat
20260001 and Rehovot 20260005. The two known missed Herzliya permits, Eilat's permit and
Herzliya's existing permit are parsed; 20260011 remains unknown despite its production
event. No historical database snapshot is edited to add these permits.
