"""Subjects with no assembly to describe.

The third topology, and the only one with no builder: a face, a tree, hair,
cloth. These are not made of parts joined together and they are not layers on a
host — the surface *is* the object, so there is nothing for a spec to state.
The honest answer is `generate`.

WHY THIS IS A MODULE AND NOT A `*_template` PACKAGE. The other two strategies
sit beside the code that builds what they claim; this one has nothing to build.
Giving it a `_template` directory would promise a builder that is never coming.
It is a strategy and only a strategy.

WHY IT CLAIMS AT ALL, INSTEAD OF LETTING THESE FALL THROUGH. Two reasons.
Declining early is cheap and a procedurally "described" face is not — the
correction loop costs a full build to discover what one word could have said.
And an unclaimed subject is genuinely unknown, which is a different answer:
"zorblatt" should say "no strategy recognises this", while "oak tree" should
say "this is a surface, generate it". Collapsing the two would report a missing
strategy as a considered judgement.
"""

from . import routing

__all__ = ["SUBJECTS", "claim"]

#: Subjects for which a spec is the wrong tool. Whole-word matched, so
#: "treeline" is not a tree and "handle" is not a hand — both of which are
#: assemblies, and both of which substring matching sent here.
SUBJECTS = (
    "face", "head", "hair", "skin", "creature", "monster", "animal",
    "beast", "tree", "foliage", "leaf", "leaves", "plant", "flower", "grass",
    "cloth", "fabric", "drape", "flag", "banner", "hand", "body",
    "muscle", "organic", "flesh", "rock", "terrain", "cliff", "moss",
    "fur", "feather", "scale", "scales", "wing", "tentacle", "vine",
)


def claim(subject: str, asset_type: str = "prop") -> routing.Claim | None:
    """Claim ``subject`` as an inseparable surface, or decline."""

    seen = routing.words(f"{subject} {asset_type}")
    found = tuple(word for word in SUBJECTS if word in seen)
    if not found:
        return None

    return routing.Claim(
        topology=routing.SURFACE,
        strength=float(len(found)),
        evidence=found,
        reason=(
            f"{subject!r} reads as organic ({', '.join(found)}): one "
            "inseparable surface rather than parts joined together. A spec "
            "describes arithmetic over primitives, which is the wrong tool when "
            "the surface is the point of the asset — use image-to-3D and review "
            "the mesh."
        ),
    )


routing.register("surface", claim)
