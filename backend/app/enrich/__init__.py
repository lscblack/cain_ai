"""KAI data-enrichment subsystem.

Pulls identity / land / telecom records from the operator's own external
databases via registered endpoints, deduplicates and links them (people,
parcels + ownership history, phones, and NID face photos), all under a
per-minute rate limit and as resumable background jobs.
"""
