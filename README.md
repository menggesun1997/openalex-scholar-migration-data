# OpenAlex 学者迁移数据 Pipeline (1998–2025)

基于 **OpenAlex** 全量 `works` 快照，复刻 [Scholarly Migration Database (SMD)](https://www.scholarlymigration.org/data.html) 的方法，自建学者国际迁移数据，抽取范围 **1998–2025**。

> **动机**：SMD 2.0 官方数据中，**双边流（countryflows）只更新到 2022**（存量表到 2024）。本 pipeline 直接从 OpenAlex 重建迁移数据，把国家×年存量与**双边流都延伸到 2025**，并与官方数据做了一致性验证。
>
> **抽取范围 vs 可用范围**：为了让迁移事件识别有足够的"预热"buffer（与 SMD 对齐从 1998 起），我们抽取 1998–2025。但**两端需谨慎**：
> - **1998–2002 为预热 buffer**：早年迁移被系统性低估（尤其 1998 首年 in/out=0），建议分析从 **2003** 起使用。
> - **2025 为临时/删失年（provisional）**：快照为 2026 年，2025 的论文仍在陆续入库、padding 也缺未来年支撑，存量与迁移都会偏低，**谨慎使用或丢弃**。
> - **稳健可用区约 2003–2024**。

---

## 目录结构

```
openalex_pipeline/
├── ssh_run.py              # 工具：驱动远程服务器（上传/执行/回传），非流程步骤
├── 01_extract.py           # ① 抽取：逐日期分区抽 (author_id, year, country) 计数
├── 02_extract_big.py       # ② 抽取（大分区）：把超大分区按单文件分片处理
├── 03_migration.py         # ③ 迁移事件识别 + 聚合（存量/流量/双边流）
├── 04_padding.py           # ④ 复刻 SMD 的 population padding（2 年向前回填）
├── 05_compare_stock.py     # ⑤ 验证：存量 vs 官方 SMD 2.0
├── 06_compare_flows.py     # ⑥ 验证：双边流 vs 官方 SMD 2.0
├── 07_top_corridors.py     # ⑦ 验证：头部双边走廊逐条对比
└── results/                # 输出数据与图
    ├── openalex_country_year_1998_2025.csv         # 国家×年（原始存量）
    ├── openalex_country_year_padded_1998_2025.csv  # 国家×年（padding 后存量）
    ├── openalex_bilateral_flows_1998_2025.csv      # 双边流
    ├── compare_stock_padding.png                    # 存量一致性散点图
    └── compare_flows.png                            # 双边流一致性散点图
```

---

## 数据来源

- **OpenAlex** S3 公开快照 `s3://openalex/data/parquet/works/`（CC0，免费，无需凭证）。
- 全量 works parquet 约 **725GB**，按 `updated_date` 分为 482 个日期分区。
- 官方对照数据：SMD 2.0（Zenodo [10.5281/zenodo.11145734](https://doi.org/10.5281/zenodo.11145734)）。

---

## 方法（与 SMD 一致）

1. **抽取**：用 DuckDB 直读 S3 parquet（列裁剪 + 谓词下推，原始数据**不落盘**），把每篇论文的作者展开为 `(author_id, publication_year, country)` 并计数。
2. **定居住国**：每个 `author × year` 取出现频次最高的国家为该年"居住国"。
3. **迁移事件**：按作者时间排序，居住国相对上一观测年发生变化 = 一次迁移事件，事件年份记为出现新居住国的那一年。
4. **Padding（存量分母）**：某年无发文但之后 2 年内有发文，则用下一可得年份的居住国回填该年，使其计入当年研究者人口（复刻 SMD 的 `padded_population_of_researchers`）。
5. **聚合**：国家×年存量、迁入/迁出/净迁移及率；双边流 `(year, from, to, n_migrations)`。

---

## 执行顺序

脚本按文件名前缀 `01→07` 顺序执行。其中 **01–04 在远程服务器上运行**（需要大内存与到 AWS 的带宽），**05–07 在本地运行**（读 `results/` 与官方 parquet 做对比）。

### 远程抽取与聚合（01–04）

`ssh_run.py` 负责把脚本上传到服务器并执行：

```bash
# 上传脚本
python ssh_run.py --put 01_extract.py 02_extract_big.py 03_migration.py 04_padding.py

# 依次执行（建议放后台 + 断点续传，详见脚本内注释）
# 01 常规分区抽取；02 超大分区分片抽取；03 迁移识别+聚合；04 padding 重算存量
```

连接信息通过环境变量覆盖：`OA_HOST / OA_PORT / OA_USER / OA_PASS`。

### 本地验证（05–07）

```bash
python 05_compare_stock.py     # 存量一致性 -> results/compare_stock_padding.png
python 06_compare_flows.py     # 双边流一致性 -> results/compare_flows.png
python 07_top_corridors.py     # 头部走廊逐条对比（打印表格）
```

官方 SMD 数据路径默认相对本仓库；如放在别处，用环境变量覆盖：
`SMD_COUNTRY_PARQUET`（05 用）、`SMD_DIR`（06/07 用）。

---

## 输出字段

### `openalex_country_year_1998_2025.csv` / `..._padded_...csv`
| 字段 | 含义 |
| --- | --- |
| year | 年份 (1998–2025) |
| country | ISO2 国家代码 |
| n_researchers / n_researchers_padded | 研究者存量（原始 / padding 后） |
| inmigration / outmigration | 迁入 / 迁出学者数 |
| netmigration | 净迁移 = in − out |
| inmigration_rate / outmigration_rate / netmigration_rate | 对应率 |

### `openalex_bilateral_flows_1998_2025.csv`
| 字段 | 含义 |
| --- | --- |
| year | 迁移事件年份 |
| from_country / to_country | 迁出国 / 迁入国 (ISO2) |
| n_migrations | 该年该方向的迁移人数 |

---

## 与官方 SMD 2.0 的一致性验证

对齐口径（gender=all, field=all, 交集年份）后与官方 SMD 2.0 OpenAlex 对比：

| 指标 | 相关性 | 说明 |
| --- | --- | --- |
| 双边流 n_migrations | Pearson **0.990**，log-log **0.947** | 1998–2022 交集，146,965 条走廊 |
| 研究者存量 stock | log-log Pearson **0.99**（RAW/PADDED 均为） | 1998–2024 交集，5,294 点，截面高度一致 |

- 2022 年头部走廊逐条吻合：USA→CHN（官方 26073 / 本数据 29997）、GBR→USA（11426 / 12461）、IND→USA（7421 / 9790）等。
- **存量绝对量级**与官方 padding 口径存在系统性差异（原始约为官方 58%，2 年回填后约 137%），因 SMD 的精确 padding 为其未公开的私有逻辑。**建议使用相对量/率或做归一**，而非直接比较绝对存量。
- 迁入/迁出计数在早期分析中与官方相关性约 0.98（同口径），本轮重点验证双边流与存量。

![存量一致性](results/compare_stock_padding.png)
![双边流一致性](results/compare_flows.png)

---

## 环境依赖

- 远程（01–04）：Python 3 + `duckdb`、`pyarrow`、`awscli`；大内存机器；能访问 `s3://openalex`。
- 本地（05–07）：Python 3 + `pandas`、`pyarrow`、`numpy`、`scipy`、`matplotlib`。
- `ssh_run.py` 需要 `paramiko`。

```bash
pip install duckdb pyarrow awscli pandas numpy scipy matplotlib paramiko
```

---

## 注意事项

- **1998 为基线年**：迁移事件依赖"与上一观测年比较"，故每个作者首个观测年（数据起点 1998）无迁移事件，**1998 年 in/out/net 全为 0**，仅用于提供后续年的基线居住国。
- **1998–2002 预热 buffer**：早年在库作者积累不足，迁移被系统性低估，建议分析从 **2003** 起。
- **2025 为删失年**：快照为 2026 年，2025 论文未入齐、padding 缺未来年，存量与迁移偏低，标注为 provisional，**谨慎使用或丢弃**。因此稳健可用区约为 **2003–2024**。
- **OpenAlex vs Scopus**：OpenAlex 对非西方国家、预印本覆盖更广（故 CN/ID/IN 等排名靠前），但作者消歧噪声高于 Scopus。建议将本数据作为 SMD(Scopus) 的**延伸 / 稳健性验证**。

---

## 引用

使用本数据请同时引用 OpenAlex 与 Scholarly Migration Database：

- OpenAlex: Priem, Piwowar, Orr (2022). *OpenAlex: A fully-open index of scholarly works.* arXiv:2205.01833.
- SMD: Akbaritabar, Theile, Zagheni (2024). *Bilateral flows and rates of international migration of scholars.* Scientific Data. [10.1038/s41597-024-03655-9](https://doi.org/10.1038/s41597-024-03655-9)
