"""
pipeline/assets_gen/gen_3d_object/run.py

3D object generation demo runner.

Loads a cloud backend, injects it into Gen3DObjectOperator, reads tasks from
test_data/test_samples/3D_object_gen_collect.jsonl (or a single game's
object_tasks.jsonl), and writes GLB outputs grouped per game project:

    test_data/outputs/<game_id>/<run_id>/assets/3d_object/<task_id>/model.glb

Two interchangeable cloud backends fill the model slot (model_require.md R6):

    --backend tripo      Tripo3D cloud API,  needs $TRIPO_API_KEY  (default)
    --backend meshy      Meshy cloud API,    needs $MESHY_API_KEY

Usage:
    # Run all tasks in the default jsonl
    python pipeline/assets_gen/gen_3d_object/run.py

    # Tripo instead of the default Meshy
    export TRIPO_API_KEY=...
    python pipeline/assets_gen/gen_3d_object/run.py --backend tripo \
        --game gameA_cyberpunk_shooter --run-id auto \
        --cache-dir test_data/outputs/_api_cache

    # Only one game project (prefers that game's own object_tasks.jsonl)
    python pipeline/assets_gen/gen_3d_object/run.py --game gameA_cyberpunk_shooter

    # Fresh timestamped run dir instead of overwriting <game>/default/
    python pipeline/assets_gen/gen_3d_object/run.py --run-id auto

    # Override model checkpoint path
    python pipeline/assets_gen/gen_3d_object/run.py \
        --ckpt /path/to/TRELLIS.2-4B

    # Run from a different jsonl
    python pipeline/assets_gen/gen_3d_object/run.py \
        --tasks test_data/test_samples/3D_object_gen_collect.jsonl

    # Legacy flat output (bypasses the per-game layout; debugging only)
    python pipeline/assets_gen/gen_3d_object/run.py --out-dir outputs/3d_object

    # Single demo (image only, no jsonl)
    python pipeline/assets_gen/gen_3d_object/run.py \
        --image path/to/image.png --task-id my_test
"""

import argparse
import json
import sys
from pathlib import Path

# ── Make repo root importable regardless of CWD ───────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
# ──────────────────────────────────────────────────────────────────────────────

from pipeline.common import config, paths  # noqa: E402

#: Registered task kind — keys into paths.TASK_* tables.
TASK_KIND = "3d_object"

DEFAULT_TASKS = paths.collect_jsonl(TASK_KIND)

#: backend -> (default "ckpt", env var holding an override).
#: The "ckpt" is a model **version id**, not a weight location
#: (api_model_require.md R9.1) — the flag stays `--ckpt` so the operator
#: and every caller keep one vocabulary.
BACKENDS: dict[str, tuple[str, str]] = {
    "tripo": ("v3.1-20260211", "TRIPO_MODEL"),
    "meshy": ("meshy-6", "MESHY_MODEL"),
}

#: 全部后端都是闭源云 API，都需要在 `.env` 里配置对应服务商。
CLOUD_BACKENDS = ("tripo", "meshy")


def resolve_ckpt(backend: str, cli_value: str | None) -> str:
    """Checkpoint / model-version precedence: CLI flag > env var > default (R3.1)."""
    import os

    default, env_var = BACKENDS[backend]
    return cli_value or os.environ.get(env_var) or default


def load_model(
    ckpt: str,
    device: str = "cpu",
    backend: str = "tripo",
    **backend_kwargs,
):
    """
    Load the 3D-object backend named by `backend` (R2.1).

    Args:
        ckpt: Model version id.
        device: Accepted and ignored — the cloud backends run server-side
              (api_model_require.md R9.2).
        backend: One of `BACKENDS`.
        **backend_kwargs: Passed to the wrapper — `cache_dir`, `low_poly`,
              `output_format`, `timeout`, … for the cloud backends.

    Returns:
        A model exposing `infer_and_save(image, output_path, seed,
        decimation_target, texture_size)`.
    """
    if backend == "tripo":
        from models.gen_3d_object.tripo_model import TripoModel
        print(f"[run] Using TripoModel (cloud API), model={ckpt}")
        return TripoModel(model_path=ckpt, device=device, **backend_kwargs)

    if backend == "meshy":
        from models.gen_3d_object.meshy_model import MeshyModel
        print(f"[run] Using MeshyModel (cloud API), model={ckpt}")
        return MeshyModel(model_path=ckpt, device=device, **backend_kwargs)

    raise ValueError(f"Unknown backend {backend!r}. Known: {sorted(BACKENDS)}")


def make_operator(
    model,
    output_dir: str | None = None,
    run_id: str = paths.DEFAULT_RUN_ID,
    default_game_id: str | None = None,
):
    """
    Build the operator.

    Leave `output_dir` unset for the per-game layout. Passing it keeps the legacy
    flat `<output_dir>/<task_id>.glb` behaviour.
    """
    from operators.gen_3d_object.operator import Gen3DObjectOperator
    return Gen3DObjectOperator(
        model=model,
        output_dir=output_dir,
        run_id=run_id,
        default_game_id=default_game_id,
    )


def generate(inp: dict, operator) -> dict:
    """Thin wrapper so eval.py can import and reuse."""
    return operator.run(inp)


def run_from_jsonl(tasks_path: str, operator, game_filter: str | None = None) -> list[dict]:
    """Iterate a jsonl file and run each task, optionally restricted to one game."""
    results = []
    for task, game_id in paths.iter_tasks(tasks_path, game_filter=game_filter):
        # A spec task has no image, so logging one would print '?' for the
        # only field that identifies what is being built.
        source = (
            f"spec={task['spec'].get('subject', '?')!r}"
            if task.get("spec") is not None
            else f"image={task.get('image_path', '?')}"
        )
        print(f"[run] game={game_id}  task_id={task.get('task_id', '?')}  {source}")
        result = generate(task, operator)
        if result.get("glb_path"):
            print(f"       → glb={result['glb_path']}  ({result['elapsed_sec']}s)")
        else:
            # A gate refused to write. Reported here rather than left to the
            # caller to notice a None: a task that produced nothing and said
            # nothing is the failure this whole route is shaped against.
            print(f"       → nothing written ({result.get('stop_reason', 'failed')})"
                  f"  ({result['elapsed_sec']}s)")
        for message in result.get("warnings", ()):
            print(f"       ! {message}")
        # Cloud backends record what the call cost and produced (R9.8).
        call = getattr(getattr(operator, "model", None), "last_call_info", None)
        if call:
            print(f"       → task_id={call.get('task_id')}  "
                  f"credits={call.get('credits')}  tris={call.get('triangles')}  "
                  f"cached={call.get('cached')}")
        results.append(result)
    return results


def main():
    import os

    parser = argparse.ArgumentParser(description="Run 3D object generation.")
    parser.add_argument("--backend",   default=os.environ.get("AAAGF_3D_BACKEND", "tripo"),
                        choices=sorted(BACKENDS),
                        help="Model slot backend: a cloud API")
    parser.add_argument("--ckpt",      default=None,
                        help="Model version id. "
                             "Precedence: this flag > env var > backend default")
    parser.add_argument("--cache-dir", default=config.api_cache_dir(),
                        help="Cloud backends: reuse identical requests instead of "
                             "paying for them twice (default: $AAAGF_API_CACHE)")
    parser.add_argument("--low-poly",  action="store_true",
                        help="Cloud backends: ask the service for low-poly "
                             "topology (mesh-particle VFX); better than local decimation")
    parser.add_argument("--format",    default="glb", dest="output_format",
                        help="Cloud backends: output format (meshy also does fbx/obj/usdz)")
    parser.add_argument("--timeout",   type=int, default=1800,
                        help="Cloud backends: seconds to wait for one task")
    parser.add_argument("--game",      default=None,
                        help=f"Game project id. Known: {paths.list_games() or '<none>'}")
    parser.add_argument("--tasks",     default=None,
                        help="Explicit jsonl path (overrides the --game task-list lookup)")
    parser.add_argument("--run-id",    default=paths.DEFAULT_RUN_ID,
                        help="Run directory name; 'auto' for a timestamp")
    parser.add_argument("--out-dir",   default=None,
                        help="Legacy flat output dir; bypasses the per-game layout")
    parser.add_argument("--device",    default="cpu")
    # Single-demo mode
    parser.add_argument("--image",     default=None, help="Path to a single image (demo mode)")
    parser.add_argument("--task-id",   default="demo")
    parser.add_argument("--seed",      type=int, default=42)
    parser.add_argument("--decimation-target", type=int, default=None,
                        help="Target face count for the single-demo run. Maps to "
                             "face_limit (Tripo) / target_polycount (Meshy); the "
                             "operator's default of 1e6 is too large for both")
    args = parser.parse_args()

    run_id = paths.new_run_id() if args.run_id == "auto" else args.run_id

    # A task file of specs needs no model at all, and loading TRELLIS.2 to
    # build a crate would demand a GPU the job does not use — on a CPU box it
    # would fail before reaching the first task. Decided from the tasks
    # themselves rather than from a flag, so the caller cannot get it wrong.
    tasks_path = (
        None if args.image
        else paths.resolve_tasks_path(TASK_KIND, args.tasks, args.game)
    )
    spec_only = False
    if tasks_path is not None:
        tasks = [task for task, _game in paths.iter_tasks(
            str(tasks_path), game_filter=args.game)]
        spec_only = bool(tasks) and all(
            task.get("spec") is not None for task in tasks
        )

    if spec_only:
        # Still true for a spec carrying `mesh` parts. Those read GLBs that
        # already exist on disk, so the generation they needed happened in an
        # earlier run and this one is arithmetic over files — the composition
        # step never calls a model, which is what keeps a 60-part weapon
        # rebuildable in a second on a machine with no GPU.
        print("[run] every task carries a spec: no model loaded, no GPU needed")
        model = None
    else:
        # 在这里就失败，而不是等到第一个任务：云端后端需要 `.env` 里的凭证。
        if args.backend in CLOUD_BACKENDS:
            config.require_cloud_or_exit(
                (args.backend,),
                context=f"3D-object backend {args.backend!r}",
            )

        ckpt = resolve_ckpt(args.backend, args.ckpt)
        backend_kwargs = {}
        if args.backend != "trellis2":
            backend_kwargs = {
                "cache_dir": args.cache_dir,
                "low_poly": args.low_poly,
                "output_format": args.output_format,
                "timeout": args.timeout,
                "verbose": True,
            }
        model = load_model(ckpt, device=args.device,
                           backend=args.backend, **backend_kwargs)

    operator = make_operator(model, output_dir=args.out_dir,
                             run_id=run_id, default_game_id=args.game)

    if args.image:
        # Single demo
        task = {"image_path": args.image, "task_id": args.task_id,
                "seed": args.seed, "game_id": args.game}
        if args.decimation_target:
            task["decimation_target"] = args.decimation_target
        result = generate(task, operator)
        print(f"[run] Done: {result}")
        return

    # Batch from jsonl
    print(f"[run] run_id={run_id}  tasks={paths.rel_to_repo(tasks_path)}")
    results = run_from_jsonl(str(tasks_path), operator, game_filter=args.game)
    if not results:
        print("[run] No matching tasks — nothing to do.")
        return

    if args.out_dir:
        # Legacy flat mode: keep the single summary next to the artifacts.
        summary_path = Path(args.out_dir) / "results_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"[run] Wrote summary → {summary_path}")
    else:
        for p in paths.write_results_summary(results, TASK_KIND, run_id):
            print(f"[run] Wrote summary → {paths.rel_to_repo(p)}")


if __name__ == "__main__":
    main()
