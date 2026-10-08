# Imported Asset Orientation Review

Decide which way an imported 3D model faces, and record the answer.

This Skill exists because the fact cannot be computed. A glTF file fixes
the up axis and the unit and says nothing binding about facing, so a
character modelled facing +Z and the same character facing -Z produce
byte-identical bounding boxes, node trees and animation clips. Loading
the file cannot distinguish them. Looking at it can, which is why a
vision-capable model is the right tool and a heuristic is not.

The symptom in a finished game is unmistakable once known, and invisible
until then: the player runs but the character strafes; an enemy charges
backwards; a car drives boot-first; a chest opens away from the player.
Nothing errors, no test fails, and the game is simply wrong.

All three models in the curated CC0 pack face **+Z**. The runtime treats
**-Z** as forward. Every generated game that staged them before this
review existed therefore ran its characters backwards.

## When To Run

Run this after any mesh import and before declaring a game complete:

- after `three.assets.import_asset` / `import_avatar` / `import_prop` /
  `import_weapon`, or after `run_art_plan` or
  `fetch_asset_pack` has staged content;
- whenever `assets.import_asset` returns a warning about an undeclared
  `forward_axis`;
- whenever an artifact's `orientation.needs_vision_check` is `true`;
- whenever a reviewer reports that a character "moves sideways", "walks
  backwards", "faces the wrong way", or "looks away from the camera".

Skip it for textures, materials, audio and motion clips: those have no
front. An asset with no `orientation` block in the manifest is one of
those.

## Authority And Inputs

Read before deciding:

- the rendered views and the geometric evidence returned by
  `three.preview.orientation_report`;
- the artifact's own metadata (`three.assets.get_orientation`);
- `<REPO_PATH>/agent_skills/engine_context/three_js_api.md`, sections *Asset
  Orientation* and *Preview*.

The rendered views outrank everything else. Geometry narrows the answer;
it never settles it. If the evidence and the images disagree, the images
are right.

## Workflow

1. **Render.** For each staged mesh artifact:

   ```python
   report = three.preview.orientation_report("<asset_id>")
   sheet  = report["payload"]["contact_sheet"]
   ```

   The sheet is a single labelled image containing five orthographic
   views. Individual view files are in `report["payload"]["views"]`.

2. **Read the labels, not the layout.** Every view is captioned
   `camera on<axis> | screen right = <axis>`. A view named `+z` was
   rendered by a camera standing on the +Z axis looking at the origin, so
   the surface it shows is the model's **+Z side**. No view is called
   "front", deliberately: naming one would presuppose the answer.

3. **Find the face.** Identify the single view in which the subject faces
   the camera, using the cues below in order of reliability.

   | Subject | The facing side is the one showing |
   |---|---|
   | Humanoid | eyes, nose, mouth, chest, belt buckle, toe tips |
   | Quadruped | snout and ears (the tail is on the opposite side) |
   | Vehicle | bonnet, grille, headlights, windscreen rake |
   | Firearm | muzzle — which points along the *barrel*, and is the one case where "forward" is not where a face is |
   | Building, arch, doorway | the opening a player walks through |
   | Chest, cabinet, fridge | the lid hinge is at the back; the latch is at the front |

   The model's `forward_axis` is the axis named in that view's label.

4. **Sanity-check with a second view.** In the `-x` view, screen right is
   `+z`. So a model that faces `+z` must show its face at the **right**
   of the `-x` view and at the **left** of the `+x` view. If that does not
   hold, the reading in step 3 was wrong.

5. **Check the up axis.** In the `+y` (top) view a standing figure should
   read as a small compact silhouette. If the top view shows the subject
   full-length, the model is lying down: it was authored Z-up. Record a
   `pitch_offset_degrees` of `-90` or `90` — whichever stands it up —
   *before* worrying about yaw, since pitch changes which axis is
   horizontal.

6. **Read the scale.** The sheet's title states the composed bounding box
   in model units. Compare its height to the subject's real height. A
   character 4.46 units tall is not 4.46 m tall; it is a 1.8 m character
   authored in a different unit.

7. **Record the decision.** One call, and it is the whole point of the
   review:

   ```python
   three.assets.set_orientation(
       "<asset_id>",
       forward_axis="+z",          # the answer from step 3
       scale_hint_metres=1.8,      # the answer from step 6
       verified_by="agent_vision", # never omit this
       notes="Eyes and visor on the +Z side.",
   )
   ```

   The adapter derives the yaw, writes it into
   `public/assets/manifest.json`, and the runtime applies it at
   instantiation. Gameplay code changes not at all.

8. **Verify.** Re-read `three.assets.get_orientation("<asset_id>")` and
   confirm `runtime_yaw_degrees` is what step 3 implies:
   `+z → 180`, `-z → 0`, `+x → 90`, `-x → 270`.

## Deciding When The Images Are Ambiguous

Say so rather than guessing. A recorded guess is worse than no record,
because it stops the next pass from checking.

- **Symmetric prop with no front** (a crate, a barrel, a rock): leave the
  orientation unrecorded and say why. It has no facing to get wrong.
- **Face painted into a texture that failed to decode** — the report
  warns when no base colour texture could be read. Judge from the
  silhouette: shoe toes, a nose, a backpack, a tail, hair.
- **A model facing a diagonal**: no cardinal axis fits. Record
  `yaw_offset_degrees` measured from the nearest axis instead of
  `forward_axis`, and note that it was estimated.
  regenerating rather than annotating. A mesh nobody can recognise from
  five angles will not read any better in play.

## What Not To Do

- **Do not rotate the model in gameplay code.** A `rotation.y += Math.PI`
  in an entity is invisible to every other consumer of that asset — the
  world spec, the next game, the animation that assumed a facing — and it
  is silently undone the first time the entity assigns its own facing.
  Record the fact instead; one place, every consumer.
- **Do not edit the manifest by hand.** It is rewritten on every import.
- **Do not re-export or re-generate the mesh to fix a rotation.** GPU
  minutes to change a number that a string could have carried.
- **Do not set `verified_by="agent_vision"` without having looked at the
  images.** That flag is the only record of whether anyone checked.
- **Do not infer facing from the animation clip names.** A clip called
  `Walking` translates along whatever axis its author chose, and it is
  the same unknown axis.

## Worked Example

`RobotExpressive.glb`, staged as an avatar in three games:

- The `+z` view shows two eyes and a visor. The `-z` view shows a smooth
  domed back. The `-x` view puts the eyes at screen right, and screen
  right is `+z` — consistent.
- The `+y` view is a compact disc: the model is upright, +Y up. No pitch
  correction.
- The sheet title reads `bbox 2.63 x 4.46 x 2.69 units`; the subject is a
  humanoid robot, so 1.8 m.
- Decision:

  ```python
  three.assets.set_orientation(
      "robot_expressive",
      forward_axis="+z", scale_hint_metres=1.8,
      verified_by="agent_vision",
      notes="Eyes and visor on the +Z side; authored 4.46 units tall.",
  )
  ```

- `get_orientation` then reports `runtime_yaw_degrees: 180`, and the
  robot walks forwards.

## Cost

The renderer is pure `numpy` and `Pillow`: no GPU, no display, no
browser, no Node process. One asset is five views in roughly two seconds,
so reviewing a whole game's art pack costs less than staging it did.
