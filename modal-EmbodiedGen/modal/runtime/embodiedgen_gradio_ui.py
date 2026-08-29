"""Small browser UI for the local/VPS EmbodiedGen Modal control plane."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import gradio as gr
from embodiedgen_direct import (
    AFFORDANCE_DEFAULTS,
    AFFORDANCE_PROFILE,
    AFFORDANCE_SEMANTIC_PROFILE,
    download_result,
    generate_affordance,
    get_job,
    list_jobs,
    retexture,
    submit_image3d,
    submit_text3d,
)

RESULT_ROOT = Path("/workspace/embodiedgen-ui-results")
RESULT_ROOT.mkdir(parents=True, exist_ok=True)

ROLE_SUFFIX = {
    "glb": ".glb",
    "obj": ".obj",
    "mtl": ".mtl",
    "obj_texture": ".png",
    "urdf": ".urdf",
    "video": ".mp4",
    "validation": ".json",
    "source_glb": ".glb",
    "source_urdf": ".urdf",
    "part_segmentation": ".json",
    "raw_grasps": ".json",
    "segment_validation": ".json",
    "grasp_validation": ".json",
    "affordance_bundle": ".json",
    "affordance_validation": ".json",
    "semantic_inputs": ".json",
    "semantic_rgb_grid": ".png",
    "semantic_mask_grid": ".png",
    "semantic_part_atlas": ".png",
    "part_semantics": ".json",
    "semantic_validation": ".json",
}


def _workflow(state: dict) -> str:
    workflow = state.get("workflow")
    if workflow:
        return str(workflow)
    input_type = (state.get("input") or {}).get("type")
    return {"image": "image_to_3d", "text": "text_to_3d"}.get(input_type, "image_to_3d")


def _elapsed(state: dict, *, live: bool = True) -> float | None:
    created = state.get("created_epoch")
    if created is None:
        return None
    try:
        if live and state.get("status") not in {"succeeded", "failed", "lost"}:
            end = time.time()
        else:
            end = float(state.get("updated_epoch") or time.time())
        return round(end - float(created), 1)
    except (TypeError, ValueError):
        return None


def _status(label: str, state: dict) -> str:
    job_id = state.get("job_id", "unknown")
    status = state.get("status", "running")
    stage = state.get("stage", "starting")
    elapsed = _elapsed(state)
    suffix = f" · 已耗时 **{elapsed:.1f}s**" if elapsed is not None else ""
    stage_times = state.get("stage_seconds") or {}
    details = ""
    if stage_times:
        details = "\n\n阶段耗时：" + " · ".join(
            f"{name} {seconds}s" for name, seconds in stage_times.items()
        )
    if state.get("error"):
        details += f"\n\n错误：`{state['error']}`"
    return f"{label} · `{job_id}` · **{status} / {stage}**{suffix}{details}"


def _history_updates():
    states = list_jobs(100)
    rows = []
    choices = []
    source_choices = []
    for state in states:
        job_id = str(state.get("job_id", ""))
        if not job_id:
            continue
        choices.append(job_id)
        if state.get("status") == "succeeded" and "glb" in set(state.get("files") or []):
            source_choices.append(job_id)
        rows.append(
            [
                job_id,
                state.get("created_at", ""),
                _workflow(state),
                state.get("status", ""),
                state.get("stage", ""),
                state.get("requested_profile", state.get("profile", "")),
                _elapsed(state, live=False),
            ]
        )
    history_value = choices[0] if choices else None
    source_value = source_choices[0] if source_choices else None
    return (
        rows,
        gr.update(choices=choices, value=history_value),
        gr.update(choices=source_choices, value=source_value),
        gr.update(choices=source_choices, value=source_value),
    )


def _download_job(state: dict):
    job_id = str(state["job_id"])
    out_dir = RESULT_ROOT / job_id
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    model = None
    video = None
    for role in state.get("files") or []:
        suffix = ROLE_SUFFIX.get(role)
        if not suffix:
            continue
        target = out_dir / f"{role}{suffix}"
        try:
            if not target.is_file() or target.stat().st_size == 0:
                download_result(job_id, role, target)
            files.append(str(target))
            if model is None and role in {"glb", "source_glb"}:
                model = str(target)
            if video is None and role == "video":
                video = str(target)
        except Exception:
            continue
    return model, video, files


def load_job(job_id: str):
    if not job_id:
        return "请选择任务。", {}, None, None, []
    state = get_job(job_id)
    if not state:
        return f"任务 `{job_id}` 不存在。", {}, None, None, []
    model = video = None
    files: list[str] = []
    if state.get("status") == "succeeded":
        model, video, files = _download_job(state)
    return _status("历史任务", state), state, model, video, files


def _watch_job(label: str, submitted: dict):
    """Poll a persisted async job; the Modal GPU call is already detached."""
    job_id = submitted.get("job_id")
    if not job_id:
        yield f"{label} · 提交失败：没有 Job ID", submitted, None, None, []
        return
    missing_since = None
    while True:
        state = get_job(job_id)
        if state is None:
            if missing_since is None:
                missing_since = time.time()
            # Allow a brief persistence/visibility window immediately after submit.
            if time.time() - missing_since < 10:
                state = submitted
            else:
                lost_state = dict(submitted)
                lost_state.update(
                    status="lost",
                    stage="state_missing",
                    updated_epoch=time.time(),
                    error="任务状态已从 Modal Dict 消失；远端任务可能已被清理、迁移或异常终止。",
                )
                yield _status(label, lost_state), lost_state, None, None, []
                return
        else:
            missing_since = None

        terminal = state.get("status") in {"succeeded", "failed", "lost"}
        if terminal:
            if state.get("status") == "succeeded":
                model, video, files = _download_job(state)
                yield _status(label, state), state, model, video, files
            else:
                yield _status(label, state), state, None, None, []
            return
        yield _status(label, state), state, None, None, []
        time.sleep(2)


def _watch_call(label: str, call):
    before = {state.get("job_id") for state in list_jobs(200)}
    result_box: list[dict] = []
    error_box: list[BaseException] = []

    def worker():
        try:
            result_box.append(call())
        except BaseException as exc:
            error_box.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    job_id = None

    while thread.is_alive():
        if job_id is None:
            for state in list_jobs(50):
                candidate = state.get("job_id")
                if candidate and candidate not in before:
                    job_id = candidate
                    break
        state = get_job(job_id) if job_id else None
        if state:
            yield _status(label, state), state, None, None, []
        else:
            yield f"{label} · 正在创建任务…", {}, None, None, []
        time.sleep(2)

    thread.join(timeout=0.1)
    if result_box:
        state = result_box[-1]
        job_id = state.get("job_id") or job_id
    elif job_id:
        state = get_job(job_id) or {}
    else:
        state = {}

    if error_box:
        if state:
            yield _status(label, state), state, None, None, []
        else:
            yield f"{label} · **失败**\n\n`{error_box[-1]}`", {}, None, None, []
        return

    model, video, files = _download_job(state)
    yield _status(label, state), state, model, video, files


def ui_image(image_path: str | None):
    if not image_path:
        yield "请先上传图片。", {}, None, None, []
        return
    submitted = submit_image3d(image_path, "auto")
    yield from _watch_job("图生 3D", submitted)


def ui_text(prompt: str, seed: float):
    prompt = (prompt or "").strip()
    if not prompt:
        yield "请输入 Prompt。", {}, None, None, []
        return
    submitted = submit_text3d(prompt, int(seed), "auto")
    yield from _watch_job("文生 3D", submitted)


def ui_retexture(source_job_id: str, prompt: str, seed: float):
    prompt = (prompt or "").strip()
    if not source_job_id:
        yield "请选择来源 3D 任务。", {}, None, None, []
        return
    if not prompt:
        yield "请输入材质 Prompt。", {}, None, None, []
        return
    yield from _watch_call(
        "Retexture",
        lambda: retexture(source_job_id, prompt, int(seed), "auto"),
    )


def ui_affordance(
    source_job_id: str,
    profile: str,
    category: str,
    point_num: float,
    prompt_num: float,
    prompt_bs: float,
    grasp_num_points: float,
    num_grasps: float,
    topk: float,
    seed: float,
):
    if not source_job_id:
        yield "请选择来源 3D 任务。", {}, None, None, []
        return
    payload = {
        "profile": profile,
        "point_num": int(point_num),
        "prompt_num": int(prompt_num),
        "prompt_bs": int(prompt_bs),
        "grasp_num_points": int(grasp_num_points),
        "num_grasps": int(num_grasps),
        "topk": int(topk),
        "seed": int(seed),
    }
    if profile == AFFORDANCE_SEMANTIC_PROFILE:
        payload["category"] = (category or "unknown object").strip()
    yield from _watch_call(
        "Affordance",
        lambda: generate_affordance(source_job_id, payload),
    )


with gr.Blocks(title="EmbodiedGen · Modal") as demo:
    gr.Markdown(
        "# EmbodiedGen · Modal\n"
        "任务提交后会持续显示当前阶段和已耗时；GPU 仅在对应 Modal worker 运行时启动。"
    )

    with gr.Tabs():
        with gr.Tab("图生 3D"):
            with gr.Row():
                with gr.Column():
                    img_in = gr.Image(type="filepath", label="输入图片", height=420)
                    gr.Markdown("运行策略：**统一 L40S · warm 180s**")
                    img_run = gr.Button("生成 3D", variant="primary")
                    img_status = gr.Markdown("等待任务。")
                with gr.Column():
                    img_model = gr.Model3D(label="GLB 预览")
                    img_video = gr.Video(label="预览视频")
            img_state = gr.JSON(label="任务状态")
            img_files = gr.Files(label="下载结果")
            img_run.click(ui_image, [img_in], [img_status, img_state, img_model, img_video, img_files])

        with gr.Tab("文生 3D"):
            with gr.Row():
                with gr.Column():
                    txt_prompt = gr.Textbox(label="Prompt", lines=6)
                    txt_seed = gr.Number(value=0, precision=0, label="Seed")
                    gr.Markdown("运行策略：**Kolors handoff 5s → 统一 L40S warm 180s**")
                    txt_run = gr.Button("文生 3D", variant="primary")
                    txt_status = gr.Markdown("等待任务。")
                with gr.Column():
                    txt_model = gr.Model3D(label="GLB 预览")
                    txt_video = gr.Video(label="预览视频")
            txt_state = gr.JSON(label="任务状态")
            txt_files = gr.Files(label="下载结果")
            txt_run.click(ui_text, [txt_prompt, txt_seed], [txt_status, txt_state, txt_model, txt_video, txt_files])

        with gr.Tab("Retexture"):
            with gr.Row():
                with gr.Column():
                    re_source = gr.Dropdown(choices=[], label="来源成功 3D Job", allow_custom_value=True)
                    re_prompt = gr.Textbox(label="材质 Prompt", lines=5)
                    re_seed = gr.Number(value=0, precision=0, label="Seed")
                    gr.Markdown("运行策略：**Retexture warm 120s**")
                    re_run = gr.Button("开始 Retexture", variant="primary")
                    re_status = gr.Markdown("等待任务。")
                with gr.Column():
                    re_model = gr.Model3D(label="GLB 预览")
                    re_video = gr.Video(label="预览视频")
            re_state = gr.JSON(label="任务状态")
            re_files = gr.Files(label="下载结果")
            re_run.click(ui_retexture, [re_source, re_prompt, re_seed], [re_status, re_state, re_model, re_video, re_files])

        with gr.Tab("Affordance"):
            with gr.Row():
                with gr.Column():
                    af_source = gr.Dropdown(choices=[], label="来源成功 3D Job", allow_custom_value=True)
                    af_profile = gr.Dropdown(
                        [AFFORDANCE_PROFILE, AFFORDANCE_SEMANTIC_PROFILE],
                        value=AFFORDANCE_PROFILE,
                        label="Affordance Profile",
                    )
                    af_category = gr.Textbox(value="unknown object", label="Semantic Category")
                    with gr.Row():
                        af_point_num = gr.Number(value=AFFORDANCE_DEFAULTS["point_num"], precision=0, label="point_num")
                        af_prompt_num = gr.Number(value=AFFORDANCE_DEFAULTS["prompt_num"], precision=0, label="prompt_num")
                        af_prompt_bs = gr.Number(value=AFFORDANCE_DEFAULTS["prompt_bs"], precision=0, label="prompt_bs")
                    with gr.Row():
                        af_grasp_points = gr.Number(value=AFFORDANCE_DEFAULTS["grasp_num_points"], precision=0, label="grasp_num_points")
                        af_num_grasps = gr.Number(value=AFFORDANCE_DEFAULTS["num_grasps"], precision=0, label="num_grasps")
                        af_topk = gr.Number(value=AFFORDANCE_DEFAULTS["topk"], precision=0, label="topk")
                    af_seed = gr.Number(value=AFFORDANCE_DEFAULTS["seed"], precision=0, label="seed")
                    af_run = gr.Button("运行 Affordance", variant="primary")
                    af_status = gr.Markdown("等待任务。")
                with gr.Column():
                    af_model = gr.Model3D(label="来源 GLB 预览")
                    af_video = gr.Video(label="视频（如有）")
            af_state = gr.JSON(label="任务状态")
            af_files = gr.Files(label="下载结果")
            af_run.click(
                ui_affordance,
                [af_source, af_profile, af_category, af_point_num, af_prompt_num, af_prompt_bs, af_grasp_points, af_num_grasps, af_topk, af_seed],
                [af_status, af_state, af_model, af_video, af_files],
            )

        with gr.Tab("历史记录"):
            with gr.Row():
                hist_refresh = gr.Button("刷新历史")
                hist_job = gr.Dropdown(choices=[], label="历史 Job", allow_custom_value=True)
                hist_load = gr.Button("加载结果", variant="primary")
            hist_table = gr.Dataframe(
                headers=["Job ID", "创建时间(UTC)", "工作流", "状态", "阶段", "Profile", "耗时(s)"],
                datatype=["str", "str", "str", "str", "str", "str", "number"],
                interactive=False,
            )
            hist_status = gr.Markdown("等待选择。")
            with gr.Row():
                hist_model = gr.Model3D(label="历史 GLB")
                hist_video = gr.Video(label="历史视频")
            hist_state = gr.JSON(label="历史状态")
            hist_files = gr.Files(label="历史下载")
            hist_refresh.click(_history_updates, [], [hist_table, hist_job, re_source, af_source])
            hist_load.click(load_job, [hist_job], [hist_status, hist_state, hist_model, hist_video, hist_files])
            demo.load(_history_updates, [], [hist_table, hist_job, re_source, af_source])


demo.queue(default_concurrency_limit=8, max_size=32)

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        show_error=True,
        allowed_paths=[str(RESULT_ROOT)],
        max_file_size="20mb",
    )
