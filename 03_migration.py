#!/usr/bin/env python
"""Stage 2+3: from per-partition (author_id, year, country, n) extracts,
build author-year residence, detect migration events, and aggregate to
country-year stocks + bilateral flows (SMD-style).

Run on the remote server AFTER 01_extract.py / 02_extract_big.py finish.
"""
import os
import time
import duckdb

BASE = "/root/autodl-tmp/openalex"
EXTRACT = os.path.join(BASE, "extract")
OUT = os.path.join(BASE, "out")
os.makedirs(OUT, exist_ok=True)

YEAR_MIN, YEAR_MAX = 1998, 2025


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    con = duckdb.connect(os.path.join(OUT, "migration.duckdb"))
    con.execute("SET threads=64;")
    con.execute("PRAGMA temp_directory='/root/autodl-tmp/openalex/tmp';")

    src = f"{EXTRACT}/*.parquet"

    # 1) Sum author-year-country counts across all partitions (a work can be
    #    re-indexed in multiple updated_date dumps, so SUM then de-dup by max).
    log("building author_year_country ...")
    con.execute(f"""
        CREATE OR REPLACE TABLE ayc AS
        SELECT author_id, year, country, SUM(n) AS n
        FROM read_parquet('{src}')
        WHERE country <> '__NA__'
        GROUP BY 1,2,3;
    """)

    # 2) Residence country per author-year = most frequent country (ties: max
    #    country code, deterministic).
    log("resolving residence per author-year ...")
    con.execute("""
        CREATE OR REPLACE TABLE residence AS
        SELECT author_id, year, country AS residence
        FROM (
            SELECT author_id, year, country, n,
                   row_number() OVER (
                       PARTITION BY author_id, year
                       ORDER BY n DESC, country DESC
                   ) AS rk
            FROM ayc
        )
        WHERE rk = 1;
    """)

    # 3) Order each author's residence years; a change vs previous observed
    #    year is a migration event dated at the new year.
    log("detecting migration events ...")
    con.execute("""
        CREATE OR REPLACE TABLE events AS
        SELECT author_id,
               year,
               prev_year,
               prev_residence AS from_country,
               residence      AS to_country
        FROM (
            SELECT author_id, year, residence,
                   lag(residence) OVER w AS prev_residence,
                   lag(year)      OVER w AS prev_year
            FROM residence
            WINDOW w AS (PARTITION BY author_id ORDER BY year)
        )
        WHERE prev_residence IS NOT NULL
          AND residence <> prev_residence;
    """)

    # 4) Country-year population of researchers (distinct authors present).
    log("aggregating country-year population ...")
    con.execute(f"""
        CREATE OR REPLACE TABLE pop AS
        SELECT year, residence AS country,
               count(DISTINCT author_id) AS n_researchers
        FROM residence
        WHERE year BETWEEN {YEAR_MIN} AND {YEAR_MAX}
        GROUP BY 1,2;
    """)

    # 5) Country-year in/out/net migration.
    log("aggregating country-year migration counts ...")
    con.execute(f"""
        CREATE OR REPLACE TABLE outmig AS
        SELECT year, from_country AS country, count(*) AS outmigration
        FROM events WHERE year BETWEEN {YEAR_MIN} AND {YEAR_MAX}
        GROUP BY 1,2;
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE inmig AS
        SELECT year, to_country AS country, count(*) AS inmigration
        FROM events WHERE year BETWEEN {YEAR_MIN} AND {YEAR_MAX}
        GROUP BY 1,2;
    """)
    con.execute("""
        CREATE OR REPLACE TABLE country_year AS
        SELECT p.year, p.country, p.n_researchers,
               COALESCE(i.inmigration,0)  AS inmigration,
               COALESCE(o.outmigration,0) AS outmigration,
               COALESCE(i.inmigration,0)-COALESCE(o.outmigration,0) AS netmigration,
               (COALESCE(i.inmigration,0))*1.0/NULLIF(p.n_researchers,0) AS inmigration_rate,
               (COALESCE(o.outmigration,0))*1.0/NULLIF(p.n_researchers,0) AS outmigration_rate,
               (COALESCE(i.inmigration,0)-COALESCE(o.outmigration,0))*1.0
                   /NULLIF(p.n_researchers,0) AS netmigration_rate
        FROM pop p
        LEFT JOIN inmig i USING (year, country)
        LEFT JOIN outmig o USING (year, country);
    """)

    # 6) Bilateral flows by year.
    log("aggregating bilateral flows ...")
    con.execute(f"""
        CREATE OR REPLACE TABLE flows AS
        SELECT year, from_country, to_country, count(*) AS n_migrations
        FROM events WHERE year BETWEEN {YEAR_MIN} AND {YEAR_MAX}
        GROUP BY 1,2,3;
    """)

    # 7) Export CSVs.
    log("exporting csv ...")
    con.execute(f"COPY (SELECT * FROM country_year ORDER BY country, year) "
                f"TO '{OUT}/openalex_country_year_1998_2025.csv' (HEADER, DELIMITER ',');")
    con.execute(f"COPY (SELECT * FROM flows ORDER BY year, from_country, to_country) "
                f"TO '{OUT}/openalex_bilateral_flows_1998_2025.csv' (HEADER, DELIMITER ',');")

    # quick summary
    ny = con.execute("SELECT count(*) FROM country_year").fetchone()[0]
    nf = con.execute("SELECT count(*) FROM flows").fetchone()[0]
    na = con.execute("SELECT count(DISTINCT author_id) FROM residence").fetchone()[0]
    log(f"country_year rows={ny}  flows rows={nf}  distinct_authors={na}")
    log("sample country_year:")
    for r in con.execute(
        "SELECT * FROM country_year WHERE country='US' ORDER BY year LIMIT 5"
    ).fetchall():
        print("   ", r)
    log("DONE")


if __name__ == "__main__":
    main()
