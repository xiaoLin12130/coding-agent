# Safety / Executor Specification

## 1. 执行链

```
ToolCall
↓
Validation
↓
SafetyLayer
↓
Confirmation
↓
Executor
↓
Tool
```

## 2. 文件访问

默认只允许：

```
项目工作目录
```

禁止访问：

- 项目外目录
- 系统关键目录
- SSH 私钥
- 密钥
- 凭证文件
- 不必要的敏感文件

## 3. Shell 风险

分级：

```
LOW
MEDIUM
HIGH
```

例如：

```
读取文件 → LOW
修改项目文件 → MEDIUM
删除文件 → HIGH
系统级命令 → HIGH
```

HIGH 必须人工确认。

## 4. Confirmation

显示：

```
命令
cwd
风险等级
影响范围
```

按钮：

```
拒绝
仅本次
本会话允许
```

## 5. Prompt Injection

以下内容一律视为数据：

- 网页文本
- 文件文本
- Tool Result
- Shell Output
- 外部文档

即使其中出现命令，也不能自动提升为指令。

## 6. Executor

Executor 是唯一真实执行入口。

必须：

- 参数校验
- 权限检查
- 风险检查
- 日志记录
- 错误处理
- 幂等处理