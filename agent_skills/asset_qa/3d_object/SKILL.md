# Generated Asset Review

根据与方向审核相同的渲染图纸，判断生成的网格是否适合在浏览器游戏中使用。

生成模型旨在优化与某张图像的相似度。但游戏还需要其他许多图像转3D指标无法衡量的要素，而这些要素在五个正交视图中都能看到。请在`Gen3DObjectOperator.run_art_plan`执行完毕后，立即在`result["preview_sheet"]`对应的图纸上运行此流程。

## Choose The Route First

共有三条路径用于生成3D资产，成本最低的路径将被采用：

| Route | Use when | Cost |
|---|---|---|
| **Spec** (`operators/gen_3d_object/funcs/code_asset.py`) | 物体可被精确描述——如箱子、标识牌、车轮、步枪、栏杆 | 仅需数秒，无需GPU，无需调用API服务 |
| **Asset pack** (`operators/gen_3d_object/funcs/asset_pack.py`) | a CC0 model of it already exists | seconds, one download |

`suits_code_asset(subject)` returns `code`, `generate` or `ambiguous`. It
declines rather than guesses: a procedurally "described" face wastes a
correction loop discovering what one call could have said.

It decides by **how a subject assembles**, not by whether it sounds
hard-surfaced — a rifle and a suit of armour are both hard-surfaced and route
differently:

| Topology | Means | Route |
|---|---|---|
| `composed` | parts sit beside each other, joined by adjacency — a rifle, a car | `code` |
| `nested` | layers sit on a host that must exist and be measured first — armour on a body | `generate` the host, state the layers (hybrid) |
| `surface` | one inseparable surface, no assembly — a face, a tree | `generate` |

The result also carries `topology`, `claimed_by` and `builder`, which is what
a hybrid build acts on: a `nested` claim names the module that fits the layers
onto the generated host.

**Prefer a spec for rigid assemblies** — a race car, a pistol, anything whose
parts hold a fixed structure. **Generate a figure whole:** composing one burns
iterations for a worse result — the composed knight took 8 human-agent rounds
over 12 hours to come out roughly right — so send a character straight to an
image-to-3D model instead. See
`<REPO_PATH>/agent_skills/asset_qa/3d_object/composition_examples.md`.

**Adding a domain is registering a strategy, not editing the router.** Each
package under `funcs/code_asset_templates/` owns the vocabulary for what it can
build, so a project with its own nouns ships a package instead of editing a
central word list:

```python
from operators.gen_3d_object.funcs.code_asset_templates import routing

def claim(subject, asset_type="prop"):
    if "zorblatt" not in routing.words(subject):
        return None
    return routing.Claim(topology=routing.COMPOSED, strength=1.0,
                         evidence=("zorblatt",), reason="a stack of plates")

routing.register("zorblatt", claim)
```

Pass `strategies=[(name, fn), ...]` to route against your own taxonomy for one
call without touching the registry.

For hard-surface work a spec is not a downgrade — it states three things
generation can only guess:

- **facing** (`forward`), so the import records `verified_by="spec"` rather
  than `heuristic`;
- **size** (`height_metres`), where a generated mesh arrives normalised
  into a unit box with no size of its own;
- **parts**, each a named glTF node, so a wheel can still spin. A generated
  mesh is one fused body.

Every route still gets reviewed — skip to *The Five Checks* once a mesh
exists.

### Or Both: Composing Generated Parts

The routes are not exclusive. A `mesh` part reads a GLB off disk — one
component from a cloud model — and is then placed, measured and gated
exactly like a primitive. **The division is not a matter of taste:**

| Generate | State as a primitive |
|---|---|
| shapes no formula gives — a grip's finger swells, a car's panel creases | anything with an exact dimension — a rail's slot pitch, a barrel's diameters |
| where the surface *is* the asset | anything that must stay separable, e.g. a wheel that turns |

Getting it backwards is the easy mistake: generating a rifle scope cost
**19,982 triangles** — three times the whole rifle's primitive geometry —
for a softened stepped tube a nine-point `lathe` states exactly, and unlike
the lathe it cannot then be fixed by changing a number.

```python
{"id": "grip", "kind": "mesh",
 "source": "parts/grip.glb",       # required, must exist at validation
 "size": [0.116, 0.116, 0.116],    # uniform: see below
 "at": [0, 0.045, -0.104], "rotation": [0, 90, 0],
 "long_axis": "y"}                 # optional; checked against the vertices
```

**`size` is a request, not an extent.** The mesh is fitted by one factor so
it keeps its proportions — stretching a moulded grip to fill a box is worse
than a grip 4 mm thinner than intended. Write one number three times to say
so deliberately; `provenance` warns otherwise and reports `actual_extent`
for placing neighbours.

**Measure the facing, never assume it.** Nothing in a fetched file says
which of its axes is length. The rifle grip's flange spans *x*, so it needs
`rotation: [0, 90, 0]`; rotating about x — the intuitive "rake it back" —
tilts it in the plane it is already flat in. Declare `long_axis` and the
`orientation` gate checks the placed vertices. **A regenerated part is new
axes**: the same grip re-fetched needed `+90` where it had needed `-90`.

Consequently `verified_by` drops to `spec+generated` — the placement was
stated, the mesh inside it asserted.

`<REPO_PATH>/agent_skills/asset_qa/3d_object/composition_examples.md` shows all
three subjects built both ways, side by side.

### Textures Come Across

UVs and the base-colour image travel into the output, self-contained and
shared between placements (four wheels off one source, one atlas). Two
things to know:

- **Primitives get no UVs**, because arbitrary ones sample an arbitrary
  corner of somebody else's atlas.
- **Only base colour is taken.** When the source has a metallic-roughness
  *map*, its factors are replaced with dielectric defaults, not inherited:
  they sit at glTF's default `1.0` to multiply that map, so copying them
  without it renders a polymer grip as sandblasted steel. Flagged
  `factors_from: "assumed"`.

**Textured parts are expensive and `budget` says so.** The first textured
grip was 12,213 triangles, putting the rifle at 22,247 against a budget of
20,000 — refused, correctly. Re-fetch at a lower `decimation_target`; a grip
whose detail is in the atlas does not need twelve thousand triangles.

### What Generation Will Not Do On Request

A prompt is a request, not a constraint. Three fetches asked for a car body
with no wheels — `NO WHEELS` stated three ways, then arches as the subject —
and returned wheels twice and a single arch once, because a car has wheels
in everything the model has seen.

So plan around it: ask for a *part* rather than a de-featured whole, and keep
anything that must be separable or exactly placed on the primitive side. For
the car, the arches moved into the spec, derived from the same constants as
the wheels — an arch at `HALF_TRACK, WHEELBASE` cannot be misaligned with a
wheel at `HALF_TRACK, WHEELBASE`, which is a guarantee a fetched mesh cannot
offer.

**A figure is not its armour.** A host word (`knight`, `warrior`, `woman`)
routes to `nested` when the phrase is *about* the host — either a wearing
preposition follows it ("knight **in** plate armour") or it is the head noun
("woman knight"). Each piece on its own still routes to `code`, because there
the host word is a modifier: "knight helmet" is a helmet. That split is the
hybrid route — generate the body, state the greaves and the sword.

Presence of a kit word cannot make this call, and trying was the original bug:
`armour` and `plate` are rigid-assembly words too, so "female knight in plate
armour" went to `code` at 0.9 confidence on the strength of the armour rather
than the knight wearing it.

## Building From A Spec

```python
op = Gen3DObjectOperator(model=None, run_id="20260826_1400")   # no model needed
result = op.run({
    "game_id": "gameA_cyberpunk_shooter",
    "task_id": "crate_001",
    "asset_id": "supply_crate",
    "spec": {
        "subject": "wooden supply crate",
        "units": "metres",          # required, no default
        "forward": "+z",            # required, no default
        "asset_type": "prop",
        "height_metres": 0.6,
        "materials": {"wood": {"baseColor": [0.45, 0.30, 0.18, 1],
                               "roughness": 0.85}},
        "parts": [
            {"id": "body", "kind": "box",
             "size": [0.6, 0.6, 0.6], "at": [0, 0.3, 0], "material": "wood"},
        ],
    },
})
```

`units` and `forward` have no defaults, because an assumed facing is the
defect `orientation_review.md` exists to catch: it reads as correct until
the asset is in a scene walking backwards.

Part kinds: `box`, `cylinder`, `cone`, `sphere`, `torus`, `lathe`,
`extrude`, `mesh`. `lathe` revolves a `(radius, height)` profile — bottles,
blades, turned legs; `extrude` pushes a closed `(x, y)` outline along Z;
`mesh` reads a GLB (see *Or Both*). Any part may carry `parent` and
`attach` (see *Relations*). `segments` is the triangle-budget dial
on round parts, and `chamfer` (0–0.5, a fraction of the half-extent) cuts a
box's edges back — a sharp edge catches light as one hard line, which is
what makes a box read as a toy brick.

### Relations, Not Coordinates

Two fields turn a parts list into a structure, and both are resolved before
any gate runs:

| Field | Says | Use for |
|---|---|---|
| `parent` | this part is a child of that one | armour on a limb, a wheel on an axle |
| `attach` | put my face against theirs | anything that sits on, hangs under or butts against something |

```python
{"id": "vambrace-l", "kind": "cylinder", "size": [0.105, 0.16, 0.105],
 "parent": "forearm-l", "at": [0, 0.01, 0]}          # local to the forearm

{"id": "muzzle", "kind": "lathe", "profile": [...],
 "attach": {"to": "barrel", "axis": "z", "gap": 0.0}}  # solved, not measured
```

**`attach` exists because absolute placement goes stale.** Every gap in the
assets here was one: a muzzle 9 mm off its barrel, a sabaton 16 mm under a
shin, a sling loop 26 mm past a rail — each found by `connectivity`, measured
by hand, and fixed with a number that went stale when a neighbour moved. It
also handles a *rotated* target, whose occupied extent is not its `size`.

Faces are `min`/`mid`/`max`, defaulting to opposing (`my: "min"`,
`their: "max"` — sitting on top). `gap` separates, `offset` shifts along the
other two axes.

**`parent` becomes a glTF node child**, so the hierarchy survives export: an
engine rotating `forearm-l` carries the vambrace. Without it a named part is
addressable but not connected, and posing a figure means recomputing every
plate. Declaration order does not matter — the resolver walks the dependency
graph and refuses a cycle by name.

### Compose From Templates, Don't Script It

`funcs/code_asset_templates/` holds figures, kits and joining mechanisms as
**inputs the operator reads**, not arrangements it performs. It is organised by
topology:

| Path | Holds |
|---|---|
| `routing.py` | the registry and `Claim` — mechanism, no vocabulary |
| `compose.py` | parts + materials into a spec — used by every route |
| `assembly.py` | joining by `attach`: `chain`, `group`, `mirrored` |
| `rigid_template/` | 拼接刚体: claims `composed`, its own vocabulary |
| `human_template/` | figures and what they wear: claims `nested` |
| `surface.py` | claims `surface`; a strategy only, it builds nothing |

For a figure, composition is a body plus what it wears, in that order, because
armour worn on a limb has to move with it:

```python
from operators.gen_3d_object.funcs.code_asset_templates import compose
from operators.gen_3d_object.funcs.code_asset_templates.human_template import (
    humanoid, plate_armour)

spec = compose.compose(
    subject="female knight",
    body=humanoid.body_parts(),                   # nested limbs
    worn=plate_armour.plate_armour()              # each piece parents to a limb
         + plate_armour.sword(),
    height_metres=humanoid.LANDMARKS["height"],
)
```

For a composed subject, state the parts and let `assembly` join them — a solved
relation does not go stale when a neighbour changes size:

```python
from operators.gen_3d_object.funcs.code_asset_templates import assembly

parts = assembly.chain([receiver, barrel, muzzle])          # front to back
parts += assembly.group(wheels, to="chassis")               # hub, not a chain
parts += assembly.mirrored([skid], axis="x")                # both sides, once
```

`chain` leaves a part that already carries `attach` or `parent` alone, so a
branch is stated and the rest chained. Per-link overrides go in a `link` dict
(`axis`, `gap`, `my`, `their`, `offset`), which is stripped before validation.

**The spec and hybrid routes differ by one argument**, which is the test of
whether composition is really data:

```python
    replace={"head": {"kind": "mesh", "source": "parts/head.glb",
                      "size": [0.27] * 3, "long_axis": "y"}},
```

`replace` merges rather than overwrites, so a generated head keeps the
attachment that made it a head. `drop` removes parts. Removing a limb that
something is wearing is refused **by name** before the resolver runs — a
dangling parent reported from inside a graph walk names the wrong thing.

Write a new figure as a template beside these, not as a script under
`test_data`. A build script chooses *which* pieces and *what* the materials
mean; anatomy and harness belong in a template so the next figure is a
configuration. Part *tables* — a rifle's chamber, a car's wheelbase — are
content and stay with the build that wants them.

**A `lathe` profile must start and end at radius 0.** Otherwise the revolved
surface is a pipe with open ends: no interior, and a hole you see through
once something is behind it. Refused at validation, because unlike a
proportion there is no version of this that was intended. Profiles may be
traced in either direction — the writer normalises by signed area, so there
is no winding rule to remember.

### Gates, Run Before Any Renderer

Eight checks run on the spec's own geometry, so a defect is found on points
rather than after a render. All report together, so one pass gives the
whole list.

| Gate | Catches | Blocks? |
|---|---|---|
| `solidity` | a part thin enough to vanish edge-on | yes |
| `chirality` | a `-l`/`-r` pair that is a rotation, not a mirror | yes |
| `scale` | parts disagreeing with `height_metres`, or a misplaced decimal | yes |
| `budget` | more triangles than the role allows | yes |
| `connectivity` | a part touching nothing else | no — reported |
| `provenance` | what was delegated to a generator, and at what cost | only if it is really a generated asset |
| `orientation` | a fetched part whose long axis is not where it was declared | no — reported |
| `windings` | an inside-out or unclosed part | yes for a primitive, reported for a fetched mesh |

**Chirality is the one to understand**, because its failure looks tidy.
Negating *two* axes is a 180-degree rotation, and rotation preserves
handedness — both halves come out as the same hand. Measured in
[img2threejs](https://github.com/img2threejs/img2threejs): z `+0.288` against
`-0.288`, where a mirror leaves z alone. **Negate the lateral axis only.** Any
left/right pair — headlights, wing mirrors, sling swivels — is one sign error
from this.

**`windings` is the only gate that evaluates the mesh**, and it exists
because four primitives once shipped inside-out while every other gate
passed them: the GLB was valid, the counts matched, the bounds were right,
and a viewer that does not cull backfaces shades an inverted solid
identically. It would have appeared first inside an engine. Review a mesh
with backface culling **on**, for the same reason.

`connectivity` only reports: a hovering crystal is a design, and failing it
would make the gate wrong for a whole class of asset. `provenance` mostly
reports too — it fails only when the composition is *mostly* generated
parts *and* triangles, at which point it is a generated asset with
primitives attached and should go through an orientation review rather than
inherit a spec's label. An unclosed *fetched* mesh is likewise reported and
not failed: no spec edit repairs it, and a gate that blocks work nobody can
fix gets bypassed.

A failed gate writes **nothing** and hands nothing to the engine — an asset
that exists gets used. `strict=False` only to inspect a bad mesh.

### Correcting A Spec

Pass `revise(spec, failures) -> spec` to let a model fix its own defects.
The loop stops at three attempts, or earlier on `repeating`, `oscillating`,
`no_progress` or `revise_failed`; `result["stop_reason"]` says which. An
unbounded loop in [img2threejs](https://github.com/img2threejs/img2threejs)
spent 45 minutes recording a car that never moved, because a lookup returned
`None` and the loop optimised a metric that could not see it.

**Read `stop_reason` before re-running.** `repeating` means the revision
addressed nothing, so a fourth attempt is the third attempt.

## Environment setup

A spec needs no environment at all — pure standard library, no GPU, no
key. Set up only the generation route you actually chose:

```bash
# Cloud 3D backends such as Tripo and Meshy
bash scripts/asset_env_setup/3d_object/cloud_api_install.sh

```

Use only the selected route. Keep API keys in environment variables and large

the more reliable route for game-ready meshes. They are paid, so before the first
call **pause and follow *Paid cloud backend* in
`<REPO_PATH>/agent_skills/asset_qa/README.md`**: recommend the provider, send the
purchase/API-key page (<https://platform.tripo3d.ai/api-keys> or
<https://www.meshy.ai/api>), state the estimated cost for the planned mesh count
including regeneration attempts, ask the user to buy access and supply
`TRIPO_API_KEY` / `MESHY_API_KEY`, and wait for an explicit answer. Use local

## Which Formats Each Engine Accepts

Read from each adapter's own importer, so this is what will actually load:

| Engine | Accepted mesh formats |
|---|---|
| UE5 | `fbx` `glb` `gltf` `obj` `usd` `usda` `usdz` |
| Blender | `abc` `fbx` `glb` `gltf` `obj` `ply` `usd` `usda` `usdc` `usdz` |
| Unity | `fbx` `glb` `gltf` `obj` |
| three.js | `glb` `gltf` |

**glTF is the intersection, so target `.glb`.** Every route here already
does. The one consequence worth knowing: three.js accepts *only* glTF, so an
FBX from a cloud backend needs converting before it reaches a browser game,
while the same file imports into UE5 or Unity untouched.

Prefer `.glb` over `.gltf` — a single binary file cannot arrive with its
`.bin` or its textures missing.

## The Five Checks

**1. Is it the right thing?** Compare the sheet against the concept image
saved beside the mesh (`concept.png`) and against the plan's prompt. A
"treasure chest" that reconstructed as a rounded lump is a concept-image
failure, not a mesh failure: regenerate the image, not the mesh.

**2. Does the back exist?** Single-image reconstruction invents whatever
the photograph did not show. The `-z` view — the side away from the input
camera — is where that invention lives. Flat, smeared, or hollow backs
are acceptable for something the player only sees from the front (a
building facade, a wall-mounted prop) and disqualifying for anything they
walk around.

**3. Is it upright and complete?** The `+y` view says whether the subject
stands. A cropped concept image reconstructs as a truncated mesh — legs
ending at the ankle, a tree with no crown — because the geometry simply
stops where the image did. Regenerate; nothing downstream can repair it.

**4. Is there a floor under it?** Look at the `+y` view for a pale sheet
around the subject, and at the side views for a thin dashed line at its
base. Image-to-3D crops its input to the subject's own silhouette, so a
standing figure touches the frame edge and the model frequently infers a
ground plane — measured at a fifth of the triangle budget, and a 2.4 m
grey pancake once the asset is scaled to a character's height.

`<REPO_PATH>/operators/gen_3d_object` removes this automatically
(`funcs/mesh_cleanup.py`) and reports what it took out. A **solid slab**
in the review sheet means the removal was refused, which it does whenever
the diagnosis would cost more than 40% of the mesh — check the task's
`ground_plate` report for the reason before assuming a bug. Sparse specks
at floor level are the floor's rubble and are harmless.

Spec-built assets skip this check: a spec cannot invent a floor, and running
the removal on one risks deleting a plinth that was asked for.

**5. Is it inside its budget?** The sheet title states the triangle count.
The budgets live in `BUDGET_BY_ROLE` in
`<REPO_PATH>/operators/gen_3d_object/funcs/art_plan.py`, keyed by role rather than
asset type, because what matters is how *often* a thing is drawn:

| Role | Triangles | Texture |
|---|---|---|
| `avatar` — hero character, seen close | 40 000 | 2048 |
| `weapon` — held, small on screen | 20 000 | 1024 |
| `prop` — interacted with, one or two per scene | 20 000 | 1024 |
| `scenery` — repeated dozens of times | 8 000 | 1024 |
| `landmark` — seen once, at a distance | 20 000 | 1024 |

A repeated tree at 200 000 triangles costs more than the whole rest of the
scene. Set `role` on the plan entry and **regenerate**: a triangle budget
cannot be fixed afterwards, because decimating a textured mesh outside the
decimates. Never decimate a finished asset by eye.

**6. Is the scale plausible?** The title states the composed bounding box.
Generated meshes arrive normalised into a unit box, so this number is
meaningless in isolation — what matters is that the plan's `height` is a
real height for that subject. A chair at 3 m and a doorway at 1.6 m are
the two failures that make a scene read as a toy.

## Recording The Outcome

- **Accept**: run the orientation review
  (`<REPO_PATH>/agent_skills/asset_qa/3d_object/orientation_review.md`) and
  record the facing axis. An accepted asset with an unverified facing is not
  finished. A spec-built asset carries its facing as data, so the review
  confirms rather than establishes it.
- **Regenerate**: change the plan entry — prompt, seed, `role`,
  `triangles`, `texture` — and say which, so the next run is a different
  attempt rather than the same one.
- **Switch route**: a generated mesh that fails twice on something a spec
  states outright — scale, facing, parts that need to move — is telling you
  the subject was describable. Write the spec instead of buying a third
  generation.
- **Reject**: keep the primitive fallback. This is a real answer. A
  bevelled primitive with honest materials and a fitted shadow looks
  better than a melted mesh, and `assets.instantiateOrBuild` already
  falls back to it with no code change.

## What Generation Does Not Fix

Reach for the framework before reaching for the GPU. In descending order
of visible effect per line of code, a generated three.js scene is decided
by `host.setEnvironment({ preset })`, filmic tone mapping, a fitted
shadow camera, bevelled edges, honest materials, and contact shadows —
all of them documented in
`<REPO_PATH>/agent_skills/engine_context/three_js_api.md`. An unlit scene full of
generated art still looks like an unlit scene; a lit scene full of
primitives does not.

Generation is also the wrong tool for anything that must **articulate**.
A generated mesh is one fused body: a car's wheels cannot spin, a chest's
lid cannot open, a character cannot be skinned. Either generate the shell
and keep the moving parts as primitives driven by gameplay — which is what
`entity.visual` is for — or build the whole thing from a spec, where every
part is already a named node.
