# Frontend Specification

## 技术栈

- React 18
- TypeScript
- Vite
- Tailwind CSS
- Zustand
- TanStack Query
- react-markdown
- Shiki
- Radix UI / shadcn
- lucide-react
- Vitest
- Playwright

## 核心布局

```
┌────────────┬──────────────────────┬──────────────────┐
│ Sessions   │ Chat                 │ Workbench        │
│            │                      │                  │
│ Search     │ Messages             │ Tool Calls       │
│ Session    │                      │ Project State    │
│ Provider   │                      │ Memory           │
│ Settings   │ Input                │ Files            │
│            │                      │ Logs / Agents    │
└────────────┴──────────────────────┴──────────────────┘
```

## 视觉原则

参考 DeepSeek 风格的信息组织：

- 深色主题为主
- 浅色主题可选
- 圆角
- 合理间距
- 清晰字体层级
- 信息密度适中

禁止：

- DeepSeek Logo
- DeepSeek 商标
- 专有字体
- 受版权保护的前端资源直接复制

## Chat

支持：

- Markdown
- 代码高亮
- 复制
- 行号
- Diff
- 流式输出
- 停止
- 自动滚动
- 回到底部
- 编辑
- 重试

## Tool Card

显示：

```
Tool
Parameters
Status
Duration
Risk
Result Summary
```

## Project State

显示：

```
Goal
Current Task
Todos
Changed Files
Commands
Failures
Git Branch
CWD
Checkpoint
Agents
```

## Memory

支持：

```
搜索
查看
编辑
删除
Sensitive
Source Turn
Updated By
```