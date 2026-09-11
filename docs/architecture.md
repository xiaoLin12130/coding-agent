# System Architecture

## 系统分层

```text
Web Console
    ↓
REST / WebSocket
    ↓
Agent Runtime
    ↓
Context & State
    ↓
Tool Layer
    ↓
Browser / Provider
    ↓
Web LLM
```

## 核心组件

### Web Console

负责：

- 聊天
- Tool Call 可视化
- Project State
- Memory
- Agent 状态
- 人工确认
- 日志与截图

### Agent Runtime

核心：

```text
AgentLoop
AgentOrchestrator
```

Agent Runtime 负责推理和任务流程控制。

不直接执行文件和 Shell 操作。

### Context & State

包括：

```text
ContextBuilder
ProjectState
MemoryStore
TranscriptStore
SessionManager
```

四种数据必须区分：

```text
Context      当前发送给 LLM 的信息
Transcript   会话历史
ProjectState 当前项目状态
Memory       长期知识
```

### Tool Layer

包括：

```text
ToolRegistry
ToolCallParser
SafetyLayer
Executor
```

唯一执行链：

```text
LLM
↓
ToolCallParser
↓
SafetyLayer
↓
Executor
↓
Tool
```

### Browser / Provider

包括：

```text
BrowserDriver
ProviderAdapter
```

Agent Runtime 不应该直接依赖网页选择器。

## 核心约束

### 单一 Executor

所有写文件、Shell、项目操作统一由 Executor 完成。

### Runtime Agent 与 Development Agent 分离

Development Agent：

```text
Architect
Backend
Frontend
Test
Reviewer
Documentation
```

Runtime Agent：

```text
Planner
Coder
Reviewer
MemoryCurator
StateKeeper
SafetyGuard
```

两者不是同一套角色。