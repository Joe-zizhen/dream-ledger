#!/usr/bin/env python3
"""replay — 探索尝试的实验账本（Dream-RSI 思想的最小落地：历史即模拟器，账本先行）。

宿主无关：任何 agent 经 shell 调用。数据存在全局数据家（默认 ~/.replay/，
环境变量 REPLAY_HOME 可覆盖），不按项目分库；项目只是记录里的一个字段。

扁平记录与发现树共存：不加树字段的记录照旧扁平（服务小循环回放表）；
探索型任务可 tree-begin 开树、tree-add 挂节点，攒出的树形历史直接服务③④层
（图纸：docs/dream-layer-design.md）。

用法：
  python replay.py init
  python replay.py log --task "..." --archetype "..." --outcome success|fail|mixed [选项] [--rollout R --parent N]
  python replay.py query <关键词...>
  python replay.py board [关键词...]     # 回放表：动手前先看历史上最近似的尝试
  python replay.py stats
  python replay.py gate                  # 进化闸门：扁平覆盖 / 树形带分数两级判定
  python replay.py eval-set <原型> --run "命令" [--score-regex "正则" | --score-mode exitcode|elapsed|filesize:路径] --better higher|lower
  python replay.py eval --archetype <原型> --task "..." [--approach "..."]   # 自动跑分并入账
  python replay.py evals
  python replay.py tree-begin --archetype "..." --task "..."               # 开一棵发现树（rollout）
  python replay.py tree-add --rollout R --archetype "..." --task "..." [--parent N]  # 挂节点，有评估器则自动跑分
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

# 做梦层开火闸门：覆盖度不够时进化 = 追噪声。阈值是合同不是物理——被实测推翻就改。
GATE = {"attempts": 8, "approaches": 2, "scored": 4}
# 做梦的门槛（论文 t=1 即可做梦，本地取保守值）：树形且带分数的记录数。
TREE_GATE = 4
DESIGN_DOC = "dream-ledger 仓库 docs/dream-layer-design.md"


def home():
    return os.environ.get("REPLAY_HOME") or os.path.join(os.path.expanduser("~"), ".replay")


def ledger_path():
    return os.path.join(home(), "ledger.jsonl")


def rollouts_path():
    return os.path.join(home(), "rollouts.jsonl")


def load():
    p = ledger_path()
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_rollouts():
    p = rollouts_path()
    if not os.path.exists(p):
        return {}
    out = {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                out[r["rollout"]] = r
    return out


def gate_gaps(rs):
    attempts = len(rs)
    approaches = len({r["approach"] for r in rs if r["approach"]})
    scored = sum(1 for r in rs if r["score"])
    gaps = []
    if attempts < GATE["attempts"]:
        gaps.append("尝试数 %d/%d" % (attempts, GATE["attempts"]))
    if approaches < GATE["approaches"]:
        gaps.append("不同做法 %d/%d" % (approaches, GATE["approaches"]))
    if scored < GATE["scored"]:
        gaps.append("带分数 %d/%d" % (scored, GATE["scored"]))
    return gaps


def tree_scored(rs):
    return sum(1 for r in rs if r.get("rollout") and r.get("score"))


def gate_verdict(name, rs):
    """两级判定：扁平覆盖满格 → 可开树模式探索；树形带分数满格 → 可做梦。"""
    ts = tree_scored(rs)
    if ts >= TREE_GATE:
        return "【可做梦】树形带分数 %d/%d 已满格——按图纸执行：%s" % (ts, TREE_GATE, DESIGN_DOC)
    gaps = gate_gaps(rs)
    if gaps:
        return "不可进化（覆盖不足：%s；树形带分数 %d/%d）" % ("、".join(gaps), ts, TREE_GATE)
    return "【可开树】扁平覆盖达标（树形带分数 %d/%d）——按图纸开树探索：%s" % (ts, TREE_GATE, DESIGN_DOC)


def write_rec(rec):
    os.makedirs(home(), exist_ok=True)
    with open(ledger_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("已入账 %s（%s / %s / %s）" % (rec["id"], rec["archetype"], rec["outcome"], rec["ts"][:10]))
    # 检测全自动：每次入账当场检查该原型覆盖度，达标即喊（开火与否仍走闸门）
    rs = [r for r in load() if r["archetype"] == rec["archetype"]]
    verdict = gate_verdict(rec["archetype"], rs)
    if verdict.startswith("【"):
        print("%s（原型「%s」）" % (verdict, rec["archetype"]))


def new_rec(task, archetype, outcome, project="", approach="", evaluator="",
            score="", cost="", death="", evidence="", note=""):
    return {
        "id": uuid.uuid4().hex[:8],
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "task": task, "archetype": archetype, "project": project,
        "approach": approach, "evaluator": evaluator, "score": score,
        "cost": cost, "outcome": outcome, "death": death,
        "evidence": evidence, "note": note,
    }


def apply_tree(a, rec):
    """可选树字段：给了 --rollout 就把记录挂成树节点（seq 自动，parent 默认 root）。"""
    rollout = getattr(a, "rollout", "") or ""
    if not rollout:
        return rec
    known = load_rollouts()
    if rollout not in known:
        print("WARN: rollout「%s」未登记（先 tree-begin 开树）；仍按树节点入账" % rollout, file=sys.stderr)
    rec["rollout"] = rollout
    rec["parent"] = (getattr(a, "parent", "") or "") or "root"
    rec["seq"] = 1 + sum(1 for r in load() if r.get("rollout") == rollout)
    return rec


def cmd_init(_):
    os.makedirs(home(), exist_ok=True)
    if not os.path.exists(ledger_path()):
        open(ledger_path(), "a", encoding="utf-8").close()
    print("账本家: %s" % ledger_path())
    print("记录数: %d" % len(load()))


def cmd_log(a):
    if a.outcome not in ("success", "fail", "mixed"):
        print("ERROR: --outcome 只能是 success / fail / mixed", file=sys.stderr)
        return 1
    rec = new_rec(a.task, a.archetype, a.outcome, a.project or "", a.approach or "",
                  a.evaluator or "", a.score or "", a.cost or "", a.death or "",
                  a.evidence or "", a.note or "")
    write_rec(apply_tree(a, rec))
    return 0


def match(rec, kws):
    hay = json.dumps(rec, ensure_ascii=False).lower()
    return all(k.lower() in hay for k in kws)


def fmt_row(r):
    tree = " [%s#%s←%s]" % (r["rollout"], r["seq"], r["parent"]) if r.get("rollout") else ""
    return "%s | %s | %s | %s | %s | %s%s%s" % (
        r["ts"][:10], r["project"] or "-", r["archetype"], r["approach"][:40] or "-",
        r["outcome"], r["score"], tree, (" | 死因: " + r["death"]) if r["death"] else "")


def cmd_query(a):
    hits = [r for r in load() if match(r, a.kw)]
    if not hits:
        print("无历史记录（账本没有与这些关键词匹配的尝试）")
        return 0
    for r in hits[-a.limit:]:
        print(fmt_row(r))
    print("--- 共 %d 条命中（账本总 %d 条）" % (len(hits), len(load())))
    return 0


def cmd_board(a):
    recs = load()
    hits = [r for r in recs if match(r, a.kw)] if a.kw else recs
    print("== 回放表：动手前先看最近似的 %d 次尝试 ==" % min(len(hits), a.limit))
    if not hits:
        print("无历史记录——本次为首次探索，回放为空，按 INV 明说不编造。")
        return 0
    for r in hits[-a.limit:]:
        print(fmt_row(r))
        if r["note"]:
            print("    备注: %s" % r["note"][:80])
    succ = sum(1 for r in hits if r["outcome"] == "success")
    fail = sum(1 for r in hits if r["outcome"] == "fail")
    print("--- 命中 %d 条（成 %d / 败 %d / 混合 %d）；历史不是预言，条件变了要声明" % (
        len(hits), succ, fail, len(hits) - succ - fail))
    return 0


def cmd_gate(_):
    recs = load()
    by_a = {}
    for r in recs:
        by_a.setdefault(r["archetype"], []).append(r)
    if not by_a:
        print("账本为空，无原型可评估")
        return 0
    for name, rs in sorted(by_a.items()):
        print("%s: %s" % (name, gate_verdict(name, rs)))
    return 0


def cmd_stats(_):
    recs = load()
    by_a, by_p = {}, {}
    tree = 0
    for r in recs:
        by_a[r["archetype"]] = by_a.get(r["archetype"], 0) + 1
        if r["project"]:
            by_p[r["project"]] = by_p.get(r["project"], 0) + 1
        if r.get("rollout"):
            tree += 1
    print("账本总条数: %d（树形 %d 条）" % (len(recs), tree))
    print("按原型: " + (", ".join("%s×%d" % kv for kv in sorted(by_a.items())) or "（空）"))
    print("按项目: " + (", ".join("%s×%d" % kv for kv in sorted(by_p.items())) or "（空）"))
    print("发现树: %d 棵" % len(load_rollouts()))
    return 0


def evaluators_path():
    return os.path.join(home(), "evaluators.json")


def load_evaluators():
    p = evaluators_path()
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


def cmd_evalset(a):
    d = load_evaluators()
    entry = {"run": a.run, "better": a.better, "timeout": a.timeout}
    entry["score_regex"] = a.score_regex if a.score_regex else None
    if not a.score_regex:
        entry["score_mode"] = a.score_mode
    if a.cwd:
        entry["cwd"] = a.cwd
    d[a.archetype] = entry
    os.makedirs(home(), exist_ok=True)
    with open(evaluators_path(), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print("已登记评估器 %s: %s" % (a.archetype, json.dumps(entry, ensure_ascii=False)))
    return 0


def cmd_evals(_):
    d = load_evaluators()
    if not d:
        print("（无已登记评估器）")
        return 0
    for k, v in sorted(d.items()):
        how = v.get("score_regex") or v.get("score_mode", "exitcode")
        print("%s: run=[%s] score=%s better=%s" % (k, v["run"], how, v["better"]))
    return 0


def extract_score(entry, out, rc, elapsed):
    if entry.get("score_regex"):
        m = re.search(entry["score_regex"], out)
        return m.group(1) if m else None
    mode = entry.get("score_mode", "exitcode")
    if mode == "exitcode":
        return "1" if rc == 0 else "0"
    if mode == "elapsed":
        return "%.2f" % elapsed
    if mode.startswith("filesize:"):
        p = mode.split(":", 1)[1]
        return str(os.path.getsize(p)) if os.path.exists(p) else None
    return None


def run_evaluator(entry, cwd=None):
    """跑登记的打分器，返回 (outcome, score_str, score_value, cost, death, diagnostics)。"""
    t0 = time.monotonic()
    death = ""
    try:
        r = subprocess.run(entry["run"], shell=True, cwd=cwd or entry.get("cwd") or None,
                           timeout=entry.get("timeout", 600), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        rc, out = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        rc, out = -1, ""
        death = "评估器超时（%ss）" % entry.get("timeout", 600)
    elapsed = time.monotonic() - t0
    score = extract_score(entry, out, rc, elapsed)
    if death or rc != 0:
        outcome = "fail"
        if not death:
            tail = out.strip().splitlines()
            death = "评估命令退出码 %d%s" % (rc, "：" + tail[-1][:100] if tail else "")
    elif score is None:
        outcome = "mixed"
        death = "命令成功但分数未抠到（检查 score 配置是否匹配输出）"
    else:
        outcome = "success"
    score_str = ""
    if score is not None:
        score_str = "%s（%s）" % (score, "越大越好" if entry["better"] == "higher" else "越小越好")
    score_value = None
    if score is not None:
        try:
            score_value = float(score)
        except ValueError:
            score_value = None
    tail = out.strip().splitlines()
    diagnostics = tail[-1][:120] if tail else ""
    return outcome, score_str, score_value, "wall %.1fs" % elapsed, death, diagnostics


def cmd_eval(a):
    """全自动评估：跑登记的打分器 → 抠分数 → 连同耗时/死因自动入账。"""
    entry = load_evaluators().get(a.archetype)
    if not entry:
        print("ERROR: 原型「%s」未登记评估器。先 eval-set 登记，或退回手动 log。" % a.archetype,
              file=sys.stderr)
        return 1
    outcome, score_str, score_value, cost, death, diag = run_evaluator(entry, a.cwd)
    if a.outcome:
        outcome = a.outcome
    rec = new_rec(a.task, a.archetype, outcome, a.project or "", a.approach or "",
                  entry["run"], score_str, cost, death, a.evidence or "", a.note or "")
    if score_value is not None:
        rec["score_value"] = score_value
        rec["diagnostics"] = diag
    write_rec(apply_tree(a, rec))
    print("评估完成: outcome=%s score=%s" % (outcome, score_str or "（未抠到）"))
    return 0 if outcome != "fail" else 1


def cmd_tree_begin(a):
    rollout = "r" + uuid.uuid4().hex[:6]
    rec = {"rollout": rollout, "archetype": a.archetype, "task": a.task,
           "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")}
    os.makedirs(home(), exist_ok=True)
    with open(rollouts_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("已开树 %s（原型 %s）。后续每次尝试：tree-add --rollout %s --parent <节点id或root>" % (
        rollout, a.archetype, rollout))
    return 0


def cmd_tree_add(a):
    """往发现树挂一个节点；原型有登记评估器则自动跑分，否则按手动字段入账。"""
    entry = load_evaluators().get(a.archetype)
    if entry and not a.manual:
        outcome, score_str, score_value, cost, death, diag = run_evaluator(entry, a.cwd)
        rec = new_rec(a.task, a.archetype, outcome, a.project or "", a.approach or "",
                      entry["run"], score_str, cost, death, a.evidence or "", a.note or "")
        if score_value is not None:
            rec["score_value"] = score_value
            rec["diagnostics"] = diag
    else:
        if a.outcome not in ("success", "fail", "mixed", None):
            print("ERROR: --outcome 只能是 success / fail / mixed", file=sys.stderr)
            return 1
        if not a.outcome:
            print("ERROR: 原型「%s」未登记评估器，手动挂节点必须给 --outcome" % a.archetype,
                  file=sys.stderr)
            return 1
        rec = new_rec(a.task, a.archetype, a.outcome, a.project or "", a.approach or "",
                      "", a.score or "", a.cost or "", a.death or "", a.evidence or "", a.note or "")
    write_rec(apply_tree(a, rec))
    print("挂树完成: rollout=%s seq=%s parent=%s outcome=%s score=%s" % (
        rec["rollout"], rec["seq"], rec["parent"], rec["outcome"], rec["score"] or "（无）"))
    return 0 if rec["outcome"] != "fail" else 1


def main():
    ap = argparse.ArgumentParser(prog="replay", description="探索尝试的实验账本")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    lp = sub.add_parser("log")
    lp.add_argument("--task", required=True)
    lp.add_argument("--archetype", required=True, help="任务原型（通用键，如 skill-tuning/build-fix/perf-opt；禁止写项目名）")
    lp.add_argument("--outcome", required=True)
    lp.add_argument("--project"), lp.add_argument("--approach"), lp.add_argument("--evaluator")
    lp.add_argument("--score"), lp.add_argument("--cost"), lp.add_argument("--death")
    lp.add_argument("--evidence"), lp.add_argument("--note")
    lp.add_argument("--rollout"), lp.add_argument("--parent")
    for name in ("query", "board"):
        p = sub.add_parser(name)
        p.add_argument("kw", nargs="*")
        p.add_argument("--limit", type=int, default=10)
    sub.add_parser("stats")
    sub.add_parser("gate")
    sp = sub.add_parser("eval-set", help="为任务原型登记自动打分器")
    sp.add_argument("archetype")
    sp.add_argument("--run", required=True, help="评估命令（shell）")
    sp.add_argument("--score-regex", help="从输出抠分数的正则（第一捕获组）")
    sp.add_argument("--score-mode", default="exitcode",
                    help="无正则时用：exitcode | elapsed | filesize:路径")
    sp.add_argument("--better", choices=["higher", "lower"], required=True)
    sp.add_argument("--cwd"), sp.add_argument("--timeout", type=int, default=600)
    ep = sub.add_parser("eval", help="自动跑分并入账")
    ep.add_argument("--archetype", required=True)
    ep.add_argument("--task", required=True)
    ep.add_argument("--approach"), ep.add_argument("--project"), ep.add_argument("--note")
    ep.add_argument("--evidence"), ep.add_argument("--cwd")
    ep.add_argument("--outcome", choices=["success", "fail", "mixed"], help="覆盖自动判定")
    ep.add_argument("--rollout"), ep.add_argument("--parent")
    sub.add_parser("evals", help="列出已登记评估器")
    tb = sub.add_parser("tree-begin", help="开一棵发现树（rollout）")
    tb.add_argument("--archetype", required=True)
    tb.add_argument("--task", required=True)
    ta = sub.add_parser("tree-add", help="往发现树挂一个节点（有评估器则自动跑分）")
    ta.add_argument("--rollout", required=True)
    ta.add_argument("--archetype", required=True)
    ta.add_argument("--task", required=True)
    ta.add_argument("--parent", help="父节点 id，缺省 root")
    ta.add_argument("--approach"), ta.add_argument("--project"), ta.add_argument("--note")
    ta.add_argument("--evidence"), ta.add_argument("--cwd")
    ta.add_argument("--manual", action="store_true", help="强制手动入账（有评估器也不跑）")
    ta.add_argument("--outcome", choices=["success", "fail", "mixed"])
    ta.add_argument("--score"), ta.add_argument("--cost"), ta.add_argument("--death")
    args = ap.parse_args()
    return {"init": cmd_init, "log": cmd_log, "query": cmd_query,
            "board": cmd_board, "stats": cmd_stats, "gate": cmd_gate,
            "eval-set": cmd_evalset, "eval": cmd_eval, "evals": cmd_evals,
            "tree-begin": cmd_tree_begin, "tree-add": cmd_tree_add}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
