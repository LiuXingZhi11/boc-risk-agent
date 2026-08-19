# 可选平台运行层

`src/platform/` 只放可选扩展的 Python 运行代码，不承载企业画像、行业画像或客户风险评级的核心业务逻辑。

- `mcp/`：MCP Provider 配置读取、工具发现、调用、超时和审计；
- `skills/`：读取并校验根目录 `skills/` 下的 Skill 定义，并提供运行时适配。

业务人员维护的 Skill 内容仍在根目录 `skills/`；MCP 连接配置在 `config/mcp_servers.yaml`。关闭相关开关时，核心画像和评级流程不依赖本目录。
