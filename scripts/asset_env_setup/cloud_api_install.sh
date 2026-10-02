#!/bin/bash
# Shared implementation for task-specific cloud API installers.
# Environment for the closed-source ("cloud API") model wrappers:
#   models/gen_3d_object/tripo_model.py
#   models/gen_3d_object/meshy_model.py
#   models/gen_audio/seed_audio_model.py
#   models/gen_image/seedream_model.py
#   models/gen_cg_video/seedance_model.py
#   models/gen_cg_video/minimax_h3_model.py
# via the shared plumbing in models/common/cloud_api.py
#
# These wrappers run anywhere Python runs: no GPU, no weights, no compiled
# extensions. The whole dependency is an HTTP client.
#
# This is the shared implementation. Invoke a task-specific wrapper instead:
#   bash scripts/asset_env_setup/3d_object/cloud_api_install.sh
#   bash scripts/asset_env_setup/image/cloud_api_install.sh
#   bash scripts/asset_env_setup/audio/cloud_api_install.sh --conda
#   bash scripts/asset_env_setup/cg_video/cloud_api_install.sh

set -e

if [ "$1" == "--conda" ]; then
    conda create -n aaagf_api python=3.10 -y
    # shellcheck disable=SC1091
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate aaagf_api
fi

# The API wrappers themselves.
python -m pip install requests

# The CPU-only development harness (tests/harness/smoke.py, the offline contract
# tests). Already present in most envs; listed so a bare env works.
python -m pip install pillow numpy scipy

echo
echo "Done. Now configure the project in ONE place:"
echo "  cp .env.example .env"
echo "  # then edit .env and fill in, for whichever backend you use:"
echo "  #   TRIPO_API_BASE / TRIPO_API_KEY          3D objects (Tripo)"
echo "  #   MESHY_API_BASE / MESHY_API_KEY          3D objects (Meshy)"
echo "  #   ARK_API_BASE / ARK_API_KEY              image (Seedream) + video (Seedance)"
echo "  #   SEED_AUDIO_API_BASE / SEED_AUDIO_API_KEY  dialogue + sound effects"
echo "  #   MINIMAX_API_BASE / MINIMAX_API_KEY      video (Hailuo)"
echo "  #   TOKENHUB_API_BASE / TOKENHUB_API_KEY    cloud rigging / animation"
echo "  # The API base URL is REQUIRED, not defaulted: the public endpoint is"
echo "  # not reachable from every network."
echo
echo "Verify without spending credits or touching the network:"
echo "  python tests/harness/smoke.py --kind 3d_object --backend tripo"
echo "  python tests/test_api_3d_object.py"
echo "  python tests/harness/smoke.py --kind tpose --backend seedream"
echo "  python tests/test_api_gen_tpose_image.py"
echo "  python tests/harness/smoke.py --kind audio --backend seed_audio"
echo "  python tests/test_api_audio.py"
echo "  python tests/harness/smoke.py --kind cg_video --backend seedance"
echo "  python tests/harness/smoke.py --kind cg_video --backend minimax-h3"
echo
echo "Check a balance (free, needs a key):"
echo "  python -c \"from models.gen_3d_object import TripoModel; print(TripoModel().balance())\""
