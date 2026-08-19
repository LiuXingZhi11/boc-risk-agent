# 页面服务层

页面入口是根目录的 `v5_app.py`。页面服务按工作区拆分：

- `material_services.py`：企业和行业材料导入、来源列表；
- `industry_services.py`：行业背景画像生成、审核和查看；
- `profile_services.py`：企业画像调查、审核、主题分析和查看；
- `rating_direction_services.py`：分方向风险评级报告、审批点报告和同行排名；
- `rating_overall_services.py`：综合评级、行动建议和组合报告；
- `rating_configuration_services.py`：同行样本、指标和审批点配置；
- `v5_services.py`：旧函数入口兼容。

旧代码仍可从 `src.ui.v5_services` 导入，便于页面和脚本逐步迁移。
