# boc-risk-agent MCP + Skill 扩展平台实施手册
## 面向“其他合作者开发 Skill”的平台接口版

> 文档状态：Codex 可执行工程规格书
> 核验日期：2026-08-18
> 目标仓库：`https://github.com/LiuXingZhi11/boc-risk-agent.git`
> 当前 Agent Runtime：继续使用现有 LangChain + DeepSeek
> 本次目标：**不迁移 DeepSeek Harness，不开发具体业务 Skill；只为现有系统新增通用 MCP 接入能力与可插拔 Skill 开发接口。**

---

# 0. 一句话目标

本次开发结束后，其他合作者应当能够：

```text
1. 在 skills/ 下新建一个目录
2. 编写 skill.yaml
3. 编写 SKILL.md
4. 声明该 Skill 允许使用哪些 MCP Server / Tool
5. 增加测试样例
6. 提交 PR
```

经过平台校验后，该 Skill 即可被现有 LangChain Agent 加载。

**新增一个普通 Skill 不应要求合作者修改：**

```text
src/profiles/react_workflow.py
src/profiles/topic_analysis.py
src/industry/react_workflow.py
Agent create_agent 代码
MCP client 核心代码
数据库核心代码
Ontology 核心代码
```

这就是本项目此次改造是否成功的最核心判断标准。

---

# 1. 本次明确不做

```text
不迁移到 DeepSeek Harness
不重写现有 LangChain Agent
不重新设计 PDF 切分
不重新设计 EvidenceUnit
不开发具体的企查查风控 Skill
不开发具体的企查查知识产权 Skill
不开发具体的授信审批 Skill
不把企查查数据自动写入正式 Ontology
不取消人工审批
不把所有企查查 Tool 一次性暴露给 Agent
```

本次只建设：

```text
MCP Provider Layer
+
Skill Package Contract
+
Skill Registry
+
Skill Loader
+
Tool Resolver
+
Agent Integration Adapter
+
权限 / 调用限制 / 审计
+
开发者模板和测试框架
```

---

# 2. 当前项目基础

当前仓库已经形成：

```text
PDF / HTML
→ SourceAsset + EvidenceUnit
→ 企业画像 / 行业画像候选
→ Python 证据与结构校验
→ 人工审核
→ 风险评级方向报告
→ 可选同行排名
→ 最终客户风险评级报告
```

现有 Agent 继续使用：

```text
LangChain create_agent
DeepSeek model
现有 search/read tools
LangChain middleware
```

本次不替换 Agent Loop。

---

# 3. 为什么要单独建设 Skill 平台层

如果后续直接在 `react_workflow.py` 中持续追加企查查 Tool：

```python
tools = [
    search_evidence,
    read_evidence,
    qcc_tool_a,
    qcc_tool_b,
    ...
]
```

会导致：

```text
Agent 核心与业务 Skill 紧耦合
每增加一个 Skill 都要改核心代码
大量 MCP Tool 同时暴露给模型
Tool 误调用和外部数据费用增加
Skill 无法独立审核和版本管理
```

目标应改成：

```text
Skill Registry
↓
Skill 声明需要哪些 MCP Tool
↓
Tool Resolver 只加载 allowlist
↓
现有 LangChain Agent 使用
```

---

# 4. 官方 MCP 基础

LangChain 当前官方通过：

```text
langchain-mcp-adapters
```

让 LangChain Agent 使用 MCP Server Tool。

平台层应封装官方 Adapter，不自行实现 MCP 协议。

企查查当前官方智能体平台提供多个远端 MCP Server，通用配置包括：

```text
qcc-company
qcc-risk
qcc-ipr
qcc-operation
qcc-history
qcc-executive
qcc-legal-regulation
qcc-legal-case
qcc-tender
qcc-document
```

典型认证方式：

```http
Authorization: Bearer <QCC_API_KEY>
```

企查查是首个 Provider，但框架不能写死为“只支持企查查”。

---

# 5. 目标架构

```text
                         DeepSeek
                            ▲
                            │
                     LangChain Agent
                            │
                 ┌──────────┴──────────┐
                 │                     │
          Existing Tools         Skill Runtime
                 │                     │
       search_evidence              SkillRegistry
       read_evidence                   │
                 │                SkillResolver
                 │                     │
                 │                 ToolResolver
                 │                     │
                 │              MCPProviderManager
                 │                     │
                 │        ┌────────────┴────────────┐
                 │        │                         │
                 │    QCC MCP                  Future MCP
                 │
                 └─────────────────────────────┐
                                               ▼
                                             Audit
                                               │
                                               ▼
                                   ExternalEvidenceTrace
```

---

# 6. 平台开发者与 Skill 开发者职责

## 平台开发者负责

```text
MCP client
MCP provider config
连接管理
Tool catalog
Tool allowlist
Tool proxy
Skill manifest schema
Skill loader
Skill registry
Skill validation
Agent integration
运行时上下文
Tool call guard
Tool call audit
ExternalEvidence trace
测试框架
Skill 模板
开发说明
```

## 后续 Skill 合作者负责

```text
skill.yaml
SKILL.md
测试案例
声明需要的 MCP tools
声明适用 Agent
声明运行限制
必要的 output schema
```

## 普通 Skill 开发者默认不允许

```text
直接改 MCP client
直接拿 API Key
直接修改 create_agent
直接修改 EvidenceQueryService
直接修改数据库 schema
直接写正式 Ontology
直接绕过 approval
直接加载 manifest 未声明的 MCP Tool
```

---

# 7. Skill 设计原则：声明式优先

第一版 Skill 应尽量是：

```text
配置 + Prompt + Tool 声明
```

而不是：

```text
任意 Python 插件
```

因此普通 Skill 包第一版只包含：

```text
skill.yaml
SKILL.md
tests/
```

普通 Skill 目录中的任意 Python 文件默认不得自动执行。

以后如果确实需要程序化 Skill，再单独设计更高权限的 `Trusted Skill Extension API`。

---

# 8. 推荐目录

```text
skills/
├── README.md
├── _template/
│   ├── skill.yaml
│   ├── SKILL.md
│   └── tests/
│       └── cases.yaml
│
└── examples/
    └── qcc_demo/
        ├── skill.yaml
        ├── SKILL.md
        └── tests/
            └── cases.yaml

src/
├── platform/
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── models.py
│   │   ├── client.py
│   │   ├── registry.py
│   │   ├── tool_catalog.py
│   │   ├── tool_resolver.py
│   │   ├── tool_proxy.py
│   │   ├── audit.py
│   │   └── providers/
│   │       ├── __init__.py
│   │       └── qcc.py
│   │
│   └── skills/
│       ├── __init__.py
│       ├── models.py
│       ├── schema.py
│       ├── loader.py
│       ├── registry.py
│       ├── resolver.py
│       ├── runtime.py
│       ├── validator.py
│       └── agent_adapter.py
│
└── evidence/
    └── external_models.py
```

仓库根 `skills/` 是业务 Skill 内容，`src/platform/skills/` 是 Skill 平台运行时代码。

---

# 9. MCP Provider 配置

建议新增：

```text
config/mcp_servers.yaml
```

示例：

```yaml
providers:
  qcc-company:
    provider: qcc
    transport: http
    url: https://agent.qcc.com/mcp/company/stream
    auth_env: QCC_API_KEY
    enabled: true

  qcc-risk:
    provider: qcc
    transport: http
    url: https://agent.qcc.com/mcp/risk/stream
    auth_env: QCC_API_KEY
    enabled: true

  qcc-ipr:
    provider: qcc
    transport: http
    url: https://agent.qcc.com/mcp/ipr/stream
    auth_env: QCC_API_KEY
    enabled: true
```

第一版可以只启用少量 Server，但 Provider Manager 必须支持继续扩展。

---

# 10. Secret 管理

`.env.example` 增加：

```text
QCC_API_KEY=
MCP_ENABLED=false
SKILLS_ENABLED=false
```

真实 API Key 禁止：

```text
写入 skill.yaml
写入 SKILL.md
写入 Git
进入 Agent prompt
进入 trace
暴露给 Skill 作者
```

Provider 层统一注入认证。

---

# 11. MCP Provider Manager

推荐核心接口：

```python
class MCPProviderManager:
    async def initialize(self) -> None:
        ...

    async def list_servers(self) -> list[MCPServerInfo]:
        ...

    async def list_tools(self, server_id: str) -> list[MCPToolInfo]:
        ...

    async def get_tools(
        self,
        requested: list[ToolReference],
    ) -> list[BaseTool]:
        ...

    async def health_check(
        self,
        server_id: str,
    ) -> MCPHealthStatus:
        ...
```

`langchain_mcp_adapters` 只能存在于该层或非常薄的 client 层，不能散落到业务 workflow。

---

# 12. Tool Catalog

系统从 MCP Server 动态发现：

```text
server
tool_name
description
input schema
```

缓存为 `MCPToolCatalog`。

不要把“企查查当前有多少 Tool”写死在代码中。

内部 Tool 唯一标识：

```text
<server_id>:<tool_name>
```

例如：

```text
qcc-company:get_company_registration_info
```

---

# 13. Skill Package Contract

每个 Skill 最低包含：

```text
skills/<skill_id>/
├── skill.yaml
├── SKILL.md
└── tests/
    └── cases.yaml
```

这是后续合作者最主要的开发接口。

---

# 14. `skill.yaml` V1

推荐 schema：

```yaml
schema_version: 1

id: example_qcc_skill
name: 示例企查查 Skill
version: 0.1.0
description: >
  用于验证 Skill 平台能够加载指定 MCP Tool。

owners:
  - team-example

enabled: false
priority: 100

applies_to:
  - profile.discovery

activation:
  mode: explicit

prompt:
  file: SKILL.md

tools:
  - server: qcc-company
    name: get_company_registration_info

limits:
  max_tool_calls: 3
  timeout_seconds: 60

context:
  required:
    - company_name
  optional:
    - unified_social_credit_code

output:
  type: advisory

persistence:
  external_tool_results: trace_only
```

---

# 15. Manifest 关键字段

`schema_version`：第一版必须为 `1`，未知版本拒绝加载。

`id`：全局唯一，目录名必须与 id 一致。

`version`：Skill 语义版本，任何 Prompt、Tool allowlist、Schema、Limits 的重要变化都应升级版本。

`applies_to`：V1 建议枚举：

```text
profile.discovery
profile.recovery
profile.topic_analysis
industry.discovery
direction.review
report.final
```

`activation.mode`：第一版只必须支持 `explicit`。不要第一版就让模型自行扫描全 Skill 库并任意开启。

`tools`：只允许使用 manifest 显式声明的 `server + tool name`。

`limits`：至少支持 `max_tool_calls` 与 `timeout_seconds`。

`context.required`：表示平台必须提供给 Skill 的可信上下文。

`output.type=advisory`：默认 Skill 输出只是辅助信息，不自动成为正式审批结论。

---

# 16. SKILL.md Contract

`SKILL.md` 只负责：

```text
业务意图
Tool 使用策略
数据解释原则
输出要求
禁止事项
```

不得写：

```text
API Key
MCP URL
数据库路径
Python import
内部 secret
```

模板：

```markdown
# Skill 名称

## 目标
说明业务目标。

## 可用数据
说明允许使用的外部数据类别。

## 执行原则
说明如何组合已声明 Tool。

## 证据原则
说明外部信息如何引用，并与内部材料区分。

## 输出要求
说明返回给上层 Agent 的内容。

## 禁止事项
- 不得调用 manifest 未声明 Tool。
- 不得把外部数据自动写成正式审批结论。
- 无结果不得直接解释为“事实不存在”。
```

---

# 17. SkillLoader / Validator / Registry

`SkillLoader` 负责：

```text
发现目录
读取 YAML
读取 SKILL.md
构造 SkillDefinition
```

`SkillValidator` 负责：

```text
manifest schema
id / 目录一致性
version
applies_to
prompt file
tool references
context keys
limits
```

`SkillRegistry` 推荐 API：

```python
class SkillRegistry:
    def refresh(self) -> SkillRegistryReport:
        ...

    def list_skills(self, enabled_only: bool = True) -> list[SkillSummary]:
        ...

    def get(self, skill_id: str) -> SkillDefinition:
        ...

    def get_for_agent(self, agent_scope: str) -> list[SkillDefinition]:
        ...
```

Registry 只管理 Skill，不执行 Skill。

---

# 18. SkillResolver

输入：

```text
agent_scope
requested skill_ids
runtime context
```

输出：

```python
@dataclass
class SkillRuntimePlan:
    skill_ids: list[str]
    prompt_sections: list[str]
    tool_refs: list[ToolReference]
    required_context: set[str]
    limits: SkillRuntimeLimits
```

Resolver 必须只合并当前 Skill 声明的 Tool，不允许把整个 MCP Server Tool 集交给 Agent。

---

# 19. ToolResolver / ToolProxy

`MCPToolResolver`：

```python
async def resolve(
    refs: list[ToolReference],
) -> list[BaseTool]:
    ...
```

必须校验：

```text
Server 是否启用
Tool 是否存在
Tool 是否在 allowlist
重复 Tool
名称冲突
```

所有 Tool 都必须经过 `MCPToolProxy` 包装后才能交给 Agent。

Proxy 负责：

```text
调用次数限制
timeout
运行时上下文注入
输入检查
错误归一化
结果大小保护
secret 清洗
调用审计
ExternalEvidenceTrace
```

禁止直接把 Adapter 返回的 MCP Tool 原样塞进 `create_agent`。

---

# 20. Runtime Context

平台建立可信：

```python
@dataclass(frozen=True)
class SkillRuntimeContext:
    run_id: str
    case_id: str | None
    company_name: str | None
    unified_social_credit_code: str | None
    domain: str | None
    industry_name: str | None
    agent_scope: str
    user_role: str | None
```

Skill 作者不能通过 Tool 参数自由选择：

```text
数据库路径
任意 case_id
任意文件路径
任意权限
```

---

# 21. AgentSkillAdapter

这是现有 Agent 与 Skill 平台之间唯一主要入口。

```python
@dataclass
class AgentSkillExtension:
    system_prompt_suffix: str
    tools: list[BaseTool]
    metadata: dict

class AgentSkillAdapter:
    async def build_extension(
        self,
        *,
        agent_scope: str,
        skill_ids: list[str],
        runtime_context: SkillRuntimeContext,
    ) -> AgentSkillExtension:
        ...
```

Profile / Industry / Topic Analysis 不应直接理解 QCC。

它们只调用：

```text
AgentSkillAdapter
```

---

# 22. Workflow 接口扩展

推荐统一新增：

```python
skill_ids: Sequence[str] = ()
```

例如：

```python
run_current_domain(
    case_id=...,
    domain=...,
    skill_ids=(),
)
```

错误：

```python
qcc_enabled=True
qcc_risk=True
qcc_ipr_tools=[...]
```

正确：

```python
skill_ids=["some_skill"]
```

这样 Agent core 不知道背后是 QCC 还是未来其它 Provider。

---

# 23. Prompt 注入

多个 Skill 应按稳定顺序生成：

```text
<enabled_skills>

<skill id="skill_a" version="1.0.0">
...
</skill>

<skill id="skill_b" version="0.3.0">
...
</skill>

</enabled_skills>
```

排序建议：

```text
priority
id
```

平台固定安全规则必须在 Skill Prompt 之前注入，Skill 作者不能覆盖。

平台固定规则至少包含：

```text
只允许调用已加载 Skill 声明的 Tool
外部 MCP 数据与内部 EvidenceUnit 不等同
Tool 无结果不能解释为风险不存在
外部数据不得自动成为正式授信结论
```

---

# 24. ExternalEvidenceTrace

MCP 外部数据不要直接塞进 `EvidenceUnit`。

新增：

```text
src/evidence/external_models.py
```

推荐：

```python
@dataclass
class ExternalEvidenceTrace:
    trace_id: str
    run_id: str
    skill_id: str
    skill_version: str

    provider: str
    server_id: str
    tool_name: str

    subject_name: str | None
    subject_identifier: str | None

    requested_at: str
    completed_at: str | None
    status: str

    request_summary: dict
    result_summary: dict | None
    raw_result_hash: str | None
    error_code: str | None
```

第一版默认只保存：

```text
trace metadata + selected summary
```

不要默认永久保存完整 MCP raw JSON。

---

# 25. 审批和业务边界

默认：

```text
Skill output = advisory
MCP result = external evidence
```

禁止自动：

```text
approved
写正式 Ontology
成为最终授信结论
修改同行排名
绕过人工审批
```

未来若 Skill 结果需要入库：

```text
Skill
→ Candidate
→ Validator
→ Approval
→ Repository
```

继续走现有业务边界。

---

# 26. Skill 启用与安装分离

目录存在只表示：

```text
installed
```

不表示：

```text
enabled
```

建议新增中央配置：

```text
config/enabled_skills.yaml
```

例如：

```yaml
enabled_skills:
  - example_qcc_skill
```

生产环境真正启用以中央配置为准，而不是 Skill 作者自己写 `enabled: true` 就自动上线。

---

# 27. 权限模型

最终有效 Tool：

```text
manifest_tools
∩
platform_allowed_tools
∩
current_user_permissions
```

第一版即使用户权限暂未完全接入，也必须预留这一层。

Server 级也应允许：

```yaml
permissions:
  qcc-company:
    enabled: true
  qcc-risk:
    enabled: true
  qcc-history:
    enabled: false
```

---

# 28. 调用预算

每个 Skill 必须声明：

```text
max_tool_calls
```

平台还有全局：

```text
MCP_MAX_TOOL_CALLS_PER_RUN
```

最终：

```text
effective_limit = min(skill_limit, platform_limit)
```

不要硬编码企查查当前积分单价；Tool 定价属于外部可变配置。

---

# 29. MCP 错误归一化

统一错误：

```text
AUTH_FAILED
PROVIDER_UNAVAILABLE
TOOL_NOT_FOUND
TIMEOUT
RATE_LIMITED
BUDGET_EXCEEDED
INVALID_INPUT
RESPONSE_TOO_LARGE
UNKNOWN
```

禁止将：

```text
API Key
Authorization Header
内部堆栈
```

返回模型或写入审计。

---

# 30. Async 边界

`langchain-mcp-adapters` 主要走 async。

Codex 必须先检查现有：

```text
invoke / ainvoke
Streamlit
create_agent
```

调用方式。

禁止各 workflow 到处 `asyncio.run()`。

统一由：

```text
MCPProviderManager
AgentSkillAdapter
```

处理 async 边界；若现有 workflow 必须同步，则提供统一 sync facade。

---

# 31. Tool Catalog Cache

建议增加：

```text
data/runtime/mcp_tool_catalog.json
```

用于缓存：

```text
server
tool
description
schema
refreshed_at
```

缓存仅供：

```text
Skill validate
开发者查看
UI 展示
```

真正调用仍以在线 Provider 为准。

---

# 32. Skill 开发 CLI

必须提供：

```text
python scripts/validate_skill.py skills/<skill_id>
```

离线验证：

```text
manifest
prompt
schema
agent scope
tool reference 格式
```

可选：

```text
--online
```

验证 MCP Tool 真实存在。

同时提供：

```text
python scripts/list_skills.py
python scripts/check_mcp.py --server qcc-company --list-tools
```

所有 CLI 禁止打印 API Key。

---

# 33. Fake MCP Server

为了让 Skill 合作者不需要企查查 Key、不消耗积分即可开发，必须提供 Fake MCP。

推荐：

```text
tests/fakes/mcp_server.py
```

至少提供：

```text
fake-company:get_company_registration_info
fake-risk:get_company_risk_scan
```

返回稳定 JSON。

绝大多数平台测试必须使用 Fake MCP。

---

# 34. Skill 开发者模板

`skills/_template/` 必须可直接复制：

```powershell
Copy-Item -Recurse skills\_template skills\my_new_skill
```

之后只改：

```text
skill.yaml
SKILL.md
tests/cases.yaml
```

普通合作者不应需要阅读整个 Agent 实现。


---

# 35. Skill 测试案例 Contract

推荐：

```yaml
cases:
  - id: basic
    description: 最小运行验证
    input:
      company_name: 示例企业
    expect:
      must_load_tools:
        - fake-company:get_company_registration_info
      max_tool_calls: 3

  - id: undeclared_tool
    description: 未声明 Tool 必须不可用
    expect:
      forbidden_tools:
        - fake-risk:get_company_risk_scan
```

Skill 作者可以完全使用 Fake MCP 完成开发和 PR。

---

# 36. 示例 Skill 的定位

仓库可以提供：

```text
skills/examples/qcc_demo/
```

但只用于验证平台：

```text
Skill Loader
Tool allowlist
MCP 调用
Agent 注入
Audit
```

示例文件中必须明确：

```text
THIS IS A PLATFORM DEMO.
DO NOT USE AS A FORMAL RISK SKILL.
```

本次平台开发者不要继续把 Demo 扩展成正式业务尽调 Skill。

---

# 37. Agent 接入点

第一阶段至少为以下 scope 预留：

```text
profile.discovery
profile.recovery
profile.topic_analysis
industry.discovery
direction.review
report.final
```

首轮实际接入可以只做：

```text
profile.discovery
```

但 `SkillRegistry / SkillResolver / AgentSkillAdapter` 不能写死为 Profile 专用。

---

# 38. Profile Agent 最小改造

目标：

```text
现有 base tools
+
AgentSkillAdapter 返回的 extension.tools
```

概念：

```python
base_tools = make_react_tools(session)

extension = await skill_adapter.build_extension(
    agent_scope="profile.discovery",
    skill_ids=skill_ids,
    runtime_context=context,
)

tools = [
    *base_tools,
    *extension.tools,
]

system_prompt = (
    base_system_prompt
    + extension.system_prompt_suffix
)
```

除此之外：

```text
react_workflow.py
```

不应理解：

```text
QCC
MCP URL
API Key
某个具体 Skill 的 Tool 名
```

---

# 39. `guide_text` 与 Skill 分离

现有 `guide_text` 属于当前业务流程输入。

新 `Skill prompt` 来自 Skill Registry。

禁止：

```text
把 Skill prompt 塞入 guide_text
```

必须单独记录：

```text
guide_text
enabled skill ids
skill versions
skill prompts
```

---

# 40. Agent Trace 增加 Skill 元数据

每次运行记录：

```json
{
  "skills": [
    {
      "id": "example_qcc_skill",
      "version": "0.1.0"
    }
  ],
  "mcp_tools": [
    "qcc-company:get_company_registration_info"
  ]
}
```

这样才能重现：

```text
某次 Agent 当时使用了哪一版 Skill
实际暴露了哪些 Tool
```

---

# 41. Skill Prompt 冲突与顺序

V1 不尝试自动解决复杂 Prompt 语义冲突。

但必须做到：

```text
稳定排序
边界清晰
可追踪
```

推荐使用：

```yaml
priority: 100
```

再按：

```text
priority
id
```

排序。

---

# 42. Tool 数量上限

多个 Skill 同时启用可能累计过多 Tool。

建议环境变量：

```text
SKILL_MAX_TOOLS_PER_AGENT=12
```

超过阈值：

```text
明确拒绝构建 Agent
```

不要直接把几十甚至上百个 MCP Tool 给模型。

---

# 43. Tool Result 大小控制

MCP 返回值可能很大。

ToolProxy 必须有：

```text
max_result_chars
```

超过后：

```text
截断并显式标记 truncated=true
```

不得静默截断。

后续可增加：

```text
pagination
summary policy
external blob storage
```

第一版不做复杂化。

---

# 44. Provider 与 Skill 解耦

多个 Skill 可以复用同一：

```text
qcc-company
```

Provider 连接配置只有一份。

即：

```text
MCP connection
≠
business skill
```

企查查 URL 或认证方式未来变化时：

```text
只改 Provider Config
```

Skill 无需修改。

---

# 45. MCP / Skill Feature Flags

新增：

```text
MCP_ENABLED=false
SKILLS_ENABLED=false
```

以及建议：

```text
MCP_CONNECT_TIMEOUT_SECONDS=10
MCP_TOOL_TIMEOUT_SECONDS=60
MCP_MAX_TOOL_CALLS_PER_RUN=10
SKILL_MAX_TOOLS_PER_AGENT=12
MCP_RAW_RESULT_RETENTION=none
```

必须保证：

```text
MCP_ENABLED=false
SKILLS_ENABLED=false
```

时现有系统行为与改造前一致。

---

# 46. Fail Closed / Fail Isolated

若某 Skill 被明确请求，但出现：

```text
API Key 缺失
MCP Server 不可用
Tool 不存在
Skill manifest invalid
```

必须：

```text
明确标记 Skill unavailable
```

不能：

```text
假装执行成功
```

是否允许 Base Agent 继续，由上层运行参数决定。

推荐后续支持：

```text
required skill
optional skill
```

第一版至少不要发生无提示降级。

---

# 47. Skill 安装、验证、启用流程

推荐状态：

```text
目录进入仓库
↓
installed
↓
schema validation
↓
tool validation
↓
review
↓
enabled
↓
runtime
```

这和现有系统：

```text
模型候选
↓
审批
↓
正式使用
```

的思路一致。

---

# 48. Skill 版本升级规则

以下变化必须升级 Skill version：

```text
SKILL.md 的业务规则变化
Tool allowlist 变化
output schema 变化
limits 重大变化
context requirement 变化
```

运行日志始终保存：

```text
skill_id + skill_version
```

---

# 49. 外部 Tool Schema 变化

外部 MCP Provider 可能调整 Tool schema。

在线 Skill validate 时至少检查：

```text
Server 仍存在
Tool 仍存在
```

推荐后续进一步检查：

```text
input schema hash
```

Tool 消失：

```text
Skill INVALID
```

不要静默跳过。

---

# 50. 推荐新增依赖

新增：

```text
langchain-mcp-adapters
```

具体版本由 Codex 在实施时：

```text
读取当前 requirements.txt 中 LangChain 版本
核对官方 compatibility
安装并实际 Smoke
pin 成功版本
```

不要仅按本手册硬猜版本。

---

# 51. 测试总体原则

此次功能不是以：

```text
“企查查能返回结果”
```

作为最终成功标准。

真正成功标准是：

```text
“未来新增 Skill 时不需要修改平台核心”
```

因此必须同时测试：

```text
MCP 基础能力
Skill Loader
Tool allowlist
Agent injection
审计
回归
开发者体验
```

---

# 52. Level 1：Manifest Unit Test

必须覆盖：

```text
合法 Skill 加载成功
缺 skill.yaml 失败
缺 SKILL.md 失败
schema_version 错误失败
目录名/id 不一致失败
未知 applies_to 失败
非法 version 失败
负数 max_tool_calls 失败
重复 tool 声明失败
未知 context key 失败
```

---

# 53. Level 2：Tool Resolver Test

Fake Catalog：

```text
声明 Tool 存在 -> 成功
Tool 不存在 -> 明确失败
Server disabled -> 明确失败
同一个 Tool 重复 -> 规范化
不同 Server 同名 Tool -> 正确区分
```

---

# 54. Level 3：Tool Allowlist Test

Skill 只声明：

```text
Tool A
```

最终 Agent Tool 集必须是：

```text
base tools
+
Tool A
```

绝对不能出现：

```text
同 Server Tool B
同 Provider Tool C
```

这是重要安全 Gate。

---

# 55. Level 4：Agent Injection Test

无 Skill：

```text
skill_ids=()
```

要求：

```text
现有 Agent Prompt 不变
现有 Agent Tool 不变
旧测试通过
```

加载 Demo Skill：

```text
Prompt 中出现 Skill block
Tool list 中增加声明 Tool
Trace 记录 Skill id/version
```

---

# 56. Level 5：Fake MCP End-to-End

完整跑：

```text
LangChain Agent
↓
Skill
↓
ToolResolver
↓
ToolProxy
↓
Fake MCP
↓
Tool Result
↓
LangChain Agent
```

必须在无真实 QCC Key 下成功。

---

# 57. Level 6：真实 QCC Smoke

只有环境存在：

```text
QCC_API_KEY
```

才运行。

标记：

```text
@pytest.mark.integration
```

建议只调用一个基础企业信息 Tool，验证：

```text
MCP HTTP 连接成功
Authorization 成功
Tool 可发现
Tool 可调用
结果可被 LangChain Agent 读取
Audit 中没有 API Key
```

CI 默认不运行真实 QCC integration test。

---

# 58. Level 7：“零核心改动新增 Skill”最终验收

这是最重要测试。

步骤：

```text
1. Copy skills/_template -> skills/new_demo_skill
2. 修改 skill.yaml
3. 写 SKILL.md
4. 声明一个 Fake MCP Tool
5. 写 cases.yaml
6. validate
7. enabled config 加入 new_demo_skill
8. 运行 Agent
```

然后检查：

```bash
git diff
```

除：

```text
skills/new_demo_skill/
config/enabled_skills.yaml
```

外，不应为了这个普通 Skill 修改：

```text
src/profiles/react_workflow.py
src/platform/skills/agent_adapter.py
src/platform/mcp/client.py
其它 Agent core
```

如果必须改核心，平台接口仍未完成。

---

# 59. 外部数据与内部 Evidence 的测试

MCP Result：

```text
ExternalEvidenceTrace
```

PDF / HTML：

```text
EvidenceUnit
```

必须在类型和 trace 中明确分开。

测试：

```text
QCC MCP 返回值不会自动变成 EvidenceUnit
不会自动 approved
不会自动写 Ontology
```

---

# 60. Secret 测试

测试捕获：

```text
日志
trace
tool error
agent messages
saved runtime metadata
```

不得出现：

```text
QCC_API_KEY
Bearer token
Authorization Header
```

---

# 61. 调用次数 Guard 测试

Skill：

```text
max_tool_calls=2
```

Agent 尝试第三次调用：

```text
必须被平台拦截
```

不能只依赖 Prompt 中一句“最多调用 2 次”。

---

# 62. Timeout 测试

Fake MCP Tool：

```text
sleep > timeout
```

要求：

```text
ToolProxy 返回统一 TIMEOUT
Agent 不无限等待
Audit 记录 timeout
其它 Skill / Base Agent 不被永久破坏
```

---

# 63. 回归测试

运行现有仓库 README 中的 pytest baseline。

必须确认：

```text
MCP/Skills disabled
```

时：

```text
企业画像
行业画像
Topic Analysis
报告
审批
Ranking
```

现有路径不受影响。

---

# 64. Skill 开发者 README 必须包含

`skills/README.md` 至少说明：

```text
Skill 是什么
Skill 不是什么
目录结构
skill.yaml 全字段
SKILL.md 模板
如何找到 MCP Tool 名称
如何离线 validate
如何 Fake test
如何真实 integration test
如何提交 PR
如何申请 enabled
谁负责 API Key
Skill 不能直接做哪些事情
```

---

# 65. Skill 开发者理想工作流

最终应该足够简单：

```text
复制模板
↓
修改 skill.yaml
↓
写 SKILL.md
↓
声明 Tool
↓
写 cases.yaml
↓
validate
↓
fake test
↓
提交 PR
↓
平台管理员 review + enable
```

普通合作者不需要：

```text
读懂整个 boc-risk-agent
修改 create_agent
自己写 MCP Client
自己处理 QCC Key
自己实现 Tool 审计
```

---

# 66. Phase 0：Baseline

Codex 先做：

```text
读取 README
读取 requirements.txt
搜索所有 create_agent
检查 invoke/ainvoke 方式
运行当前 pytest
确认当前 LangChain 版本
核对 langchain-mcp-adapters 当前官方兼容方式
```

Phase 0 不改变业务行为。

---

# 67. Phase 1：通用 MCP 基础层

新增：

```text
src/platform/mcp/
config/mcp_servers.yaml
```

先接：

```text
Fake MCP
```

实现：

```text
MCPServerConfig
MCPProviderManager
MCPToolCatalog
Tool list
Health check
```

不要先碰 Agent。

---

# 68. Phase 2：Skill Contract

新增：

```text
src/platform/skills/
skills/_template/
skills/README.md
```

实现：

```text
SkillDefinition
schema validation
loader
registry
resolver
validate CLI
list CLI
```

此阶段仍不接真实 QCC。

---

# 69. Phase 3：ToolResolver + ToolProxy

实现：

```text
Tool allowlist
Tool name normalization
Timeout
Call count
Audit
ExternalEvidenceTrace
Error normalization
```

使用 Fake MCP 验证。

---

# 70. Phase 4：AgentSkillAdapter

实现：

```text
SkillRuntimeContext
SkillRuntimePlan
AgentSkillExtension
AgentSkillAdapter
```

用 Fake Skill 验证 Prompt 和 Tool 注入。

---

# 71. Phase 5：接入 Profile Discovery

给 Profile Workflow 增加：

```text
skill_ids=()
```

默认空。

要求：

```text
无 Skill 时旧行为完全兼容
```

此阶段禁止加入任何 QCC-specific 分支。

---

# 72. Phase 6：企查查 Provider

配置：

```text
qcc-company
qcc-risk
qcc-ipr
```

接入真实 QCC API Key。

验证：

```text
health
list tools
调用一个基础 Tool
```

但只做平台 Demo，不做正式业务 Skill。

---

# 73. Phase 7：其它 Agent Scope

按需要将同一个：

```text
AgentSkillAdapter
```

接入：

```text
profile.recovery
profile.topic_analysis
industry.discovery
```

不复制 Loader / MCP client。

---

# 74. Phase 8：Developer Experience

完善：

```text
Skill template
skills/README.md
Fake MCP
validate CLI
list CLI
check_mcp CLI
PR checklist
```

让新的合作者可以独立操作。

---

# 75. 建议 Codex 第一轮授权

当前第一轮只让 Codex执行：

```text
Phase 0
Phase 1
Phase 2
```

即：

```text
Baseline
Fake MCP 基础层
Skill manifest/loader/registry
```

第一轮不要：

```text
真实调用企查查
修改 Profile Agent 行为
写正式业务 Skill
```

---

# 76. 第一轮完成 Gate

必须能做到：

```text
复制 skills/_template
↓
validate 成功
↓
SkillRegistry 能发现
↓
解析出 ToolReference
↓
Fake MCP Catalog 能验证 Tool 存在
```

同时原项目 tests 继续通过。

---

# 77. 第二轮授权

第一轮通过后执行：

```text
Phase 3
Phase 4
```

即：

```text
ToolProxy
Audit
AgentSkillAdapter
Fake E2E
```

只有：

```text
Agent -> Skill -> Fake MCP -> Agent
```

跑通后，才接真实 QCC。

---

# 78. 第三轮授权

再执行：

```text
Phase 5
Phase 6
```

即：

```text
Profile Discovery 接入
真实 QCC Provider Smoke
```

仍然只使用平台 Demo Skill。

---

# 79. Definition of Done

## MCP Platform

- [ ] LangChain 可连接通用 MCP Server
- [ ] Provider 配置与 Skill 分离
- [ ] QCC Provider 可作为首个真实 Provider
- [ ] API Key 不进入 Skill
- [ ] Tool catalog 可动态发现
- [ ] Tool allowlist 可强制
- [ ] ToolProxy 统一保护外部 Tool
- [ ] MCP failure 有统一错误

## Skill Platform

- [ ] `skill.yaml` V1 schema 可用
- [ ] `SKILL.md` contract 可用
- [ ] Skill Loader 可用
- [ ] Skill Validator 可用
- [ ] Skill Registry 可用
- [ ] Skill Resolver 可用
- [ ] Skill version 可追踪
- [ ] 安装与启用分离
- [ ] 普通 Skill 不执行任意 Python

## Agent Integration

- [ ] AgentSkillAdapter 为唯一主要 Skill 注入接口
- [ ] Agent core 不理解 QCC
- [ ] `skill_ids=()` 时旧行为不变
- [ ] Skill 只得到 manifest 声明的 Tool
- [ ] Tool 总数量有平台上限
- [ ] Prompt 有稳定 Skill block 和平台 Policy

## Audit / Safety

- [ ] MCP Tool 全部经过 Proxy
- [ ] API Key 不进入 trace
- [ ] Tool call 有审计
- [ ] 外部数据与 EvidenceUnit 区分
- [ ] 外部数据不自动 approved
- [ ] Skill 不直接写正式 Ontology
- [ ] Tool count / timeout 由代码强制

## Developer Experience

- [ ] `skills/_template` 可复制
- [ ] 不需要 QCC Key 即可离线开发
- [ ] Fake MCP 可测试
- [ ] validate CLI 可用
- [ ] list CLI 可用
- [ ] MCP health/list-tools CLI 可用
- [ ] README 足以让新合作者独立开发

## 最终核心验收

- [ ] 新建一个普通 Skill 无需修改 Agent core
- [ ] 新 Skill 只通过目录 + manifest + prompt + tests 接入
- [ ] 删除该 Skill 后核心系统仍正常
- [ ] `MCP_ENABLED=false / SKILLS_ENABLED=false` 时旧系统回归通过

---

# 80. Codex 必须遵守的修改约束

1. 不迁 DSH。
2. 不重写 LangChain Agent Loop。
3. 不开发正式企查查业务 Skill。
4. 不把 QCC 写死进 Profile Workflow。
5. 不允许 Skill 自己管理 API Key。
6. 不允许普通 Skill 自动执行 Python。
7. 不直接把全量 MCP Tool 给 Agent。
8. 不把 MCP Result 自动变成 EvidenceUnit。
9. 不把 MCP Result 自动 approved。
10. 不改 PDF chunking。
11. 不改 Ontology 核心 schema。
12. 不改 Ranking 逻辑。
13. 不破坏现有无 Skill 路径。
14. 每 Phase 跑测试。
15. 每 Phase 输出修改文件和测试报告。

---

# 81. Codex 第一轮必须输出

```text
1. 当前 LangChain 版本
2. langchain-mcp-adapters 选择版本及依据
3. 当前 Agent sync/async 结构
4. Baseline pytest
5. 新增 MCP 模块列表
6. Fake MCP 启动/测试方式
7. Skill manifest schema
8. SkillRegistry 列表输出
9. validate CLI 示例
10. 原有无 Skill 流程回归结果
11. 修改文件清单
12. 下一 Phase 风险
```

---

# 82. 官方参考

LangChain MCP：

```text
https://docs.langchain.com/oss/python/langchain/mcp
```

企查查 MCP 接入：

```text
https://agent.qcc.com/guide
```

企查查数据 Tool 目录：

```text
https://agent.qcc.com/data
```

企查查 Skill 广场：

```text
https://agent.qcc.com/skills
```

当前项目：

```text
https://github.com/LiuXingZhi11/boc-risk-agent
```

---

# 83. 最终架构原则

此次交付的是：

```text
Skill 插槽
```

而不是：

```text
若干具体 Skill
```

此次交付的是：

```text
通用 MCP Provider 能力
```

而不是：

```text
把企查查 API 写死进 Agent
```

最终应形成：

```text
现有 LangChain Agent
       +
通用 Skill Runtime
       +
通用 MCP Runtime
       +
可审核、可插拔、可版本化的 Skill Package
```

让后续合作者只需要理解 Skill Contract，就能安全地把企查查或其它 MCP 数据能力组合成新的业务 Skill。
