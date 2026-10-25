# 静态海报架构

`朝的创意` 是一条可追溯的静态赛前海报链路。它不包含动态生成、音频、视频合成或视频上传。

```text
赛事源 + API-Football
        |
        v
phase1/recommended-fixtures.json
        |
        | 人工确认 fixture_id 和可选风格
        v
phase1/selected-fixtures.json
        |
        v
phase2/当前研究证据
        |
        v
Image2 无文字背景 + 官方队徽 + 固定 Logo + pt-BR 信息层
        |
        v
phase3/posters/*.png --> phase4 PNG QA --> deliveries/<run>/
```

## 阶段边界

1. `recommend`：按当前的 Brasileirão、目标赛事、目标俱乐部、巴西球员和成年男子国家队规则排列候选比赛。它只写候选清单。
2. `select`：只接受候选清单内的 `fixture_id`。这一步写入人工决策和单场的 `poster_style`，并解锁后续阶段。
3. `phase2`：每场必须有当前研究资料。非演练状态不能用占位数据。
4. `phase3`：Image2 只画没有文字、没有 Logo、没有队徽的 4:5 背景。确定性拼接器生成最后的 2048x2560 PNG。
5. `phase4`：验证画布、Logo、队徽和内容边界，复制合格 PNG 到 `deliveries/`。

## 两种画面

- `fan_crowd`：两队看台与球迷情绪是画面主角；球员不能成为主视觉。
- `star_faceoff`：左右各一名已授权、当前效力的球星正脸。研究记录中必须有两队各一条带 `license_record` 的 `poster_assets`；缺一条就不能强制做该风格。

`auto` 在合格资料足够时交替两种画面，避免每日都像同一张模板。

## 不可绕过的规则

- 没有人工选择，不生成海报。
- 没有两枚经过验证的官方队徽，不生成海报。
- Logo 只能使用项目内精确 Figure 1 文件，最终海报仅出现一次。
- 主 Image2 路由失败时才尝试已配置的 APIMart 备用路由，并将两次尝试写入 manifest。
