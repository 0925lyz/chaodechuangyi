# 赛前静态海报每日流程

工作目录：`/Users/jaguar/Documents/ChatGPT/朝的创意`。

## 1. 定时推荐，等待人工确认

每日定时任务只执行：

```bash
scripts/task1_launcher.sh 1
```

默认目标是巴西利亚时间的明天。需要当天时加 `--date today`；需要指定日期时加 `--date YYYYMMDD`。输出为 `runs/YYYYMMDD_batch1/phase1/recommended-fixtures.json`。

脚本完成后状态一定是 `WAITING_FOR_MANUAL_SELECTION`，不是失败，也不是遗漏生产步骤。它代表系统正在等你挑比赛。

## 2. 你确认做哪些比赛

打开推荐文件，复制想做的 `fixture_id`。例如：

```bash
jaguartv-prematch select \
  --run-dir runs/20261026_batch1 \
  --fixture-id fixture-1001 \
  --fixture-id fixture-1002 \
  --operator "JaguarTV"
```

选择记录可指定画面：

```json
{
  "selected_fixture_ids": ["fixture-1001", "fixture-1002"],
  "poster_styles": {
    "fixture-1001": "fan_crowd",
    "fixture-1002": "star_faceoff"
  }
}
```

未指定的比赛使用 `auto`。选择文件只允许出现当天的推荐比赛，防止手误混入错误赛程。

## 3. 生产和交付 PNG

```bash
scripts/task1_launcher.sh 1 --stage produce --date 20261026
```

生产会停在以下任一问题上：研究资料不完整、球星风格缺少两队授权球员资料、官方队徽缺失、Image2 主/备路由都失败，或 PNG 质检不通过。

成功后，使用 `deliveries/20261026_batch1/` 内的 PNG。`runs/20261026_batch1/` 是完整审计记录，保留推荐、人工选择、研究、提示词、路由尝试、拼接信息和质检结果。

## 4. 定时任务示例

系统调度器只需要运行推荐阶段。下面是一条可直接给 cron 的示例，时间按机器本地时区解释：

```cron
0 9 * * * cd /Users/jaguar/Documents/ChatGPT/朝的创意 && scripts/task1_launcher.sh 1
```

人工选择之后，生产命令必须由操作员显式执行；定时任务不能跳过这道门。
