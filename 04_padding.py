#!/usr/bin/env python
"""Replicate SMD's 'padded population of researchers': 2-year BACKWARD fill.

Definition (per SMD README_variables.md):
  If an author has no publication in year y, but publishes within the next
  up to 2 years, they are still counted in year y's population, using the
  residence country of the NEXT available year.

We start from table `residence(author_id, year, residence)` (observed pub
years only) already in migration.duckdb, and build `residence_padded` that
adds the filled-in (author, year) rows, then recompute country-year stock.

Only the STOCK (population) changes vs 03_migration.py; migration EVENTS are
unchanged (they are defined on observed residences), matching SMD where
padding affects the denominator, not the event detection.
"""
import time
import duckdb

DB = "/root/autodl-tmp/openalex/out/migration.duckdb"
OUT = "/root/autodl-tmp/openalex/out"
YEAR_MIN, YEAR_MAX = 1998, 2025


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    con = duckdb.connect(DB)
    con.execute("SET threads=64;")
    con.execute("PRAGMA temp_directory='/root/autodl-tmp/openalex/tmp';")

    # For each observed (author, year, residence), that residence can fill the
    # 1 or 2 years BEFORE it (y-1, y-2). Build candidate fills, then for each
    # (author, target_year) keep the residence from the NEAREST future observed
    # year within gap<=2. Observed years themselves keep their own residence.
    log("building candidate padded rows ...")
    con.execute("""
        CREATE OR REPLACE TABLE residence_padded AS
        WITH obs AS (
            SELECT author_id, year, residence FROM residence
        ),
        cand AS (
            -- observed years (gap = 0, highest priority)
            SELECT author_id, year AS target_year, residence, 0 AS gap
            FROM obs
            UNION ALL
            -- fill y-1 and y-2 from an observed year y (backward fill)
            SELECT author_id, year - 1 AS target_year, residence, 1 AS gap FROM obs
            UNION ALL
            SELECT author_id, year - 2 AS target_year, residence, 2 AS gap FROM obs
        ),
        ranked AS (
            SELECT author_id, target_year, residence, gap,
                   row_number() OVER (
                       PARTITION BY author_id, target_year
                       ORDER BY gap ASC
                   ) AS rk
            FROM cand
        )
        SELECT author_id, target_year AS year, residence
        FROM ranked
        WHERE rk = 1;
    """)

    n_obs = con.execute("SELECT count(*) FROM residence").fetchone()[0]
    n_pad = con.execute("SELECT count(*) FROM residence_padded").fetchone()[0]
    log(f"residence rows: observed={n_obs}  padded={n_pad}  (+{n_pad-n_obs})")

    # recompute country-year padded population
    log("recomputing padded population ...")
    con.execute(f"""
        CREATE OR REPLACE TABLE pop_padded AS
        SELECT year, residence AS country,
               count(DISTINCT author_id) AS padded_pop
        FROM residence_padded
        WHERE year BETWEEN {YEAR_MIN} AND {YEAR_MAX}
        GROUP BY 1,2;
    """)

    # join with existing in/out migration counts (events unchanged)
    log("assembling padded country-year table ...")
    con.execute(f"""
        CREATE OR REPLACE TABLE country_year_padded AS
        SELECT pp.year, pp.country, pp.padded_pop AS n_researchers_padded,
               COALESCE(i.inmigration,0)  AS inmigration,
               COALESCE(o.outmigration,0) AS outmigration,
               COALESCE(i.inmigration,0)-COALESCE(o.outmigration,0) AS netmigration,
               COALESCE(i.inmigration,0)*1.0/NULLIF(pp.padded_pop,0) AS inmigration_rate,
               COALESCE(o.outmigration,0)*1.0/NULLIF(pp.padded_pop,0) AS outmigration_rate,
               (COALESCE(i.inmigration,0)-COALESCE(o.outmigration,0))*1.0
                   /NULLIF(pp.padded_pop,0) AS netmigration_rate
        FROM pop_padded pp
        LEFT JOIN inmig  i ON i.year=pp.year AND i.country=pp.country
        LEFT JOIN outmig o ON o.year=pp.year AND o.country=pp.country;
    """)

    log("exporting csv ...")
    con.execute(f"""COPY (SELECT * FROM country_year_padded ORDER BY country, year)
        TO '{OUT}/openalex_country_year_padded_1998_2025.csv' (HEADER, DELIMITER ',');""")

    ny = con.execute("SELECT count(*) FROM country_year_padded").fetchone()[0]
    log(f"country_year_padded rows={ny}")
    log("US sample (padded vs raw):")
    for r in con.execute("""
        SELECT p.year, p.n_researchers_padded, r.n_researchers AS raw_pop
        FROM country_year_padded p
        JOIN country_year r ON r.year=p.year AND r.country=p.country
        WHERE p.country='US' ORDER BY p.year LIMIT 6
    """).fetchall():
        print("   ", r)
    log("DONE")


if __name__ == "__main__":
    main()
