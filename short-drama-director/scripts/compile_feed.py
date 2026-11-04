#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compile_feed.py · V7.5.0 P4 投喂提示词自动装配编译器（【视频 X】唯一工业标准版）
设计动机：
  读取 project_state.json，自动将结构化分镜编译为 100% 符合 V7.5.0【视频 X】标准格式、
  validate_prompt.py（C1~C32）与 gate_check.py（六道闸门）的可投喂提示词稿。
  彻底剔除【STYLE】/【PERFORMANCE】等 500 字伪技术参数污染，100% 聚焦物理动作与高级运镜。
用法：
  python3 scripts/compile_feed.py --state project_state.json [--out feed.md]
  python3 scripts/compile_feed.py --self-test
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import sd_core


def _fmt_sec(val):
    v = round(float(val), 2)
    m = int(v) // 60
    s = v - m * 60
    if abs(s - round(s)) < 1e-6:
        return f"{m:02d}:{int(round(s)):02d}"
    s_str = f"{s:04.1f}" if abs(s * 10 - round(s * 10)) < 1e-6 else f"{s:05.2f}"
    return f"{m:02d}:{s_str}"


def _normalize_vx_dialogue(dlg):
    if not dlg or dlg.strip() in ("无", "无。"):
        return ""
    s = dlg.strip().rstrip("。 ")
    # 若已是 `角色名说：“…”` 或 `角色名内心独白：…` 直接返回
    if re.search(r"说：[“\"]", s) or "内心独白：" in s:
        return s
    # 兼容旧 state 中的 `【林风（语气）：“台词”】` 自动转译为 `林风说：“台词”`
    m = re.match(r"^【([^【】（(:：]+?)(?:[（(][^）)]*[）)])?\s*[:：]\s*[\"“](.*?)[\"”]\s*】$", s)
    if m:
        return f'{m.group(1).strip()}说：“{m.group(2).strip()}”'
    return s


def compile_project_to_feed(state):
    locks = state.get("locks", {})
    mode = locks.get("asset_mode", "M1").upper()
    model = str(locks.get("model", "2.5"))
    aspect = locks.get("aspect", "16:9")
    style_card = locks.get("style_card", "冷峻电影级写实质感")[:28]
    wa = state.get("world_anchor", {})
    era = wa.get("era_anchor", "现代")
    region = wa.get("region", "")
    receipt = state.get("receipt", {})
    plugins = receipt.get("active_plugins", ["sd-storyboard-engine", "sd-feed-engine"])
    read_refs = receipt.get("read_refs", ["model-adapters.md", "segment-splicing.md"])
    fps = receipt.get("fingerprints", ["【默认镜头策略】"])

    out_lines = [
        f"> 素材形态：{mode}",
        f"> 画幅锁：{aspect} ｜ 模型版本：Seedance {model}",
        f"> 激活外挂：{' + '.join(plugins)}",
        f"> 已读子库：{' / '.join(read_refs)}",
        f"> 本段调用外挂指纹：{'｜'.join(fps)}",
        "",
    ]

    chars = state.get("characters", {})
    scenes = state.get("scenes", {})
    props = state.get("props", {})
    segments = state.get("segments", [])
    total_segs = max(len(segments), 1)
    used_figs = []

    for idx, seg in enumerate(segments, 1):
        sid = seg.get("seg_id", f"段{idx}")
        scn_name = seg.get("scene", "")
        scn = scenes.get(scn_name, {})
        scn_fig = scn.get("fig_no")

        # 场景描述（完整环境描述：时间/年代、地点、空间布局、光线、介质、整体氛围）
        scn_fig_tag = f"（图{scn_fig}）" if (mode != "M0" and scn_fig) else ""
        if mode != "M0" and scn_fig:
            used_figs.append((scn_fig, f"场景·{scn_name}", "只控制空间几何、建筑材质与主光源方向", "不控制人物站位与动作"))
        coords = scn.get("coords", "")
        set_st = scn.get("set_states", {}).get("default", "")
        media = scn.get("media_layer", "")
        lt = re.sub(r"（[^）]*光影基准[^）]*）", "", scn.get("lighting", "")).strip(" ；。")
        scn_desc_parts = [p for p in [f"{era}{region}{scn_name}{scn_fig_tag}", coords, set_st, media, lt] if p]

        # 检查 CHAR_STATE 脱离声明（如摘眼镜以本段提示词为准，覆盖角色参考图）
        dev_notes = []
        cast_items = []
        for cname, cinfo in chars.items():
            cfig = cinfo.get("fig_no")
            vlock = cinfo.get("voice_lock", "")
            for _k, st_v in (cinfo.get("char_states") or {}).items():
                item = st_v.get("item", "")
                act = st_v.get("action", "")
                cons = st_v.get("consequence", "")
                if item:
                    dev_notes.append(f"本段{cname}{act}（{cons}），关于「{item}」佩戴状态以本段提示词为准，覆盖角色参考图")
            if mode != "M0" and cfig:
                no_ctrl = "不控制本段动作姿态与已声明偏离的配饰状态"
                ctrl = f"只控制{cname}面部五官、头身比与基础服装形制" + (f"（声线参考：{vlock}）" if vlock else "")
                used_figs.append((cfig, f"角色·{cname}", ctrl, no_ctrl))
                cast_items.append(f"{cname}（图{cfig}）")
            else:
                age = cinfo.get("age_anchor", "")
                body = cinfo.get("body_anchor", "")
                look = cinfo.get("look_3piece", "")
                cast_items.append(f"{cname}（{age}，{body}，{look}）")

        if dev_notes:
            scn_desc_parts.append("；".join(dev_notes))
        scene_desc_line = f"场景描述：{'；'.join(scn_desc_parts)}。"
        role_line = f"角色：{'，'.join(cast_items)}" if cast_items else "角色：无"

        prop_items = []
        for pname, pinfo in props.items():
            pfig = pinfo.get("fig_no")
            mdesc = pinfo.get("material_desc", "")
            if mode != "M0" and pfig:
                used_figs.append((pfig, f"道具·{pname}", f"只控制{pname}外观形制与材质", "不控制持握人物与运动轨迹"))
                prop_items.append(f"{pname}（图{pfig}）")
            elif mdesc:
                prop_items.append(f"{pname}（{mdesc}）")
            else:
                prop_items.append(pname)

        shots = seg.get("shots", [])
        shot_lines = []
        for s_i, sh in enumerate(shots):
            st_t = sh.get("start", 0)
            ed_t = sh.get("end", float(st_t) + 3.0)
            t_str = f"【{_fmt_sec(st_t)}-{_fmt_sec(ed_t)} 秒】："
            spec = sh.get("spec", "中景，平视缓推").replace(" · ", "，")
            act = re.sub(r"@(?:CHR-|SCN-|PRP-)?", "", sh.get("action", "")).rstrip("。； ")
            # 遵循 C20m 铁律：零默认摄影机理论废话注入，仅当显式传入 optics_and_camera_lock 时拼入物理锁焦动作
            opt_lock = sh.get("optics_and_camera_lock", "").strip("。； ")
            if opt_lock:
                act = f"{act}，{opt_lock}" if act else opt_lock
            dlg_norm = _normalize_vx_dialogue(sh.get("dialogue", ""))
            snd = sh.get("sound", "").strip("。 ")
            parts_sh = [spec, act]
            if dlg_norm:
                parts_sh.append(dlg_norm)
            if snd and snd != "无" and "音效" not in act:
                parts_sh.append(f"音效：{snd}")
            shot_lines.append(t_str + "，".join(p for p in parts_sh if p) + "。")

        vx_block = [
            f"## 【投喂单元 {idx}/{total_segs} · {sid}】",
            "```text",
            f"【视频 {idx}】",
            scene_desc_line,
            role_line,
        ]
        if prop_items:
            vx_block.append(f"道具：{'，'.join(prop_items)}")
        vx_block.append(f"风格要求：{style_card}")
        vx_block.extend(shot_lines)
        vx_block.extend(["```", ""])
        out_lines.extend(vx_block)

    # M1 模式下自动编译《素材接线单》
    if mode == "M1" and used_figs:
        seen_f = set()
        uniq_figs = []
        for item in used_figs:
            if item[0] not in seen_f:
                seen_f.add(item[0])
                uniq_figs.append(item)
        uniq_figs.sort(key=lambda x: x[0])
        out_lines.extend([
            "## 素材接线单（M1 编号占位必备 · 平台挂图指南）",
            "",
            "| 图号 | 对应资产 | 你该挂哪张 | 只控制什么 | 不控制什么 |",
            "|---|---|---|---|---|",
        ])
        for fno, aname, ctrl, no_ctrl in uniq_figs:
            out_lines.append(f"| 图{fno} | {aname} | 挂载 P2 产出的「{aname}」设定图 | {ctrl} | {no_ctrl} |")
        out_lines.append("")

    return "\n".join(out_lines)


def self_test():
    st = sd_core.default_project_state()
    feed_md = compile_project_to_feed(st)
    assert "【视频 1】" in feed_md and "场景描述：" in feed_md and "【画幅风格】" not in feed_md
    # 1. 对账校验
    iss_s, wrn_s = sd_core.verify_feed_against_state(feed_md, st)
    assert not iss_s and not wrn_s, f"state verify failed: {iss_s} / {wrn_s}"
    # 2. 跑 validate_prompt.py 与 gate_check.py 实测
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(feed_md)
        tmp_path = f.name
    try:
        vp_script = os.path.join(SCRIPT_DIR, "validate_prompt.py")
        r1 = subprocess.run(
            [sys.executable, vp_script, tmp_path, "--model", "2.5"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r1.returncode == 0, f"validate_prompt failed on compiled feed: {r1.stdout}\n{r1.stderr}"
        gc_script = os.path.join(os.path.dirname(os.path.dirname(SCRIPT_DIR)), "sd-feed-engine", "scripts", "gate_check.py")
        r2 = subprocess.run(
            [sys.executable, gc_script, tmp_path, "--model", "2.5"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert r2.returncode == 0, f"gate_check failed on compiled feed: {r2.stdout}\n{r2.stderr}"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    print("[+] compile_feed self-test PASSED (0 FAIL across validate_prompt & gate_check)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="漫剧老李 V7.5.0 P4 投喂自动装配编译器（【视频 X】标准版）")
    ap.add_argument("--state", help="project_state.json 路径")
    ap.add_argument("--out", help="输出投喂稿 .md 路径（不指定则打印到标准输出）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if not args.state:
        ap.print_help()
        sys.exit(2)
    state = json.load(open(args.state, encoding="utf-8"))
    md = compile_project_to_feed(state)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"[+] 已编译生成投喂稿：{args.out}")
    else:
        print(md)


if __name__ == "__main__":
    main()
