# 健康饮食面板

[English](README.en.md) · [项目操作约定](SKILL.md)

本机优先的饮食记录、营养估算和历史查看工具，采用 FastAPI + SQLite + React。此仓库是**空白软件模板**：不含个人资料、实际餐食、体重记录、私人图片、个人目标、账号凭据或线上部署。

界面主要为中文；英文 README 不代表界面已完整英文化。

## 能做什么，不能做什么

- 保存自己的身体资料、饮食偏好、餐食、食品标签及带来源的结构化分析；查看历史与版本。
- 区分真实摄入、候选菜单、菜式参考和食品营养资料。通用食物成分不是任何人的已吃记录。
- 按已保存资料计算或展示营养估算，校验结构化候选方案，并保留来源和审计。内置菜单生成仅支持有限的通用菜式模板，不是通用智能配餐；其他菜式需要操作者提供并校验结构化候选。
- **不包含 AI 模型、图片识别服务、聊天机器人连接器或内部定时器。** 上传图片不等于识别完成；界面中有关分析的入口不代表开箱即用的自动分析。
- 没有预装的每日任务。配置中的 07:00 是规则时间，不会自动唤醒程序执行。
- 空白或未记录日期表示“缺少记录”，不是零摄入、漏餐或禁食。
- 这是个人记录工具，不作医疗诊断或处方。估算值、目标和评分不等于精确测量或医学结论。

## 空白历史页面

以下为使用全新空数据目录运行应用后截取的历史页面，不含个人餐食、体重或评分记录。

![全新安装的空白历史页面](docs/images/history-empty.jpg)

## 从零启动

### 1. 准备环境

需要 Python 3.11+、Node.js 22.12+、npm 和 Git。建议 Linux；macOS 可使用同一套命令，但应自行验证环境。CLI 使用 Unix 的 `fcntl` 文件锁，原生 Windows 不支持，Windows 请使用 WSL/Linux。系统须有 `Asia/Shanghai` 时区数据。

克隆本仓库后，进入其根目录。首次安装需要访问 Python 与 npm 软件包仓库：

```bash
bash scripts/setup.sh
bash scripts/start.sh
```

安装脚本建立 `.venv` 并安装依赖、构建前端。`requirements.lock` 锁定完整 Python 依赖版本，npm 使用 `package-lock.json`。等价的手工安装步骤：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
npm --prefix apps/web ci
npm --prefix apps/web run build
bash scripts/start.sh
```

浏览器打开 **http://127.0.0.1:8765/diet/health**。保持终端运行，使用 Ctrl+C 停止服务。数据库及目录会在首次启动时创建，无需导入他人的数据或手工执行迁移。

### 2. 建立自己的资料

1. 在“个人资料与喜好”中填写自己的资料与目标方向。使用真实测量日期；不知道的字段留空，不照抄示例值。
2. 添加自己的饮食偏好、忌口和活动信息。尚无完整资料时，目标或建议可能保持待补充，这是正常状态。
3. 要记录餐食，使用本地 API 或下面的 CLI 结构化导入。照片可以作为附件，但营养分析必须由你或你明确接入的工具提供，再经本地校验写入。
4. 明确设定每日营养目标时使用 `target-set`；不运行它也不会自动导入一套个人默认目标。缺失目标不能随意编造。

默认不启用菜式种子（`recipe_seed: "none"`）。如启用随仓库提供的可选通用菜式，它们只提供候选搭配，不代表偏好、真实摄入或个体营养目标。

### 3. 确认运行状态

在另一个终端、同一仓库目录运行：

```bash
.venv/bin/python scripts/diet_cli.py health
.venv/bin/python scripts/diet_cli.py overview
.venv/bin/python scripts/diet_cli.py targets
```

CLI 在进程内调用本地应用，不需要额外开启网络监听。`health` 中 worker/provider 不在线不意味着数据库故障：本项目没有后台 AI worker 或调度服务。

## 存储模式与隐私边界

默认数据根目录为仓库下 `data/`，可通过 `config.json` 的 `data_root` 或环境变量 `PDP_DATA_ROOT` 改到仓库外。环境变量优先；请对启动和 CLI 使用同一个绝对路径：

```bash
export PDP_DATA_ROOT="$HOME/.local/share/healthy-eating"
bash scripts/start.sh
# 在其他终端也设置同一个变量，或者使用 CLI 的 --data-root。
.venv/bin/python scripts/diet_cli.py --data-root "$HOME/.local/share/healthy-eating" overview
```

- `DATA/database/platform.sqlite3`：权威数据源。保存记录、分析、目标版本、设置、审计和运行状态；SQLite 使用 WAL，运行时可能有 `-wal`/`-shm` 文件。
- `DATA/assets/`：本地上传的图片等文件；数据库保存其引用和校验信息。
- `DATA/reference_materials/`、`DATA/planning_audits/`：使用相关功能后产生的私人参考资料和规划审计。
- `DATA/exports/`、`DATA/backups/`、`DATA/runtime/`、`DATA/agent-work/`：导出及运行辅助目录，不是第二套权威数据库。
- `apps/api/app/data/` 是软件自带的通用参考资料，与私人 `DATA` 不是同一目录。
- 浏览器本地存储主要用于展示偏好；清空浏览器缓存不会代替清除服务器数据。

这些本地文件**没有应用层静态加密**。依靠操作系统账号权限、磁盘加密和安全备份保护它们。Git 忽略规则只是防误提交措施，不是访问控制。修改数据目录后也须确保新位置不进入 Git。

默认仅本机访问，不是可直接公开部署的多用户服务。不要将监听地址改为公网、配置穿透或上传私人数据来“同步”。

### 可选快照导出，不是云同步

`mirror_transport` 默认 `disabled`。本仓库所有镜像兼容接口只返回“已禁用”状态，不会生成快照或向外部服务器推送数据；本地快照须显式运行独立导出器。原环境的专有连接器不随仓库提供，也不会因为安装本项目而自动出现。

独立只读导出器的参数见：

```bash
.venv/bin/python scripts/diet_mirror_export.py --help
.venv/bin/python scripts/diet_cli.py mirror-status
```

导出的快照即使去掉了部分标识符，仍可能含私人健康信息；不要提交到 Git 或公开托管。快照不是完整备份。

## CLI 与结构化操作

以实际 `--help`、Pydantic 模型和当前返回的版本为准，不手工猜测记录 ID、版本号或幂等键：

```bash
.venv/bin/python scripts/diet_cli.py --help
.venv/bin/python scripts/diet_cli.py ingest --help
.venv/bin/python scripts/diet_cli.py analysis --help
.venv/bin/python scripts/diet_cli.py target-set --help
```

主要命令：

- 读取：`health`、`overview`、`targets`、`target-review-status`、`target-review-context`。
- 实际记录：`ingest --input <JSON文件>`；之后使用 `analysis --meal-id <记录ID> --input <JSON文件>` 写入分析。
- 食品标签：`food-match`、`food-save`、`food-versions`、`food-calculate`。保存标签、计算份量不等于记录已吃。
- 目标：`target-set --input <JSON文件>`，以及显式目标复核命令 `target-review-enable`、`target-review-commit`。
- 菜单：`planning-context --date YYYY-MM-DD`、`plan-preview --date YYYY-MM-DD`、`validate-plan --input <JSON文件>`、`publish-candidate --input <JSON文件>`、`revise-remaining --input <JSON文件>`。
- 结算：`settle --date YYYY-MM-DD` 受 07:00 规则及证据条件约束，不是定时器，也不保证空资料可生成菜单或评分；`--score-only` 已弃用并会拒绝执行。

`ingest` 的顶层字段是 `channel`、`message_id`、`images`、`meal`，可选 `analysis`。`images` 使用本机绝对路径，`meal` 遵循 `apps/api/app/schemas.py` 的 `Meal` 模型，时间必须带时区。相同 channel/message_id 幂等，不应拿同一个键冒充一餐新的内容。

独立 `analysis` 使用 `apps/api/app/external_api.py` 的 `AnalysisWrite` 完整信封，包含当前版本、图片引用及哈希、幂等键和 `MealVisionOutput`。`target-set` 遵循 `apps/api/app/diet_targets.py` 的 `TargetWrite`。没有证据的数据应保持未知，不填零来通过校验。

CLI 输出 JSON；常规错误退出码为 2，冲突为 3。遇到冲突先重读当前数据再处理，不盲目重试写入。

### 可选：在隔离目录试一次结构化导入

以下是完全虚构的测试餐，不是推荐食物或真实历史。只有你执行命令时才会写入新建的临时数据目录，不会写入平常使用的资料库。示例故意不填营养数值；记录成功不代表分析完成。实际使用时应换成真实已吃内容、正确日期及独立消息标识。

```bash
DEMO_ROOT="$(mktemp -d)"
cat > "$DEMO_ROOT/meal.json" <<'JSON'
{
  "channel": "local-demo",
  "message_id": "synthetic-example-001",
  "images": [],
  "meal": {
    "eaten_at": "2030-01-01T12:00:00+08:00",
    "diet_date": "2030-01-01",
    "meal_type": "午餐",
    "title": "Synthetic demonstration meal",
    "notes": "Fictional test only; no nutrition or portion evidence.",
    "status": "pending"
  }
}
JSON
.venv/bin/python scripts/diet_cli.py --data-root "$DEMO_ROOT/data" ingest --input "$DEMO_ROOT/meal.json"
.venv/bin/python scripts/diet_cli.py --data-root "$DEMO_ROOT/data" overview
```

测试结束后可自行删除该临时目录；不要把它设成正式服务的数据根目录。本地交互式 API 文档位于 http://127.0.0.1:8765/api/docs 。

## 日期、评分与自动化限制

- 饮食日固定采用 **Asia/Shanghai 07:00 至次日 07:00**；明确指定的记录日期优先，旧记录归属不应随意重写。
- 不是通用时区产品。仅修改 `config.json` 的 timezone 不会迁移饮食日、发布和评分规则。
- 正式发布和前一完整饮食日的结算遵守 07:00 规则。同日正式结果复用；预览不自动变成正式菜单；实际摄入与计划始终分开。
- 若自行接入外部调度器或分析工具，需要独立实现、测试并授权。项目本身不会定时运行，也不会自动调用模型。
- 评分采用固定 **100 分**分母，不把缺失项重新归一化。显示颜色为 **≥85 绿、≥70 黄、其余红**；无有效评分显示未知，不应伪造 0 分。
- 合理估算会保留范围、来源及估算标记。分数用于目标遵循和饮食结构参考，不表示疾病风险或医学合格线。

## 备份与恢复

不要只复制正在使用的 SQLite 主文件。使用 CLI 一致性备份，保留数据库、数据库引用的附件、参考资料和规划审计，并生成校验清单。源代码不包含在备份内，必须另存匹配的代码版本；恢复会校验相应源码文件哈希，包括配置、策略和 SKILL。

```bash
mkdir -p "$HOME/healthy-eating-backups"
.venv/bin/python scripts/diet_cli.py backup --output "$HOME/healthy-eating-backups/snapshot-001"
.venv/bin/python scripts/diet_cli.py restore --input "$HOME/healthy-eating-backups/snapshot-001" --target "$HOME/healthy-eating-restored"
```

备份输出和恢复目标必须是**尚不存在**的目录，父目录须存在。恢复完成后停止旧服务，将 `PDP_DATA_ROOT` 指向恢复目录，重新启动并核对 `overview` 和附件。以上名称只是路径示例，不含个人数据。

完整恢复需要“数据备份 + 匹配源码/配置”，不是一个页面截图或快照。备份可能包含被保留的历史版本和审计，仍属敏感数据；不要上传 GitHub。软件包升级前先备份并做恢复演练。

## 哪几个 Skill？

仓库只包含 **一个项目自有 Skill：[`SKILL.md`](SKILL.md)**。它描述资料收集、证据分类、分析写回、候选校验和发布的操作约定。程序会读取并计算其哈希，以绑定策略版本。

它是普通 Markdown 工作流程，不是安装后自动运行的智能体，不提供模型、任务调度、账号权限或外部连接。无需安装其他助手内部 Skill；本仓库不分发此类内容。结构化策略在 `apps/api/app/diet_policy.json`，它是软件规则文件，不是第二个 Skill。

## 开发与排错

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/audit_distribution.py
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
```

- 页面提示前端未构建：运行 build 后重启/刷新。
- 端口冲突：停止占用程序，或设置 `PDP_PORT` 后重启，使用相应端口访问。
- 图片显示但没有分析：这是预期限制，先提供有效的结构化分析，不要寻找不存在的模型密钥开关。
- 没有菜单/目标/评分：先检查资料和证据是否完整，再检查目标日期和发布条件。
- 恢复报告源码不匹配：切回备份对应的代码和配置，不要绕过完整性校验。

目前未选择开源许可证。公开可查看不等于已授予任意复制、修改或再分发许可；第三方依赖遵守各自许可证。

