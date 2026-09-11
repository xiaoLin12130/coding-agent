# Testing Specification

## 测试层级

```
Unit
Integration
E2E
```

## 必须测试的模块

```
BrowserDriver
ProviderAdapter
ContextBuilder
MemoryStore
ProjectState
ToolCallParser
SafetyLayer
Executor
AgentLoop
Session Recovery
API
WebSocket
```

## ToolCallParser

必须建立黄金测试集，覆盖：

- 标准 JSON
- Markdown Code Fence
- JSON5
- 多 Tool Call
- 括号错误
- 缺失字段
- 非法 JSON
- 混合文本

## Safety

测试：

- 越权路径
- 敏感文件
- 高危 Shell
- Prompt Injection
- 未确认操作

## E2E

至少覆盖：

```
打开页面
↓
发送消息
↓
收到回复
↓
Tool Card
↓
Confirmation
↓
执行
↓
状态更新
```

## 测试原则

禁止只测试“正常路径”。

必须包含：

```
失败
超时
断连
非法输入
恢复
```

## 评估（M9）

```
backend/evaluation/parser_golden.jsonl   黄金测试集（50 例，覆盖上面八类）
backend/evaluation/agent_cases.json      Agent 场景（15 例，覆盖六个维度）
backend/app/evaluation/                  评估执行器、阈值与报告
```

Agent 评估的六个维度：

```
Tool Selection
Tool Parsing
Task Completion      —— 断言磁盘上的结果，而不只是 status
Recovery
Safety
Context Switching
```

运行方式：

```bash
cd backend
python -m app.evaluation.cli run            # 两个套件，报告写入 runs/evaluation/<时间戳>/
python -m app.evaluation.cli run --json
```

规则：

- 每个用例同时给出**输入**与**契约**（期望的调用 / issue / 状态 / 文件内容），
  评估器只报告差异，不反过来迁就实现。
- 阈值默认要求两个套件 100% 通过，并检查分类覆盖、维度覆盖与用例数量；
  阈值不通过时 CLI 退出码为 1。
- `tests/test_evaluation_regression.py` 是回归闸门：任何用例不再符合契约都会
  让测试失败。
- 已知缺陷写入用例的 `known_gap`：期望仍然描述当前行为，报告单独列出，
  修好后必须同步修改数据集。
- 评估全程离线，不需要浏览器、网络或真实模型。

## 拟人化与会话复用（M10）

单元测试（离线，注入 RNG，不真实等待）：

```
tests/test_browser_human.py
  打字节奏：快带 / 慢带混合、范围可配置、词边界额外停顿
  指针：分段移动、点击、清空草稿
  开关：未开启则点击、已开启不点击、点击后未生效则报错
  会话：首次导航、第二次复用、漂移后回到同一会话、显式开新会话
```

真机验证（手动，需已登录的浏览器 profile）：

```
tests/manual/live_deepseek_check.py        两个问题，同一会话；深度思考已打开
tests/manual/live_browser_agent_check.py   真实模型调用工具，整轮同一会话
tests/manual/live_console_check.py         真实 uvicorn + 浏览器 WebSocket
```