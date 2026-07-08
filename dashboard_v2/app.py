import os
from datetime import datetime, timedelta, timezone

import boto3
import pandas as pd
import plotly.express as px
from dash import Dash, dcc, html, dash_table
from dash.dependencies import Input, Output

TABLE_NAME = os.environ.get("TABLE_NAME", "sales-call-classifications")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
REFRESH_INTERVAL_MS = int(os.environ.get("REFRESH_INTERVAL_MS", "60000"))  # 1 min

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(TABLE_NAME)


def load_data() -> pd.DataFrame:
    """Scan the full table into a DataFrame.

    A full scan is fine at current data volume. If this table grows large,
    switch to paginated Query calls against the classification-timestamp or
    booking-decision-timestamp GSIs, filtered by a date range, instead of
    scanning everything on every refresh.
    """
    items = []
    scan_kwargs = {}
    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    if not items:
        return pd.DataFrame(
            columns=[
                "call_id", "timestamp", "classification", "agent_id",
                "booking_decision", "decline_reason", "mc_number",
                "reference_number", "call_duration",
            ]
        )

    df = pd.DataFrame(items)

    # Fields may be missing on older records — DynamoDB is schemaless, so
    # not every item will have every attribute.
    for col in ["classification", "booking_decision", "decline_reason",
                "mc_number", "reference_number"]:
        if col not in df.columns:
            df[col] = None

    if "call_duration" not in df.columns:
        df["call_duration"] = None
    df["call_duration"] = pd.to_numeric(df["call_duration"], errors="coerce")

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.sort_values("timestamp", ascending=False)
    return df


app = Dash(__name__)
app.title = "Sales Call Dashboard"
server = app.server  # exposed for gunicorn

app.layout = html.Div(
    style={"fontFamily": "Arial, sans-serif", "margin": "20px"},
    children=[
        html.H2("Sales Call Classification Dashboard"),
        dcc.Interval(id="refresh", interval=REFRESH_INTERVAL_MS, n_intervals=0),

        # KPI row
        html.Div(id="kpi-row", style={"display": "flex", "gap": "20px", "marginBottom": "20px"}),

        # Charts row
        html.Div(
            style={"display": "flex", "gap": "20px", "flexWrap": "wrap"},
            children=[
                dcc.Graph(id="calls-over-time", style={"flex": "1", "minWidth": "400px"}),
                dcc.Graph(id="booking-decision-pie", style={"flex": "1", "minWidth": "300px"}),
                dcc.Graph(id="classification-bar", style={"flex": "1", "minWidth": "300px"}),
            ],
        ),

        html.H3("Recent Calls"),
        dash_table.DataTable(
            id="recent-calls-table",
            page_size=15,
            style_table={"overflowX": "auto"},
            style_cell={"textAlign": "left", "padding": "6px", "fontSize": "13px"},
            style_header={"fontWeight": "bold"},
        ),
    ],
)


def kpi_card(label, value):
    return html.Div(
        style={
            "border": "1px solid #ddd", "borderRadius": "8px", "padding": "16px",
            "flex": "1", "textAlign": "center", "backgroundColor": "#fafafa",
        },
        children=[
            html.Div(label, style={"fontSize": "13px", "color": "#666"}),
            html.Div(str(value), style={"fontSize": "28px", "fontWeight": "bold"}),
        ],
    )


@app.callback(
    Output("kpi-row", "children"),
    Output("calls-over-time", "figure"),
    Output("booking-decision-pie", "figure"),
    Output("classification-bar", "figure"),
    Output("recent-calls-table", "data"),
    Output("recent-calls-table", "columns"),
    Input("refresh", "n_intervals"),
)
def refresh_dashboard(_):
    df = load_data()

    total_calls = len(df)
    booked = int((df["booking_decision"] == "booked").sum()) if "booking_decision" in df else 0
    avg_duration = df["call_duration"].mean() if "call_duration" in df and not df["call_duration"].isna().all() else None
    avg_duration_display = f"{avg_duration:.0f}s" if avg_duration is not None else "N/A"

    kpis = [
        kpi_card("Total Calls", total_calls),
        kpi_card("Booked", booked),
        kpi_card("Avg Call Duration", avg_duration_display),
    ]

    # Calls over time
    if not df.empty and df["timestamp"].notna().any():
        daily = (
            df.dropna(subset=["timestamp"])
            .set_index("timestamp")
            .resample("1D")
            .size()
            .reset_index(name="count")
        )
        fig_time = px.line(daily, x="timestamp", y="count", title="Calls Per Day", markers=True)
    else:
        fig_time = px.line(title="Calls Per Day (no data yet)")

    # Booking decision breakdown
    if not df.empty and df["booking_decision"].notna().any():
        decision_counts = df["booking_decision"].fillna("unknown").value_counts().reset_index()
        decision_counts.columns = ["booking_decision", "count"]
        fig_decision = px.pie(decision_counts, names="booking_decision", values="count", title="Booking Decisions")
    else:
        fig_decision = px.pie(title="Booking Decisions (no data yet)")

    # Classification breakdown
    if not df.empty and df["classification"].notna().any():
        class_counts = df["classification"].fillna("unknown").value_counts().reset_index()
        class_counts.columns = ["classification", "count"]
        fig_class = px.bar(class_counts, x="classification", y="count", title="Calls by Classification")
    else:
        fig_class = px.bar(title="Calls by Classification (no data yet)")

    # Recent calls table
    display_cols = [c for c in [
        "timestamp", "classification", "booking_decision", "decline_reason",
        "mc_number", "reference_number", "call_duration", "agent_id",
    ] if c in df.columns]
    table_df = df[display_cols].head(50).copy()
    if "timestamp" in table_df.columns:
        table_df["timestamp"] = table_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M UTC")
    columns = [{"name": c, "id": c} for c in display_cols]
    data = table_df.to_dict("records")

    return kpis, fig_time, fig_decision, fig_class, data, columns


if __name__ == "__main__":
    # Local dev only — App Runner uses gunicorn via the Dockerfile CMD instead.
    app.run(host="0.0.0.0", port=8080, debug=True)
