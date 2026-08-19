# Skill 运行代码

本目录是 Skill 的 Python 运行层，负责读取根目录 `skills/` 中的定义文件，执行结构校验、权限和工具限制，并将合规的 Skill 交给 Agent 适配器。

业务人员不应直接修改本目录来维护 Skill 规则；规则应写在 `skills/<skill>/skill.yaml` 和 `SKILL.md` 中。
