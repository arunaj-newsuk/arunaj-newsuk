import re
from google.cloud import bigquery


def read_sql_file(path):
    with open(path, "r", encoding="utf-8") as file:
        return file.read()


def check_bigquery_best_practices(sql_text: str):
    warnings = []

    # Normalize SQL for easier pattern detection
    sql = sql_text.strip().lower()

    # 1. SELECT * usage — only outside WITH clause
    main_query = sql
    if "with" in sql:
        # Remove WITH block
        with_block = re.findall(r"with\s+.*?\)\s*select", sql, re.DOTALL)
        if with_block:
            main_query = sql.replace(with_block[0], "select")  # replace WITH block with just 'select'

    if re.search(r"select\s+\*", main_query):
        warnings.append("❌ Avoid using SELECT * in main query — select only required columns.")

    # 2. Partition filter (basic check)
    if "partition" in sql and not re.search(r"where.*(partition|date)", sql, re.DOTALL):
        warnings.append("❌ Query on a partitioned table might be missing a partition filter.")

    # 3. Join without ON clause
    join_count = len(re.findall(r"\bjoin\b", sql))
    on_count = len(re.findall(r"\bon\b", sql))
    if join_count > on_count:
        warnings.append("❌ One or more JOINs are missing ON conditions — may lead to cartesian joins.")

    # 4. CROSS JOIN detection
    if "cross join" in sql:
        warnings.append("⚠️ CROSS JOIN detected — use with care, especially on large tables.")

    # 5. Subqueries vs CTEs
    nested_subquery_count = sql.count("(select")
    has_cte = "with" in sql

    if nested_subquery_count > 2 and not has_cte:
        warnings.append("❌ Deeply nested subqueries detected — consider using WITH CTEs for better readability.")

    # 6. Repeated subquery detection
    subqueries = re.findall(r"\((\s*select.*?from.*?)(?=\))", sql, re.DOTALL)
    subquery_patterns = [sq.strip() for sq in subqueries]
    duplicates = len(subquery_patterns) != len(set(subquery_patterns))
    if duplicates:
        warnings.append("❌ Repeated subqueries detected — refactor using CTEs to avoid duplication.")

    # 7. CTE used only once
    cte_matches = re.findall(r"with\s+(.*?)\s+as\s*\(", sql, re.DOTALL)
    if has_cte and len(cte_matches) > 0:
        for cte_name in cte_matches:
            cte_name_clean = cte_name.strip().split()[0]
            usage_count = sql.count(cte_name_clean)
            if usage_count == 1:
                warnings.append(f"⚠️ CTE '{cte_name_clean}' is used only once — consider using a subquery instead.")

    # 8. Join on computed expressions
    if re.search(r"on\s+.*(date|cast|substr|format|extract)\s*\(", sql):
        warnings.append("⚠️ Join on computed expressions — prefer joining on raw/precomputed keys.")

    # 9. LEFT JOIN used but no null check in WHERE clause
    if "left join" in sql and "is null" not in sql and "ifnull" not in sql:
        warnings.append("⚠️ LEFT JOIN used without IS NULL check — consider INNER JOIN if nulls not needed.")

    # 10. Multiple joins without filtering
    join_blocks = re.findall(r"(from\s+\S+\s+join\s+\S+)", sql)
    for block in join_blocks:
        if "where" not in block and "on" in block:
            warnings.append("⚠️ Multiple joins without filtering — consider filtering tables before joining.")

    # 11. Duplicate join keys across joins (potential cartesian product or fanout)
    join_keys = re.findall(r"on\s+(\S+)\s*=\s*(\S+)", sql)
    key_pairs = [f"{a}={b}" for a, b in join_keys]
    if len(key_pairs) != len(set(key_pairs)):
        warnings.append("⚠️ Same join key used multiple times — check for fanout joins or duplicates.")

    # 12. Detect repeated COUNTIF patterns
    countif_patterns = re.findall(r'countif\([^)]+\)', sql)
    if len(set(countif_patterns)) < len(countif_patterns):
        warnings.append("⚠️ Repeated COUNTIF patterns detected — consider refactoring with reusable expressions.")

    if re.search(r"count\s*\(\s*distinct\s+\w+", sql) and "approx_count_distinct" not in sql:
        warnings.append("⚠️ Consider using APPROX_COUNT_DISTINCT for large distinct counts.")

    # 13. ORDER BY RAND() detection
    if re.search(r"order\s+by\s+rand\s*\(", sql):
        warnings.append("⚠️ ORDER BY RAND() detected — this is very expensive and should be avoided in large datasets.")

    return warnings


def estimate_query_cost(sql: str, project_id: str) -> tuple:
    try:
        client = bigquery.Client(project=project_id)

        job_config = bigquery.QueryJobConfig(
            dry_run=True,
            use_query_cache=False
        )

        query_job = client.query(sql, job_config=job_config)

        scan_mb = query_job.total_bytes_processed / (1024 * 1024) if query_job.total_bytes_processed else 0
        billed_mb = query_job.total_bytes_billed / (1024 * 1024) if query_job.total_bytes_billed else 0

        estimated_cost_usd = (scan_mb / 1024) / 1024 * 5.0
        # print(f"Estimated $ Cost: ${estimated_cost_usd:.4f}")

        # SAFE way to get query plan — no crash if not present
        plan = query_job._properties.get("statistics", {}).get("query", {}).get("queryPlan", [])

        num_slots = sum([step.get('slotMs', 0) for step in plan]) if plan else 0
        num_steps = len(plan) if plan else 0
        num_shuffles = sum(1 for step in plan if step.get('shuffleOutputBytes', 0) > 0) if plan else 0

        return scan_mb, estimated_cost_usd, billed_mb, num_slots, num_steps, num_shuffles

    except Exception as e:
        print(f"Error estimating query cost: {str(e)}")
        return None, None, None, None, None, None


if __name__ == "__main__":

    # sql_file_path = "/Users/ajayabalu/PycharmProjects/sqlcode_review/sql/sun_club_summary_v9.sql"
    sql_file_path = "/Users/ajayabalu/PycharmProjects/sqlcode_review/sql/tnl_times_customer_subscription_profile_latest.sql"
    sql_query = read_sql_file(sql_file_path)
    issues = check_bigquery_best_practices(sql_query)

    print("🔍 SQL Review Results:")

    if issues:
        for i, issue in enumerate(issues, 1):
            print(f"{i}. {issue}")
    else:
        print("✅ No major issues detected! Looks good.")

    scan_mb, estimated_cost_usd, billed_mb, num_slots, num_steps, num_shuffles = estimate_query_cost(sql_query,
                                                                                                     project_id="nuk-data-dev-dw-customer")

    print("\n=== Dynamic Analysis ===")
    print(f"Estimated scan: {scan_mb:.2f} MB" if scan_mb else "Could not estimate scan")
    print(f"Estimated cost: {estimated_cost_usd}")

    print(f"Total billed: {billed_mb:.2f} MB" if billed_mb else "Could not estimate billed bytes")
    print(f"Query Steps: {num_steps}")
    print(f"Num Shuffles: {num_shuffles}")
    print(f"Slot Time (ms): {num_slots}")
