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