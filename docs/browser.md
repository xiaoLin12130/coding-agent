# Browser / Provider Specification

## BrowserDriver

负责：

- headed browser
- persistent profile
- 页面打开
- 输入
- 发送
- 完成判定
- 回复获取
- Screenshot
- DOM Snapshot

## 完成判定

采用多信号：

```
停止按钮消失
+
DOM 稳定
+
文本长度稳定
```

可辅助：

```
复制按钮可用
网络状态稳定
```

必须支持超时兜底。

## 回复获取优先级

```
网络响应 / SSE
>
复制按钮
>
DOM / HTML
```

## ProviderAdapter

至少定义：

```
open()
send()
wait_until_complete()
capture_response()
is_logged_in()
recover_session()
```

Provider 细节不得散落到 AgentLoop。

MVP 只实现一个 Provider。

## 拟人化操作（M10）

页面必须按真人的方式驱动：

```
鼠标分段移动到输入框
↓
点击
↓
清空草稿
↓
逐字符输入（快慢混合、随机停顿）
↓
停顿后回车
```

节奏要求：

- 快带 / 慢带混合，禁止用单一均值模拟；
- 每次停顿随机，可配置上下限；
- 词边界与标点额外停顿；
- 回复完成后停顿。

## 会话复用（M10）

`open()` 默认**复用当前会话**：页面已在本站点且输入框可用时不重新导航，
第二个问题继续同一个对话。只有显式 `new_conversation=True` 才开新会话。

会话 URL 在每次回复后记录，页面漂移后回到同一会话。

## 默认开关（M10）

站点开关（如"深度思考"）由 profile 的 `toggles` 声明：
发送前检查其 ON 标记，未开启则点击，点击后仍未开启则报错（不允许静默失败）。

## 约束

浏览器必须 headed。

允许 Xvfb。

不得实现：

- 验证码绕过
- 指纹伪造
- 多账号规避
- 风控绕过