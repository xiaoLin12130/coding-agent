# Development Agent Workflow

## 1. 目的

本流程用于开发 Coding Agent 系统本身。

不用于 Runtime Agent 的用户任务执行。

## 2. 角色

### Architect

负责：

- 架构
- 模块边界
- 接口
- 关键技术决策

### Backend

负责：

- Python
- FastAPI
- WebSocket
- Agent Runtime
- Tool Layer
- State / Memory
- Browser / Provider

### Frontend

负责：

- React
- TypeScript
- UI
- 状态管理
- REST / WebSocket

### Test

负责：

- Unit Test
- Integration Test
- E2E
- Regression Test

### Reviewer

负责：

- 功能
- 代码质量
- 测试
- 安全
- 是否偏离 Milestone
- 是否破坏已有架构

### Documentation

负责：

- 架构文档
- API 文档
- Milestone 文档
- 必要变更记录

## 3. 协作原则

禁止多个 Agent 同时修改同一文件。

推荐：

```
Architect
↓
Implementation Agent
↓
Test
↓
Reviewer
```

共享信息优先通过：

```
state/project_state.json
state/memory.json
```

而不是复制完整聊天记录。

## 4. 每个任务必须有

```
Task
Owner
Input
Output
Files
Acceptance Criteria
```

## 5. Review

Review 至少检查：

```
功能正确性
测试结果
安全边界
修改范围
架构一致性
Milestone 一致性
```

失败后：

```
Review
↓
问题
↓
修复
↓
测试
↓
再次 Review
```

## 6. Definition of Done

任务必须同时满足：

```
代码完成
+
测试通过
+
Project State 更新
+
必要文档更新
+
Review 通过
```