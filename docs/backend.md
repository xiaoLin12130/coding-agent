# Backend Specification

## 目录职责

```
API
WebSocket
Agent Runtime
Context / State
Tool Layer
Browser
Persistence
```

## 推荐模块

```
backend/
├── app/
│   ├── api/
│   ├── agents/
│   ├── browser/
│   ├── context/
│   ├── tools/
│   ├── safety/
│   ├── storage/
│   ├── models/
│   └── main.py
└── tests/
```

具体目录允许根据实际代码调整，但职责边界必须保持。

## 设计原则

- Pydantic 作为数据模型来源
- Service 与 API 层分离
- Provider 与 Runtime 解耦
- Tool 与 Executor 解耦
- 状态必须可持久化
- 关键操作必须可测试

## 持久化

MVP 可以使用：

```
SQLite
JSON checkpoint
```

不要为了抽象而引入额外数据库。