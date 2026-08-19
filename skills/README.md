# Skill 定义目录

这里存放具体 Skill 的业务定义文件，不存放 Python 运行代码。

每个 Skill 至少包含：

```text
skill.yaml   元数据、适用场景、工具和限制
SKILL.md     给模型使用的行为规则
```

Skill 的加载、校验和运行由 `src/platform/skills/` 负责；外部工具调用由 `src/platform/mcp/` 负责。新增 Skill 通常只需要新增本目录下的子目录并通过校验。
