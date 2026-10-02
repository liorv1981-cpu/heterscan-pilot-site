# Source payload validation

`heterscan.validator` checks every collected `ApplicationRecord` before the worker saves it. It uses only responses the adapter has already fetched; validation sends no additional municipal requests.

## Checks

- Every record must belong to the requested city and adapter, have an application number and an in-range submission date, and link to the expected source family and the same application number.
- Complot checks the public number-search row against the detail page for number, submission date and address. It also checks that an issued-permit claim is supported by the detail fields. The adapter now retains both source payloads in `raw_data`.
- Jerusalem checks the street-search candidate against the case number, a process event against the submission date, the available address fields, and explicit permit evidence when an issued permit is claimed.
- Tel Aviv checks the ArcGIS row's number, date, address and permit fields against the normalized record. This is a consistency check of one source payload; it does not independently establish source completeness.

Passing records retain their fields and receive `raw_data.validator.status = "passed_consistency_checks"` with the validator version, evidence level and checked field names. This status describes consistency of the collected payloads. City acceptance and independent zero validation remain separate gates.

When evidence disagrees, the work unit becomes `requires_review`. The worker keeps a source-backed summary as a partial record when it can establish a number and in-range date. Permit and approval claims are removed from that partial record and the validator's issue codes remain in `raw_data.validator` and the unit log. A Complot link mismatch is repaired from the public-search route while the record remains partial and under review. Records with an unresolved city, identity or date, or a link that cannot be repaired safely, are withheld from the results while their work unit retains the review reason. A missing or blocked detail page remains `requires_review`.

The validator does not solve CAPTCHA, circumvent rate limits, infer that an unknown permit does not exist, or turn an unverified zero into a verified zero.
