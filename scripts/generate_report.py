"""
Generate a markdown report summarizing key findings and trends from the
sales call classification data in DynamoDB — mirrors the metrics shown on
the dashboard, but as a written narrative instead of charts.

Usage:
    python3 generate_report.py
    python3 generate_report.py --table sales-call-classifications --region us-east-1
    python3 generate_report.py --output report.md
"""

import argparse
from datetime import datetime, timezone

import boto3
import pandas as pd


def load_data(table_name: str, region: str) -> pd.DataFrame:
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    items = []
    scan_kwargs = {}
    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    df = pd.DataFrame(items)
    if df.empty:
        return df

    for col in ["classification", "booking_decision", "decline_reason",
                "mc_number", "reference_number"]:
        if col not in df.columns:
            df[col] = None

    if "call_duration" not in df.columns:
        df["call_duration"] = None
    df["call_duration"] = pd.to_numeric(df["call_duration"], errors="coerce")

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    return df.sort_values("timestamp")


def booking_rate_trend(df: pd.DataFrame) -> tuple[str, float, float]:
    """Compare booking rate in the first half of the date range vs. the
    second half. Returns (direction, first_half_rate, second_half_rate)."""
    qualified = df.dropna(subset=["booking_decision", "timestamp"])
    if qualified.empty:
        return "no data", 0.0, 0.0

    midpoint = qualified["timestamp"].min() + (
        qualified["timestamp"].max() - qualified["timestamp"].min()
    ) / 2
    first_half = qualified[qualified["timestamp"] < midpoint]
    second_half = qualified[qualified["timestamp"] >= midpoint]

    def rate(d):
        if d.empty:
            return 0.0
        return (d["booking_decision"] == "booked").mean() * 100

    r1, r2 = rate(first_half), rate(second_half)
    if r2 - r1 > 3:
        direction = "improving"
    elif r1 - r2 > 3:
        direction = "declining"
    else:
        direction = "roughly flat"
    return direction, r1, r2


def weekday_weekend_split(df: pd.DataFrame) -> tuple[int, int]:
    valid = df.dropna(subset=["timestamp"])
    is_weekend = valid["timestamp"].dt.dayofweek >= 5
    return int((~is_weekend).sum()), int(is_weekend.sum())


def build_report(df: pd.DataFrame, table_name: str) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if df.empty:
        return (
            f"# Sales Call Classification Report\n\n"
            f"*Generated {generated_at} from table `{table_name}`*\n\n"
            f"No records found in the table yet.\n"
        )

    total_calls = len(df)
    date_min = df["timestamp"].min()
    date_max = df["timestamp"].max()

    qualified = df.dropna(subset=["booking_decision"])
    booked = int((qualified["booking_decision"] == "booked").sum())
    declined = int((qualified["booking_decision"] == "declined").sum())
    overall_booking_rate = (booked / len(qualified) * 100) if len(qualified) else 0.0
    qualification_rate = (len(qualified) / total_calls * 100) if total_calls else 0.0

    trend_direction, rate_early, rate_late = booking_rate_trend(df)

    weekday_count, weekend_count = weekday_weekend_split(df)

    # Disqualification breakdown (calls that never reached booking/declined)
    disqualified = df[df["booking_decision"].isna()]
    disqualify_breakdown = (
        disqualified["classification"].value_counts().to_dict()
        if not disqualified.empty else {}
    )

    # Decline reasons
    declined_df = df[df["booking_decision"] == "declined"].dropna(subset=["decline_reason"])
    decline_counts = declined_df["decline_reason"].value_counts()
    top_decline_reason = decline_counts.index[0] if not decline_counts.empty else None
    top_decline_pct = (
        (decline_counts.iloc[0] / len(declined_df) * 100) if not decline_counts.empty else 0.0
    )

    # Call duration by outcome
    duration_by_decision = (
        df.dropna(subset=["call_duration", "booking_decision"])
        .groupby("booking_decision")["call_duration"]
        .agg(["mean", "median", "count"])
        if "call_duration" in df.columns else pd.DataFrame()
    )

    lines = []
    lines.append("# Sales Call Classification Report")
    lines.append("")
    lines.append(f"*Generated {generated_at} from table `{table_name}`*")
    lines.append(
        f"*Data range: {date_min.strftime('%Y-%m-%d') if pd.notna(date_min) else 'N/A'} "
        f"to {date_max.strftime('%Y-%m-%d') if pd.notna(date_max) else 'N/A'}*"
    )
    lines.append("")

    lines.append("## Key Takeaways")
    lines.append("")
    lines.append(f"- **{total_calls} total calls** processed in the period covered.")
    lines.append(
        f"- **{qualification_rate:.0f}% of calls reached the negotiation stage** "
        f"({len(qualified)} of {total_calls}); the rest were disqualified "
        f"(no answer, MC not found, not interested)."
    )
    lines.append(
        f"- **Overall booking rate is {overall_booking_rate:.0f}%** among qualified calls "
        f"({booked} booked, {declined} declined)."
    )
    lines.append(
        f"- **Booking rate is {trend_direction}** over the period: "
        f"{rate_early:.0f}% in the first half of the range vs. {rate_late:.0f}% in the second half."
    )
    if top_decline_reason:
        lines.append(
            f"- **Top decline reason is \"{top_decline_reason}\"**, accounting for "
            f"{top_decline_pct:.0f}% of all declined calls."
        )
    if weekday_count + weekend_count > 0:
        weekday_pct = weekday_count / (weekday_count + weekend_count) * 100
        lines.append(
            f"- **{weekday_pct:.0f}% of call volume happens on weekdays** "
            f"({weekday_count} weekday calls vs. {weekend_count} weekend calls)."
        )
    if not duration_by_decision.empty and "booked" in duration_by_decision.index and "declined" in duration_by_decision.index:
        booked_mean = duration_by_decision.loc["booked", "mean"]
        declined_mean = duration_by_decision.loc["declined", "mean"]
        longer = "booked" if booked_mean > declined_mean else "declined"
        lines.append(
            f"- **{longer.capitalize()} calls run longer on average** "
            f"(booked: {booked_mean:.0f}s avg, declined: {declined_mean:.0f}s avg)."
        )
    lines.append("")

    lines.append("## Funnel Breakdown")
    lines.append("")
    lines.append("| Stage | Count | % of Total |")
    lines.append("|---|---|---|")
    lines.append(f"| Total calls | {total_calls} | 100% |")
    lines.append(f"| Reached negotiation (qualified) | {len(qualified)} | {qualification_rate:.0f}% |")
    lines.append(f"| Booked | {booked} | {(booked/total_calls*100):.0f}% |")
    lines.append(f"| Declined | {declined} | {(declined/total_calls*100):.0f}% |")
    if disqualify_breakdown:
        for reason, count in disqualify_breakdown.items():
            lines.append(f"| Disqualified — {reason} | {count} | {(count/total_calls*100):.0f}% |")
    lines.append("")

    if not decline_counts.empty:
        lines.append("## Decline Reasons")
        lines.append("")
        lines.append("| Reason | Count | % of Declines |")
        lines.append("|---|---|---|")
        for reason, count in decline_counts.items():
            lines.append(f"| {reason} | {count} | {(count/len(declined_df)*100):.0f}% |")
        lines.append("")

    if not duration_by_decision.empty:
        lines.append("## Call Duration by Outcome")
        lines.append("")
        lines.append("| Outcome | Avg Duration (s) | Median Duration (s) | Count |")
        lines.append("|---|---|---|---|")
        for outcome, row in duration_by_decision.iterrows():
            lines.append(f"| {outcome} | {row['mean']:.0f} | {row['median']:.0f} | {int(row['count'])} |")
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(
        "This report is generated directly from the live DynamoDB table via "
        "`generate_report.py` — rerun it any time for an updated snapshot. "
        "Trend direction compares the first vs. second half of the available "
        "date range, so accuracy improves as more data accumulates over time."
    )
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=str, default="sales-call-classifications")
    parser.add_argument("--region", type=str, default="us-east-1")
    parser.add_argument("--output", type=str, default="report.md")
    args = parser.parse_args()

    print(f"Pulling data from '{args.table}' in {args.region}...")
    df = load_data(args.table, args.region)
    print(f"Loaded {len(df)} records. Generating report...")

    report = build_report(df, args.table)

    with open(args.output, "w") as f:
        f.write(report)

    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()