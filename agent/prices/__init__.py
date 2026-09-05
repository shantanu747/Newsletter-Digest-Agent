"""Price data clients — daily closes for track-record scoring.

Only Stooq's free, unauthenticated CSV endpoint is supported. Fetchers here are
read-only and fail-soft by design: every failure mode returns an empty result
and logs, never raises, so a price outage can never break a Signals run.
"""
