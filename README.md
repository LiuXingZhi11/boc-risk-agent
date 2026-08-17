# 科技型企业风险辅助审查系统

本项目把企业年报、招股说明书和行业报告转换为可追溯 EvidenceUnit，建立企业事实与行业背景，并面向授信审批方向生成同行比较、审批点评价和综合风险判断。

## 当前流程

```text
PDF / HTML
→ SourceAsset + EvidenceUnit
→ 企业十领域画像候选 / 行业八维背景候选
→ Python 证据与结构校验
→ 人工审核
→ 授信审批方向报告、同行排名和综合评级
```

当前企业画像支持企业与控制、团队、技术与知识产权、产品与项目、市场与商业化、客户与供应商、财务与融资、风险事项、权威认定、结果与处置十个领域。行业背景支持发展阶段、市场规模与增长、技术路线、价值链、竞争格局、商业化、政策监管、行业风险八个维度。

所有生产模型调用默认使用 `deepseek-v4-flash`。模型生成的画像和报告均为 `pending`，不能自动成为正式结论。

## 目标流程

下一阶段以企业审批方向为主线：

```text
企业标准化事实
+ 行业报告中的环境基准
+ 约十家同行企业年报形成的指标矩阵
→ 审批点比较
→ 样本内排名和排名赋分
→ 分方向审批报告
→ 综合审批报告
```

排名由 Python 根据统一口径计算，模型只根据企业事实、行业基准和计算结果生成审批语言。未披露数据不自动记为零或末位；十家企业的结果只能称为样本内排名。

完整的当前架构、目标 Schema、实施步骤和验收标准见：

- [当前与目标技术手册](docs/project/科技型企业风险辅助审查系统_当前与目标技术手册.md)
- [本体设计与维护手册](docs/project/本体设计与维护手册.md)
- [项目交接说明](docs/project/PROJECT_HANDOFF.md)

## 启动

```powershell
pip install -r requirements.txt
streamlit run v5_app.py
```

常用命令：

```powershell
python -m pytest -q
```

## 主要目录

```text
v5_app.py                 页面入口
src/sources/              PDF、HTML 数据源解析
src/evidence/             EvidenceUnit 存储与查询
src/profiles/             企业画像、主题分析和报告
src/industry/             行业背景画像
src/ontology/             Ontology 加载与校验
prompts/data/             企业画像本体与数据层模型协议
prompts/logic/            分析、排名和审批模型协议
prompts/action/           审批后的人工跟进规则
scripts/                  命令行入口
materials/                企业 PDF、行业研报与审批指引图片
docs/                     项目、业务与审查手册
data/                     SQLite 数据库、报告、审查记录与运行日志
eval_data/                测试和评估产物，不是架构文档
```

## 使用边界

- 所有事实和结论必须可追溯到 EvidenceUnit；
- 行业背景不能单独证明当前企业存在风险；
- 同行企业比较必须统一报告期、单位、合并范围和指标口径；
- 表现评价与证据充分度必须分开；
- 未经人工批准的画像、样本、排名和报告不能进入正式结论；
- 系统输出仅用于信息核实和辅助审查，不构成自动授信或业务决策。
