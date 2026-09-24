# OpenAlex 学者迁移数据 Pipeline (1998–2025)

*语言 / Language: **中文** · [English](README.en.md)*

这套代码从 **OpenAlex** 的全量论文数据出发，按照 [Scholarly Migration Database (SMD)](https://www.scholarlymigration.org/data.html) 的做法，自己算出一份学者跨国流动的数据，年份范围是 **1998 到 2025**。

> **为什么要做这个**：SMD 官方发布的数据里，国家之间的双边流动只算到了 2022 年（国家存量算到 2024）。这套代码直接用 OpenAlex 重新算，把国家存量和双边流动都补到了 2025 年，并且和官方数据做了对比，结果高度吻合。
>
> **哪些年份能放心用**：为了准确判断一个人是不是"迁移"了，需要知道他更早在哪，所以我们从 1998 年开始算。但头尾两段要注意：
> - **开头几年（1998–2002）数据不全**：这几年数据库里积累的学者还太少，算出来的迁移量会偏低（尤其 1998 年，因为没有更早的数据可比，迁入迁出直接是 0）。建议正式分析从 **2003 年** 开始。
> - **最后一年（2025）还没齐**：数据快照是 2026 年做的，2025 年的论文还在陆续录入，所以 2025 的数字会偏低。**建议谨慎使用，或者干脆不用。**
> - **真正稳妥可用的区间大约是 2003–2024。**

---

## 文件说明

```
openalex_pipeline/
├── ssh_run.py              # 辅助工具：连服务器、传文件、跑脚本、取结果（不算正式步骤）
├── 01_extract.py           # ① 抽取：从每个数据分区里数出 (作者, 年份, 国家)
├── 02_extract_big.py       # ② 抽取（大文件）：把特别大的分区拆成单个文件来处理
├── 03_migration.py         # ③ 识别迁移事件，并汇总成存量、流量、双边流
├── 04_padding.py           # ④ 按 SMD 的办法补全学者人数（用后一两年的记录往前补）
├── 05_compare_stock.py     # ⑤ 对比：学者存量 vs 官方 SMD
├── 06_compare_flows.py     # ⑥ 对比：双边流动 vs 官方 SMD
├── 07_top_corridors.py     # ⑦ 对比：最主要的几条迁移路线逐条核对
└── results/                # 输出的数据和图
    ├── openalex_country_year_1998_2025.csv         # 国家×年（原始学者数）
    ├── openalex_country_year_padded_1998_2025.csv  # 国家×年（补全后的学者数）
    ├── openalex_bilateral_flows_1998_2025.csv      # 双边流动
    ├── compare_stock_padding.png                    # 存量对比散点图
    └── compare_flows.png                            # 双边流动对比散点图
```

---

## 数据从哪来

- **OpenAlex** 的公开数据 `s3://openalex/data/parquet/works/`（完全免费，无需账号）。
- 全部论文数据约 **725GB**，按更新日期分成 482 份。
- 用来对比的官方数据：SMD 2.0（Zenodo [10.5281/zenodo.11145734](https://doi.org/10.5281/zenodo.11145734)）。

---

## 具体怎么算的（和 SMD 一致）

1. **抽取**：用 DuckDB 直接读云端数据（只取需要的几列，原始数据不下载到本地），把每篇论文的作者拆成 `(作者, 发表年份, 国家)` 来计数。
2. **确定居住国**：一个作者在某一年里，哪个国家出现得最多，就算他那年住在哪国。
3. **识别迁移**：把一个作者按年份排好，如果今年住的国家和上次记录的不一样，就算发生了一次迁移，迁移年份记为出现新国家的那一年。
4. **补全学者人数**：如果一个作者某年没发论文，但之后一两年内发了，就用之后那年的居住国把这一年补上，让他也算进当年的学者总数（这是 SMD 计算学者人数的做法）。
5. **汇总**：按国家和年份，算出学者人数、迁入/迁出/净迁移及各自比率；再算出国家之间的双边流动 `(年份, 从哪国, 到哪国, 人数)`。

---

## 运行顺序

脚本按开头的编号 `01→07` 依次运行。其中 **01–04 在远程服务器上跑**（需要大内存，以及连 AWS 的网络），**05–07 在本地跑**（读 `results/` 里的结果，和官方数据对比）。

### 远程抽取和汇总（01–04）

用 `ssh_run.py` 把脚本传到服务器上运行：

```bash
# 上传脚本
python ssh_run.py --put 01_extract.py 02_extract_big.py 03_migration.py 04_padding.py

# 按顺序运行（建议挂后台，支持断点续跑，细节见脚本内注释）
# 01 常规分区抽取；02 大分区拆分抽取；03 识别迁移并汇总；04 补全学者人数
```

服务器连接信息通过环境变量设置：`OA_HOST / OA_PORT / OA_USER / OA_PASS`。

### 本地对比验证（05–07）

```bash
python 05_compare_stock.py     # 存量对比 -> results/compare_stock_padding.png
python 06_compare_flows.py     # 双边流动对比 -> results/compare_flows.png
python 07_top_corridors.py     # 主要迁移路线逐条核对（打印表格）
```

官方 SMD 数据的路径默认相对本仓库；如果放在别处，用环境变量指定：
`SMD_COUNTRY_PARQUET`（05 用）、`SMD_DIR`（06/07 用）。

---

## 输出的数据字段

### `openalex_country_year_1998_2025.csv` / `..._padded_...csv`
| 字段 | 含义 |
| --- | --- |
| year | 年份 (1998–2025) |
| country | 两位国家代码（ISO2） |
| n_researchers / n_researchers_padded | 学者人数（原始 / 补全后） |
| inmigration / outmigration | 迁入 / 迁出的学者数 |
| netmigration | 净迁移 = 迁入 − 迁出 |
| inmigration_rate / outmigration_rate / netmigration_rate | 对应的比率 |

### `openalex_bilateral_flows_1998_2025.csv`
| 字段 | 含义 |
| --- | --- |
| year | 迁移发生的年份 |
| from_country / to_country | 从哪国 / 到哪国（ISO2） |
| n_migrations | 这一年这个方向的迁移人数 |

---

## 和官方 SMD 2.0 的对比结果

在相同口径下（都取 gender=all、field=all，只比共同年份）和官方 SMD 2.0 的 OpenAlex 数据对比：

| 对比项 | 相关性 | 说明 |
| --- | --- | --- |
| 双边流动 n_migrations | Pearson **0.990**，log-log **0.947** | 共同年份 1998–2022，14.7 万条路线 |
| 学者存量 | log-log Pearson **0.99**（原始和补全后都是） | 共同年份 1998–2024，5294 个点，非常吻合 |

- 2022 年最主要的几条迁移路线，数字都对得上：美国→中国（官方 26073 / 本数据 29997）、英国→美国（11426 / 12461）、印度→美国（7421 / 9790）等。
- **学者人数的绝对值**和官方有系统性差别（原始约为官方的 58%，补全后约 137%），这是因为 SMD 补全人数的精确算法没有公开。**建议用比率或相对量，不要直接比绝对人数。**
- 迁入/迁出的数量，之前在相同口径下和官方相关性约 0.98；这次重点核对的是双边流动和存量。

![存量对比](results/compare_stock_padding.png)
![双边流动对比](results/compare_flows.png)

---

## 需要装的东西

- 远程（01–04）：Python 3，加上 `duckdb`、`pyarrow`、`awscli`；一台大内存机器；能访问 `s3://openalex`。
- 本地（05–07）：Python 3，加上 `pandas`、`pyarrow`、`numpy`、`scipy`、`matplotlib`。
- `ssh_run.py` 需要 `paramiko`。

```bash
pip install duckdb pyarrow awscli pandas numpy scipy matplotlib paramiko
```

---

## 使用时要注意的地方

- **1998 是起始年**：判断迁移要和上一次记录比，所以每个作者第一次出现的那年不算迁移。数据从 1998 年开始，因此 **1998 年的迁入/迁出/净迁移都是 0**，它只是用来给后面的年份打底。
- **开头几年数据不全**：1998–2002 这几年，数据库里的学者还不够多，迁移量会偏低，建议正式分析从 **2003 年** 开始。
- **2025 年数据没齐**：快照是 2026 年做的，2025 年的论文还没录完，人数和迁移都会偏低，建议谨慎用或不用。所以真正稳妥的区间大约是 **2003–2024**。
- **OpenAlex 和 Scopus 的区别**：OpenAlex 对非西方国家和预印本收录得更全（所以中国、印尼、印度排名靠前），但区分同名作者的准确度不如 Scopus。建议把这份数据当作 SMD（基于 Scopus）的**补充和交叉验证**。

---

## 引用

用到这份数据时，请同时引用 OpenAlex 和 Scholarly Migration Database：

- OpenAlex: Priem, Piwowar, Orr (2022). *OpenAlex: A fully-open index of scholarly works.* arXiv:2205.01833.
- SMD: Akbaritabar, Theile, Zagheni (2024). *Bilateral flows and rates of international migration of scholars.* Scientific Data. [10.1038/s41597-024-03655-9](https://doi.org/10.1038/s41597-024-03655-9)
