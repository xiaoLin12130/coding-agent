# API / WebSocket Specification

## WebSocket

入口：

```
/ws
```

事件：

```
assistant_delta
tool_call
tool_result
state_update
memory_update
agent_update
confirm_request
error
done
```

## 事件原则

每个事件至少包含：

```
event
timestamp
session_id
payload
```

必要时包含：

```
request_id
tool_call_id
agent_id
```

## REST

```
/api/sessions
/api/messages
/api/memory
/api/project_state
/api/settings
/api/logs
/api/agents
```

## 类型来源

后端 Pydantic 模型作为单一事实来源。

输出：

```
OpenAPI
JSON Schema
```

前端 TypeScript 类型根据后端 schema 生成。

禁止前后端分别手工维护同一数据模型两份定义。