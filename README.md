# 朝的创意

JaguarTV 的赛前静态海报工厂。它只产生 2048x2560 PNG 海报，不生成视频、不拼接视频、不上传视频。

每天的流程故意分成两段：机器先按现有赛前规则推荐赛事，你人工确认具体比赛后，才允许研究、生成和拼接海报。

## 一次配置

```bash
cd /Users/jaguar/Documents/ChatGPT/朝的创意
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp config/prematch.example.json config/local.json
```

在 `config/local.json` 对应的环境变量或 macOS Keychain 中配置赛事源、API-Football 和 Image2 凭据。配置文件不放密钥。

## 每日实际操作

1. 每日推荐。这个动作只写候选清单，绝不会做图：

```bash
scripts/task1_launcher.sh 1
```

候选清单在 `runs/YYYYMMDD_batch1/phase1/recommended-fixtures.json`。每一条都有 `fixture_id`、开球时间和推荐原因。

2. 人工挑选。直接写入要做的场次：

```bash
jaguartv-prematch select \
  --run-dir runs/YYYYMMDD_batch1 \
  --fixture-id fixture-a \
  --fixture-id fixture-b \
  --operator "JaguarTV"
```

也可以复制 [examples/selection-decisions.example.json](examples/selection-decisions.example.json)，填好后执行：

```bash
jaguartv-prematch select \
  --run-dir runs/YYYYMMDD_batch1 \
  --decisions examples/selection-decisions.example.json
```

`poster_styles` 可写 `fan_crowd`、`star_faceoff` 或 `auto`。`fan_crowd` 是以两队球迷、看台、旗帜和现场情绪为主；`star_faceoff` 是两队各一名已授权球星的正脸对峙。`auto` 会优先交替风格，但只有研究证据完整才会选择球星对峙。

3. 生产静态海报：

```bash
scripts/task1_launcher.sh 1 --stage produce --date YYYYMMDD
```

生产会依次核对研究证据、官方队徽、Image2 主/备路由，接着生成无文字背景，再把队徽、赛程、预测、频道图标和精确 JaguarTV Logo 拼成成品。最终 PNG 在 `deliveries/YYYYMMDD_batch1/`，完整记录在同名 `runs/` 目录。

## 本地演练

下列命令不调用赛事源或 Image2，可走完整的“推荐 → 人工选择 → 静态海报交付”路径：

```bash
jaguartv-prematch recommend \
  --config config/prematch.example.json \
  --run-dir runs/demo_batch1 \
  --fixtures-file examples/manual-fixtures.example.json \
  --date 20260906

jaguartv-prematch select \
  --run-dir runs/demo_batch1 \
  --fixture-id manual-20260906-santos-internacional

jaguartv-prematch produce \
  --config config/prematch.example.json \
  --run-dir runs/demo_batch1 \
  --dry-run
```

正式生产不用 `--dry-run`。如果球星对峙没有两队当前且授权的球员资料，流程会阻止强制球星海报；改为 `fan_crowd`，或补齐研究证据后重试。
