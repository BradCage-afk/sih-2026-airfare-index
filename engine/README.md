# APIx — calculation engine and export API

The collector gathers fares. This turns them into an index a statistical office
can ingest.

```bash
python3 engine/engine.py                 # print the series
python3 engine/engine.py --json          # machine-readable
python3 engine/engine.py --write         # upsert into apix_daily

cd api && uvicorn main:app --port 8000   # export API
curl "localhost:8000/api/v1/apix?month=2026-09"
```

## Method

| Step | What | Why |
|---|---|---|
| 1 | **Minimum logical fare** per route × lead-time × day | What a price collector records — the fare a consumer could transact at |
| 2 | **Price relatives** against the base period | Routes at very different fare levels contribute comparably |
| 3 | **Jevons** — geometric, not arithmetic, mean | International standard for elementary aggregates; symmetric to doubling and halving |
| 4 | **Seat weighting** by route | Delhi–Mumbai moves the index ~3× Delhi–Srinagar, as it should |

```
APIx_t = 100 × exp( Σ wᵢ · ln(Pᵢ,t / Pᵢ,0) / Σ wᵢ )
```

## Publication discipline

A day is marked **provisional** when it covers under 60% of basket weight or
fewer than 3 lead-time buckets. The figure is still computed and served — it is
just never presented as a headline, because an index built from one lead-time
bucket is not comparable with one built from the whole basket. Cells with fewer
than 3 observed flights are excluded entirely, and a price relative outside
0.2–5.0 is treated as a data fault rather than a price move.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/apix?month=YYYY-MM` | Monthly index plus its daily components |
| `GET /api/v1/apix?from=&to=` | A daily series |
| `GET /api/v1/apix/latest` | Most recent figure |
| `GET /api/v1/health` | Liveness **and freshness** — an ingesting system needs to know the number is current |

Set `APIX_API_KEYS` to a comma-separated list to require `X-API-Key`. Verified:
no key → 401, wrong key → 401, correct key → 200. Unset means open, which is
fine locally and refused the moment any key is configured.

Every response carries `base_period` and `method`, so an ingested number can
never be separated from how it was produced.
