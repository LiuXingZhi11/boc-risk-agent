# 企查查平台演示 Skill

> THIS IS A PLATFORM DEMO. DO NOT USE AS A FORMAL RISK SKILL.

## 目标

验证 Skill manifest、Prompt 加载和 Tool 声明能够被平台解析。

## 执行原则

只调用 manifest 中声明的演示 Tool。外部结果只能作为辅助信息。

## 禁止事项

- 不得调用未声明的 Tool。
- 不得把外部结果自动写入正式 Ontology 或评级结论。
- Tool 无结果不得解释为企业不存在风险。
