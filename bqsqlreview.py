# BigQuery SQL Code Reviewer - Sample Kickstart
# Features: Linting, EXPLAIN analysis, performance scoring, CircleCI-ready

import os
import re
import sqlfluff
from google.cloud import bigquery
from datetime import datetime, timezone

# Initialize BigQuery client
client = bigquery.Client()

# ---------------------------
# SQL Best Practice Checks (BigQuery specific)
# ---------------------------
def check_best_practices(sql_text):
    issues = []

    if re.search(r"SELECT\\s+\\*", sql_text, re.IGNORECASE):
        issues.append("Avoid using SELECT * — list specific columns.")

    if "JOIN" in sql_text.upper() and not re.search(r"JOIN\\s+.*\\s+ON", sql_text, re.IGNORECASE):
        issues.append("JOIN without ON clause — may cause cross join or cartesian product.")

    if "WHERE" in sql_text.upper() and "PARTITION" not in sql_text.upper():
        issues.append("Query may be missing a partition filter on partitioned table.")

    if re.search(r"CROSS\\s+JOIN", sql_text, re.IGNORECASE):
        issues.append("Avoid CROSS JOIN — expensive unless filtered.")

    if sql_text.count("(SELECT") > 2:
        issues.append("Query may be too deeply nested. Consider simplifying or using CTEs.")

    return issues

# ---------------------------
# SQL Linting (using SQLFluff)
# ---------------------------
def lint_sql(sql_text):
    result = sqlfluff.lint(sql_text, dialect="bigquery")
    return result

# ---------------------------
# BigQuery EXPLAIN Analysis
# ---------------------------
def explain_query(sql_text):
    query_job = client.query("EXPLAIN " + sql_text)
    result = query_job.result()
    explain_output = [dict(row.items()) for row in result]
    return explain_output

# ---------------------------
# Fetch Query Stats (from JOBS)
# ---------------------------
def fetch_query_stats(job_id):
    job = client.get_job(job_id)
    stats = job.statistics
    return {
        "total_bytes_processed": stats.total_bytes_processed,
        "total_slot_ms": stats.total_slot_ms,
        "start_time": stats.start_time,
        "end_time": stats.end_time
    }

# ---------------------------
# Performance Scoring System
# ---------------------------
def score_query(stats):
    score = 100
    messages = []

    if stats["total_bytes_processed"] > 1_000_000_000:  # >1GB
        score -= 20
        messages.append("Large scan size")
    if stats["total_slot_ms"] > 10000:
        score -= 15
        messages.append("High slot usage")
    if stats["end_time"] and stats["start_time"]:
        runtime = (stats["end_time"] - stats["start_time"]).total_seconds()
        if runtime > 10:
            score -= 10
            messages.append("Long runtime")

    return max(score, 0), messages

# ---------------------------
# Run Full Review
# ---------------------------
def review_sql(sql_text):
    lint_issues = lint_sql(sql_text)
    best_practice_issues = check_best_practices(sql_text)
    explain = explain_query(sql_text)
    job = client.query(sql_text)
    job.result()  # Wait for job to complete
    stats = fetch_query_stats(job.job_id)
    score, feedback = score_query(stats)

    return {
        "lint_issues": lint_issues,
        "best_practice_issues": best_practice_issues,
        "score": score,
        "feedback": feedback,
        "slot_ms": stats["total_slot_ms"],
        "bytes_processed": stats["total_bytes_processed"],
        "explain_plan": explain
    }

# ---------------------------
# Example Usage
# ---------------------------
if __name__ == "__main__":
    sample_query = """
    SELECT * FROM `your_project.your_dataset.large_table`
    WHERE DATE(created_at) = '2024-01-01'
    """

    review = review_sql(sample_query)
    print("Performance Score:", review["score"])
    print("Slot Time (ms):", review["slot_ms"])
    print("Bytes Processed:", review["bytes_processed"])
    print("Lint Warnings:", review["lint_issues"])
    print("Best Practice Suggestions:", review["best_practice_issues"])
    print("Performance Feedback:", review["feedback"])
    print("Explain Plan:", review["explain_plan"])