# AstrBot 青龙面板管理插件 v1.5.0

通过 AstrBot 管理青龙面板的环境变量和定时任务，支持任务执行日志自动推送和定时推送。

## 主要功能

### v1.4.0 新增：群内自动保存/更新 Cookie

用户在群里直接发送 Cookie（如 `pt_key=xxx;pt_pin=xxx`），插件自动将其保存到青龙面板的环境变量中；同一用户再次发送时，自动更新其上次保存的变量，不会重复新增。

**特性：**
- ✅ **自动识别，无需命令**：消息中包含 `key=value;key=value` 格式的文本即自动识别（可配置正则）
- ✅ **每个用户独立变量**：按发送者区分，如 `JD_COOKIE_张三`、`JD_COOKIE_李四`
- ✅ **同一账号自动更新**：同一账号再次发送 Cookie 时，更新其原有变量而非新增
- ✅ **同一人可挂多个账号**：按京东账号标识（pt_pin）区分，多账号各自独立、互不覆盖；再次登录同一账号时只更新该账号
- ✅ **防误触发**：默认要求至少 2 组键值对，普通聊天消息不会被误识别
- ✅ **隐私保护**：保存成功后在群内回复只显示掩码值（如 `pt_key=abcd***(8位)`），不暴露完整 Cookie
- ✅ **群白名单**：可配置仅允许指定群号自动保存
- ✅ **管理命令**：`/ql cookie status` 查看状态、`/ql cookie list` 查看已保存变量（含京东账号）

**使用方式：**
1. 群成员直接发送 Cookie 文本即可，例如：
   ```
   pt_key=AAABBBCCC;pt_pin=user123
   ```
   或者带说明文字：`我的cookie：pt_key=AAABBBCCC;pt_pin=user123`
2. 插件自动保存到青龙环境变量 `JD_COOKIE_昵称`（前缀可在配置中修改），并在群内回复确认
3. 同一账号再次发送新 Cookie 时，自动更新原变量；同一人登录不同京东账号时，自动新建独立变量（`JD_COOKIE_昵称_2`…），互不覆盖

**管理命令：**
- `/ql cookie status` - 查看自动保存状态与配置
- `/ql cookie list` - 查看已保存的 Cookie 变量（值以掩码显示）
- `/ql cookie enable` - 启用自动保存
- `/ql cookie disable` - 禁用自动保存

**配置项（插件配置中设置）：**
| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| cookie_auto_enabled | true | 是否启用群内自动识别并保存Cookie |
| cookie_env_prefix | JD_COOKIE | 环境变量名前缀，变量名为 前缀_昵称 |
| cookie_enabled_groups | [] | 允许自动保存的群号列表，留空表示所有群 |
| cookie_match_regex | 默认正则 | Cookie识别正则（需匹配 key=value;key=value 形式） |
| cookie_min_pairs | 2 | 识别为Cookie所需的最少键值对数量 |
| cookie_reply_enabled | true | 保存/更新成功后是否在群内回复提示 |

**注意：** Cookie 属于敏感凭证，请勿在群内公开传播；本功能仅将 Cookie 保存到你自己的青龙面板。

### v1.4.0 新增：京东短信验证码登录（自动更新 Cookie）

群友在群里发送手机号，插件下发短信验证码；群友把收到的验证码发到群里，插件自动完成登录并把新 Cookie 保存/更新到该用户的青龙环境变量。

**使用流程：**
1. 群友在群里发送「登录」两个字，开始登录流程（**注意**：AstrBot 群聊默认需要唤醒机器人，建议 @机器人 + 登录，如 `@机器人 登录`；或在 AstrBot 配置的「唤醒前缀 wake_prefix」中加入 `登录`，即可直接发「登录」触发）
2. 插件引导后，群友发送京东绑定手机号：`13800138000`
3. 手机收到京东短信验证码后，把验证码发到群里：`123456`
4. 登录成功，插件自动保存/更新该用户的京东 Cookie（变量名与 Cookie 自动保存相同，如 `JD_COOKIE_昵称`）

**管理命令：**
- `/ql sms status` - 查看短信登录状态（含打码平台配置状态）
- `/ql sms enable` - 启用
- `/ql sms disable` - 禁用

**安全与防滥用设计：**
- 必须先发送「登录」触发流程，未触发时直接发手机号不会被处理（防止对任意手机号发码）
- 同一手机号/同一发送者默认 60 秒限频（可配置），防止被用作短信轰炸
- 验证码必须由发起登录的同一用户回传，他人无法冒用
- 验证码流程 5 分钟有效（可配置）
- 群内回复不暴露完整手机号（显示 `138****8000`）和完整 Cookie（显示掩码）
- 每个用户独立浏览器登录会话，多账号互不串号

### v1.5.0 新增：真实浏览器自动破解验证码（重点）

京东短信登录已启用强风控：纯 HTTP 调用发码接口会被 403 拦截，且必须通过旋转/轨迹类验证码。v1.5.0 起，插件内置 **Playwright 真实 Chromium** 完成登录：

```
发送手机号 → 自动打开京东登录页 → 输入手机号 → 自动破解验证码
（旋转/轨迹题提交打码平台识别 → 模拟人类拖动/绘制）→ 京东发码
→ 用户回传验证码 → 自动登录 → 提取 Cookie → 保存/更新到青龙
```

**部署前提（一次性）：**
1. **安装浏览器依赖**：插件首次使用登录功能时自动下载 Chromium（约 130MB）；如遇系统依赖缺失，在服务器上执行（需 root）：
   ```bash
   python -m playwright install-deps chromium
   ```
2. **注册打码平台**（免费送测试点数）：https://www.ttshitu.com ，注册后在插件配置中填写 `jd_captcha_username` / `jd_captcha_password`。每次识别约几分钱，验证码识别失败会自动刷新换题重试。

**新增配置项（插件配置中设置）：**
| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| jd_browser_enabled | true | 是否启用浏览器登录助手 |
| jd_browser_headless | true | 无头模式运行 Chromium |
| jd_browser_auto_install | true | 首次使用自动下载 Chromium |
| jd_browser_max_concurrent | 1 | 同时登录会话数（每会话占 200-400MB 内存） |
| jd_browser_max_retry | 4 | 验证码破解失败换题重试次数 |
| jd_browser_rotate_px_per_deg | 1.0 | 旋转验证码拖动像素/角度系数 |
| jd_browser_rotate_direction | 1 | 旋转验证码拖动方向（1/-1） |
| jd_captcha_username / jd_captcha_password | 空 | 图鉴打码平台账号密码 |
| jd_captcha_api_url | api.ttshitu.com/predict | 打码平台接口地址 |
| jd_captcha_rotate_typeid | 29 | 旋转题识别类型 |
| jd_captcha_track_typeid | 48 | 轨迹题识别类型 |
| jd_captcha_gap_typeid | 33 | 缺口题识别类型 |

**接口说明：** 旧版纯 HTTP 发码接口（sendCode/checkCode/getCookie）仍保留为回退路径（`jd_browser_enabled=false` 时使用），但京东已风控，一般不再生效。

**注意：** 请遵守京东用户协议，仅用于本人账号的 Cookie 管理；验证码识别为打码平台提供的通用图像识别服务。

## 支持的配置格式

### 群组配置（支持多种格式）：
- **纯数字格式**: `123456789` → 自动转换为 `aiocqhttp:GroupMessage:123456789`
- **简写格式**: `default:GroupMessage:123456789` → 保持原样
- **完整格式**: `CoCo机器人:GroupMessage:123456789` → 保持原样

### 好友配置（支持多种格式）：
- **纯数字格式**: `123456789` → 自动转换为 `aiocqhttp:FriendMessage:123456789`
- **简写格式**: `default:FriendMessage:123456789` → 保持原样
- **完整格式**: `CoCo机器人:FriendMessage:123456789` → 保持原样

## 使用步骤

### 1. 清理现有配置
由于您的配置中可能有空值，请先清理：
/ql schedule remove friend # 移除空的好友配置

### 2. 重新添加配置（使用简单格式）
添加群组（使用纯数字格式）
/ql schedule add group "群号"

添加好友（使用纯数字格式）
/ql schedule add friend "好友QQ号"

### 3. 测试推送
/ql schedule push

## 功能总览

- ✅ 环境变量管理（查看、添加、更新、删除、启用、禁用）
- ✅ 定时任务管理（查看、执行、停止、启用、禁用、置顶、删除、日志）
- ✅ 系统信息查询
- ✅ 分页显示，支持搜索
- ✅ **定时任务执行日志自动推送（实时推送）**
- ✅ **定时推送所有运行日志（定时推送）**
- ✅ **推送后询问是否推送错误日志**
- ✅ **自定义显示数量**
- ✅ **完整错误日志显示**
- ✅ **群内自动保存/更新 Cookie（v1.4.0 新增）**
- ✅ **京东短信验证码登录（v1.4.0 新增）**
- ✅ **真实浏览器自动破解验证码（v1.5.0 新增：Playwright + 打码平台）**

## 命令大全

### 基础命令
/ql - 查看帮助
/ql ls - 查看任务列表
/ql run <任务ID> - 执行任务
/ql log <任务ID> - 查看日志

### 定时推送配置
/ql schedule status - 查看状态
/ql schedule add group <群号> - 添加推送群（支持多种格式）
/ql schedule add friend <QQ号> - 添加推送好友（支持多种格式）
/ql schedule count <数量> - 设置显示任务数量
/ql schedule errors <行数> - 设置错误日志显示行数
/ql schedule push - 手动推送

### Cookie 自动保存配置
/ql cookie status - 查看状态
/ql cookie list - 查看已保存的Cookie变量
/ql cookie enable - 启用自动保存
/ql cookie disable - 禁用自动保存

### 京东短信登录配置
/ql sms status - 查看状态
/ql sms enable - 启用短信验证码登录
/ql sms disable - 禁用短信验证码登录

## 新增功能说明

### 推送后询问错误日志
当定时推送检测到有错误任务时：
1. 先推送汇总消息
2. 然后发送询问消息："是否推送错误日志详情？"
3. 等待30秒，期间接收用户回复
4. 如果回复"是"/"需要"/"推送错误日志"，则推送错误日志详情
5. 如果回复"否"/"不需要"/"取消"，或30秒内无回复，则不推送

### 支持的回复杂命令
- **确认推送**: 是、需要、推送错误日志、推送、发送、yes、y、确认
- **取消推送**: 否、不需要、取消、不推送、no、n、取消推送

## 常见问题

### Q: 配置时报"目标格式无效"错误怎么办？
A: 使用最简单的纯数字格式，插件会自动转换。

### Q: 推送成功但QQ群收不到消息？
A: 检查：
1. 机器人是否在目标群中
2. 机器人是否被禁言
3. 使用 `/send aiocqhttp:GroupMessage:"测试群号" 测试` 测试发送

### Q: 如何查看详细的错误日志？
A: 设置错误日志显示为完整：
/ql schedule errors 0

### Q: 定时推送后询问错误日志，如何确认？
A: 在30秒内回复：
- 确认: "是"、"需要"、"推送错误日志"
- 取消: "否"、"不需要"、"取消"

## 更新日志

### v1.4.0 (2026-10-08)
- 新增: 群内自动识别 Cookie 并保存到青龙环境变量
- 新增: 每个用户独立环境变量，同一用户再次发送自动更新
- 新增: Cookie 掩码显示，群内回复不暴露完整值
- 新增: 防误触发机制（默认最少 2 组键值对）
- 新增: /ql cookie 管理命令（status/list/enable/disable）
- 新增: 群白名单、识别正则等配置项
- 新增: 京东短信验证码登录（手机号→验证码→自动更新Cookie）
- 新增: 短信登录限频防滥用、会话超时、手机号掩码
- 新增: /ql sms 管理命令（status/enable/disable）
- 新增: 京东接口地址与参数可配置（便于风控变化时校准）
- 新增: 同一人多账号支持（按 pt_pin 区分，同账号再登自动更新，多账号互不覆盖）
- 新增: /ql cookie list 显示京东账号标识（pt_pin）
- 优化: 短信登录改为先发送「登录」触发流程，未触发不发码

### v1.3.3 (2024-01-03)
- 新增: 定时推送后询问是否推送错误日志详情
- 新增: 30秒等待确认机制
- 新增: 智能确认和取消识别
- 优化: 错误日志详情格式化

### v1.3.2 (2024-01-01)
- 修复: 目标格式自动转换问题
- 修复: 配置空值清理问题
- 新增: 多种配置格式支持
- 优化: 错误处理和日志记录

## 许可

MIT License

使用方法
1.清理现有配置：
/ql schedule status  # 查看当前配置
/ql schedule remove friend   # 移除空的好友配置（如果存在）
2.重新配置（使用简单格式）：
# 添加群组
/ql schedule add group 123456789

# 添加好友
/ql schedule add friend 123456789

# 设置显示20个任务
/ql schedule count 20

# 设置完整错误日志
/ql schedule errors 0
3.测试：
/ql schedule push  # 手动测试推送
/ql schedule status  # 查看配置状态