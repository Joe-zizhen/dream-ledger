# dream-ledger — 实验账本：Dream-RSI 思想的本地最小落地

> 灵感来自 [Dream-RSI（arXiv:2609.14858）](https://arxiv.org/abs/2609.14858)：「你不需要一个神级世界模型才能做反事实模拟；你过去走过的所有弯路与踏平的坑，本身就是最精确的离线宇宙。」
>
> 本仓库是这条思想的第一步：**先把每一次探索性尝试结构化地记下来、自动打分、自动判断什么时候历史稠密到可以做「梦」**。回放模拟器和做梦层（路线图的③④）不是忘了做——它们被刻意放在闸门之后，原因见下文。

- **宿主无关**：任何 agent（Kimi Code / Claude Code / Codex）或人，都通过 shell 调用同一个 CLI；
- **跨项目通用**：账本在全局数据家（`~/.replay/`，`REPLAY_HOME` 可覆盖），不按项目分库；记录按「任务原型」匹配，跨项目积累；
- **零依赖**：单文件 Python 3，拷到任何机器就能跑。

## 安装

```bash
git clone https://github.com/Joe-zizhen/dream-ledger.git
cd dream-ledger
python replay.py init
```

需要 Python 3.8+，无第三方依赖。

## 快速开始（三分钟）

```bash
# 1. 登记一个自动打分器：跑什么命令、怎么抠分、哪个方向是好
python replay.py eval-set perf-opt --run "python examples/bench_target.py" \
    --score-regex "elapsed_ms: (\d+)" --better lower

# 2. 每次尝试后自动跑分并入账（分数、耗时、死因全自动）
python replay.py eval --archetype perf-opt --task "优化素数计数" --approach "naive 试除"

# 3. 动手前先回放：历史上最近似的尝试、成本、死因
python replay.py board perf-opt

# 4. 看看哪个原型的历史稠密到可以「进化」
python replay.py gate
```

## 命令

| 命令 | 作用 |
| --- | --- |
| `init` | 建账本家（`~/.replay/`） |
| `log` | 手动入账一条尝试（任务/原型/做法/结局/分数/成本/死因/证据） |
| `query <词...>` | 全文检索账本 |
| `board [词...]` | 回放表：动手前看最近似的 N 次尝试与成败统计 |
| `stats` | 账本规模（按原型/项目） |
| `gate` | 进化闸门：按原型检查覆盖度（尝试≥8、不同做法≥2、带分数≥4），达标=值得建做梦层 |
| `eval-set` | 给任务原型登记自动打分器（机制通用，配置专属） |
| `eval` | 全自动评估：跑打分器 → 抠分数 → 量耗时 → 自动入账 |
| `evals` | 列出已登记打分器 |

**检测是全自动的**：每次入账会当场检查该原型的覆盖度，达标即提示【可进化】——不需要任何人记得去跑 `gate`。

## 评估器配置（机制通用，打分器按原型专属）

`eval-set` 把配置写进 `~/.replay/evaluators.json`：

```json
{
  "perf-opt": {"run": "python examples/bench_target.py", "better": "lower", "timeout": 600, "score_regex": "elapsed_ms: (\\d+)"},
  "unit-test": {"run": "pytest -q", "better": "higher", "score_regex": "(\\d+) passed"}
}
```

抠分方式四选一：`--score-regex`（正则第一捕获组）、`--score-mode exitcode`（退出码 0/1）、`--score-mode elapsed`（命令耗时）、`--score-mode filesize:路径`（产物体积）。

**安全边界**：`eval` 会执行配置里的命令——配置文件只能由你自己写，接受他人配置前先看内容。

## 四层路线图（以及为什么③④不在包里）

| 层 | 状态 |
| --- | --- |
| ① 实验账本 | ✅ 已实现 |
| ② 评估器层（通用机制 + 原型专属配置，全自动入账） | ✅ 已实现 |
| ③ 回放模拟器（答「当时换策略会怎样」+ 置信度） | ⛔ 未实现——等闸门 |
| ④ 做梦层（离线策略搜索与部署） | ⛔ 未实现——等闸门 |

设计原则：**回放模拟器只能回答历史覆盖到的反事实**。Dream-RSI 敢做梦，是因为先有数万次在线探索攒下的稠密历史；覆盖不足时建的「进化」是追噪声。所以本框架把「什么时候值得建③④」做成可执行闸门（`gate` 命令 + 入账自动检测），而不是预装一个对着想象数据设计的模拟器。③④到来时会以垂直场景优先：第一个满格的原型先拥有做梦层。

## 多机器部署与数据汇总

每台机器独立积累自己的 `~/.replay/ledger.jsonl`。账本是 append-only JSONL，**合并多台机器的数据就是 `cat` 若干账本到一起**（ID 为随机片段，冲突概率可忽略）。

## 可选组件：宿主纪律 skill

`skill/replay/SKILL.md` 是给 agent 宿主的「回放优先」纪律：探索性/昂贵动作前先交回放表、动作后必入账、无历史明说不编造。拷进宿主 skills 目录（`~/.agents/skills/` 或 `~/.claude/skills/`）后重启宿主生效。它不是必需的——CLI 本身完整可用。

## 诚实边界

- ③④层未实现，且不会在覆盖不足时被实现——这不是缺陷，是设计；
- LLM 评委类软评估器的分数，结论按方向性对待（盲评噪声见 SKILL.md 说明）；
- 账本是历史不是预言：条件（版本/环境/规模）变了，旧记录的适用性要重新声明。

## License

MIT © 2026 Joe-zizhen
