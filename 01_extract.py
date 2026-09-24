#!/usr/bin/env python
"""Stream-extract (author_id, publication_year, country) counts from OpenAlex
works parquet on S3, one date-partition at a time, into compact local parquet.

Designed to run ON THE REMOTE SERVER. Never downloads the 725GB whole; DuckDB
does column projection + predicate pushdown and we only keep tiny aggregates.

Resumable: a partition whose output parquet already exists is skipped.
"""
import os
import sys
import time
import subprocess
import concurrent.futures as cf
import duckdb

BASE = "/root/autodl-tmp/openalex"
OUT = os.path.join(BASE, "extract")
LOG = os.path.join(BASE, "logs", "extract.log")
YEAR_MIN = 1998
YEAR_MAX = 2025
S3_WORKS = "s3://openalex/data/parquet/works"
WORKERS = int(os.environ.get("OA_WORKERS", "6"))
THREADS_PER = int(os.environ.get("OA_THREADS", "8"))

os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.dirname(LOG), exist_ok=True)


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def list_partitions():
    """Return list of partition prefixes like 'updated_date=2024-04-06/'."""
    out = subprocess.check_output(
        ["aws", "s3", "ls", f"{S3_WORKS}/", "--no-sign-request"],
        text=True,
    )
    parts = []
    for ln in out.splitlines():
        ln = ln.strip()
        if ln.startswith("PRE "):
            parts.append(ln[4:].strip())
    return sorted(parts)


def new_con():
    con = duckdb.connect()
    for s in [
        "INSTALL httpfs", "LOAD httpfs",
        "SET s3_region='us-east-1'",
        "SET s3_endpoint='s3.amazonaws.com'",
        "SET s3_use_ssl=true",
        f"SET threads={THREADS_PER}",
        "SET enable_progress_bar=false",
    ]:
        con.execute(s)
    return con


def process_partition(part):
    """part like 'updated_date=2024-04-06/'. Returns (part, rows, secs)."""
    name = part.rstrip("/").split("=")[-1]
    out_path = os.path.join(OUT, f"{name}.parquet")
    done_flag = out_path + ".done"
    if os.path.exists(done_flag):
        return (name, -1, 0.0)  # skip

    url = f"{S3_WORKS}/{part}*.parquet"
    con = new_con()
    t0 = time.time()
    # Explode authorships; take each authorship's affiliation countries.
    # One row per (author, work, country); later aggregated to author-year.
    q = f"""
    COPY (
        SELECT a.author.id AS author_id,
               w.publication_year AS year,
               ctry AS country,
               count(*) AS n
        FROM read_parquet('{url}') w,
             UNNEST(w.authorships) AS t1(a),
             UNNEST(
                 CASE WHEN len(a.countries) > 0 THEN a.countries
                      ELSE ['__NA__'] END
             ) AS t2(ctry)
        WHERE w.publication_year BETWEEN {YEAR_MIN} AND {YEAR_MAX}
          AND a.author.id IS NOT NULL
        GROUP BY 1,2,3
    ) TO '{out_path}' (FORMAT parquet, COMPRESSION zstd);
    """
    try:
        con.execute(q)
        rows = con.execute(
            f"SELECT count(*) FROM read_parquet('{out_path}')"
        ).fetchone()[0]
        open(done_flag, "w").close()
        secs = time.time() - t0
        return (name, rows, secs)
    except Exception as e:
        # remove partial output so it can be retried next run
        if os.path.exists(out_path):
            os.remove(out_path)
        log(f"ERROR {name}: {e}")
        return (name, -2, time.time() - t0)
    finally:
        con.close()


def main():
    parts = list_partitions()
    total = len(parts)
    todo = [p for p in parts
            if not os.path.exists(
                os.path.join(OUT, p.rstrip('/').split('=')[-1] + ".parquet.done"))]
    log(f"partitions total={total} todo={len(todo)} workers={WORKERS} threads/worker={THREADS_PER}")

    done = 0
    t_start = time.time()
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(process_partition, p): p for p in todo}
        for fut in cf.as_completed(futs):
            name, rows, secs = fut.result()
            done += 1
            elapsed = time.time() - t_start
            rate = done / elapsed if elapsed > 0 else 0
            eta = (len(todo) - done) / rate if rate > 0 else 0
            status = "skip" if rows == -1 else ("FAIL" if rows == -2 else f"{rows} rows")
            log(f"[{done}/{len(todo)}] {name} {status} {secs:.0f}s "
                f"| elapsed {elapsed/60:.1f}m ETA {eta/60:.1f}m")
    log(f"DONE all partitions in {(time.time()-t_start)/60:.1f} min")


if __name__ == "__main__":
    main()
