"""Compare padded stock (and raw stock) vs official SMD 2.0 padded population."""
import os
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Paths are resolved relative to this script so the repo is portable.
# Override the official SMD file via env var SMD_COUNTRY_PARQUET if needed.
PIPE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(PIPE, "results", "openalex_country_year_1998_2025.csv")
PAD = os.path.join(PIPE, "results", "openalex_country_year_padded_1998_2025.csv")
OFF = os.environ.get(
    "SMD_COUNTRY_PARQUET",
    os.path.join(PIPE, "..",
                 "Global-flows-and-rates-of-international-migration-of-scholars-2026_V2",
                 "2026_V2", "openalex_2026_V2_scholarlymigration_country.parquet"))
OUTDIR = os.path.join(PIPE, "results")

raw = pd.read_csv(RAW)[["year", "country", "n_researchers"]].rename(
    columns={"country": "iso2code", "n_researchers": "raw_pop"})
pad = pd.read_csv(PAD)[["year", "country", "n_researchers_padded"]].rename(
    columns={"country": "iso2code", "n_researchers_padded": "pad_pop"})

off = pd.read_parquet(OFF)
off = off[(off["gender"] == "all") & (off["field"] == "all")].copy()
off = off[["year", "iso2code", "padded_population_of_researchers"]].rename(
    columns={"padded_population_of_researchers": "off_pop"})

m = off.merge(raw, on=["year", "iso2code"], how="inner") \
       .merge(pad, on=["year", "iso2code"], how="inner")
m = m[(m["year"] >= 1998) & (m["year"] <= 2024)]  # official stock covers 1998-2024
print("merged rows:", len(m), "| countries:", m["iso2code"].nunique())


def report(col, label):
    x = m[col].astype(float)
    y = m["off_pop"].astype(float)
    ok = (x > 0) & (y > 0)
    print(f"\n[{label}] n={ok.sum()}")
    print(f"  Pearson (level)   = {stats.pearsonr(x[ok], y[ok])[0]:.4f}")
    print(f"  Spearman          = {stats.spearmanr(x[ok], y[ok])[0]:.4f}")
    print(f"  log-log Pearson   = {stats.pearsonr(np.log(x[ok]), np.log(y[ok]))[0]:.4f}")
    ratio = (x[ok] / y[ok])
    print(f"  median ratio mine/official = {ratio.median():.3f}")


print("\n===== STOCK vs official padded population =====")
report("raw_pop", "RAW stock (no padding)")
report("pad_pop", "PADDED stock (2-yr backfill)")

# per-country time-series correlation, padded
rows = []
for c, g in m.groupby("iso2code"):
    if len(g) >= 10 and g["pad_pop"].std() > 0 and g["off_pop"].std() > 0:
        rows.append((c, stats.pearsonr(g["pad_pop"], g["off_pop"])[0]))
cc = pd.DataFrame(rows, columns=["iso2", "r"])
print(f"\nper-country padded-stock time-series Pearson: "
      f"median={cc['r'].median():.4f} mean={cc['r'].mean():.4f} "
      f"(n_countries={len(cc)})")

# scatter: raw vs official, padded vs official
fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
for ax, (col, lab) in zip(axes, [("raw_pop", "RAW stock"),
                                  ("pad_pop", "PADDED stock")]):
    x = m[col].astype(float) + 1
    y = m["off_pop"].astype(float) + 1
    ax.scatter(x, y, s=7, alpha=0.25, edgecolors="none")
    lim = [1, max(x.max(), y.max())]
    ax.plot(lim, lim, "r--", lw=1, label="y=x")
    r = stats.pearsonr(np.log(x), np.log(y))[0]
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_title(f"{lab} vs official padded\nlog-log Pearson={r:.3f}")
    ax.set_xlabel(f"Mine: {lab}")
    ax.set_ylabel("Official SMD 2.0 padded pop")
    ax.legend(loc="upper left", fontsize=8)
plt.tight_layout()
fp = os.path.join(OUTDIR, "compare_stock_padding.png")
plt.savefig(fp, dpi=130)
print("\nsaved:", fp)
