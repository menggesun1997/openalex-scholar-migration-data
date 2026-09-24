#!/usr/bin/env python
"""Handle the few HUGE date-partitions by processing ONE part_XXXX.parquet
file at a time (instead of a whole-partition glob), so each unit finishes in
minutes and survives the ~20-min periodic disconnects via fine-grained resume.

Outputs go to extract/ as <date>__<partfile>.parquet with a .done flag.
03_migration.py already globs extract/*.parquet, so these are picked up too.
"""
import os
import sys
import time
import subprocess
import concurrent.futures as cf
import duckdb

BASE = "/root/autodl-tmp/openalex"
OUT = os.path.join(BASE, "extract")
LOG = os.path.join(BASE, "logs", "extract_big.log")
YEAR_MIN, YEAR_MAX = 1998, 2025
S3_WORKS = "s3://openalex/data/parquet/works"
WORKERS = int(os.environ.get("OA_BIG_WORKERS", "8"))
THREADS_PER = int(os.environ.get("OA_BIG_THREADS", "6"))

BIG_PARTS = [
    "2025-10-10", "2025-11-06", "2026-01-13",
    "2026-05-21", "2026-06-19", "2026-06-26",
]

os.makedirs(OUT, exist_ok=True)
os.makedirs(os.path.dirname(LOG), exist_ok=True)


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def list_part_files(date):
    out = subprocess.check_output(
        ["aws", "s3", "ls", f"{S3_WORKS}/updated_date={date}/",
         "--no-sign-request"], text=True)
    files = []
    for ln in out.splitlines():
        parts = ln.split()
        if parts and parts[-1].endswith(".parquet"):
            files.append(parts[-1])
    return sorted(files)


def new_con():
    con = duckdb.connect()
    for s in ["INSTALL httpfs", "LOAD httpfs",
              "SET s3_region='us-east-1'",
              "SET s3_endpoint='s3.amazonaws.com'",
              "SET s3_use_ssl=true",
              f"SET threads={THREADS_PER}"]:
        con.execute(s)
    return con


def process_one(date, fname):
    tag = f"{date}__{fname.replace('.parquet','')}"
    out_path = os.path.join(OUT, tag + ".parquet")
    done_flag = out_path + ".done"
    if os.path.exists(done_flag):
        return (tag, -1, 0.0)
    url = f"{S3_WORKS}/updated_date={date}/{fname}"
    con = new_con()
    t0 = time.time()
    q = f"""
    COPY (
        SELECT a.author.id AS author_id, w.publication_year AS year,
               ctry AS country, count(*) AS n
        FROM read_parquet('{url}') w,
             UNNEST(w.authorships) AS t1(a),
             UNNEST(CASE WHEN len(a.countries)>0 THEN a.countries
                         ELSE ['__NA__'] END) AS t2(ctry)
        WHERE w.publication_year BETWEEN {YEAR_MIN} AND {YEAR_MAX}
          AND a.author.id IS NOT NULL
        GROUP BY 1,2,3
    ) TO '{out_path}' (FORMAT parquet, COMPRESSION zstd);
    """
    try:
        con.execute(q)
        open(done_flag, "w").close()
        return (tag, 1, time.time() - t0)
    except Exception as e:
        if os.path.exists(out_path):
            os.remove(out_path)
        log(f"ERROR {tag}: {e}")
        return (tag, -2, time.time() - t0)
    finally:
        con.close()


def main():
    jobs = []
    for date in BIG_PARTS:
        for f in list_part_files(date):
            jobs.append((date, f))
    todo = [(d, f) for (d, f) in jobs
            if not os.path.exists(
                os.path.join(OUT, f"{d}__{f.replace('.parquet','')}.parquet.done"))]
    log(f"big parts: total_files={len(jobs)} todo={len(todo)} "
        f"workers={WORKERS} threads/worker={THREADS_PER}")

    done = 0
    t_start = time.time()
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(process_one, d, f): (d, f) for (d, f) in todo}
        for fut in cf.as_completed(futs):
            tag, rc, secs = fut.result()
            done += 1
            el = time.time() - t_start
            rate = done / el if el > 0 else 0
            eta = (len(todo) - done) / rate if rate > 0 else 0
            st = "skip" if rc == -1 else ("FAIL" if rc == -2 else "ok")
            log(f"[{done}/{len(todo)}] {tag} {st} {secs:.0f}s "
                f"| elapsed {el/60:.1f}m ETA {eta/60:.1f}m")
    # mark whole date-partitions done so the counter reaches 482
    for date in BIG_PARTS:
        open(os.path.join(OUT, date + ".parquet.done"), "w").close()
    log(f"BIG DONE in {(time.time()-t_start)/60:.1f} min")


if __name__ == "__main__":
    main()
