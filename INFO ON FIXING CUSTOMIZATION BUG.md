# Customization slider bugs: what broke, why, and how it was fixed

This file exists so that a future debugging session (me or anyone else) doesn't have
to re-derive all of this from scratch. Read this FIRST if a user reports "the
slider doesn't work / resets / doesn't change the model" for any override pack.

Written 2026-07-07 after fixing this across two releases (v1.21, v1.22).

## Symptoms this covers

- Slider drags but resets to 0 every time you reopen the customization menu ("dead slot").
- Slider drags, holds its value, but the model never visibly changes.
- Slider drags, holds its value, model changes, but it's the WRONG thing (e.g. a
  "shoes" slider that actually toggles something else entirely).
- "Works a bit" / "barely works at all" -- some sliders on a pack work, most don't.
- Skin sliders (SetSkin) are a DIFFERENT, simpler mechanism and are basically never
  the problem -- see "Skins vs bodygroups" below. If only the skin slider works and
  bodygroup sliders don't exist at all for a pack (e.g. George Droyd K1-B0), that's
  normal, not a bug.

## The mechanism (read this to understand ANY future variant of this bug)

The Shinri Trial customization tool (`rb655_easy_bodygroup`) builds one slider per
bodygroup **the CLIENT's current model** (i.e. the override .mdl) has, using
`GetBodygroupName(k)` / `GetBodygroupCount(k)`. When you drag a slider, the request
goes to the **server**, which calls `SetBodygroup(index, value)` on **its own copy
of the model** -- the real, unmodified, workshop-subscribed player model (the
override only replaces files on your OWN client; the server never sees it).

Both sides store the current bodygroup selection in ONE shared networked integer
(`m_nBody`). Each bodygroup's value occupies `base * value` in that integer, where
`base` is a multiplier baked into the compiled .mdl at compile time (roughly: the
product of the option-counts of every PRECEDING bodygroup in that SAME model's own
table). Critically:

- The SERVER computes/writes using the base/count from ITS OWN (native) model at
  whatever index the client told it to touch.
- The CLIENT decodes/renders using the base/count from ITS OWN (override) model at
  that SAME index.
- These are two DIFFERENT files. Nothing keeps their bodygroup tables in sync
  automatically -- it's on us (the override) to make sure the override's table lines
  up with whatever the CURRENT native table looks like, index-for-index.

Two independent ways this goes wrong, and both must be checked:

1. **Index has no room (count=1 / dead) on the native side.** The server has zero
   bits allocated there, so any value sent is discarded -- always decodes back to 0.
   Symptom: stuck/reset slider. Root cause found 2026-07-07: a **Jul 1 workshop
   update to the PlayerModels @ ST addon reordered several characters' native
   bodygroup tables** (e.g. Kirumi's real 2-option slots moved from index 3 to
   indices 4/5/6; index 3 became a dead 1-option "skirt"). Any override pack built
   before that update, whose slider happened to sit at an index that's since gone
   dead, breaks this way. **This can happen again if the addon updates again** --
   if a previously-working pack suddenly goes dead, re-extract the current native
   models (see "Diagnosing" below) and compare bodygroup tables before/after.

2. **Same index, same count, but DIFFERENT base.** `base` is computed from each
   model's OWN other bodygroups, not from the shared index. Two models can agree on
   (index, count) at some slot and still disagree on base if their other groups
   differ in composition. Confirmed on Shiroko Mahiru's own "Shoes" (index 11, its
   own base 64) vs. Ibuki Mioda's native index 11 "bracelet Right" (count matches,
   but base 256). The slider writes to bit position 256 server-side and the client
   reads bit position 64 -- completely unrelated, so the slider "works" (holds a
   value) but visibly does nothing, or drives some other native toggle instead.

There's a THIRD bug class that isn't part of the networking mechanism itself but
caused just as much damage: **the matching algorithm that decides "which override
bodygroup corresponds to which native bodygroup" could assign the same override
group to two different native targets.** See "The compat-map collision bug" below.
If reachability still looks wrong after confirming (1) and (2) are handled, suspect
this next.

## Skins vs bodygroups

Skins (`SetSkin`/`GetSkin`, `m_nSkin`) are a completely separate, uncapped, raw
networked integer -- NOT packed into `m_nBody`, NOT subject to any of the above.
A skin slider just works as long as the native model has `SkinCount() > 1`. This is
why George Droyd (skin-only, no bodygroup sliders at all on its override model)
"just works" and always has -- it was never exposed to any of this.

## The compat-map collision bug (fixed in v1.22)

`bodygroup_compat_map(target_groups, override_groups)` matches each native
(target) bodygroup to an override bodygroup: first by NAME (e.g. override "Shoes"
<-> native "shoes"), falling back to whatever's left (by position) for anything
without a name match.

**The bug (present through v1.21):** name-matching and fallback-matching ran in a
single interleaved pass, in TARGET INDEX ORDER. A target with no name match could
grab an override group via fallback BEFORE a LATER target's real name match to that
SAME override group was processed. Both ends up "claiming" it in the mapping dict,
but only one can actually be acted on -- so the override group's real slot
assignment silently became whichever one won, not necessarily the correct
name-matched one.

Confirmed on real packs:
- Shiroko Mahiru -> Ibuki Mioda: override "Shoes" got mapped to native "ribbon"
  (index 9, processed first, no name match, fallback grabbed it) AND to native
  "shoes" (index 13, processed later, real name match). Whichever actually got
  acted on, the shoe slider ended up driving the wrong bit.
- Hoshino Himiko -> Ibuki Mioda: override "shoes" collided across THREE different
  native targets. Nearly every slider on the pack was wired wrong as a result --
  this is why Hoshino "barely worked at all" while Shiroko Mahiru (fewer, luckier
  collisions) "worked a lot better."

**The fix:** `bodygroup_compat_map` now runs in two clean passes -- ALL real name
matches are resolved FIRST (marking the override group used), and only THEN does
fallback run, using whatever override groups are left. A real name match can never
be pre-empted or double-booked again.

## The actual fix: full-layout relocation (v1.22), not one group at a time (v1.21)

v1.21 fixed the FIRST bug class only (dead slots), one group at a time, by
appending a single new bodypart entry. That's insufficient in general:

- It doesn't fix base mismatches at an already-occupied index (bug class 2).
- Appending only works if the native model has a "spare" index beyond the
  override's own current count (true for Kirumi vs its native, by luck -- native
  had MORE total groups than the override). It is NOT generally true (Shiroko
  Mahiru and Ibuki both have exactly 14 total groups -- there's no spare native
  index to append onto; the fix has to reuse/reorder EXISTING positions).

v1.22 replaced this with a full-table rebuild, computed once per pack:

1. `plan_bodygroup_layout(override_groups, target_groups)` computes a `slots` list
   describing the ENTIRE rebuilt bodypart table. Every configurable override group
   with a real native match (per the fixed compat map) is UNCONDITIONALLY relocated
   onto that native index, with the native's `base` and an honestly-capped `count`
   (`min(own_count, native_count)`) -- even if it happened to already be sitting at
   that exact index, because "already there" doesn't guarantee the base matches.
   Anything a relocation DISPLACES (an original occupant of the target index that
   isn't itself relocating) is never silently destroyed -- it's pushed to a freshly
   appended slot at the tail. This matters: e.g. Hoshino's non-configurable "card"/
   "cloth" pieces originally sat at indices that incoming relocated groups needed;
   losing them would have been a visual regression (a permanently-worn item
   disappearing), even though they never had a working slider.
2. `patch_mdl_relocate_bodygroups(path, slots)` and
   `patch_vtx_relocate_bodygroups(vtx_path, slots)` rebuild the .mdl and every
   paired .vtx from the EXACT SAME `slots` list, so the two files can never
   describe a different bodypart count/order -- see "the vtx crash" below for why
   that specific invariant is non-negotiable.
3. `relocate_unreachable_bodygroups(copied_mdl, override_groups, target_groups)` is
   the shared entry point used by BOTH `patch_default_model_bodygroup_names` (no
   retarget) and `patch_retargeted_model_bodygroup_names` (retargeted install) --
   fixing it once covers every pack, present and future, Default or retargeted.

## The vtx crash (why this can't be a pure .mdl fix)

An earlier same-day attempt (2026-07-07, commit `0598947`, reverted in `8897cac`)
grew ONLY the .mdl's bodypart table (added one entry) without touching the paired
`.dx90.vtx`. **This crashed the game on model load.** The engine indexes vtx
bodyparts positionally against the mdl's bodypart array -- vtx has its OWN
`numBodyParts`/bodypart table (`OptimizedModel` format, see below) that must have
the exact same COUNT and per-slot data availability as the mdl. Any code that
changes bodypart count/order in one file MUST make the identical change in the
other, in the same call. `relocate_unreachable_bodygroups` always does both
together; never call `patch_mdl_relocate_bodygroups` without also calling
`patch_vtx_relocate_bodygroups` with the SAME `slots` on every file from
`vtx_paths_for_mdl(mdl_path)`.

## The "slider works but nothing changes" bug (the OTHER thing that bit us)

A first, corrected attempt at the vtx-lockstep fix (still 2026-07-07, before v1.21
shipped) made the relocated (new) slot and the OLD (vacated) slot both point at the
SAME real mesh data, reasoning "sharing a model pointer is harmless." It is NOT: the
two are still separate bodyparts, so the engine draws BOTH every frame -- the old
slot permanently draws submodel 0 (e.g. "outfit1") on top of/underneath whatever the
new slot's slider selects. Confirmed in-game: slider held its value, but the outfit
never appeared to change (it was there the whole time, just occluded/co-rendered).

**Fix:** every vacated/displaced/empty slot gets a freshly appended, genuinely EMPTY
model instead -- 148 zeroed bytes for a `mstudiomodel_t` in the .mdl (0 meshes, 0
vertices), and a `ModelHeader_t{numLods=1} -> ModelLODHeader_t{numMeshes=0}` in the
.vtx. Zero meshes means the engine draws nothing for that bodypart, full stop. This
is what "kind": "empty" in a `slots` entry produces.

## Binary format notes (reverse-engineered from scratch 2026-07-07 -- expensive to redo, don't lose this)

Both formats use "record-start-relative" offsets throughout: a stored offset field's
absolute address = (the address of the START of the containing record/struct) +
(the stored value). NOT relative to the field's own position. This matches how
`parse_mdl_bodygroups` already read bodygroup names (`offset + sznameindex` where
`offset` is the record start), and turned out to hold for the .vtx format too.

**.mdl bodypart table** (already known before this session, see `parse_mdl_bodygroups`):
- `numbodyparts`, `bodypartindex` at studiohdr offset 232 (`<ii`).
- Each `mstudiobodyparts_t` record is 16 bytes: `sznameindex, nummodels, base, modelindex` (`<iiii`), all relative to that record's own start.
- File's total declared length is at offset 76 (`<i`) -- MUST be updated to the new file length after appending anything, or the engine may refuse/mis-load the file.
- `mstudiomodel_t` (one per submodel within a bodypart) is **148 bytes**, `name[64]` inline at offset 0 of the struct (not an indirect string). Verified directly against Shiroko Terror Kirumi's compiled mdl (submodel names "outfit1.dmx"/"outfit2.dmx"/"outfit3.dmx" read out exactly 148 bytes apart).

**.dx90.vtx (`OptimizedModel`) format** (newly reverse-engineered this session, NOT documented anywhere I had access to -- verified structurally by parsing the entire hierarchy of a real file with zero exceptions and cross-checking bodypart/model counts against the paired .mdl):
- `FileHeader_t` (36 bytes, offset 0): `version(i), vertCacheSize(i), maxBonesPerStrip(H), maxBonesPerTri(H), maxBonesPerVert(i), checkSum(i), numLODs(i), materialReplacementListOffset(i), numBodyParts(i)@28, bodyPartOffset(i)@32`. `version` must be 7 (this is what GMod's current studiomdl/engine produces; if a future workshop update ships a different vtx version this all needs re-verifying).
- `BodyPartHeader_t` (8 bytes): `numModels(i), modelOffset(i)`, relative to that record's own start.
- `ModelHeader_t` (8 bytes): `numLods(i), lodOffset(i)`.
- `ModelLODHeader_t` (12 bytes): `numMeshes(i), meshOffset(i), switchPoint(f)`.
- `MeshHeader_t` (9 bytes, NOT padded -- these formats are tightly packed, no compiler alignment): `numStripGroups(i), stripGroupHeaderOffset(i), flags(B)`.
- `StripGroupHeader_t` (25 bytes): `numVerts(i), vertOffset(i), numIndices(i), indexOffset(i), numStrips(i), stripOffset(i), flags(B)`.
- `StripHeader_t` is 27 bytes (not needed for the relocate fix -- we never touch strip/vertex/index data, only bodypart/model/lod headers, since we always reuse or empty out at the MODEL level and never duplicate real mesh data).
- No file-length field to update in .vtx (unlike .mdl's offset-76 field) -- just `numBodyParts`/`bodyPartOffset` in the header.

## Diagnosing this again in the future

1. Get the CURRENT native (server-side) model. `find_known_target_mdl(target)` looks
   in a few hardcoded local extract folders (`debug_extracts/dro_playermodels_2562456244`
   first, then older Female Shuichi extract folders as fallback). **If the workshop
   addon has updated since these were extracted, re-extract it first** (SteamCMD /
   Steam Workshop download to a fresh folder, or re-subscribe and copy from
   `garrysmod/addons`) -- comparing against a STALE native model will look like it
   works in this diagnostic but still be wrong in-game against the REAL current
   server content.
2. `om.parse_mdl_bodygroups(mdl_path)` on both the override and the current native
   model. Eyeball: does the override's configurable (count>1) group's index match a
   configurable native group at the SAME index? If not, or if unsure about base,
   don't trust "same index" -- run step 3.
3. `om.bodygroup_compat_map(target_groups, override_groups)` -- print it, check for
   any override_index appearing more than once across different mapping entries
   (would indicate the collision bug has regressed or a new variant appeared).
4. `om.plan_bodygroup_layout(override_groups, target_groups)` -- this is the ACTUAL
   plan that gets applied. For each "move" slot, verify `base` and `count` match
   the REAL current native group at `final_index`.
5. If everything above looks right in a dry run, actually run `om.enable(cfg, pack,
   target)` against a scratch `gmod_path` (tempdir), then re-parse the resulting
   .mdl/.vtx and check `numbodyparts` matches between the two files, and that no
   in-range parse errors occur when walking the full vtx hierarchy (bodypart ->
   model -> lod -> mesh -> stripgroup, checking every offset stays `< len(data)`).
   This is the same deep-walk the test suite (`tests/test_retargeting.py`, search
   for "relocate" and "compat") already does against real pack files -- run those
   tests first before writing new diagnostic code.
6. Only after all of the above passes structurally should you rebuild the exe and
   ask the user to test in-game. Two separate crash/bug incidents in this saga
   happened specifically because a fix LOOKED right without this level of
   structural verification.

## Where the code lives

Everything above is implemented in `override_manager.py` in this repo:
`parse_mdl_bodygroups`, `bodygroup_key`, `configurable_groups`,
`bodygroup_compat_map`, `plan_bodygroup_layout`, `patch_mdl_relocate_bodygroups`,
`patch_vtx_relocate_bodygroups`, `relocate_unreachable_bodygroups`,
`patch_default_model_bodygroup_names`, `patch_retargeted_model_bodygroup_names`.
Tests: `tests/test_retargeting.py`, search for "relocate", "compat_map", or
"bodygroup_layout".

Community pack .zip files and `community_packs.json` do NOT need to change for any
fix in this category -- all of this patching happens at `enable()` time, driven by
whatever `override_manager.py` code the USER'S APP is currently running, never
baked into the shipped pack files. Fixing and republishing the APP (new GitHub
release) is sufficient to fix every pack, local or community-downloaded, for anyone
who updates.

## History (for context on what NOT to redo)

- v1.7 (2026-06-28): client-side Lua compat script (`ovr_bodygroup_compat_*.lua`).
  Confirmed DEAD by 2026-06-29 -- this server blocks client Lua entirely once you've
  ever connected to it (`sv_allowcslua 0` + likely anticheat); the lua never ran.
  Don't waste time on lua-based fixes on this server. File-level binary patching is
  the only thing that has ever actually worked here.
- v1.21 (2026-07-07): fixed the dead-slot (count=1) case only, one group at a time,
  append-only. Left base-mismatch and compat-map-collision bugs completely
  unaddressed. Superseded by v1.22 -- the single-group functions
  (`patch_mdl_relocate_bodygroup`/`patch_vtx_relocate_bodygroup`, singular) were
  deleted; use the plural `plan_bodygroup_layout` / `patch_mdl_relocate_bodygroups`
  / `patch_vtx_relocate_bodygroups` instead.
- v1.22 (2026-07-07): the fix described above. Current as of this writing.
