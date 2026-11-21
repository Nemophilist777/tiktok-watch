# TikTok 新作品监控（GitHub Actions + 邮件）

监控指定博主的新视频，发现后发邮件提醒。你在国内正常收邮件即可，**不需要开梯子**。

## 一、准备

1. 一个 GitHub 账号，新建一个 **私有** 仓库（Private）；
2. 把本目录所有文件推到仓库；
3. 准备一个能发信的邮箱（推荐 163/QQ 邮箱，开启 SMTP 并使用「授权码」而不是登录密码）。

## 二、获取 TikTok Cookie

1. 浏览器登录 `https://www.tiktok.com`（需要能访问，临时开一下代理）；
2. 按 `F12` → Network → 刷新页面 → 随便点一个请求；
3. 复制请求头里的 `Cookie` 整行；
4. 这就是 `TIKTOK_COOKIE` 的值。

> Cookie 会过期（通常几周），过期后监控会失败，需要重新复制更新 Secret。

## 三、配置 GitHub Secrets

仓库 → Settings → Secrets and variables → Actions → New repository secret：

| Secret | 说明 | 示例 |
|---|---|---|
| `TIKTOK_COOKIE` | 上面复制的 Cookie | `ttwid=...; sessionid=...` |
| `SMTP_HOST` | SMTP 服务器 | `smtp.163.com` |
| `SMTP_PORT` | 端口（465 用 SSL） | `465` |
| `SMTP_USER` | 发信邮箱 | `xxx@163.com` |
| `SMTP_PASS` | 邮箱授权码 | `ABCDEFG...` |
| `MAIL_TO` | 收信邮箱 | `xxx@qq.com` |

## 四、配置博主列表

编辑 `creators.txt`，每行一个用户名（不带 `@`）：

```
tiktok
khaby.lame
```

## 五、启用并测试

1. 仓库 → Actions → 允许 workflows；
2. 选择 `TikTok Watch` → `Run workflow` 手动跑一次；
3. 看日志：
   - 第一次运行会记录每个博主的最新视频（`[INIT]`），**不会发邮件**；
   - 之后发现有新视频才会发。

## 六、已知限制

- **GitHub 的 IP 可能被 TikTok 风控**：日志里如果大量 `[WARN] 未解析到最新视频` 或 403，说明被拦了；
- 检查频率 15 分钟，实际可能有几分钟延迟；
- Cookie 过期需要更新；
- 本方案免费，但不保证长期稳定。如果长期不可用，可改用第三方付费 API 或 RSS 服务。
