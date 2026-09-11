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

## 约束

浏览器必须 headed。

允许 Xvfb。

不得实现：

- 验证码绕过
- 指纹伪造
- 多账号规避
- 风控绕过