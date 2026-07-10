# Sales Call Classification Report

*Generated 2026-07-10 03:40 UTC from table `sales-call-classifications`*
*Data range: 2026-04-10 to 2026-07-08*

## Key Takeaways

- **501 total calls** processed in the period covered.
- **61% of calls reached the negotiation stage** (304 of 501); the rest were disqualified (no answer, MC not found, not interested).
- **Overall booking rate is 44%** among qualified calls (135 booked, 169 declined).
- **Booking rate is improving** over the period: 37% in the first half of the range vs. 52% in the second half.
- **Top decline reason is "rate_too_low"**, accounting for 32% of all declined calls.
- **87% of call volume happens on weekdays** (435 weekday calls vs. 65 weekend calls).
- **Booked calls run longer on average** (booked: 269s avg, declined: 241s avg).

## Funnel Breakdown

| Stage | Count | % of Total |
|---|---|---|
| Total calls | 501 | 100% |
| Reached negotiation (qualified) | 304 | 61% |
| Booked | 135 | 27% |
| Declined | 169 | 34% |
| Disqualified — no_answer | 76 | 15% |
| Disqualified — no_mc_match | 72 | 14% |
| Disqualified — not_interested | 48 | 10% |
| Disqualified — test_call | 1 | 0% |

## Decline Reasons

| Reason | Count | % of Declines |
|---|---|---|
| rate_too_low | 54 | 32% |
| schedule_conflict | 42 | 25% |
| no_available_truck | 37 | 22% |
| equipment_mismatch | 36 | 21% |

## Call Duration by Outcome

| Outcome | Avg Duration (s) | Median Duration (s) | Count |
|---|---|---|---|
| booked | 269 | 277 | 135 |
| declined | 241 | 229 | 169 |

## Notes

This report is generated directly from the live DynamoDB table via `generate_report.py` — rerun it any time for an updated snapshot. Trend direction compares the first vs. second half of the available date range, so accuracy improves as more data accumulates over time.
