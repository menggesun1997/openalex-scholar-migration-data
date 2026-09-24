"""Show top bilateral corridors (2022): mine vs official, side by side."""
import os
import pandas as pd

# Paths resolved relative to this script (portable). Override official SMD
# directory via env var SMD_DIR if needed.
PIPE = os.path.dirname(os.path.abspath(__file__))
MINE = os.path.join(PIPE, "results", "openalex_bilateral_flows_1998_2025.csv")
OFFDIR = os.environ.get(
    "SMD_DIR",
    os.path.join(PIPE, "..",
                 "Global-flows-and-rates-of-international-migration-of-scholars-2026_V2",
                 "2026_V2"))
OFF_FLOW = os.path.join(OFFDIR, "openalex_2026_V2_scholarlymigration_countryflows.parquet")
OFF_CTRY = os.path.join(OFFDIR, "openalex_2026_V2_scholarlymigration_country.parquet")

ctry = pd.read_parquet(OFF_CTRY)[["iso2code", "iso3code"]].drop_duplicates()
iso2to3 = dict(zip(ctry["iso2code"], ctry["iso3code"]))

CMP_YEAR = 2022  # official countryflows only go up to 2022
mine = pd.read_csv(MINE)
mine = mine[mine["year"] == CMP_YEAR].copy()
mine["ff"] = mine["from_country"].map(iso2to3)
mine["tt"] = mine["to_country"].map(iso2to3)
mine = mine.dropna(subset=["ff", "tt"])
mine_map = {(r.ff, r.tt): r.n_migrations for r in mine.itertuples()}

off = pd.read_parquet(OFF_FLOW)
off = off[(off["gender"] == "all") & (off["field"] == "all") & (off["year"] == CMP_YEAR)].copy()
off = off.sort_values("n_migrations", ascending=False).head(15)

print(f"Top 15 official corridors in {CMP_YEAR} (official vs mine):")
print(f"{'corridor':<12}{'official':>10}{'mine':>10}{'ratio':>8}")
for _, r in off.iterrows():
    key = (r["iso3codefrom"], r["iso3codeto"])
    mv = mine_map.get(key, 0)
    ratio = mv / r["n_migrations"] if r["n_migrations"] else float("nan")
    print(f"{r['iso3codefrom']}->{r['iso3codeto']:<7}{int(r['n_migrations']):>10}"
          f"{int(mv):>10}{ratio:>8.2f}")
