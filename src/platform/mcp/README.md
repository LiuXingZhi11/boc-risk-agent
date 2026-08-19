# MCP 运行代码

本目录负责 MCP Provider 的连接、工具发现、调用、超时和审计。

服务器地址和启用状态维护在根目录 `config/mcp_servers.yaml`，真实密钥通过配置指定的环境变量读取。这里不存放具体业务 Skill 定义。
