# State / Context / Memory Specification

## Context

Context 是：

> 当前这一轮真正发送给 LLM 的信息。

由 ContextBuilder 动态构建。

优先级：

```text
当前系统规则
>
当前用户任务
>
Project State
>
必要 Memory
>
最近 Transcript
>
工具结果
>
旧历史摘要
```

禁止默认注入全部项目内容。

---

## Transcript

保存会话历史。

规则：

- 最近 N 轮完整保存
- 更旧内容摘要
- 保留原始消息索引

Transcript 不等于 Memory。

---

## Project State

描述当前任务事实。

至少包括：

```text
current_milestone
current_task
goal
files_changed
todos
commands_run
failures
git_branch
cwd
checkpoint
```

Project State 优先描述：

> “现在项目做到哪里了。”

---

## Memory

保存长期知识。

适合保存：

- 长期项目决策
- 稳定的设计约束
- 可复用经验
- 用户明确要求长期记住的信息

不适合保存：

- 普通聊天内容
- 每次工具调用
- 临时错误
- 完整 Transcript

LLM 只能提出：

```text
memory_propose
```

系统负责：

```text
过滤
→ 去重
→ 冲突检测
→ 敏感检查
→ 写入
```

---

## Session

Session 是一次完整的对话执行环境。

Context 接近硬阈值时：

```text
完成当前 turn
↓
保存 Project State
↓
生成旧 Transcript 摘要
↓
归档 Session
↓
创建新 Session
↓
注入：
Project State
+
必要 Memory
+
最近 2~3 轮
+
当前任务
```

目标：

> Session 切换后任务可以继续，而不是从头开始。

---

## Context Budget

ContextBuilder 必须支持预算。

大结果：

```text
截断
摘要
分页
按需重新读取
```

不能简单把所有信息全部塞入 Context。