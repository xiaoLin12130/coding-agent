# Runtime Multi-Agent

Runtime Multi-Agent 只负责：

> 帮助 Coding Agent 完成用户任务。

## Planner

负责：

- 理解目标
- 制定计划
- 拆分任务

不直接修改文件。

## Coder

负责：

- 使用工具
- 修改代码
- 执行测试

必须通过 Executor。

## Reviewer

负责：

- 检查代码
- 检查测试
- 检查任务完成度

## MemoryCurator

负责：

- 判断长期知识
- 提出 Memory proposal

不直接修改 Memory。

## StateKeeper

负责：

- 更新 Project State
- 保存 checkpoint

## SafetyGuard

负责：

- 检查风险
- 阻止越权行为

## 协作规则

角色共享：

```text
Project State
Memory
当前任务
必要 Context
```

所有真实工具执行统一经过：

```text
Executor
```

必须限制：

```text
最大协作轮次
最大 Agent 步数
超时
```

优先保证单 Agent Loop 正常，再增加 Multi-Agent。