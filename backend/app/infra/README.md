# Redis Caches

Enable caches with `REDIS_ENABLED=true` and `REDIS_URL` in the backend environment.
PostgreSQL remains the source of truth for ownership and conversation state.

| Cache | Default TTL | Key inputs |
| --- | --- | --- |
| Weather | 30 minutes | Location, mode, day, forecast offsets, units, language |
| Goong forward geocoding | 24 hours | Provider URL, normalized address, administrative-unit option |
| Conversation context | 30 minutes | User ID and conversation ID |

Configure TTLs using `CACHE_WEATHER_TTL_SECONDS`, `CACHE_GEOCODE_TTL_SECONDS`,
and `CACHE_CONTEXT_TTL_SECONDS`. Keys use the `vta:cache` prefix and hashed inputs.
Weather failures and empty geocoding results are not cached. Redis connection
errors and malformed JSON fall back to the provider or database.

The async executor caches weather observations. Map, Routing, and Distance
Matrix share a Goong client whose geocoding cache reaches the application event
loop from worker threads. `ThreadJsonCache` must only be used from these workers.

Context is read only after verifying ownership in PostgreSQL. A cache hit skips
the recent-messages query only when its activity timestamp matches PostgreSQL.
Writing a user message invalidates the snapshot; committing a successful answer
replaces it and resets the TTL. A failed turn leaves no reusable snapshot.
