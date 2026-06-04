# 安全政策 | Security Policy

## 报告漏洞

如果你发现安全漏洞，**请不要创建公开的 Issue**。

请通过以下方式私密报告：

1. 发送邮件至项目维护者
2. 使用 GitHub 的 [私密漏洞报告](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) 功能

请在报告中包含：

- 漏洞的详细描述
- 复现步骤
- 受影响版本
- 可能的修复建议（如有）

## 处理流程

1. 确认收到报告后，我们将在 **48 小时内** 回复
2. 我们将在 **7 天内** 评估并确认漏洞
3. 修复将在确认后尽快发布
4. 修复发布后，我们将公开披露漏洞详情（如报告者同意）

## 安全最佳实践

- 不要在代码中硬编码 API 密钥或密码
- 使用 `.env` 文件管理敏感配置（已加入 `.gitignore`）
- 定期更新依赖项
- 生产环境使用强密码并启用 HTTPS

## 支持的版本

| 版本 | 支持状态 |
|------|---------|
| 1.0.x | 活跃支持 |

## 致谢

我们感谢所有负责任地报告安全漏洞的研究人员。经报告者同意，我们将在此列出致谢名单。
