# 项目交接说明

> 更新日期：2026-08-19
> 本文件只记录当前有效结构、运行方式和待办事项，不记录历史试错过程。

## 一、系统范围

当前系统只保留四个业务工作区：

1. 材料管理：导入企业年报、招股说明书和行业研报，解析为可追溯的 EvidenceUnit；
2. 企业画像：按企业领域运行 ReAct 调查，生成候选事实，人工审核后形成正式画像，并可生成领域主题分析；
3. 行业背景：从行业研报生成行业维度和证据引用，人工审核后作为企业风险判断的行业基准；
4. 客户风险评级报告：按风险评级指引生成单企业分方向判断，可选加入同行样本内排名，再形成最终客户风险评级报告和行动建议。

历史案例、相似案例、旧金融风险案例结构化流程和本地 Embedding RAG 不属于当前系统。

审批指引的图片转写参考位于 `docs/business/授信审批图片文字提取.md`；它不是运行时提示词。运行时审批规则由 `src/approval/guideline_definitions.py` 和 `prompts/logic/授信审批逻辑规则.md` 提供。

## 二、主要数据流

```text
企业 PDF / 行业 PDF
        ↓
SourceAsset + EvidenceUnit
        ↓
企业画像候选 / 行业背景候选
        ↓
Python 结构校验 + 人工审核
        ↓
正式企业画像 + 正式行业画像
        ↓
单企业风险评级方向报告
        ↓（可选）
同行样本内比较与排名
        ↓
客户风险评级报告
```

所有企业事实、行业要点和报告结论都必须保留 EvidenceUnit 引用。未披露不等于零，也不自动等于不通过。

## 三、代码入口

```text
v5_app.py                  Streamlit 页面入口
src/sources/               PDF、HTML 解析和切片
src/evidence/              EvidenceUnit 存储与查询
src/profiles/              企业画像、ReAct、主题分析
src/industry/              行业背景画像
src/approval/              风险评级方向、排名和综合报告
src/authorization/         身份与字段可见性
src/ontology/              本体加载、字段和关系校验
src/llm/                   DeepSeek 客户端和 thinking/sampling 参数
src/platform/mcp/          MCP Provider、ToolProxy 和审计
src/platform/skills/       Skill 清单、校验和运行时适配
src/ui/material_services.py 材料管理页面服务
src/ui/industry_services.py 行业画像页面服务
src/ui/profile_services.py  企业画像页面服务
src/ui/rating_direction_services.py 风险评级分方向报告和同行排名服务
src/ui/rating_overall_services.py 综合评级、行动建议和组合报告服务
src/ui/rating_configuration_services.py 同行样本、指标和审批点配置服务
src/ui/v5_services.py       旧页面和脚本入口兼容层
prompts/data/              事实抽取和字段语义规则
prompts/logic/             画像、审批、排名和综合评级规则
prompts/action/            后续行动建议规则
config/                    MCP、Skill 和本地模型配置
authorization/             权限规则及说明
scripts/                   当前仍需使用的初始化、导入、画像审核和 Skill 工具
tests/                     自动化测试
materials/                企业、行业和参考材料
data/current_project.db   当前工作数据库
```

## 四、模型配置

模型名称、DeepSeek API 地址和密钥统一写在：

```text
config/model_config.yaml
```

该文件被 `.gitignore` 忽略，不能提交到 Git。当前默认模型为 `deepseek-v4-flash`；事实抽取使用 `sampling`，检索、主题分析、审批、排名和报告使用 `thinking`。MCP 的 QCC 密钥仍由 MCP 配置中的 `auth_env` 指定。

## 五、运行命令

```powershell
pip install -r requirements.txt
streamlit run v5_app.py
python -m pytest -q -p no:cacheprovider
```

初始化或导入材料：

```powershell
python scripts/init_database.py
python scripts/ingest_evidence.py --database data/current_project.db --case-id CASE_ID --paths path/to/report.pdf
```

Skill 只在平台开关打开且通过校验后使用；真实 QCC MCP Smoke Test 需要配置本地 QCC 密钥，相关依赖已列在 `requirements.txt`，默认不连接外部服务。

## 六、当前约束

- 模型不计算同行排名，Python 只按固定口径计算数值排名；
- Python 不补写 PDF 中不存在的企业事实；
- 单企业报告不要求同行样本，同行排名属于可选增强；
- 所有画像、同行样本、排名和报告都有人工审核状态；
- 普通业务人员可以生成报告，高级业务人员负责审核和维护业务规则；
- 自动化测试不调用真实付费模型；
- MCP/Skill 平台必须保持关闭时的旧业务流程不变。

## 七、下一步

1. 在目标环境配置 QCC MCP 密钥；
2. 使用真实 QCC MCP 地址完成一次单 Tool Smoke Test；
3. 在不改变现有画像、行业背景和风险评级业务逻辑的前提下，逐步接入经过审核的 Skill。
