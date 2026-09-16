# ALS Global Intelligence

一个不依赖人工逐站登录的 ALS（Amyotrophic Lateral Sclerosis）公开信息监测系统。每天从 PubMed 与 ClinicalTrials.gov 收集新增论文和试验更新，经本地去重后生成响应式静态网页及 Email Daily Briefing。

第一阶段刻意不加入复杂 AI 摘要：页面只展示来源提供的结构化字段与原始摘要，并始终链接到官方记录。

## 当前能力

- PubMed：NCBI E-utilities（ESearch + EFetch XML），收集题名、作者、期刊、发表日期、PMID、DOI、链接和摘要。由于裸缩写 `ALS` 也可能代表其他术语，系统会再用 `sources.yaml` 中透明、可审计的疾病相关性规则过滤缩写误命中。
- ClinicalTrials.gov：官方 API v2，收集 NCT ID、题名、申办方、分期、招募状态、干预、开始日期和最后更新日期。
- 增量去重：论文按 PMID；试验按 `NCT ID + last update date`，因此试验的新版本仍会被推送。
- 可扩展来源：通用 RSS / Atom collector 已可用；没有 feed 的网站可按 adapter 模式后续接入。
- 故障隔离：每个来源单独捕获异常。一个来源失败时，其他来源仍继续处理，错误会写入 Actions 控制台与 `logs/als-intelligence.log`。
- 输出：`docs/index.html` 是可直接部署到 GitHub Pages 的静态页面，邮件只包含本轮新增内容。

## 项目结构

```text
sources.yaml                 # 数据源、查询、分类和运行参数
collector.py                 # 采集、解析、单源故障隔离、增量去重
generate_digest.py           # 生成网页和邮件正文
send_email.py                # 使用环境变量发送 SMTP 邮件
requirements.txt
data/
  articles.json              # 论文当前记录与本轮新增键
  trials.json                # 试验当前记录与本轮新增键
  news.json                  # RSS / website 新闻记录
  seen.json                  # 已处理事件键与各来源最近成功时间
docs/
  index.html                 # 自动生成的公开页面
.github/workflows/
  daily.yml                  # 北京时间 08:30 定时运行，也支持手动运行
```

仓库根目录已有的 `YYYY-MM-DD.md` 历史日报仍保留，不被新管线移动或覆盖。

## 本地安装和运行

需要 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python collector.py
python generate_digest.py
python send_email.py --dry-run
```

首次运行使用 `bootstrap_days` 回看窗口；后续运行使用较短的 `lookback_days` 重叠窗口，再由 `seen.json` 消除重复。重叠窗口可以容忍上游延迟收录和临时中断。

不要手工清空 `seen.json`，否则当前回看窗口内的内容会再次被判定为新增。如果需要重新生成网页但不想采集，单独运行 `python generate_digest.py`。

## GitHub Actions

工作流使用 cron `30 0 * * *`。GitHub Actions 的 cron 是 UTC，因此对应北京时间（Asia/Shanghai）每天 08:30。`workflow_dispatch` 可在仓库 Actions 页面手动触发。

工作流流程：

1. 安装固定范围内的 Python 依赖。
2. 独立采集每个已启用来源。
3. 生成 `docs/index.html` 与邮件正文。
4. 当 SMTP 必要 Secrets 已设置时发送邮件；未设置时明确跳过。
5. 邮件成功（或未配置邮件）后，仅提交四个持久化 JSON 文件与 `docs/index.html`。

如果已经配置 SMTP 但发送失败，工作流不会提交新的 `seen.json`，下次运行会重新尝试这些新增内容。这是“至少投递一次”策略；极少数“邮件已送达但网络响应丢失”的情况可能造成一次重复邮件，但不会静默漏报。

如需启用 GitHub Pages，在仓库 **Settings → Pages** 中选择 **Deploy from a branch**，分支选择 `main`、目录选择 `/docs`。

## GitHub Secrets 配置

在 **Settings → Secrets and variables → Actions → New repository secret** 中配置：

| Secret | 必需 | 示例 / 说明 |
|---|---:|---|
| `NCBI_EMAIL` | 建议 | NCBI 建议随 E-utilities 请求提供的联系邮箱 |
| `NCBI_API_KEY` | 否 | NCBI API key；不设置也可低速运行 |
| `SMTP_HOST` | 邮件必需 | 例如 `smtp.gmail.com` |
| `SMTP_PORT` | 否 | SSL 默认 `465`；STARTTLS 常用 `587` |
| `SMTP_USERNAME` | 视服务商 | SMTP 登录用户名 |
| `SMTP_PASSWORD` | 视服务商 | SMTP 密码或邮箱应用专用密码 |
| `SMTP_FROM` | 邮件必需 | 发件地址 |
| `SMTP_TO` | 邮件必需 | 一个或多个收件地址，逗号分隔 |
| `SMTP_USE_SSL` | 否 | 默认 `true` |
| `SMTP_USE_STARTTLS` | 否 | 默认 `false`；与 SSL 只能启用一个 |
| `SEND_EMPTY_DIGEST` | 否 | 默认不发送空日报；设为 `true` 可发送 |

所有凭据只从环境变量读取。不要把真实密码或 API key 写入 `sources.yaml`、Python 文件、Actions YAML 或提交历史。Gmail 等服务通常需要应用专用密码，而不是账户主密码。

## 增加 RSS / Atom 来源

在 `sources.yaml` 的 `sources` 列表加入：

```yaml
- id: organization_slug
  name: Organization Name
  type: rss
  enabled: true
  category: Organization News
  url: https://example.org/feed.xml
  max_entries: 30
```

`category` 应使用以下固定值之一：

- `Research`
- `Clinical Trials`
- `Drug Development`
- `Organization News`
- `Regulatory`

通用 RSS collector 使用 feed entry 的 ID、链接或标题构造稳定事件键。启用前应验证 feed 是机构官方入口、发布时间正确、且内容确实与 ALS/MND 有关。

## 增加 website adapter

ALS Association、MND Association、ALS TDI、NEALS、FDA 与 EMA 已作为禁用的 `website` 配置保留。网站页面结构比 API/RSS 更容易变化，所以第一阶段不做脆弱的通用 HTML 抓取。

接入新网站时：

1. 优先寻找官方 RSS、Atom、JSON API 或邮件归档；能用 RSS 时直接改为 `type: rss`。
2. 确实没有结构化入口时，在 `collector.py` 中实现一个返回统一记录字典的 adapter。
3. 为 adapter 注册独立 source type 或 adapter 名，并让每条记录包含稳定的 `id`、`event_key`、`title`、`url`、`published_date`、`category`。
4. 添加不访问网络的解析 fixture 测试。
5. 先保持 `enabled: false`，验证一周后再启用自动运行。

## 数据与去重规则

- `articles.json` 和 `trials.json` 保存每个实体的当前版本，避免页面无限出现同一实体的重复卡片。
- `seen.json` 保存已经推送过的事件版本。论文键为 `pubmed:<PMID>`；试验键为 `clinicaltrials:<NCT ID>:<last update date>`。
- `new_keys` 只代表最近一次 collector 运行的新项目，供网页标记与邮件筛选使用。
- JSON 采用临时文件写入后原子替换；先更新内容库，最后更新 `seen.json`，降低中断造成“记录已见但内容未保存”的风险。

## 历史日报

- [2026-09-15](2026-09-15.md)
- [2026-09-10](2026-09-10.md)
- [2026-09-09](2026-09-09.md)
- [2026-09-08](2026-09-08.md)
- [2026-09-05](2026-09-05.md)
- [2026-09-04](2026-09-04.md)
- [2026-09-03](2026-09-03.md)
- [2026-09-02](2026-09-02.md)
- [2026-09-01](2026-09-01.md)
