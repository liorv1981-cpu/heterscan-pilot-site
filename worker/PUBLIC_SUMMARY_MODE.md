# Public summary collection

When there is no additional source access, an operator can choose **סיכומי בקשות בלבד**
before starting a new Complot run. This mode reads the same documented autocomplete and
number-search routes used by the existing adapter. It never requests `GetBakashaFile`.
It does not establish that the public search is currently readable.

The authenticated `start-run` handler validates `collectionMode` (`full_details` or
`public_summary`) against the city's adapter. It saves that choice both at the top of the
new run's configuration snapshot and as `city.adapter_config.collection_mode` inside that
snapshot. It does not update the city row or any older run. Omitted mode preserves the
existing detail strategy. Invalid values and unsupported adapter families are rejected
before any state changes.

The worker reads the existing immutable adapter configuration. For each in-range public
summary it keeps the application identity/date/address and any building-file/block/parcel
fields present in that summary, with field provenance. The detail state is `not_requested`,
not a claim that a challenge was observed. It returns the partial record through the existing
review/validator/persistence path. Permit status remains `unknown` and the final run requires
review. The existing independent zero gate is unchanged.

If the search itself returns a visible challenge, a denial, blank or unrecognized markup,
the ordinary safety guards still apply. A detail challenge does not trigger an automatic
route switch; this policy must be chosen before collection. Shared 429/Retry-After controls
remain in force. The mode cannot fill protected permit details or verify city completeness.

New XLSX exports append the collection policy and unknown-permit count to the summary sheet.
Summary-mode reports also include **מקור שדות הסיכום** with each field/value, its public-search
origin, and source URL. The regular result columns and source hyperlink positions are
preserved. Historical workbooks/snapshots are not regenerated or modified.

The UI offers the mode only for Complot cities, locks it during active work, and resets it
when another city is chosen. Run history reads the stored mode. The results area separately
counts unknown permits; it does not interpret a zero count of verified permits as absence.

The local demo simulates partial records for browser validation. Its bundled full-detail
demo workbook is not served as a summary-mode report. Actual XLSX generation is validated
with the worker's offline fixture pipeline. Production deployment and source availability
were not validated by these local checks.

Implementation uses the existing request-body/snapshot path; no database migration,
authorization change, new municipal endpoint or third-party CAPTCHA service is introduced.
Supabase request-handling reference:
[Edge Function request handling](https://supabase.com/docs/guides/functions/quickstart).
