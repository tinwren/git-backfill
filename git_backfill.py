#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
git-backfill
=============
GitHub 贡献图补全: 私有仓库 + 每天一个拟真提交, 填满历史绿墙。

一键:    fill (规划 -> 生成提交 -> 推送到私有仓库)
分步:    plan(规划) -> apply(生成提交) -> push(推送)

参考并吸取了以下项目的经验:
  - Shpota/github-activity-generator : CLI 参数化 / 晚间时段分布
  - idiomeo/github_contribution_feed : GIT_AUTHOR_DATE+GIT_COMMITTER_DATE 双时间戳 / 加权强度 / 增量续跑
  - git_matrix / github_painter      : 本地交互式设计器范式 / 绿墙画布思路

声明: 仅供学习 git 机制与个人存档用途。GitHub 禁止滥用贡献图, 过量提交存在账号风控风险,
      后果自负。脚本硬拒绝未来日期, 默认只操作最近 12 个月可见窗口。
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import random
import subprocess
import sys
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

try:  # Windows 控制台编码兜底
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VERSION = "1.1.0"
BRANCH = "main"
MAX_SAFE_COMMITS = 2500          # 超过给出风险提示

# ---------------------------------------------------------------- 常量池

EN_FILL = [
    "docs: fix typo", "docs: update comments", "docs: clarify wording",
    "style: format code", "style: fix lint warnings", "style: trailing whitespace",
    "chore: cleanup", "chore: tidy imports", "chore: update deps",
    "chore: bump patch dep", "refactor: simplify helper", "refactor: minor cleanup",
    "refactor: rename local var", "docs: tweak readme wording",
]
EN_DEVLOG = [
    "- sketched module design", "- implemented core skeleton", "- fixed edge case in input parsing",
    "- refactored storage layer", "- reviewed and merged feedback", "- researched caching strategies",
    "- profiled hot path", "- wrote regression tests", "- pair-programmed auth flow",
    "- cleaned up dead code", "- drafted api docs", "- upgraded toolchain",
    "- investigated flaky test", "- tuned default config",
]
EN_DEVLOG_MSG = ["docs: dev notes", "docs: update devlog", "docs: journal entry"]

ZH_FILL = [
    "docs: 修个错别字", "docs: 补充注释", "docs: 措辞微调", "style: 格式化代码",
    "style: lint 修正", "chore: 清理无用代码", "chore: 整理 import", "chore: 依赖小升级",
    "refactor: 小幅重构", "refactor: 改个变量名",
]
ZH_DEVLOG = [
    "- 梳理模块设计", "- 实现核心骨架", "- 修复解析边界问题", "- 重构存储层",
    "- 写回归测试", "- 调研缓存方案", "- 清理死代码", "- 补充接口文档",
    "- 排查不稳定测试", "- 调整默认配置",
]
ZH_DEVLOG_MSG = ["docs: 开发笔记", "docs: 更新日志"]

# 5x7 点阵字模 (每行 5bit, 高位在左)
FONT5X7 = {
    "A": [0x0E, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11], "B": [0x1E, 0x11, 0x11, 0x1E, 0x11, 0x11, 0x1E],
    "C": [0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E], "D": [0x1C, 0x12, 0x11, 0x11, 0x11, 0x12, 0x1C],
    "E": [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x1F], "F": [0x1F, 0x10, 0x10, 0x1E, 0x10, 0x10, 0x10],
    "G": [0x0E, 0x11, 0x10, 0x17, 0x11, 0x11, 0x0F], "H": [0x11, 0x11, 0x11, 0x1F, 0x11, 0x11, 0x11],
    "I": [0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x0E], "J": [0x07, 0x02, 0x02, 0x02, 0x02, 0x12, 0x0C],
    "K": [0x11, 0x12, 0x14, 0x18, 0x14, 0x12, 0x11], "L": [0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F],
    "M": [0x11, 0x1B, 0x15, 0x15, 0x11, 0x11, 0x11], "N": [0x11, 0x19, 0x15, 0x13, 0x11, 0x11, 0x11],
    "O": [0x0E, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E], "P": [0x1E, 0x11, 0x11, 0x1E, 0x10, 0x10, 0x10],
    "Q": [0x0E, 0x11, 0x11, 0x11, 0x15, 0x12, 0x0D], "R": [0x1E, 0x11, 0x11, 0x1E, 0x14, 0x12, 0x11],
    "S": [0x0F, 0x10, 0x10, 0x0E, 0x01, 0x01, 0x1E], "T": [0x1F, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04],
    "U": [0x11, 0x11, 0x11, 0x11, 0x11, 0x11, 0x0E], "V": [0x11, 0x11, 0x11, 0x11, 0x11, 0x0A, 0x04],
    "W": [0x11, 0x11, 0x11, 0x15, 0x15, 0x1B, 0x11], "X": [0x11, 0x11, 0x0A, 0x04, 0x0A, 0x11, 0x11],
    "Y": [0x11, 0x11, 0x0A, 0x04, 0x04, 0x04, 0x04], "Z": [0x1F, 0x01, 0x02, 0x04, 0x08, 0x10, 0x1F],
    "0": [0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E], "1": [0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E],
    "2": [0x0E, 0x11, 0x01, 0x06, 0x08, 0x10, 0x1F], "3": [0x0E, 0x11, 0x01, 0x06, 0x01, 0x11, 0x0E],
    "4": [0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02], "5": [0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E],
    "6": [0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E], "7": [0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08],
    "8": [0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E], "9": [0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C],
    " ": [0, 0, 0, 0, 0, 0, 0], "!": [0x04, 0x04, 0x04, 0x04, 0x04, 0x00, 0x04],
    "?": [0x0E, 0x11, 0x01, 0x02, 0x04, 0x00, 0x04], "-": [0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00],
}
PAINT_LEVEL_COUNT = {1: 2, 2: 5, 3: 9, 4: 13}  # 色阶 -> 目标提交数

# ---------------------------------------------------------------- 小工具

def say(msg=""):
    print(msg, flush=True)


def die(msg, code=2):
    print(f"[git-backfill] 错误: {msg}", file=sys.stderr)
    sys.exit(code)


def warn(msg):
    print(f"[git-backfill] 警告: {msg}", file=sys.stderr)


def run_git(repo, args, env_extra=None, check=True):
    env = os.environ.copy()
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})
    r = subprocess.run(["git", "-C", str(repo)] + args,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    if check and r.returncode != 0:
        die(f"git {' '.join(args[:3])} ... 失败:\n{r.stderr.strip()}")
    return r


def parse_ds(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        die(f"日期格式错误: {s} (需要 YYYY-MM-DD)")


# ---------------------------------------------------------------- 时间模型

SESSIONS_WEEKDAY = [("m", 600, 705), ("a", 840, 1065), ("e", 1230, 1380)]   # 10:00-11:45 / 14:00-17:45 / 20:30-23:00
SESSIONS_WEEKEND = [("a", 840, 1065), ("e", 1230, 1380)]
LATE_SESSION = ("n", 10, 80)  # 00:10-01:20


def gen_times(d: date, n: int, rng: random.Random):
    """一天内 n 个提交的拟真时刻: 工作时段加权 + 抖动 + 最小间隔, 绝不整点"""
    weekend = d.weekday() >= 5
    sessions = list(SESSIONS_WEEKEND if weekend else SESSIONS_WEEKDAY)
    if not weekend and rng.random() < 0.05:
        sessions[-1] = LATE_SESSION  # 偶尔熬夜, 替换晚间档
    order = list(range(len(sessions)))
    rng.shuffle(order)
    counts = [0] * len(sessions)
    for i in range(n):
        counts[order[i % len(order)]] += 1
    out = []
    for (name, s, e), c in zip(sessions, counts):
        if c == 0:
            continue
        t = s + rng.randint(0, max(10, (e - s) - 45))
        for _ in range(c):
            hh, mm = divmod(min(t, 1439), 60)
            ss = rng.randint(0, 59)
            if mm == 0:
                mm = rng.randint(1, 5)
            out.append(datetime.combine(d, dtime(hh, mm, ss)))
            t += rng.randint(25, 110)
    out.sort()
    for i in range(1, len(out)):  # 全天最小间隔 20 分钟
        if (out[i] - out[i - 1]) < timedelta(minutes=20):
            nt = out[i - 1] + timedelta(minutes=20, seconds=rng.randint(0, 59))
            if nt.date() == d:
                out[i] = nt
    return out

# ---------------------------------------------------------------- 图案模式

def paint_targets(text, start_d: date, end_d: date, level=3):
    """把 5x7 点阵文字映射到绿墙坐标 -> {iso_date: 目标提交数}"""
    text = text.upper()
    first_sunday = start_d - timedelta(days=(start_d.weekday() + 1) % 7)
    total_weeks = (end_d - first_sunday).days // 7 + 1
    cols_needed = sum(6 for _ in text) - 1
    if cols_needed > total_weeks:
        warn(f"图案 '{text}' 需要 {cols_needed} 列, 窗口只有 {total_weeks} 列, 将被截断")
    week_off = max(0, (total_weeks - cols_needed) // 2)
    target_n = PAINT_LEVEL_COUNT.get(level, 9)
    targets = {}
    col = week_off
    for ch in text:
        glyph = FONT5X7.get(ch)
        if glyph:
            for r in range(7):
                for c in range(5):
                    if (glyph[r] >> (4 - c)) & 1:
                        d = first_sunday + timedelta(days=(col + c) * 7 + r)
                        if start_d <= d <= end_d:
                            targets[d.isoformat()] = target_n
        col += 6
    return targets

# ---------------------------------------------------------------- plan 构建

def daterange(start_d, end_d):
    return [start_d + timedelta(days=i) for i in range((end_d - start_d).days + 1)]


def build_plan(args):
    today = date.today()
    end_d = parse_ds(args.end) if args.end else today - timedelta(days=1)
    start_d = parse_ds(args.start) if args.start else end_d - timedelta(days=370)
    if start_d > end_d:
        die(f"开始日期 {start_d} 晚于结束日期 {end_d}")
    if end_d > today:
        die(f"结束日期 {end_d} 在未来 ({today} 为今天) — 未来提交是封号重灾区, 拒绝执行")
    if start_d < today - timedelta(days=371):
        warn(f"开始日期 {start_d} 早于绿墙可见窗口(约最近 371 天), 再早的提交不会显示")

    rng = random.Random(args.seed)
    name = args.name
    email = args.email
    if not name:
        name = os.environ.get("GIT_AUTHOR_NAME") or _git_global("user.name")
    if not email:
        email = _git_global("user.email")
    if not name or not email:
        die("缺少提交者身份: 请传 --name 和 --email (建议用 GitHub noreply 邮箱)")

    say(f"[1/3] 补墙窗口: {start_d} ~ {end_d} ({(end_d - start_d).days + 1} 天)")

    days = daterange(start_d, end_d)
    weights = {}
    for d in days:
        if d.weekday() >= 5:
            weights[d] = 0.0 if args.no_weekends else 0.35
        else:
            weights[d] = 1.0
    if all(weights[d] == 0 for d in days):
        die("--no-weekends 把所有天都排除了? 请检查日期范围")

    buckets = {d: [] for d in days}

    fill_pool = EN_FILL if args.lang == "en" else ZH_FILL
    devlog_pool = EN_DEVLOG if args.lang == "en" else ZH_DEVLOG
    devlog_msgs = EN_DEVLOG_MSG if args.lang == "en" else ZH_DEVLOG_MSG

    if args.fill in ("empty", "devlog") and not args.paint:
        for d in days:
            if weights[d] == 0:
                continue
            if rng.random() < args.frequency:
                # 加权每日强度 1~4, 绿墙深浅错落更像真人
                add = rng.choices([1, 2, 3, 4], weights=[55, 28, 12, 5])[0]
                for _ in range(add):
                    if args.fill == "devlog":
                        buckets[d].append({"type": "devlog", "msg": rng.choice(devlog_msgs)})
                    else:
                        buckets[d].append({"type": "fill", "msg": rng.choice(fill_pool)})

    if args.paint:
        targets = paint_targets(args.paint, start_d, end_d, args.paint_level)
        say(f"[2/3] 图案模式: 在墙上画 '{args.paint.upper()}' (色阶{args.paint_level}, "
            f"{len(targets)} 格 x {PAINT_LEVEL_COUNT[args.paint_level]} 提交)")
        for d in days:
            tgt = targets.get(d.isoformat(), 0)
            cur = len(buckets[d])
            for _ in range(max(0, tgt - cur)):
                if args.fill == "devlog":
                    buckets[d].append({"type": "devlog", "msg": rng.choice(devlog_msgs)})
                else:
                    buckets[d].append({"type": "fill", "msg": rng.choice(fill_pool)})
    else:
        say("[2/3] 补格策略: " + {"empty": "空提交", "devlog": "devlog 日记文件",
                                 "none": "不补格"}[args.fill])

    # -- 生成时刻 + 汇总
    day_objs, seq = [], 0
    for d in days:
        commits = buckets[d]
        times = gen_times(d, len(commits), rng) if commits else []
        entry = {"date": d.isoformat(), "times": [t.isoformat(timespec="seconds") for t in times], "commits": []}
        for c, t in zip(commits, times):
            seq += 1
            entry["commits"].append(
                {"id": f"c{seq:04d}", "type": c["type"], "msg": c["msg"],
                 "time": t.isoformat(timespec="seconds")})
        day_objs.append(entry)

    total = seq
    if total > MAX_SAFE_COMMITS:
        warn(f"总提交数 {total} 偏高 (> {MAX_SAFE_COMMITS}), 存在风控风险, 建议减少范围/频率")

    plan = {
        "version": 1,
        "meta": {
            "tool": "git-backfill", "tool_version": VERSION,
            "created": datetime.now().isoformat(timespec="seconds"),
            "seed": args.seed, "lang": args.lang, "fill": args.fill,
            "branch": BRANCH, "paint": args.paint or None,
            "user": {"name": name, "email": email},
        },
        "days": day_objs,
    }
    say(f"[3/3] 计划生成: {total} 个提交, "
        f"活跃 {sum(1 for d in day_objs if d['commits'])}/{len(day_objs)} 天")
    if email and "@users.noreply.github.com" not in email:
        say("提示: 邮箱不是 GitHub noreply 地址。确认它在 GitHub 账号 Settings->Emails 里已绑定,\n"
            "     否则绿墙不计入。noreply 格式: <数字ID>+<用户名>@users.noreply.github.com")
    return plan


def _git_global(key):
    try:
        r = subprocess.run(["git", "config", "--global", "--get", key],
                           capture_output=True, text=True, encoding="utf-8")
        return r.stdout.strip() or None
    except Exception:
        return None

# ---------------------------------------------------------------- ASCII 摘要

def ascii_summary(plan):
    months = {}
    for d in plan["days"]:
        y, m = d["date"][:7].split("-")
        key = (int(y), int(m))
        months.setdefault(key, [0, 0])
        if d["commits"]:
            months[key][0] += 1
        months[key][1] += len(d["commits"])
    lines = []
    W = 22
    for (y, m) in sorted(months):
        act, tot = months[(y, m)]
        dim = calendar.monthrange(y, m)[1]
        filled = round(act / dim * W)
        lines.append(f"{y}-{m:02d} |{'█' * filled}{'·' * (W - filled)}| "
                     f"{act:>2}/{dim} 天活跃, {tot:>3} commits")
    return "\n".join(lines)

# ---------------------------------------------------------------- cmd: plan

def cmd_plan(args):
    if args.fill == "none" and not args.paint:
        die("--fill none 且无图案 = 没事可做")
    plan = build_plan(args)
    out = Path(args.out)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    say("")
    say(ascii_summary(plan))
    say("")
    say(f"已写入 {out}")
    say(f"下一步: python git_backfill.py apply {out} --repo-dir <新目录> --yes")

# ---------------------------------------------------------------- cmd: apply

def cmd_apply(args):
    plan_path = Path(args.plan_file)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    total = sum(len(d["commits"]) for d in plan["days"])
    if not total:
        die("计划里没有任何提交")
    say(f"即将在 {args.repo_dir} 生成 {total} 个提交 "
        f"({plan['days'][0]['date']} ~ {plan['days'][-1]['date']})")
    if not args.yes:
        ans = input("确认执行? [y/N] ").strip().lower()
        if ans != "y":
            say("已取消")
            return
    apply_plan(plan, plan_path, args.repo_dir,
               force=args.force, no_mtime=args.no_mtime)


def apply_plan(plan, plan_path, repo_dir, force=False, no_mtime=False):
    plan_path = Path(plan_path)
    meta = plan["meta"]
    user = meta["user"]

    repo = Path(repo_dir)
    all_commits = [(d, c) for d in plan["days"] for c in d["commits"]]
    if not all_commits:
        die("计划里没有任何提交")

    # ---- 断点续跑状态 (按计划的创建时间戳隔离: 同一计划重跑可续, 新计划互不干扰)
    stamp = meta.get("created", "x").replace(":", "").replace("-", "")
    state_path = plan_path.parent / (plan_path.name + "." + stamp + ".state.json")
    done = set()
    if state_path.exists():
        try:
            done = set(json.loads(state_path.read_text(encoding="utf-8"))["applied"])
        except Exception:
            done = set()

    # ---- 仓库初始化/守卫
    if repo.exists() and any(repo.iterdir()):
        if not (repo / ".git").exists():
            die(f"{repo} 已存在且不是 git 仓库, 为防误删请换一个空目录或删除后重试")
        n = run_git(repo, ["rev-list", "--count", "--all"]).stdout.strip()
        if int(n or 0) > 0 and not done:
            managed = run_git(repo, ["config", "--get", "git-backfill.managed"],
                              check=False).returncode == 0
            if managed:
                say(f"(追加模式: {repo} 已有 {n} 个提交, 新计划将续在其后)")
            elif not force:
                die(f"{repo} 已有 {n} 个提交且不是本工具创建的, 为防污染现有历史已中止。"
                    f"确认要往里追加请加 --force")
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        run_git(repo, ["-c", "init.defaultBranch=" + meta.get("branch", BRANCH), "init"])
    run_git(repo, ["config", "git-backfill.managed", "true"])
    run_git(repo, ["config", "user.name", user["name"]])
    run_git(repo, ["config", "user.email", user["email"]])
    run_git(repo, ["config", "core.autocrlf", "false"])

    mtime_map = {}
    say(f"开始生成 {len(all_commits)} 个提交 -> {repo}")
    if done:
        say(f"(断点续跑: 跳过已完成的 {len(done)} 个)")

    todo = [i for i, (d, c) in enumerate(all_commits) if c["id"] not in done]
    for idx, (d, c) in enumerate([x for x in all_commits if x[1]["id"] not in done]):
        t = c["time"]
        env = {"GIT_AUTHOR_DATE": t, "GIT_COMMITTER_DATE": t}
        if c["type"] == "devlog":
            ym = d["date"][:7]
            rel = f"devlog/{ym}.md"
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            entry_pool = EN_DEVLOG if meta.get("lang", "en") == "en" else ZH_DEVLOG
            _e = random.Random(d["date"] + c["id"]).choice(entry_pool).lstrip("- ").strip()
            line = f"- {d['date']}: {_e}\n"
            with open(dest, "a", encoding="utf-8") as f:
                f.write(line)
            run_git(repo, ["add", "--", rel])
            mtime_map[rel] = t
        run_git(repo, ["commit", "--no-verify", "-q", "--allow-empty",
                       "-m", c["msg"], "--date", t], env_extra=env)
        if idx == 0:
            run_git(repo, ["branch", "-M", meta.get("branch", BRANCH)])
        done.add(c["id"])
        state_path.write_text(json.dumps({"applied": sorted(done)}), encoding="utf-8")
        if (idx + 1) % 25 == 0 or idx + 1 == len(todo):
            say(f"  {idx + 1}/{len(todo)} ({d['date']} {c['msg'][:40]})")

    # ---- 收尾: 分支名 / mtime / 验证
    run_git(repo, ["branch", "-M", meta.get("branch", BRANCH)])
    if not no_mtime:
        for rel, t in mtime_map.items():
            p = repo / Path(rel)
            if p.exists():
                ts = datetime.fromisoformat(t).timestamp()
                os.utime(p, (ts, ts))
    say("")
    say(f"完成: {len(all_commits)} 个提交已生成在 {repo} (分支 {meta.get('branch', BRANCH)})")
    r = run_git(repo, ["log", "--date=iso", "--format=%h | A:%ad | C:%cd | %ae | %s", "-n", "3"])
    say("抽样验证 (作者时间应 == 提交者时间):")
    say("  " + r.stdout.strip().replace("\n", "\n  "))
    r = run_git(repo, ["log", "--date=iso", "--format=%h | A:%ad | C:%cd | %ae | %s",
                       "-n", "3", "--skip", str(max(0, len(all_commits) - 3))])
    say("  " + r.stdout.strip().replace("\n", "\n  "))
    st = run_git(repo, ["status", "--porcelain"]).stdout.strip()
    say(("工作树干净 ✓" if not st else f"工作树有未跟踪内容:\n{st}") +
        ("" if no_mtime else " · 文件 mtime 已回写提交时间"))
    say("")
    say(f"推送到 GitHub: python git_backfill.py push {repo} --remote git@github.com:<user>/<repo>.git")
    say("提醒: 建议推到新建的空仓库; 私有仓库需在 Profile 勾选 Private contributions 才显示绿点")

# ---------------------------------------------------------------- cmd: push

def cmd_push(args):
    push_repo(args.repo_dir, remote=args.remote, branch=args.branch, yes=args.yes)


def push_repo(repo_dir, remote=None, branch=BRANCH, yes=False):
    repo = Path(repo_dir)
    if not (repo / ".git").exists():
        die(f"{repo} 不是 git 仓库")
    n = run_git(repo, ["rev-list", "--count", "--all"]).stdout.strip()
    if int(n or 0) == 0:
        die("仓库没有提交, 没什么可推")
    if remote:
        ex = run_git(repo, ["remote", "get-url", "origin"], check=False)
        if ex.returncode == 0:
            run_git(repo, ["remote", "set-url", "origin", remote])
        else:
            run_git(repo, ["remote", "add", "origin", remote])
    else:
        if run_git(repo, ["remote", "get-url", "origin"], check=False).returncode != 0:
            die("没有 origin 远程, 请用 --remote 指定 git@github.com:<user>/<repo>.git")
    run_git(repo, ["branch", "-M", branch])
    url = run_git(repo, ["remote", "get-url", "origin"]).stdout.strip()
    if not yes:
        ans = input(f"确认推送 {repo} ({n} commits) -> {url} ? [y/N] ").strip().lower()
        if ans != "y":
            say("已取消 (本地提交已保留, 稍后可手动 push)")
            return False
    r = run_git(repo, ["push", "-u", "origin", branch], check=False)
    if r.returncode != 0:
        say(r.stderr.strip())
        die("推送失败 (检查 SSH key / 仓库是否已有内容冲突)")
    say("推送成功 ✓ 绿墙一般在几分钟到几小时内刷新")
    return True


# ---------------------------------------------------------------- cmd: fill (一键)

def repo_max_commit_date(repo_dir):
    """仓库里所有提交的最大日期 (YYYY-MM-DD), 空仓库/无仓库返回 None"""
    repo = Path(repo_dir)
    if not (repo / ".git").exists():
        return None
    r = run_git(repo, ["log", "--format=%ad", "--date=short"], check=False)
    if r.returncode != 0:
        return None
    ds = sorted(set(r.stdout.split()))
    return ds[-1] if ds else None


def cmd_fill(args):
    """纯补墙一条龙: 规划 -> (确认) -> 生成提交 -> 推送到私有仓库"""
    name = args.name or _git_global("user.name")
    email = args.email or _git_global("user.email")
    if not name:
        name = input("输入提交者名 (GitHub 用户名): ").strip()
    if not email:
        email = input("输入提交邮箱 (建议 GitHub noreply): ").strip()
    if not name or not email:
        die("缺少提交者身份")

    # 智能续补: 不指定 --start 时, 从仓库最新提交的次日开始, 避免重复叠加
    repo_max = repo_max_commit_date(args.repo_dir)
    if args.start is None and repo_max:
        end = args.end or (date.today() - timedelta(days=1)).isoformat()
        floor = (datetime.strptime(end, "%Y-%m-%d").date() - timedelta(days=370)).isoformat()
        cand = (datetime.strptime(repo_max, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
        start = max(floor, cand)
        if start > end:
            say(f"仓库已补到 {repo_max}, 暂无新日子可补 (过几天再来跑一次)")
            return
        args.start = start
        say(f"(检测到仓库已补至 {repo_max}, 本次从 {start} 续补)")
    elif args.start and repo_max and args.start <= repo_max:
        warn(f"--start {args.start} 不晚于仓库最新提交 {repo_max}, 重叠日期会叠加新提交")

    ns = argparse.Namespace(
        start=args.start, end=args.end, seed=args.seed,
        name=name, email=email, lang=args.lang,
        fill=args.fill, frequency=args.frequency,
        no_weekends=args.no_weekends, paint=args.paint, paint_level=args.paint_level)
    plan = build_plan(ns)
    out = Path(args.out)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    say("")
    say(ascii_summary(plan))
    say("")
    if not args.yes:
        ans = input(f"计划已存 {out}, 生成 {sum(len(d['commits']) for d in plan['days'])} 个提交? [y/N] ").strip().lower()
        if ans != "y":
            say("已取消 (计划文件保留, 稍后可 apply)")
            return
    apply_plan(plan, out, args.repo_dir, force=args.force, no_mtime=args.no_mtime)

    if args.remote:
        if push_repo(args.repo_dir, remote=args.remote, yes=args.yes):
            say("")
            say("★ 私有仓库记得: GitHub 头像 -> Settings -> Profile -> 勾选 Private contributions,")
            say("  否则绿点只有你自己可见")
    else:
        say("")
        say(f"未指定 --remote, 本地仓库在 {args.repo_dir}。推送到 GitHub:")
        say(f"  python git_backfill.py push {args.repo_dir} --remote git@github.com:<user>/<repo>.git")
        say("★ 建议在 GitHub 新建一个私有空仓库; 并在 Profile 设置里勾选 Private contributions")
    say("")
    say("后续继续补格子: 过段时间用同一 --repo-dir 再跑一次 fill (选新的日期段), 然后重新 push 即可,")
    say("仓库会自动追加; 也可以随时手动往这个仓库提交真实内容。")

# ---------------------------------------------------------------- 配置文件

CONFIG_NAME = "backfill.json"
CFG_KEYS = ["name", "email", "remote", "repo_dir", "out", "lang", "fill",
            "frequency", "seed", "paint", "paint_level"]


def load_config(explicit=None):
    """按 运行目录 -> 脚本目录 查找 backfill.json; --config 可指定其他路径"""
    if explicit:
        paths = [Path(explicit)]
    else:
        paths = [Path.cwd() / CONFIG_NAME, Path(__file__).resolve().parent / CONFIG_NAME]
    for p in paths:
        if p.exists():
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                die(f"配置文件解析失败 {p}: {e}")
            say(f"(已加载配置 {p})")
            return cfg if isinstance(cfg, dict) else {}
    return {}


def merge_config(args, cfg):
    """命令行没给的参数, 用配置文件补上 (优先级: 命令行 > 配置 > 内置默认)"""
    for k in CFG_KEYS:
        if getattr(args, k, None) is None and cfg.get(k) is not None:
            setattr(args, k, cfg[k])
    if cfg.get("no_weekends"):
        args.no_weekends = True


def cmd_config(args):
    p = Path(args.config) if args.config else (Path.cwd() / CONFIG_NAME)
    cfg = {}
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            die(f"配置文件解析失败 {p}: {e}")
    changed = False
    for k in CFG_KEYS:
        v = getattr(args, k, None)
        if v is not None:
            cfg[k] = v
            changed = True
    if args.no_weekends:
        cfg["no_weekends"] = True
        changed = True
    if not changed:
        say(f"当前配置 {p}" + ("" if p.exists() else " (尚未创建, 带 --email 等选项运行即可写入)"))
        say(json.dumps(cfg, ensure_ascii=False, indent=2) if cfg else "  (空)")
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    say(f"已保存 {p}:")
    say(json.dumps(cfg, ensure_ascii=False, indent=2))

# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(
        prog="git_backfill.py",
        description="git-backfill: GitHub 贡献图补全 (fill 一键 / plan -> apply -> push 分步)")
    ap.add_argument("--version", action="version", version="git-backfill " + VERSION)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fill", help="一键补墙: 规划->提交->推送 (最常用)",
                       description="纯贡献图补全: 建私有仓库 -> 每天 1~4 个拟真提交 -> 推送")
    p.add_argument("--start", help="开始日期 YYYY-MM-DD (默认 结束日期往前371天, 铺满可见绿墙)")
    p.add_argument("--end", help="结束日期 YYYY-MM-DD (默认 昨天, 拒绝未来)")
    p.add_argument("--remote", help="私有仓库地址 git@github.com:user/repo.git, 给了就自动推送")
    p.add_argument("--email", help="提交邮箱, 建议 GitHub noreply (可用 config 子命令预置)")
    p.add_argument("--name", help="提交者名 (可用 config 子命令预置)")
    p.add_argument("--frequency", type=float, help="每天有数据的概率 0~1 (默认 1.0 = 每天都绿)")
    p.add_argument("--fill", choices=["empty", "devlog"], help="提交形态: 空提交 / devlog日记 (默认 empty)")
    p.add_argument("--lang", choices=["en", "zh"], help="提交信息语言 (默认 en)")
    p.add_argument("--paint", help="顺便画图案, 如 --paint HELLO")
    p.add_argument("--paint-level", type=int, choices=[1, 2, 3, 4], help="图案色阶 1~4 (默认 3)")
    p.add_argument("--no-weekends", action="store_true", help="周末留空")
    p.add_argument("--repo-dir", help="本地仓库目录 (默认 backfill-out)")
    p.add_argument("--out", help="计划文件 (默认 fill-plan.json)")
    p.add_argument("--seed", type=int, help="随机种子")
    p.add_argument("--yes", action="store_true", help="跳过所有确认")
    p.add_argument("--force", action="store_true", help="允许向已有仓库追加")
    p.add_argument("--no-mtime", action="store_true")
    p.add_argument("--config", help="配置文件路径 (默认 运行目录/脚本目录下的 backfill.json)")
    p.set_defaults(func=cmd_fill)

    p = sub.add_parser("plan", help="只生成计划 plan.json (进阶)")
    p.add_argument("--start", help="开始日期 YYYY-MM-DD (默认 结束日期往前371天, 铺满可见绿墙)")
    p.add_argument("--end", help="结束日期 YYYY-MM-DD (默认 昨天, 不允许未来)")
    p.add_argument("--email", help="提交邮箱, 建议GitHub noreply (默认取 git 全局配置)")
    p.add_argument("--name", help="提交者名 (默认取 git 全局配置)")
    p.add_argument("--lang", choices=["en", "zh"], help="提交信息语言 (默认 en)")
    p.add_argument("--fill", choices=["empty", "devlog", "none"],
                   help="空格子补全策略: 空提交/devlog日记/不补 (默认 empty)")
    p.add_argument("--frequency", type=float, help="空白天补格概率 0~1 (默认 1.0 = 每天都绿)")
    p.add_argument("--no-weekends", action="store_true", help="周末完全不提交")
    p.add_argument("--paint", help="在绿墙上画图案文字, 如 --paint HELLO")
    p.add_argument("--paint-level", type=int, choices=[1, 2, 3, 4], help="图案色阶深度 1~4 (默认 3)")
    p.add_argument("--seed", type=int, help="随机种子, 固定后计划可复现")
    p.add_argument("--out", help="输出计划文件 (默认 plan.json)")
    p.add_argument("--config", help="配置文件路径")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("apply", help="按计划生成 git 提交")
    p.add_argument("plan_file", help="plan.json 路径")
    p.add_argument("--repo-dir", help="输出仓库目录 (默认 backfill-out)")
    p.add_argument("--yes", action="store_true", help="跳过交互确认直接执行")
    p.add_argument("--force", action="store_true", help="允许向已有提交的仓库追加")
    p.add_argument("--no-mtime", action="store_true", help="不回写文件修改时间")
    p.add_argument("--config", help="配置文件路径")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("push", help="推送到 GitHub")
    p.add_argument("repo_dir", help="本地仓库目录")
    p.add_argument("--remote", help="远程地址, 如 git@github.com:user/repo.git (可从配置读取)")
    p.add_argument("--branch", default=BRANCH, help="分支名 (默认 main)")
    p.add_argument("--yes", action="store_true", help="跳过确认")
    p.add_argument("--config", help="配置文件路径")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("config", help="查看/写入配置文件 backfill.json")
    for k in CFG_KEYS:
        p.add_argument("--" + k.replace("_", "-"))
    p.add_argument("--no-weekends", action="store_true", help="设置周末留空")
    p.add_argument("--config", help="配置文件路径 (默认 运行目录下的 backfill.json)")
    p.set_defaults(func=cmd_config)

    args = ap.parse_args()
    if args.cmd != "config":
        merge_config(args, load_config(getattr(args, "config", None)))
    # 配置和命令行都没给时, 补回内置默认值
    if args.cmd == "fill":
        args.repo_dir = args.repo_dir or "backfill-out"
        args.out = args.out or "fill-plan.json"
    elif args.cmd == "plan":
        args.out = args.out or "plan.json"
    elif args.cmd == "apply":
        args.repo_dir = args.repo_dir or "backfill-out"
    if args.cmd in ("fill", "plan"):
        args.lang = args.lang or "en"
        args.fill = args.fill or "empty"
        args.frequency = 1.0 if args.frequency is None else args.frequency
        args.paint_level = 3 if args.paint_level is None else args.paint_level
    args.func(args)


if __name__ == "__main__":
    main()
