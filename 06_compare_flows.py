"""Compare my bilateral flows vs official SMD 2.0 OpenAlex countryflows.

Official flows use ISO3 (area_from/area_to). Mine use ISO2. Build an ISO2->ISO3
map from the official country table, convert mine, then merge on
(year, from, to) and correlate n_migrations.
"""
import os
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Paths resolved relative to this script (portable). Override the official SMD
# directory via env var SMD_DIR if your copy lives elsewhere.
PIPE = os.path.dirname(os.path.abspath(__file__))
MINE = os.path.join(PIPE, "results", "openalex_bilateral_flows_1998_2025.csv")
OFFDIR = os.environ.get(
    "SMD_DIR",
    os.path.join(PIPE, "..",
                 "Global-flows-and-rates-of-international-migration-of-scholars-2026_V2",
                 "2026_V2"))
OFF_FLOW = os.path.join(OFFDIR, "openalex_2026_V2_scholarlymigration_countryflows.parquet")
OFF_CTRY = os.path.join(OFFDIR, "openalex_2026_V2_scholarlymigration_country.parquet")
OUTDIR = os.path.join(PIPE, "results")

# ISO2 -> ISO3 map from official country table
ctry = pd.read_parquet(OFF_CTRY)[["iso2code", "iso3code"]].drop_duplicates()
iso2to3 = dict(zip(ctry["iso2code"], ctry["iso3code"]))

# mine (ISO2) -> ISO3
mine = pd.read_csv(MINE)
mine["iso3from"] = mine["from_country"].map(iso2to3)
mine["iso3to"] = mine["to_country"].map(iso2to3)
n_unmapped = mine["iso3from"].isna().sum() + mine["iso3to"].isna().sum()
mine = mine.dropna(subset=["iso3from", "iso3to"])
mine = mine.rename(columns={"n_migrations": "mine_n"})
mine = mine[["year", "iso3from", "iso3to", "mine_n"]]
print(f"mine flows rows={len(mine)} (dropped {n_unmapped} unmapped code refs)")

# official, totals slice
off = pd.read_parquet(OFF_FLOW)
off = off[(off["gender"] == "all") & (off["field"] == "all")].copy()
off = off.rename(columns={"iso3codefrom": "iso3from", "iso3codeto": "iso3to",
                          "n_migrations": "off_n"})
off = off[["year", "iso3from", "iso3to", "off_n"]]
off = off[(off["year"] >= 1998) & (off["year"] <= 2022)]
# NOTE: official countryflows only go up to 2022 (stock table goes to 2024).
# Restrict mine to the same window for a fair corridor comparison.
mine = mine[(mine["year"] >= 1998) & (mine["year"] <= 2022)]
print(f"official flows rows(all,all,1998-22)={len(off)}")
print("(official bilateral flows stop at 2022; my flows extend to 2024)")

# outer merge: keep union so we can measure coverage; fill 0 for correlation
m = mine.merge(off, on=["year", "iso3from", "iso3to"], how="outer")
both = m.dropna()
print(f"\ncorridors: mine-only={m['off_n'].isna().sum()} "
      f"official-only={m['mine_n'].isna().sum()} both={len(both)}")

x = both["mine_n"].astype(float)
y = both["off_n"].astype(float)
print("\n===== bilateral flow correlation (matched corridors) =====")
print(f"  n corridors      = {len(both)}")
print(f"  Pearson (level)  = {stats.pearsonr(x, y)[0]:.4f}")
print(f"  Spearman         = {stats.spearmanr(x, y)[0]:.4f}")
print(f"  log-log Pearson  = {stats.pearsonr(np.log1p(x), np.log1p(y))[0]:.4f}")
print(f"  median ratio mine/off = {(x/y).replace([np.inf], np.nan).median():.3f}")

# top corridors 2024 side by side
print("\n===== top 12 official corridors 2024, with mine =====")
t = both[both["year"] == 2024].sort_values("off_n", ascending=False).head(12)
for _, r in t.iterrows():
    print(f"  {r['iso3from']}->{r['iso3to']}: official={int(r['off_n'])} mine={int(r['mine_n'])}")

# scatter
plt.figure(figsize=(6.2, 6))
plt.scatter(x + 1, y + 1, s=6, alpha=0.15, edgecolors="none")
lim = [1, max(x.max(), y.max())]
plt.plot(lim, lim, "r--", lw=1, label="y=x")
plt.xscale("log"); plt.yscale("log")
r = stats.pearsonr(np.log1p(x), np.log1p(y))[0]
plt.title(f"Bilateral flows: mine vs official SMD 2.0\n"
          f"log-log Pearson={r:.3f}  (n={len(both)} corridors)")
plt.xlabel("Mine n_migrations")
plt.ylabel("Official n_migrations")
plt.legend(loc="upper left")
plt.tight_layout()
fp = os.path.join(OUTDIR, "compare_flows.png")
plt.savefig(fp, dpi=130)
print("\nsaved:", fp)
