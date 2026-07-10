"""
Generate dummy sales call classification data into DynamoDB for dashboard testing.

Baked-in patterns:
  - ~500 calls spread over the past 90 days
  - Weekday volume ~3x weekend volume
  - Booking rate improves linearly from ~30% (90 days ago) to ~60% (today),
    among calls that reach the negotiation stage
  - Decline reasons spread evenly across 4 categories
  - Call duration varies by outcome (no-answer calls are short, negotiated
    calls run longer)

Usage:
    python generate_dummy_data.py                # writes to DynamoDB
    python generate_dummy_data.py --dry-run       # prints sample records only, no writes
    python generate_dummy_data.py --count 500 --days 90 --table sales-call-classifications
"""

import argparse
import random
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

# --- Tunable constants -------------------------------------------------

DISQUALIFY_REASONS = {
    "no_answer": 0.15,
    "no_mc_match": 0.15,
    "not_interested": 0.10,
}
# Remaining probability mass reaches the negotiation stage (qualified)

DECLINE_REASONS = [
    "rate_too_low",
    "no_available_truck",
    "schedule_conflict",
    "equipment_mismatch",
]

AGENT_IDS = ["happyrobot-va-01"]  # single AI voice agent; extend if you run multiple

WEEKDAY_WEIGHT = 3
WEEKEND_WEIGHT = 1
BUSINESS_HOUR_START = 7
BUSINESS_HOUR_END = 19


def booking_probability_for_day(day_offset: int, total_days: int) -> float:
    """Linear interpolation from 0.30 (day 0, oldest) to 0.60 (most recent day)."""
    progress = day_offset / max(total_days - 1, 1)
    return 0.30 + (0.60 - 0.30) * progress


def weighted_day_choices(total_days: int, count: int):
    """Pick `count` day-offsets (0 = oldest, total_days-1 = most recent),
    weighted so weekdays get ~3x the volume of weekend days."""
    today = datetime.now(timezone.utc).date()
    offsets = list(range(total_days))
    weights = []
    for offset in offsets:
        day = today - timedelta(days=(total_days - 1 - offset))
        is_weekend = day.weekday() >= 5  # Sat/Sun
        weights.append(WEEKEND_WEIGHT if is_weekend else WEEKDAY_WEIGHT)
    return random.choices(offsets, weights=weights, k=count)


def random_business_timestamp(day_offset: int, total_days: int) -> datetime:
    today = datetime.now(timezone.utc).date()
    day = today - timedelta(days=(total_days - 1 - day_offset))
    # Skew slightly toward mid-morning / early afternoon using a triangular distribution
    hour = int(random.triangular(BUSINESS_HOUR_START, BUSINESS_HOUR_END, 11))
    minute = random.randint(0, 59)
    second = random.randint(0, 59)
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=timezone.utc)


def random_mc_number() -> str:
    return str(random.randint(100000, 999999))


def random_reference_number() -> str:
    return f"REF-{random.randint(10000, 99999)}"


def call_duration_for(classification: str) -> int:
    if classification == "no_answer":
        return random.randint(3, 12)
    if classification == "not_interested":
        return random.randint(15, 60)
    if classification == "no_mc_match":
        return random.randint(20, 45)
    # booked or declined — reached negotiation, longer calls
    return random.randint(90, 420)


def generate_record(day_offset: int, total_days: int) -> dict:
    ts = random_business_timestamp(day_offset, total_days)

    roll = random.random()
    cumulative = 0.0
    disqualified_as = None
    for reason, prob in DISQUALIFY_REASONS.items():
        cumulative += prob
        if roll < cumulative:
            disqualified_as = reason
            break

    if disqualified_as:
        classification = disqualified_as
        booking_decision = None
        decline_reason = None
    else:
        # Reached negotiation — apply the day's booking probability trend
        booked_prob = booking_probability_for_day(day_offset, total_days)
        booked = random.random() < booked_prob
        classification = "booked" if booked else "declined"
        booking_decision = classification
        decline_reason = random.choice(DECLINE_REASONS) if not booked else None

    record = {
        "call_id": str(uuid.uuid4()),
        "timestamp": ts.isoformat(),
        "classification": classification,
        "agent_id": random.choice(AGENT_IDS),
        "call_duration": Decimal(str(call_duration_for(classification))),
    }
    if booking_decision:
        record["booking_decision"] = booking_decision
    if decline_reason:
        record["decline_reason"] = decline_reason
    if classification in ("booked", "declined"):
        record["mc_number"] = random_mc_number()
    if classification == "booked":
        record["reference_number"] = random_reference_number()

    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=500, help="Number of records to generate")
    parser.add_argument("--days", type=int, default=90, help="Span of days to spread records across")
    parser.add_argument("--table", type=str, default="sales-call-classifications", help="DynamoDB table name")
    parser.add_argument("--region", type=str, default="us-east-1", help="AWS region")
    parser.add_argument("--dry-run", action="store_true", help="Print sample records instead of writing to DynamoDB")
    args = parser.parse_args()

    day_offsets = weighted_day_choices(args.days, args.count)
    records = [generate_record(offset, args.days) for offset in day_offsets]

    if args.dry_run:
        print(f"Generated {len(records)} records (dry run — nothing written).\n")
        print("Sample of 5:")
        for r in records[:5]:
            print(r)
        booked = sum(1 for r in records if r.get("booking_decision") == "booked")
        declined = sum(1 for r in records if r.get("booking_decision") == "declined")
        print(f"\nTotals — booked: {booked}, declined: {declined}, "
              f"disqualified: {len(records) - booked - declined}")
        return

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    table = dynamodb.Table(args.table)

    print(f"Writing {len(records)} records to '{args.table}' in {args.region}...")
    with table.batch_writer() as batch:
        for record in records:
            batch.put_item(Item=record)

    print("Done.")


if __name__ == "__main__":
    main()