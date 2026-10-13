"""
operators/gen_3d_object/operator.py

Gen3DObjectOperator — accepts a loaded model and processes an input dict into a
3D output (GLB file on disk).

The operator is intentionally model-agnostic: you inject any object that
implements the same interface as `TripoModel`.  New model wrappers can be
swapped in without touching this file.

Output layout — two modes, chosen by whether `output_dir` is given:

  * **per-game (default, `output_dir=None`)** — resolved by
    `pipeline.common.paths`, so artifacts are grouped by generated game project::

        outputs/runs/<game_id>/<run_id>/assets/3d_object/<task_id>/
            ├── model.glb
            └── meta.json

  * **flat (legacy, `output_dir="..."`)** — writes `<output_dir>/<task_id>.glb`,
    byte-for-byte the historical behaviour. Existing callers are unaffected.

Usage:
    from models.gen_3d_object.tripo_model import TripoModel
    from operators.gen_3d_object.operator import Gen3DObjectOperator

    model = TripoModel(model_path="v3.1-20260211")

    # per-game layout
    op = Gen3DObjectOperator(model=model, run_id="20260731_1032")

    # legacy flat layout (unchanged)
    op = Gen3DObjectOperator(model=model, output_dir="outputs/3d_object")

    result = op.run({
        "game_id": "gameA_cyberpunk_shooter",   # optional, inferred when omitted
        "task_id": "sword_001",
        "image_path": "path/to/image.png",      # or "image": PIL.Image
        "seed": 42,
    })
    print(result["glb_path"])

One optional extra, additive and off unless asked for:

  * ``run_art_plan(game_id, image_model)`` generates a whole game's
    recorded art plan (``funcs/art_plan.py``) in one call.

A second route skips inference entirely and costs nothing:
``funcs/asset_pack.py`` stages a published CC0 model from the Khronos glTF
sample library as an ordinary task artifact. Reach for it when the asset does
not have to match a concept - a shipping crate, a calibration target, a rigged
mannequin - rather than paying an image-to-3D call to re-derive something
that is already solved::

    from operators.gen_3d_object.funcs import fetch_asset_pack

    fetch_asset_pack(game_id="gameA_cyberpunk_shooter",
                    asset_ids=("box", "xbot"))
"""

import time
from pathlib import Path
from typing import Any, Optional

from PIL import Image

#: Registered task kind for this operator (see pipeline/common/paths.py).
TASK_KIND = "3d_object"

#: Artifact filename used by the per-game layout.
GLB_FILENAME = "model.glb"


class Gen3DObjectOperator:
    """
    Operator for 3D object generation.

    Args:
        model: A loaded model with an `infer_and_save(image, output_path, ...)` method.
               Currently supports TripoModel and MeshyModel; any model with the
               same interface works.
        output_dir (str, optional): **Legacy flat mode.** When given, every GLB is
               written as `<output_dir>/<task_id>.glb`, exactly as before. When
               omitted (default), the per-game layout under
               `outputs/runs/<game_id>/<run_id>/assets/3d_object/<task_id>/`
               is used instead.
        run_id (str): Groups all artifacts of one generation run. Per-game mode only.
        default_game_id (str, optional): Fallback game project for tasks that carry
               no `game_id` and whose input paths reveal none. Per-game mode only.
    """

    def __init__(
        self,
        model: Any,
        output_dir: Optional[str] = None,
        run_id: str = "default",
        default_game_id: Optional[str] = None,
    ):
        self.model = model
        self.run_id = run_id
        self.default_game_id = default_game_id
        # Legacy flat mode is active only when an explicit output_dir is supplied.
        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------

    def _load_image(self, inp: dict) -> Image.Image:
        """Return a PIL image from an input dict that has 'image_path' or 'image'."""
        if "image" in inp and isinstance(inp["image"], Image.Image):
            return inp["image"]
        if "image_path" in inp:
            p = Path(inp["image_path"])
            if not p.is_absolute() and not p.exists():
                # resolve relative to repo root (codes_official/)
                repo_root = Path(__file__).resolve().parents[2]
                p = repo_root / inp["image_path"]
            return Image.open(str(p)).convert("RGBA")
        raise ValueError("Input must contain 'image_path' (str) or 'image' (PIL.Image).")

    # --------------------------------------------------------------------------

    def _artifact_suffix(self) -> str:
        """
        File extension for the artifact — GLB unless the injected model says
        otherwise (the cloud backends can emit FBX / OBJ / USDZ).

        The result dict keeps the ``glb_path`` key whatever the extension is:
        renaming a returned key breaks `eval.py` and `test/`.
        """
        fmt = getattr(self.model, "output_format", None)
        return str(fmt).lower().lstrip(".") if fmt else "glb"

    def _resolve_out_path(self, inp: dict, task_id: str) -> tuple[str, Path, Path]:
        """
        Return ``(game_id, task_dir, glb_path)`` for either output mode.

        Legacy flat mode keeps the historical `<output_dir>/<task_id>.glb`.
        """
        suffix = self._artifact_suffix()
        if self.output_dir is not None:
            game_id = str(inp.get("game_id") or inp.get("game") or "")
            return game_id, self.output_dir, self.output_dir / f"{task_id}.{suffix}"

        from pipeline.common import paths
        game_id = paths.infer_game_id(inp, fallback=self.default_game_id)
        task_dir = paths.task_output_dir(game_id, TASK_KIND, task_id, run_id=self.run_id)
        filename = GLB_FILENAME if suffix == "glb" else f"model.{suffix}"
        return game_id, task_dir, task_dir / filename

    # --------------------------------------------------------------------------

    def run(self, inp: dict) -> dict:
        """
        Generate a 3D object from a reference image.

        Args:
            inp (dict):
                - image_path (str): path to the reference / concept image
                  OR image (PIL.Image): pre-loaded image
                - game_id (str, optional): game project this task belongs to;
                  inferred from `image_path` when omitted
                - task_id (str, optional): used to name the output file / directory
                - seed (int, optional): random seed (default 42)
                - decimation_target (int, optional)
                - texture_size (int, optional)

        Returns:
            dict:
                - task_id (str)
                - glb_path (str): absolute path to the saved GLB file
                - elapsed_sec (float)
                - game_id (str), task_kind (str), output_dir (str)  ← additive

        For a mesh that does not need to match a concept, use
        `funcs.asset_pack.fetch_asset_pack` instead: it costs nothing and reuses
        a published CC0 model rather than deriving a new one.
        """
        task_id = inp.get("task_id", f"task_{int(time.time())}")
        seed = inp.get("seed", 42)
        decimation_target = inp.get("decimation_target", 1_000_000)
        texture_size = inp.get("texture_size", 4096)

        game_id, task_dir, out_path = self._resolve_out_path(inp, task_id)

        image = self._load_image(inp)

        t0 = time.time()
        glb_path = self.model.infer_and_save(
            image,
            output_path=str(out_path),
            seed=seed,
            decimation_target=decimation_target,
            texture_size=texture_size,
        )
        elapsed = time.time() - t0

        result = {
            "task_id": task_id,
            "glb_path": glb_path,
            "elapsed_sec": round(elapsed, 2),
            "game_id": game_id,
            "task_kind": TASK_KIND,
            "output_dir": str(task_dir),
        }

        # Image-to-3D infers a floor under a subject that stands on the edge
        # of its own crop, and it is never wanted: measured at a fifth of the
        # triangle budget, and a grey pancake under the character in the
        # scene. Removing it here means every consumer of this task output
        # gets a clean mesh, rather than each game discovering the slab.
        if inp.get("strip_ground_plate", True):
            from .funcs.mesh_cleanup import strip_ground_plate

            cleanup = strip_ground_plate(glb_path)
            result["ground_plate"] = cleanup
            if cleanup.get("applied"):
                result.setdefault("warnings", []).append(
                    f"removed an inferred floor: {cleanup['plate_count']} "
                    f"sheets and {cleanup['debris_count']} loose lumps, "
                    f"{cleanup['removed_fraction']:.0%} of the mesh"
                )
            elif cleanup.get("reason") and "nothing" not in cleanup["reason"]:
                result.setdefault("warnings", []).append(
                    f"left the mesh alone: {cleanup['reason']}"
                )

        # meta.json only in per-game mode, so legacy output dirs stay untouched.
        if self.output_dir is None:
            from pipeline.common import paths
            meta = {
                **result,
                "run_id": self.run_id,
                "prompt": inp.get("prompt"),
                "source_image": inp.get("image_path"),
                "seed": seed,
                "decimation_target": decimation_target,
                "texture_size": texture_size,
                "model": type(self.model).__name__,
            }
            for key in ("asset_id", "asset_type", "forward_axis",
                        "scale_hint_metres", "notes"):
                if inp.get(key) is not None:
                    meta[key] = inp[key]
            # Cloud backends expose what the call cost and produced — task id,
            # credits, triangle count (model_require.md R6–R8.8). Recording it
            # here is what makes a billed run reproducible after the fact.
            call_info = getattr(self.model, "last_call_info", None)
            if call_info:
                meta["model_call"] = dict(call_info)
            paths.write_task_meta(task_dir, meta)

        return result

    # --------------------------------------------------------------------------

    def run_art_plan(
        self,
        game_id: str,
        image_model: Any = None,
        plan: Optional[list[dict]] = None,
        assets: tuple[str, ...] = (),
    ) -> list[dict]:
        """
        Generate a game's recorded art plan and import each asset.

        The plan lives in `funcs/art_plan.py`; it names a subject, an asset
        type and a **height in metres**, because a mesh normalised into a
        unit box has no size of its own. Concept images come from
        `image_model` unless an entry points at one.

        Facing is recorded as `heuristic`, never as verified: single-image
        reconstruction puts the input view on a predictable axis, but a
        guess labelled as checked stops anyone checking. Each import leaves
        a review sheet for `agent_skills/asset_qa/`.
        """
        from .funcs.art_plan import concept_image, plan_for_game

        entries = plan if plan is not None else plan_for_game(game_id)
        if not entries:
            raise ValueError(
                f"No art plan for {game_id!r}; add one to "
                "operators/gen_3d_object/funcs/art_plan.py"
            )

        results: list[dict] = []
        for entry in entries:
            if assets and entry["asset_id"] not in assets:
                continue
            image, provenance, framing = concept_image(entry, image_model)
            task_dir = Path(
                self._resolve_out_path(
                    {"game_id": game_id}, entry["task_id"]
                )[1]
            )
            task_dir.mkdir(parents=True, exist_ok=True)
            # Keep the concept image beside the mesh it produced: a bad
            # asset is almost always a bad concept image, and that is not
            # diagnosable after the fact if the input was thrown away.
            image.save(task_dir / "concept.png")
            result = self.run(
                {
                    "game_id": game_id,
                    "task_id": entry["task_id"],
                    "image": image,
                    "prompt": entry["full_prompt"],
                    "seed": entry.get("seed", 42),
                    "decimation_target": entry["triangles"],
                    "texture_size": entry["texture"],
                    "asset_id": entry["asset_id"],
                    "asset_type": entry["type"],
                    "forward_axis": entry["faces"],
                    "scale_hint_metres": entry["height"],
                    "verified_by": "heuristic",
                    "notes": entry["notes"]
                    or f"Generated from: {provenance}. Facing assumed "
                    "from the input view.",
                }
            )
            result["asset_id"] = entry["asset_id"]
            result["concept_source"] = provenance
            result["framing"] = framing
            if framing.get("touched_border"):
                # The subject ran off the edge of the generated image, so
                # part of it was never drawn. Cropping cannot invent it.
                result.setdefault("warnings", []).append(
                    "the concept image was cropped at the border, so the "
                    "mesh is probably truncated: regenerate with another "
                    "seed"
                )
            results.append(result)
        return results

    # --------------------------------------------------------------------------

    def run_batch(self, inputs: list[dict]) -> list[dict]:
        """Run a list of input dicts sequentially and return results."""
        return [self.run(inp) for inp in inputs]
