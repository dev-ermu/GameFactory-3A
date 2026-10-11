"""Step functions for the 3D object operator.

Two routes produce a mesh, and they answer different questions:

* :mod:`.asset_pack` - a published CC0 model, for an asset that does not need
  to match a concept (a crate, a calibration target, a rigged mannequin).
* the cloud model behind :mod:`~operators.gen_3d_object.operator` - generated
  from a reference image, for an asset that does.

The declarative part-spec route used to live here too. It was removed because
the meshes it produced were not good enough to ship; the two remaining routes
cover the same ground without that compromise.
"""

from .art_plan import (
    DEFAULT_DECIMATION_TARGET,
    DEFAULT_TEXTURE_SIZE,
    GAME_ART_PLANS,
    GENERATED_FORWARD_AXIS,
    PROMPT_STYLE,
    concept_image,
    describe_plans,
    frame_subject,
    neutral_canvas,
    plan_for_game,
)
from .asset_pack import (
    ASSET_PACK,
    CACHE_ROOT,
    asset_url,
    describe_pack,
    download,
    fetch_asset_pack,
    stage_asset,
)
from .mesh_cleanup import strip_ground_plate

__all__ = [
    "ASSET_PACK",
    "CACHE_ROOT",
    "DEFAULT_DECIMATION_TARGET",
    "DEFAULT_TEXTURE_SIZE",
    "GAME_ART_PLANS",
    "GENERATED_FORWARD_AXIS",
    "PROMPT_STYLE",
    "asset_url",
    "concept_image",
    "describe_pack",
    "describe_plans",
    "download",
    "fetch_asset_pack",
    "frame_subject",
    "neutral_canvas",
    "plan_for_game",
    "stage_asset",
    "strip_ground_plate",
]