"""Human figures and what they wear: the NESTED topology.

A body is a *host*. Armour worn on it takes its curvature from a torso, so the
plates cannot be placed until the body exists and has been measured — which is
the structural fact that decides the route, and the reason this is a topology
rather than an adjective. The host is generated, the layers are stated, and the
two are fitted together here. That split *is* the hybrid route.

WHY THE WEARER WORDS LIVE HERE. They were `wearers` and `worn_items` in a
central lexicon, next to `hard_surface`, being counted against it — and one
word, "armour", outvoted the knight wearing it, routing "female knight in plate
armour" to `code` at 0.9 confidence. Two problems, both fixed by locality: a
wearer is not the opposite of a hard surface, and the package that knows what a
pauldron is should be the package that ships one. Everything about dressing a
figure is in this one directory now — the vocabulary, the anatomy, the
measuring, the fitting.

WHAT IS HERE:

`humanoid`
    A *stated* body, from nominal proportions. No network, no generator.

`figure_fit`
    The other half: *measures* the same landmark names off a generated mesh.
    Its numbers differ from `humanoid`'s by up to 0.157 m at the same nominal
    height, because a generated body has its own proportions. The names match
    on purpose, so a kit written against one fits with the other — but only
    while it is clear which is which. Fitting to a mesh with nominal numbers
    puts the plates where the body is not.

`plate_armour`
    A harness, each piece naming the limb it is worn on and nothing else. Any
    figure providing those part ids can wear it.

`armour_fit`
    Scales and places each piece against measured landmarks — which shin, how
    big, and where.

A stated body, dressed:

    from operators.gen_3d_object.funcs.code_asset_templates import compose
    from operators.gen_3d_object.funcs.code_asset_templates.human_template import (
        humanoid, plate_armour)

    spec = compose.compose(
        subject="female knight",
        body=humanoid.body_parts(),
        worn=plate_armour.plate_armour() + plate_armour.sword(),
        height_metres=humanoid.LANDMARKS["height"],
    )

A generated body, measured and dressed — the order reverses:

    marks = figure_fit.landmarks_for("parts/tpose.glb", height_metres=1.72)
    parts = [armour_fit.body_part("parts/tpose.glb", height_metres=1.72)]
    parts += armour_fit.fit_armour(body_id="figure", landmarks=marks, pieces=[
        {"id": "greave-l", "source": "parts/greave.glb", "slot": "shin",
         "side": "l", "span": 0.30},
    ])
"""

import re

from .. import routing
from . import armour_fit, figure_fit, humanoid, plate_armour

__all__ = [
    "HOSTS",
    "LAYERS",
    "armour_fit",
    "claim",
    "figure_fit",
    "humanoid",
    "plate_armour",
]

#: Words naming a *wearer* — a host that has to exist before anything can be
#: put on it. Matched as whole words: "man" is inside "human", and substring
#: matching sent "human face" down this branch and reported it as somebody
#: wearing kit. A wearer word inside another word is not a wearer.
HOSTS = (
    "knight", "warrior", "soldier", "character", "person", "people",
    "figure", "woman", "women", "man", "men", "girl", "boy", "lady",
    "elf", "orc", "dwarf", "goblin", "human", "humanoid",
    "rider", "pilot", "hero", "heroine", "villain", "guard", "mage",
    "archer", "paladin", "berserker", "assassin", "monk", "priest",
)

#: Words naming something a host *wears*. Kept because a layer word is what
#: makes a subject the kit rather than the wearer — see :func:`claim` for how
#: that is decided, which is by position and not by presence.
LAYERS = (
    "helmet", "helm", "cuirass", "breastplate", "pauldron", "gauntlet",
    "greave", "greaves", "vambrace", "bracer", "sabaton", "boot", "boots",
    "shield", "sword", "blade", "axe", "hammer", "spear", "lance", "bow",
    "cape", "cloak", "belt", "armour", "armor", "plate", "mail",
    "tunic", "robe", "hood", "mask", "visor", "crown", "circlet",
)

#: Prepositions that mark what follows as *worn*, which makes the host the head
#: of the phrase however many layer words come after it.
#:
#: This is what tells "female knight in plate armour" from "knight helmet". The
#: first is a knight — "in plate armour" modifies him — and the second is a
#: helmet. Deciding on the mere *presence* of a layer word cannot tell them
#: apart, and getting that wrong reintroduces the original defect: "armour" and
#: "plate" are also rigid-assembly words, so the rigid strategy took the subject
#: unopposed and a knight in plate routed to `code` at 0.9 confidence.
WEARING = ("in", "with", "wearing", "clad", "holding", "carrying", "bearing",
           "wields", "wielding", "armed")


def claim(subject: str, asset_type: str = "prop") -> routing.Claim | None:
    """Claim ``subject`` as a figure wearing things, or decline.

    A host word alone is not enough: it has to be what the phrase is *about*.
    Two ways that holds, and everything else declines —

    * a wearing preposition follows the host, so the layers modify it:
      "female knight **in** plate armour" is a knight;
    * the host is the head noun, i.e. the last word: "woman knight",
      "armoured warrior".

    Otherwise the host word is itself a modifier and the subject is something
    else — "knight helmet" is a helmet, "human face" is a face. Declining
    outright rather than claiming weakly, because a weak claim still competes,
    and competing would make a helmet *ambiguous* instead of letting the rigid
    strategy have it cleanly.

    Reports :data:`~..routing.STRUCTURAL`, so a claim here is not outvoted by
    counted evidence. A knight in plate is a knight however hard-surfaced the
    plate is, and letting word counts settle that was the original bug.
    """

    # Word order matters here, so the subject is tokenised in sequence rather
    # than as the set the other strategies use. ``asset_type`` is deliberately
    # excluded: appending "avatar" would put a host-like word at the end of
    # every subject and make the head-noun test always succeed.
    tokens = re.findall(r"[a-z]+", subject.lower())
    if not tokens:
        return None

    hosts = tuple(word for word in HOSTS if word in set(tokens))
    if not hosts:
        return None

    first_host = next(index for index, word in enumerate(tokens)
                      if word in HOSTS)
    wears = any(word in WEARING for word in tokens[first_host + 1:])
    is_head = tokens[-1] in HOSTS

    if not (wears or is_head):
        return None

    return routing.Claim(
        topology=routing.NESTED,
        strength=float(len(hosts)),
        evidence=hosts,
        tier=routing.STRUCTURAL,
        builder="operators.gen_3d_object.funcs.code_asset_templates.human_template",
        detail={"hosts": hosts,
                "layers": tuple(word for word in LAYERS if word in set(tokens))},
        reason=(
            f"{subject!r} names someone who wears the kit ({', '.join(hosts)}), "
            "not the kit. A figure is a host: its plates take their curvature "
            "from a torso, and a torso is not arithmetic over primitives — so "
            "generate the body, measure it with `figure_fit.landmarks_for`, and "
            "state each piece onto the measured landmarks with "
            "`armour_fit.fit_armour`. Each piece on its own still routes to "
            "`code`, which is what makes this the hybrid route rather than a "
            "refusal."
        ),
    )


routing.register("human", claim)
