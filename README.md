# Reference Boundary

本目录不存放论文原始 PDF 或未发布实验结果。项目通过 `ESG_REFERENCE_ROOT` 指向论文参考目录，并从 manifest/page index 读取元数据做审计。

默认参考根目录：`/Users/guohuiwen/华健/论文 esg`

允许的参考用途：

- 了解论文中的页面级证据字段、报告版本和来源 manifest 结构。
- 为 ESG 领域适配器设计 `company`、`report_year`、`source_pdf`、`page_number` 等 metadata 字段。
- 在明确选择并授权的本地数据上重新摄取。

禁止的默认行为：

- 自动复制原始报告 PDF、人工标注包或受发布门禁约束的结果。
- 把论文的 BM25/神经检索数字写入本项目的生产或简历指标。
- 把 synthetic illustration、模拟结果、候选 release artifact 当作 gold data。
