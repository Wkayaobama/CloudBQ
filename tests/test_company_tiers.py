#!/usr/bin/env python3
"""Offline structure checks for pass 2b — the company object by foreign-key resolution (sql/company_tiers_body.sql, sql/company_tiers_v1.sql,
sql/company_tiers_apply.sql, sql/company_tiers_schedule.sh, notebooks/company_tiers.ipynb).

    python3 tests/test_company_tiers.py        or        python3 -m pytest tests -q

One SQL text, two sources: the body's CTE chain is spliced into the views by sql/apply.sh and into the notebook's dry run (deal_source =
UNNEST(@deals_payload)); what can be proved offline is that both assemblies render, the resolvers come in the documented order, the
icalps_dealstatus rule and the grain are the documented ones, the refresh writes exactly the DDL's columns inside one transaction with
the guards, and the notebook gates the writes. The executed checks (the dry run, the ship, one refresh) are the notebook's own cells.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BODY = (ROOT / "sql/company_tiers_body.sql").read_text()
VIEWS = (ROOT / "sql/company_tiers_v1.sql").read_text()
APPLY = (ROOT / "sql/company_tiers_apply.sql").read_text()
SCHED = (ROOT / "sql/company_tiers_schedule.sh").read_text()
NB = json.loads((ROOT / "notebooks/company_tiers.ipynb").read_text())
NB_CODE = "\n".join("".join(c["source"]) for c in NB["cells"] if c["cell_type"] == "code")
PH = {"PROJECT": "p", "DATASET": "hubspot", "SYNC_DATASET": "hs", "SYNC_COMPANIES_TABLE": "Companies", "SYNC_COMPANY_ID_COLUMN": "id", "ARR_PROJECT": "p", "ARR_DATASET": "arrdash"}


def _render(text):
    out = []
    for line in text.splitlines():
        out.append(line)
        if line.startswith("-- @include "): out.extend((ROOT / "sql" / line.split(" ", 2)[2].strip()).read_text().splitlines())
    text = "\n".join(out)
    for k, v in PH.items(): text = text.replace("${" + k + "}", v)
    return text


def _code(sql): return "\n".join(re.sub(r"--.*$", "", l) for l in sql.splitlines())


def test_body_is_a_cte_chain_over_deal_source_and_both_assemblies_render():
    assert not BODY.lstrip().startswith("WITH") and _code(BODY).lstrip().startswith("labelled AS (") and _code(BODY).rstrip().endswith(")")
    assert "FROM deal_source d" in BODY and "resolved AS (" in BODY and "rollup AS (" in BODY
    for ph in set(re.findall(r"\$\{([A-Z_]+)\}", BODY + VIEWS + APPLY)): assert ph in PH, ph
    views = _render(VIEWS); assert "${" not in views and views.count("labelled AS (") == 2, "the body is spliced into both views"
    dry = "WITH deal_source AS (SELECT * FROM UNNEST(@deals_payload)),\n" + _render(BODY) + "\nSELECT * FROM rollup"
    assert "${" not in dry and dry.count("labelled AS (") == 1
    # the view input exposes exactly the columns the body documents for deal_source
    documented = re.search(r"deal_source must expose:\n((?:--.*\n)+)", BODY).group(1)
    cols = re.findall(r"([a-z_]+) (?:STRING|FLOAT64|INT64|BOOL)", documented)
    inp = VIEWS[VIEWS.index("company_deal_input_v1` AS"):VIEWS.index("QUALIFY ROW_NUMBER() OVER (PARTITION BY t.deal_id")]
    got = [c.split(".")[-1].strip() for c in re.search(r"SELECT (.*?)\nFROM", inp, re.S).group(1).replace("\n", " ").split(",")]
    assert got == cols, (got, cols)
    assert len(re.findall(r'S\("([a-z_]+)"', NB_CODE)) and [m for m in re.findall(r'S\("([a-z_]+)"', NB_CODE)] == cols, "the notebook's payload struct has the same fields in the same order"


def test_resolvers_status_rule_and_grain():
    body = _code(BODY)
    assert body.index("primary_assoc AS (") < body.index("clinic_map AS (") < body.index("companies_norm AS (") < body.index("resolved AS (")
    assert "COALESCE(p.company_id, c.company_id, n.company_id)" in body, "resolver precedence: association, clinic map, name match"
    for r in ("'1_primary_assoc'", "'2_clinic_fc_map'", "'3_direct_company_name'", "'4_unresolved_fc'", "'5_no_fc_or_company'"): assert r in body
    assert "WHEN l.pipeline_id = '766126206' THEN l.dealstatus_norm = 'in progress'" in body and "ELSE l.dealstatus_norm IN ('', 'in progress')" in body
    assert "REGEXP_REPLACE(LOWER(TRIM(COALESCE(d.icalps_dealstatus, ''))), r'[_-]+', ' ')" in body, "'In Progress' = 'in_progress'"
    assert "WHERE status_ok" in body and "GROUP BY sales_region, entity_key, tier" in body, "the company object: one row per region × company × tier"
    assert "CONCAT('fc:', LOWER(TRIM(d.fc)))" in body and "CONCAT('deal:', d.deal_id)" in body, "unresolved deals keep a stable key"
    assert "ARRAY_AGG(STRUCT(deal_id, dealname, deal_stage, certainty, amount_kusd)" in body, "the deals are nested in the company row"
    assert "deal_tiers_v1" in VIEWS and "deals_synced_v1" in VIEWS and "companies_synced_v1" in VIEWS, "the sync source is the L2 tier view joined with the deal adapter"
    assert "ALTER TABLE" not in VIEWS and "UPDATE " not in VIEWS and "MERGE " not in VIEWS, "nothing is written into the sync tables"


def _ddl_cols(table):
    m = re.search(r"CREATE TABLE IF NOT EXISTS `\$\{PROJECT\}\.\$\{DATASET\}\." + table + r"` \((.*?)\)\n(?:PARTITION|CLUSTER|OPTIONS)", VIEWS, re.S)
    body = re.sub(r"<[^<>]*(?:<[^<>]*>[^<>]*)*>", "", m.group(1))        # drop the ARRAY<STRUCT<…>> internals
    return re.findall(r"([a-z0-9_]+) (?:STRING|TIMESTAMP|FLOAT64|INT64|BOOL|ARRAY)", body)


def test_refresh_writes_the_ddl_columns_in_one_transaction_with_guards():
    cols = _ddl_cols("company_tiers"); assert cols == _ddl_cols("company_tiers_history"), "snapshot and history share the column list"
    for ins in re.findall(r"INSERT INTO `\$\{PROJECT\}\.\$\{DATASET\}\.company_tiers(?:_history)?`\n\s*\((.*?)\)\n", APPLY, re.S):
        assert [c.strip() for c in ins.replace("\n", " ").split(",")] == cols, "the INSERT lists exactly the DDL columns, in order"
    assert APPLY.count("BEGIN TRANSACTION") == 1 and APPLY.count("COMMIT TRANSACTION") == 1 and "DELETE FROM `${PROJECT}.${DATASET}.company_tiers` WHERE TRUE" in APPLY
    assert "INTERVAL 36 HOUR" in APPLY and "v_batch_rows < v_current_rows / 2" in APPLY, "freshness and row-count guards"
    assert "EXCEPTION WHEN ERROR THEN" in APPLY and "BEGIN ROLLBACK TRANSACTION; EXCEPTION WHEN ERROR THEN END;" in APPLY and "'FAILED'" in APPLY and "RAISE;" in APPLY
    assert "CREATE OR REPLACE TEMP TABLE batch AS SELECT * FROM `${PROJECT}.${DATASET}.company_tiers_v1`" in APPLY
    assert "@run_time" in APPLY and APPLY.index("DECLARE v_in_txn") < APPLY.index("BEGIN\n")
    refresh_cols = re.search(r"company_tiers_refreshes` \((.*?)\)\nPARTITION", VIEWS, re.S).group(1)
    assert re.findall(r"([a-z_]+) (?:STRING|TIMESTAMP|INT64)", refresh_cols) == ["refresh_ts", "orchestrator", "status", "error", "n_rows", "n_companies", "n_unresolved", "n_deals", "duration_ms"]


def test_schedule_script_renders_off_the_hour_and_refuses_before_the_view():
    env = dict(os.environ, DRYRUN="1", PROJECT="p", DATASET="hubspot", SYNC_DATASET="hs")
    r = subprocess.run(["bash", str(ROOT / "sql/company_tiers_schedule.sh")], env=env, capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    rendered = Path("/tmp/company_tiers_apply.sql").read_text(); assert "${" not in rendered and "`p.hubspot.company_tiers_v1`" in rendered
    bad = subprocess.run(["bash", str(ROOT / "sql/company_tiers_schedule.sh")], env=dict(env, SCHEDULE_UTC_COMPANY_TIERS="every day 03:00"), capture_output=True, text=True, cwd=ROOT)
    assert bad.returncode == 2 and "on the hour" in bad.stderr
    assert "company_tiers_v1 does not exist" in SCHED and 'NAS="--no_auto_scheduling=$([[ -n "${DISABLE_SCHEDULE:-}" ]] && echo true || echo false)"' in SCHED and SCHED.count('"$NAS"') == 2 and "company-tiers-refresh" in SCHED
    apply_sh = (ROOT / "sql/apply.sh").read_text()
    assert 'FILES+=("$HERE/company_tiers_v1.sql")' in apply_sh and 'SYNC_COMPANIES_TABLE' in apply_sh and "company_tiers_body.sql" in apply_sh
    order = re.findall(r'/([a-z_0-9]+\.sql)"', apply_sh); assert order.index("deal_tiers_v1.sql") < order.index("new_deals_batch.sql")
    for v in ("SYNC_COMPANIES_TABLE", "SYNC_COMPANY_ID_COLUMN", "ARR_PROJECT", "ARR_DATASET", "SCHEDULE_UTC_COMPANY_TIERS"): assert v + "=" in (ROOT / ".env.example").read_text(), v


def test_notebook_dry_runs_then_ships_then_gates_the_writes():
    assert "UNNEST(@deals_payload)" in NB_CODE and 'render("sql/company_tiers_body.sql")' in NB_CODE and "0 BigQuery tables written" in NB_CODE
    assert NB_CODE.index("deal_level = dry(") < NB_CODE.index('render("sql/company_tiers_v1.sql")') < NB_CODE.index("company_tiers_schedule.sh"), "dry run before the ship before the schedule"
    assert "I_HAVE_READ_THE_DRY_RUN_AND_WANT_THE_REFRESH_REGISTERED = False" in NB_CODE and "I_HAVE_READ_THE_PROBE_AND_WANT_THE_DAILY_REFRESH = False" in NB_CODE, "every write beyond the ship is flag-guarded"
    assert "DISABLE_SCHEDULE=1 bash sql/company_tiers_schedule.sh" in NB_CODE and "company_tiers_refreshes" in NB_CODE and "company_tiers_summary_v1" in NB_CODE
    assert "getpass.getpass" in NB_CODE and "del token" in NB_CODE, "the token is prompted or read from Secret Manager, never stored"
    assert all(not c.get("outputs") for c in NB["cells"] if c["cell_type"] == "code")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print("ok ", name)
    print("company tiers structure OK")
