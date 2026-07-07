import importlib
import inspect
import json
import os
import shutil
import struct
import sys
import tempfile
import types
import unittest


sys.modules.setdefault("translate_cache", types.SimpleNamespace())
sys.modules.setdefault("live_translator", types.SimpleNamespace())
om = importlib.import_module("override_manager")


class RetargetingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def write_file(self, rel, data=b"x"):
        path = os.path.join(self.tempdir, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(data, bytes) else "w"
        kwargs = {} if isinstance(data, bytes) else {"encoding": "utf-8"}
        with open(path, mode, **kwargs) as f:
            f.write(data)
        return path

    def test_target_slug_and_addon_slug_include_target_for_non_default(self):
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko"}
        target = {"name": "Mukuro Ikusaba"}

        self.assertEqual("default", om.target_slug(om.DEFAULT_TARGET_NAME))
        self.assertEqual("mukuro_ikusaba", om.target_slug("Mukuro Ikusaba"))
        self.assertEqual("ovr_hoshino_himiko", om.addon_slug(pack, None))
        self.assertEqual("ovr_hoshino_himiko__mukuro_ikusaba", om.addon_slug(pack, target))

    def test_infer_source_target_from_pack_files(self):
        pack_dir = os.path.join(self.tempdir, "Hoshino Himiko")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/char12.mdl")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/char12.dx90.vtx")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/c_arms/char12_arms.mdl")
        self.write_file("Hoshino Himiko/materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf")

        source = om.infer_source_target(pack_dir)

        self.assertEqual("models/dro/player/characters3/char12/char12", source["model_base"])
        self.assertEqual("models/dro/player/characters3/char12/c_arms/char12_arms", source["arms_base"])
        self.assertEqual("materials/dro/sprites/characters/dr_v3/himiko yumeno", source["sprite_dir"])

    def test_infer_source_target_prefers_override_json(self):
        pack_dir = os.path.join(self.tempdir, "Pack")
        os.makedirs(pack_dir, exist_ok=True)
        with open(os.path.join(pack_dir, "override.json"), "w", encoding="utf-8") as f:
            json.dump({
                "source_target": {
                    "model_base": "models/dro/player/characters3/char12/char12.mdl",
                    "arms_base": "models/dro/player/characters3/char12/c_arms/char12_arms.mdl",
                    "sprite_dir": "materials/dro/sprites/characters/dr_v3/himiko yumeno/"
                }
            }, f)

        source = om.infer_source_target(pack_dir)

        self.assertEqual("models/dro/player/characters3/char12/char12", source["model_base"])
        self.assertEqual("models/dro/player/characters3/char12/c_arms/char12_arms", source["arms_base"])
        self.assertEqual("materials/dro/sprites/characters/dr_v3/himiko yumeno", source["sprite_dir"])

    def test_retarget_path_maps_model_arms_and_sprite_paths(self):
        source = {
            "model_base": "models/dro/player/characters3/char12/char12",
            "arms_base": "models/dro/player/characters3/char12/c_arms/char12_arms",
            "sprite_dir": "materials/dro/sprites/characters/dr_v3/himiko yumeno",
        }
        target = {
            "name": "Mukuro Ikusaba",
            "model_base": "models/dro/player/characters1/char16/char16",
            "arms_base": "models/dro/player/characters1/char16/c_arms/char16_arms",
            "sprite_dir": "materials/dro/sprites/characters/dr_1/mukuro ikusaba",
        }

        self.assertEqual(
            "models/dro/player/characters1/char16/char16.mdl",
            om.map_retarget_path("models/dro/player/characters3/char12/char12.mdl", source, target),
        )
        self.assertEqual(
            "models/dro/player/characters1/char16/c_arms/char16_arms.dx90.vtx",
            om.map_retarget_path("models/dro/player/characters3/char12/c_arms/char12_arms.dx90.vtx", source, target),
        )
        self.assertEqual(
            "materials/dro/sprites/characters/dr_1/mukuro ikusaba/ct_sprite_1.vtf",
            om.map_retarget_path("materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf", source, target),
        )
        self.assertEqual(
            "materials/models/hoshino_new/hair.vmt",
            om.map_retarget_path("materials/models/hoshino_new/hair.vmt", source, target),
        )

    def test_retarget_path_leaves_sprites_when_target_sprite_missing(self):
        source = {
            "model_base": "models/dro/player/characters3/char12/char12",
            "arms_base": "models/dro/player/characters3/char12/c_arms/char12_arms",
            "sprite_dir": "materials/dro/sprites/characters/dr_v3/himiko yumeno",
        }
        target = {
            "name": "Mukuro Ikusaba",
            "model_base": "models/dro/player/characters1/char16/char16",
            "arms_base": "models/dro/player/characters1/char16/c_arms/char16_arms",
            "sprite_dir": "",
        }

        self.assertEqual(
            "materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf",
            om.map_retarget_path("materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf", source, target),
        )

    def test_builtin_angie_target_has_sprite_directory(self):
        target = om.find_target({}, "Angie Yonaga")

        self.assertEqual("materials/dro/sprites/characters/dr_v3/angie yonaga", target["sprite_dir"])

    def test_update_button_stays_in_bottom_row_and_window_is_tall_enough(self):
        source = inspect.getsource(om.App._build)
        init_source = inspect.getsource(om.App.__init__)

        self.assertGreater(source.index("Check for Updates"), source.index("bot4 = ttk.Frame"))
        self.assertIn('self.geometry("760x540")', init_source)
        self.assertIn('self.minsize(640, 520)', init_source)

    def test_extract_workshop_gma_uses_fresh_folder_when_previous_extract_is_locked(self):
        app_dir = os.path.join(self.tempdir, "app")
        gmod_dir = os.path.join(self.tempdir, "GarrysMod", "garrysmod")
        os.makedirs(os.path.join(self.tempdir, "GarrysMod", "bin"), exist_ok=True)
        os.makedirs(gmod_dir, exist_ok=True)
        self.write_file("GarrysMod/bin/gmad.exe")
        old_extract = os.path.join(app_dir, "workshop_extracts", "12345")
        os.makedirs(os.path.join(old_extract, "lua", "autorun"), exist_ok=True)

        old_app_dir = om.APP_DIR
        old_run = om.subprocess.run
        old_rmtree = om.shutil.rmtree
        try:
            om.APP_DIR = app_dir

            def locked_rmtree(path, *args, **kwargs):
                if os.path.abspath(path) == os.path.abspath(old_extract):
                    raise PermissionError(5, "Access is denied", os.path.join(path, "lua", "autorun"))
                return old_rmtree(path, *args, **kwargs)

            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                return types.SimpleNamespace(returncode=0, stderr="", stdout="")

            om.shutil.rmtree = locked_rmtree
            om.subprocess.run = fake_run

            out_dir = om.extract_workshop_gma(gmod_dir, os.path.join(self.tempdir, "item.gma"), "12345")

            self.assertNotEqual(os.path.abspath(old_extract), os.path.abspath(out_dir))
            self.assertTrue(os.path.basename(out_dir).startswith("12345_"))
            self.assertEqual(out_dir, calls[0][-1])
        finally:
            om.APP_DIR = old_app_dir
            om.subprocess.run = old_run
            om.shutil.rmtree = old_rmtree

    def test_patch_mdl_bodygroup_names_appends_without_overwriting_existing_string(self):
        mdl_path = self.write_file("model.mdl", b"\0" * 320)
        with open(mdl_path, "rb") as f:
            data = bytearray(f.read())
        bodypartindex = 256
        name_offset = 272
        struct.pack_into("<i", data, 76, len(data))
        struct.pack_into("<ii", data, 232, 1, bodypartindex)
        struct.pack_into("<iiii", data, bodypartindex, name_offset - bodypartindex, 1, 1, 0)
        data[name_offset:name_offset + len(b"Clothes\0")] = b"Clothes\0"
        with open(mdl_path, "wb") as f:
            f.write(data)

        self.assertTrue(om.patch_mdl_bodygroup_names(mdl_path, {0: "shirt"}))

        with open(mdl_path, "rb") as f:
            patched = f.read()
        new_name_index = struct.unpack_from("<i", patched, bodypartindex)[0]
        self.assertEqual(b"Clothes", patched[name_offset:name_offset + len(b"Clothes")])
        self.assertEqual("shirt", om.read_c_string(patched, bodypartindex + new_name_index))

    def test_copy_model_sidecars_includes_dx80_vtx(self):
        model = self.write_file("src/model.mdl")
        self.write_file("src/model.dx80.vtx", b"dx80")

        copied = om.copy_model_sidecars(model, "models/dro/player/test/test", self.tempdir)

        expected = os.path.join(self.tempdir, "models", "dro", "player", "test", "test.dx80.vtx")
        self.assertIn(expected, copied)
        with open(expected, "rb") as f:
            self.assertEqual(b"dx80", f.read())

    def test_target_change_needs_auto_apply_when_pack_already_enabled(self):
        addons = os.path.join(self.tempdir, "addons")
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko"), exist_ok=True)
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko"}

        self.assertTrue(om.target_change_needs_apply(cfg, pack, "Angie Yonaga"))
        self.assertFalse(om.target_change_needs_apply(cfg, pack, om.DEFAULT_TARGET_NAME))

    def test_parse_mdl_bodygroups_from_hoshino_model(self):
        path = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko\models\dro\player\characters3\char12\char12.mdl"
        if not os.path.exists(path):
            self.skipTest("Hoshino override model not available")

        groups = om.parse_mdl_bodygroups(path)

        names = [group["name"] for group in groups]
        self.assertIn("halo", names)
        self.assertIn("shoes", names)
        self.assertEqual(7, names.index("halo"))
        self.assertEqual(10, names.index("shoes"))

    def test_bodygroup_compat_map_matches_names_then_falls_back(self):
        override_groups = [
            {"index": 0, "name": "reference", "count": 1},
            {"index": 5, "name": "glove", "count": 2},
            {"index": 7, "name": "halo", "count": 2},
            {"index": 8, "name": "pants", "count": 2},
            {"index": 10, "name": "shoes", "count": 4},
        ]
        target_groups = [
            {"index": 0, "name": "reference", "count": 1},
            {"index": 1, "name": "hat", "count": 2},
            {"index": 2, "name": "shoes", "count": 2},
            {"index": 3, "name": "cape", "count": 2},
        ]

        mapping = om.bodygroup_compat_map(target_groups, override_groups)

        self.assertEqual(7, mapping[1]["override_index"])
        self.assertEqual(10, mapping[2]["override_index"])
        self.assertIn(mapping[3]["override_index"], {5, 8})

    def test_bodygroup_reorder_plan_places_override_groups_at_target_indexes(self):
        override_groups = [
            {"index": 0, "name": "reference", "count": 1},
            {"index": 5, "name": "glove", "count": 2},
            {"index": 7, "name": "halo", "count": 2},
            {"index": 8, "name": "pants", "count": 2},
            {"index": 10, "name": "shoes", "count": 4},
            {"index": 11, "name": "skirt", "count": 2},
            {"index": 12, "name": "tie", "count": 2},
        ]
        target_groups = [
            {"index": 0, "name": "reference", "count": 1},
            {"index": 3, "name": "glasses", "count": 2},
            {"index": 4, "name": "tie", "count": 2},
            {"index": 6, "name": "skirt", "count": 2},
        ]

        plan = om.bodygroup_reorder_plan(target_groups, override_groups)

        self.assertEqual(5, plan[3])
        self.assertEqual(12, plan[4])
        self.assertEqual(11, plan[6])

    def test_safe_game_path_rejects_unsafe_paths(self):
        self.assertEqual("models/dro/player/characters1/char16/char16", om.safe_game_path("models\\dro\\player\\characters1\\char16\\char16.mdl", allow_empty=False, strip_ext=True))
        for value in ("", "../models/x", "/models/x", "C:/models/x", "cfg/client.vdf"):
            with self.assertRaises(ValueError):
                om.safe_game_path(value, allow_empty=False)

    def test_installed_pack_addons_uses_pack_prefix_only(self):
        addons = os.path.join(self.tempdir, "addons")
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko"), exist_ok=True)
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko__mukuro_ikusaba"), exist_ok=True)
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko_extra"), exist_ok=True)
        os.makedirs(os.path.join(addons, "ovr_other_pack"), exist_ok=True)
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko"}

        found = sorted(os.path.basename(p) for p in om.installed_pack_addons(cfg, pack))

        self.assertEqual(["ovr_hoshino_himiko", "ovr_hoshino_himiko__mukuro_ikusaba"], found)

    def test_enable_retarget_copies_to_target_specific_addon(self):
        pack_dir = os.path.join(self.tempdir, "Hoshino Himiko")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/char12.mdl", b"model")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/char12.dx90.vtx", b"vtx")
        self.write_file("Hoshino Himiko/models/dro/player/characters3/char12/c_arms/char12_arms.mdl", b"arms")
        self.write_file("Hoshino Himiko/materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf", b"sprite")
        self.write_file("Hoshino Himiko/materials/models/hoshino_new/hair.vtf", b"material")
        with open(os.path.join(pack_dir, "addon.json"), "w", encoding="utf-8") as f:
            json.dump({"title": "Hoshino Himiko"}, f)
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko", "folder": pack_dir}
        target = {
            "name": "Mukuro Ikusaba",
            "model_base": "models/dro/player/characters1/char16/char16",
            "arms_base": "models/dro/player/characters1/char16/c_arms/char16_arms",
            "sprite_dir": "materials/dro/sprites/characters/dr_1/mukuro ikusaba",
        }

        om.enable(cfg, pack, target)

        addon = os.path.join(self.tempdir, "addons", "ovr_hoshino_himiko__mukuro_ikusaba")
        self.assertTrue(os.path.exists(os.path.join(addon, "models/dro/player/characters1/char16/char16.mdl")))
        self.assertTrue(os.path.exists(os.path.join(addon, "models/dro/player/characters1/char16/c_arms/char16_arms.mdl")))
        self.assertTrue(os.path.exists(os.path.join(addon, "materials/dro/sprites/characters/dr_1/mukuro ikusaba/ct_sprite_1.vtf")))
        self.assertTrue(os.path.exists(os.path.join(addon, "materials/models/hoshino_new/hair.vtf")))
        self.assertFalse(os.path.exists(os.path.join(self.tempdir, "addons", "ovr_hoshino_himiko")))

    def test_enable_retarget_writes_bodygroup_compat_lua(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko"
        target_model = r"C:\Users\user\Desktop\Female_Shuichi_Addon_Extracts\2562456244_PlayerModels_ST\models\dro\player\characters3\char15\char15.mdl"
        if not os.path.exists(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl")) or not os.path.exists(target_model):
            self.skipTest("real Hoshino/target models not available")
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko", "folder": source_pack}
        target = om.find_target({}, "Angie Yonaga")

        om.enable(cfg, pack, target)

        lua_path = os.path.join(
            self.tempdir,
            "addons",
            "ovr_hoshino_himiko__angie_yonaga",
            "lua/autorun/ovr_bodygroup_compat_ovr_hoshino_himiko__angie_yonaga.lua",
        )
        self.assertTrue(os.path.exists(lua_path))
        with open(lua_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("GetInternalVariable('m_nBody')", content)
        self.assertIn("SetBodygroup", content)

    def test_enable_default_writes_bodygroup_compat_lua_when_source_target_known(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko"
        target_model = r"C:\Users\user\Desktop\Female_Shuichi_Addon_Extracts\2562456244_PlayerModels_ST\models\dro\player\characters3\char12\char12.mdl"
        if not os.path.exists(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl")) or not os.path.exists(target_model):
            self.skipTest("real Hoshino/Himiko models not available")
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko", "folder": source_pack}

        om.enable(cfg, pack, None)

        lua_path = os.path.join(
            self.tempdir,
            "addons",
            "ovr_hoshino_himiko",
            "lua/autorun/ovr_bodygroup_compat_ovr_hoshino_himiko.lua",
        )
        self.assertTrue(os.path.exists(lua_path))
        with open(lua_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("models/dro/player/characters3/char12/char12.mdl", content)
        self.assertIn("GetInternalVariable('m_nBody')", content)

    def test_bodygroup_compat_lua_combines_duplicate_override_targets(self):
        mapping = {
            3: {"target_base": 1, "target_count": 2, "override_index": 3, "override_count": 3, "override_name": "outfit"},
            4: {"target_base": 2, "target_count": 2, "override_index": 3, "override_count": 3, "override_name": "outfit"},
            5: {"target_base": 4, "target_count": 2, "override_index": 3, "override_count": 3, "override_name": "outfit"},
        }

        content = om.generate_bodygroup_compat_lua("models/example.mdl", mapping)

        self.assertIn("local OVERRIDES = {", content)
        self.assertIn("sources = {", content)
        self.assertEqual(1, content.count("if ply:GetBodygroup(item.override) ~= value then"))

    def test_bodygroup_name_patch_can_append_longer_labels(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko"
        if not os.path.exists(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl")):
            self.skipTest("real Hoshino model not available")
        mdl_path = os.path.join(self.tempdir, "char12.mdl")
        shutil.copy2(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl"), mdl_path)

        changed = om.patch_mdl_bodygroup_names(mdl_path, {7: "glasses", 10: "shoes"})

        self.assertTrue(changed)
        groups = {group["index"]: group for group in om.parse_mdl_bodygroups(mdl_path)}
        self.assertEqual("glasses", groups[7]["name"])
        self.assertEqual("shoes", groups[10]["name"])
        self.assertEqual("pants", groups[8]["name"])

    def test_bodygroup_name_patch_updates_mdl_declared_length_when_appending(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko"
        if not os.path.exists(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl")):
            self.skipTest("real Hoshino model not available")
        mdl_path = os.path.join(self.tempdir, "char12.mdl")
        shutil.copy2(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl"), mdl_path)

        om.patch_mdl_bodygroup_names(mdl_path, {7: "very_long_halo_slider_name"})

        with open(mdl_path, "rb") as f:
            data = f.read()
        declared_length = int.from_bytes(data[76:80], "little", signed=True)
        self.assertEqual(len(data), declared_length)

    def test_patch_mdl_relocate_bodygroup_moves_real_submodels_to_new_slot(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Shiroko Terror Kirumi"
        source_model = os.path.join(source_pack, "models/dro/player/characters3/char13/char13.mdl")
        if not os.path.exists(source_model):
            self.skipTest("real Shiroko Terror Kirumi model not available")
        mdl_path = os.path.join(self.tempdir, "char13.mdl")
        shutil.copy2(source_model, mdl_path)
        before = {g["index"]: g for g in om.parse_mdl_bodygroups(mdl_path)}
        self.assertEqual(3, before[3]["count"])  # "outfit", the group we're relocating

        with open(mdl_path, "rb") as f:
            before_data = f.read()
        before_numbodyparts, before_bodypartindex = struct.unpack_from("<ii", before_data, 232)
        before_offset = before_bodypartindex + 3 * 16
        _n, _c, _b, before_modelindex = struct.unpack_from("<iiii", before_data, before_offset)
        original_outfit_model_abs = before_offset + before_modelindex
        original_outfit_bytes = before_data[original_outfit_model_abs:original_outfit_model_abs + 148 * 3]

        changed = om.patch_mdl_relocate_bodygroup(mdl_path, 3, native_base=1, native_count=2, new_name="neck")

        self.assertTrue(changed)
        groups = {g["index"]: g for g in om.parse_mdl_bodygroups(mdl_path)}
        # old slot neutralized (no longer shows a slider) but not deleted
        self.assertEqual(1, groups[3]["count"])
        # new slot appended at the end, matching the native base/count, real submodels
        new_index = max(groups)
        self.assertEqual("neck", groups[new_index]["name"])
        self.assertEqual(2, groups[new_index]["count"])
        self.assertEqual(1, groups[new_index]["base"])
        # every other original group is untouched
        self.assertEqual(before[0], groups[0])
        self.assertEqual(before[1], groups[1])
        self.assertEqual(before[2], groups[2])
        with open(mdl_path, "rb") as f:
            data = f.read()
        declared_length = int.from_bytes(data[76:80], "little", signed=True)
        self.assertEqual(len(data), declared_length)

        # the old slot must point at a genuinely EMPTY submodel (not the real outfit
        # data) so it stops permanently drawing outfit1 on top of whatever the new,
        # reachable slot picks -- two bodyparts must never share one real mesh subtree.
        numbodyparts, bodypartindex = struct.unpack_from("<ii", data, 232)
        old_offset = bodypartindex + 3 * 16
        _sznameindex, _nummodels, _base, modelindex = struct.unpack_from("<iiii", data, old_offset)
        old_model_abs = old_offset + modelindex
        new_offset = bodypartindex + new_index * 16
        _sznameindex2, _nummodels2, _base2, modelindex2 = struct.unpack_from("<iiii", data, new_offset)
        new_model_abs = new_offset + modelindex2
        self.assertNotEqual(old_model_abs, new_model_abs)
        self.assertEqual(b"\x00" * 148, bytes(data[old_model_abs:old_model_abs + 148]))
        # the new slot's model data is the ORIGINAL real outfit array, at its original
        # location, untouched and not duplicated
        self.assertEqual(new_model_abs, original_outfit_model_abs)
        self.assertEqual(bytes(data[new_model_abs:new_model_abs + 148 * 3]), original_outfit_bytes)

    def test_patch_vtx_relocate_bodygroup_stays_structurally_consistent(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Shiroko Terror Kirumi"
        source_vtx = os.path.join(source_pack, "models/dro/player/characters3/char13/char13.dx90.vtx")
        if not os.path.exists(source_vtx):
            self.skipTest("real Shiroko Terror Kirumi vtx not available")
        vtx_path = os.path.join(self.tempdir, "char13.dx90.vtx")
        shutil.copy2(source_vtx, vtx_path)

        with open(vtx_path, "rb") as f:
            before_bytes = bytes(f.read())
        before_count = struct.unpack_from("<i", before_bytes, 28)[0]

        changed = om.patch_vtx_relocate_bodygroup(vtx_path, 3)

        self.assertTrue(changed)
        with open(vtx_path, "rb") as f:
            data = f.read()
        # everything up to the header's own bodypart-count/offset fields is untouched,
        # and the file only grew (append-only, nothing before it shifted or was rewritten)
        self.assertEqual(before_bytes[:28], data[:28])
        self.assertEqual(before_bytes[36:len(before_bytes)], data[36:len(before_bytes)])
        self.assertGreater(len(data), len(before_bytes))
        numBodyParts, bodyPartOffset = struct.unpack_from("<ii", data, 28)
        self.assertEqual(before_count + 1, numBodyParts)
        # walk the full hierarchy for every bodypart to prove no out-of-range offsets
        models_abs = []
        for bp in range(numBodyParts):
            bp_off = bodyPartOffset + bp * 8
            numModels, modelOffset_rel = struct.unpack_from("<ii", data, bp_off)
            model_abs = bp_off + modelOffset_rel
            models_abs.append((numModels, model_abs))
            for m in range(numModels):
                m_off = model_abs + m * 8
                self.assertLessEqual(m_off + 8, len(data))
                numLods, lodOffset_rel = struct.unpack_from("<ii", data, m_off)
                lod_abs = m_off + lodOffset_rel
                for l in range(numLods):
                    l_off = lod_abs + l * 12
                    self.assertLessEqual(l_off + 12, len(data))
        # bodypart 3 itself now points at a genuinely empty model (0 meshes at LOD0),
        # while the new (last) slot gets the real 3-submodel outfit data instead.
        old_num_models, old_model_abs = models_abs[3]
        self.assertEqual(1, old_num_models)
        numLods, lodOffset_rel = struct.unpack_from("<ii", data, old_model_abs)
        lod_abs = old_model_abs + lodOffset_rel
        numMeshes, _meshOffset_rel, _switchPoint = struct.unpack_from("<iif", data, lod_abs)
        self.assertEqual(0, numMeshes)
        # and the new slot's model data is NOT the same location as the old (empty) one
        new_num_models, new_model_abs = models_abs[-1]
        self.assertEqual(3, new_num_models)
        self.assertNotEqual(old_model_abs, new_model_abs)

    def test_enable_default_relocates_dead_slot_to_reachable_native_index(self):
        app_dir = r"C:\Users\user\Desktop\GMod_Override_Manager"
        source_pack = os.path.join(app_dir, "overrides", "Shiroko Terror Kirumi")
        source_model = os.path.join(source_pack, "models/dro/player/characters3/char13/char13.mdl")
        target_model = os.path.join(app_dir, "debug_extracts/dro_playermodels_2562456244/models/dro/player/characters3/char13/char13.mdl")
        if not os.path.exists(source_model) or not os.path.exists(target_model):
            self.skipTest("real Shiroko Terror/Kirumi models not available")
        old_app_dir = om.APP_DIR
        try:
            om.APP_DIR = app_dir
            cfg = {"gmod_path": self.tempdir}
            pack = {"name": "Shiroko Terror Kirumi", "slug": "ovr_shiroko_terror_kirumi", "folder": source_pack}

            om.enable(cfg, pack, None)

            mdl_path = os.path.join(
                self.tempdir,
                "addons",
                "ovr_shiroko_terror_kirumi",
                "models/dro/player/characters3/char13/char13.mdl",
            )
            vtx_path = mdl_path[:-4] + ".dx90.vtx"
            groups = {g["index"]: g for g in om.parse_mdl_bodygroups(mdl_path)}
            # the outfit group's original index (3, "skirt" server-side, count 1) must no
            # longer expose a (dead) slider
            self.assertEqual(1, groups[3]["count"])
            # a genuinely reachable slider must exist somewhere with the outfit meshes,
            # capped to the honest 2-of-3 the server-native model actually allows
            relocated = [g for g in groups.values() if g["index"] > 3]
            self.assertTrue(relocated)
            self.assertEqual(2, relocated[0]["count"])

            # the paired .vtx must have grown in lockstep, or the client crashes on load
            with open(vtx_path, "rb") as f:
                vtx_data = f.read()
            vtx_numbodyparts = struct.unpack_from("<i", vtx_data, 28)[0]
            mdl_numbodyparts = struct.unpack_from("<i", open(mdl_path, "rb").read(240), 232)[0]
            self.assertEqual(mdl_numbodyparts, vtx_numbodyparts)

            # the old (dead) slot's vtx model must be genuinely empty (0 meshes), so it
            # doesn't permanently draw outfit1 on top of whatever the new slot picks
            vtx_bodyPartOffset = struct.unpack_from("<i", vtx_data, 32)[0]
            bp3_off = vtx_bodyPartOffset + 3 * 8
            _numModels, modelOffset_rel = struct.unpack_from("<ii", vtx_data, bp3_off)
            model_abs = bp3_off + modelOffset_rel
            numLods, lodOffset_rel = struct.unpack_from("<ii", vtx_data, model_abs)
            lod_abs = model_abs + lodOffset_rel
            numMeshes = struct.unpack_from("<i", vtx_data, lod_abs)[0]
            self.assertEqual(0, numMeshes)
        finally:
            om.APP_DIR = old_app_dir

    def test_enable_retarget_also_relocates_dead_slot_bodygroups(self):
        # The relocate-on-dead-slot fix must apply on the RETARGET path too, not just
        # Default installs -- retargeted packs can hit the exact same "workshop update
        # reordered the native bodygroup table" problem. Retargeting Shiroko Terror onto
        # its own native character (Kirumi Tojo) exercises the identical dead "skirt" slot
        # as the Default-install test, just through patch_retargeted_model_bodygroup_names
        # instead of patch_default_model_bodygroup_names -- proving both paths share the
        # same relocate_unreachable_bodygroups logic.
        app_dir = r"C:\Users\user\Desktop\GMod_Override_Manager"
        source_pack = os.path.join(app_dir, "overrides", "Shiroko Terror Kirumi")
        source_model = os.path.join(source_pack, "models/dro/player/characters3/char13/char13.mdl")
        target_model = os.path.join(app_dir, "debug_extracts/dro_playermodels_2562456244/models/dro/player/characters3/char13/char13.mdl")
        if not os.path.exists(source_model) or not os.path.exists(target_model):
            self.skipTest("real Shiroko Terror/Kirumi models not available")
        old_app_dir = om.APP_DIR
        try:
            om.APP_DIR = app_dir
            cfg = {"gmod_path": self.tempdir}
            pack = {"name": "Shiroko Terror Kirumi", "slug": "ovr_shiroko_terror_kirumi", "folder": source_pack}
            target = om.find_target({}, "Kirumi Tojo")

            om.enable(cfg, pack, target)

            mdl_path = os.path.join(
                self.tempdir, "addons", om.addon_slug(pack, target),
                "models/dro/player/characters3/char13/char13.mdl",
            )
            vtx_path = mdl_path[:-4] + ".dx90.vtx"
            groups = {g["index"]: g for g in om.parse_mdl_bodygroups(mdl_path)}
            self.assertEqual(1, groups[3]["count"])
            relocated = [g for g in groups.values() if g["index"] > 3]
            self.assertTrue(relocated)
            self.assertEqual(2, relocated[0]["count"])
            mdl_numbodyparts = struct.unpack_from("<i", open(mdl_path, "rb").read(240), 232)[0]
            vtx_numbodyparts = struct.unpack_from("<i", open(vtx_path, "rb").read(36), 28)[0]
            self.assertEqual(mdl_numbodyparts, vtx_numbodyparts)
        finally:
            om.APP_DIR = old_app_dir

    def test_enable_retarget_renames_override_bodygroups_to_target_slider_names(self):
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko"
        target_model = r"C:\Users\user\Desktop\Female_Shuichi_Addon_Extracts\2562456244_PlayerModels_ST\models\dro\player\characters1\char9\char9.mdl"
        if not os.path.exists(os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl")) or not os.path.exists(target_model):
            self.skipTest("real Hoshino/Junko models not available")
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko", "folder": source_pack}
        target = om.find_target({}, "Junko Enoshima (Default)")

        om.enable(cfg, pack, target)

        mdl_path = os.path.join(
            self.tempdir,
            "addons",
            "ovr_hoshino_himiko__junko_enoshima__default",
            "models/dro/player/characters1/char9/char9.mdl",
        )
        names = [group["name"] for group in om.parse_mdl_bodygroups(mdl_path)]
        self.assertIn("glasses", names)
        self.assertIn("tie", names)
        self.assertIn("skirt", names)

    def test_enable_retarget_preserves_override_bodygroup_counts(self):
        # Retargeting must NOT collapse the override model's own bodygroups. Richly
        # bodygrouped models (e.g. Shiroko: separate Clothes/Coat/Glove/Scarf/Shoes/
        # Socks groups) carry more clothing groups than the target slot; forcing the
        # unmatched ones to count=1 pins them to submodel 0 and hides clothing /
        # corrupts the body-index decode. Only names may change; counts stay native.
        source_pack = r"C:\Users\user\Desktop\GMod_Override_Manager\overrides\Hoshino Himiko"
        source_model = os.path.join(source_pack, "models/dro/player/characters3/char12/char12.mdl")
        target_model = r"C:\Users\user\Desktop\Female_Shuichi_Addon_Extracts\2562456244_PlayerModels_ST\models\dro\player\characters1\char9\char9.mdl"
        if not os.path.exists(source_model) or not os.path.exists(target_model):
            self.skipTest("real Hoshino/Junko models not available")
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko", "folder": source_pack}
        target = om.find_target({}, "Junko Enoshima (Default)")

        om.enable(cfg, pack, target)

        mdl_path = os.path.join(
            self.tempdir,
            "addons",
            "ovr_hoshino_himiko__junko_enoshima__default",
            "models/dro/player/characters1/char9/char9.mdl",
        )
        source_counts = sorted(g["count"] for g in om.parse_mdl_bodygroups(source_model))
        retargeted_counts = sorted(g["count"] for g in om.parse_mdl_bodygroups(mdl_path))
        self.assertEqual(source_counts, retargeted_counts)

    def test_disable_removes_default_and_retargeted_addons_for_pack(self):
        addons = os.path.join(self.tempdir, "addons")
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko"), exist_ok=True)
        os.makedirs(os.path.join(addons, "ovr_hoshino_himiko__mukuro_ikusaba"), exist_ok=True)
        os.makedirs(os.path.join(addons, "ovr_other_pack"), exist_ok=True)
        cfg = {"gmod_path": self.tempdir}
        pack = {"name": "Hoshino Himiko", "slug": "ovr_hoshino_himiko"}

        om.disable(cfg, pack)

        self.assertFalse(os.path.exists(os.path.join(addons, "ovr_hoshino_himiko")))
        self.assertFalse(os.path.exists(os.path.join(addons, "ovr_hoshino_himiko__mukuro_ikusaba")))
        self.assertTrue(os.path.exists(os.path.join(addons, "ovr_other_pack")))

    def test_create_override_pack_copies_models_materials_sprites_and_metadata(self):
        source_root = os.path.join(self.tempdir, "source")
        os.makedirs(os.path.join(source_root, "models", "player"), exist_ok=True)
        os.makedirs(os.path.join(source_root, "materials", "models", "example"), exist_ok=True)
        model = os.path.join(source_root, "models", "player", "example.mdl")
        arms = os.path.join(source_root, "models", "player", "c_example_arms.mdl")
        for path in (
            model,
            os.path.join(source_root, "models", "player", "example.vvd"),
            os.path.join(source_root, "models", "player", "example.dx90.vtx"),
            arms,
            os.path.join(source_root, "models", "player", "c_example_arms.vvd"),
        ):
            with open(path, "wb") as f:
                f.write(b"model")
        with open(os.path.join(source_root, "materials", "models", "example", "body.vmt"), "wb") as f:
            f.write(b"material")
        sprite = os.path.join(self.tempdir, "sprite.vtf")
        with open(sprite, "wb") as f:
            f.write(b"sprite")

        target = om.find_target({}, "Himiko Yumeno")
        output = om.create_override_pack({
            "name": "Maker Pack",
            "character": "Himiko Yumeno",
            "skin": "Local model",
            "description": "Created by test",
            "source_target": target,
            "main_model": model,
            "arms_model": arms,
            "material_root": source_root,
            "sprite_dir": target["sprite_dir"],
            "sprite_assignments": {"Talk 1": {"path": sprite, "filename": "ct_sprite_1.vtf"}},
            "overrides_dir": os.path.join(self.tempdir, "overrides"),
        })

        self.assertTrue(os.path.exists(os.path.join(output, "models/dro/player/characters3/char12/char12.mdl")))
        self.assertTrue(os.path.exists(os.path.join(output, "models/dro/player/characters3/char12/char12.vvd")))
        self.assertTrue(os.path.exists(os.path.join(output, "models/dro/player/characters3/char12/c_arms/char12_arms.mdl")))
        self.assertTrue(os.path.exists(os.path.join(output, "materials/models/example/body.vmt")))
        self.assertTrue(os.path.exists(os.path.join(output, "materials/dro/sprites/characters/dr_v3/himiko yumeno/ct_sprite_1.vtf")))
        with open(os.path.join(output, "override.json"), "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual("Maker Pack", meta["name"])
        self.assertEqual("Himiko Yumeno", meta["character"])
        self.assertEqual(target, meta["source_target"])

    def test_create_override_pack_uses_selected_character_as_override_target(self):
        source_root = os.path.join(self.tempdir, "source")
        os.makedirs(os.path.join(source_root, "models", "player"), exist_ok=True)
        model = os.path.join(source_root, "models", "player", "example.mdl")
        with open(model, "wb") as f:
            f.write(b"model")

        target = om.find_target({}, "Junko Enoshima (Default)")
        output = om.create_override_pack({
            "name": "Maker Junko Pack",
            "character": target["name"],
            "skin": "Local model",
            "description": "",
            "source_target": target,
            "main_model": model,
            "arms_model": "",
            "material_root": "",
            "sprite_dir": target["sprite_dir"],
            "sprite_assignments": {},
            "overrides_dir": os.path.join(self.tempdir, "overrides"),
        })

        self.assertTrue(os.path.exists(os.path.join(output, "models/dro/player/characters1/char9/char9.mdl")))
        with open(os.path.join(output, "override.json"), "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual("Junko Enoshima (Default)", meta["character"])
        self.assertEqual(target["model_base"], meta["source_target"]["model_base"])

    def test_create_override_pack_rejects_non_game_ready_sprite_files(self):
        source_root = os.path.join(self.tempdir, "source")
        os.makedirs(os.path.join(source_root, "models", "player"), exist_ok=True)
        model = os.path.join(source_root, "models", "player", "example.mdl")
        with open(model, "wb") as f:
            f.write(b"model")
        sprite = os.path.join(self.tempdir, "sprite.png")
        with open(sprite, "wb") as f:
            f.write(b"not vtf")

        with self.assertRaises(ValueError) as cm:
            om.create_override_pack({
                "name": "Bad Sprite Pack",
                "character": "Himiko Yumeno",
                "skin": "",
                "description": "",
                "source_target": om.find_target({}, "Himiko Yumeno"),
                "main_model": model,
                "arms_model": "",
                "material_root": "",
                "sprite_dir": "materials/dro/sprites/characters/dr_v3/himiko yumeno",
                "sprite_assignments": {"Talk 1": {"path": sprite, "filename": "ct_sprite_1.vtf"}},
                "overrides_dir": os.path.join(self.tempdir, "overrides"),
            })
        self.assertIn("game-ready .vtf or .vmt", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.tempdir, "overrides", "Bad Sprite Pack")))

    def test_make_talk_sprite_slots_can_extend_optional_talk_sprites(self):
        self.assertEqual(
            [("Talk 1", "ct_sprite_1.vtf"), ("Talk 2", "ct_sprite_2.vtf"), ("Talk 3", "ct_sprite_3.vtf")],
            om.make_talk_sprite_slots(3),
        )
        self.assertEqual(("Talk 5", "ct_sprite_5.vtf"), om.make_talk_sprite_slots(5)[-1])

    def test_make_sprite_group_slot_extends_special_sprite_groups(self):
        self.assertEqual(("Argue 3", "ct_argue_3.vtf"), om.make_sprite_group_slot("Argue", 3))
        self.assertEqual(("Consent 2", "ct_consent_2.vtf"), om.make_sprite_group_slot("Consent", 2))
        self.assertEqual(("Scrum Debate Left 2", "ct_scrum_left_2.vtf"), om.make_sprite_group_slot("Scrum Debate Left", 2))
        self.assertEqual(("Scrum Debate Right 2", "ct_scrum_right_2.vtf"), om.make_sprite_group_slot("Scrum Debate Right", 2))
        self.assertEqual(("Objection", "ct_objection.vtf"), om.make_sprite_group_slot("Objection", 1))
        self.assertEqual(("Door Sprite", "doorpixelart.vtf"), om.make_sprite_group_slot("Door Sprite", 1))

    def test_make_sprite_group_slot_includes_misc_sprite_types(self):
        self.assertEqual(("Talk Icon 2", "ct_spriteico_2.vtf"), om.make_sprite_group_slot("Talk Icon", 2))
        self.assertEqual(("Dead", "dead.vtf"), om.make_sprite_group_slot("Dead", 1))
        self.assertEqual(("HUD Icon", "hud_ico.vtf"), om.make_sprite_group_slot("HUD Icon", 1))
        self.assertEqual(("Pixel Icon", "pixel_ico.vtf"), om.make_sprite_group_slot("Pixel Icon", 1))
        self.assertEqual(("Pixel Sprite", "pixel_sprite.vtf"), om.make_sprite_group_slot("Pixel Sprite", 1))
        self.assertEqual(("Vote Icon", "vote_ico.vtf"), om.make_sprite_group_slot("Vote Icon", 1))
        self.assertEqual(("Vote Sprite", "vote_sprite.vtf"), om.make_sprite_group_slot("Vote Sprite", 1))

    def test_make_sprite_group_slots_returns_batch_slots(self):
        self.assertEqual(
            [
                ("Scrum Debate Left", "ct_scrum_left.vtf"),
                ("Scrum Debate Left 2", "ct_scrum_left_2.vtf"),
                ("Scrum Debate Left 3", "ct_scrum_left_3.vtf"),
            ],
            om.make_sprite_group_slots("Scrum Debate Left", 3),
        )

    def test_workshop_item_id_parses_urls_and_plain_ids(self):
        self.assertEqual("3035125163", om.workshop_item_id("https://steamcommunity.com/sharedfiles/filedetails/?id=3035125163&searchtext=hoshino"))
        self.assertEqual("3035125163", om.workshop_item_id("3035125163"))

    def test_find_workshop_gma_uses_gmod_steamapps_folder(self):
        steamapps = os.path.join(self.tempdir, "steamapps")
        gmod_path = os.path.join(steamapps, "common", "GarrysMod", "garrysmod")
        item_dir = os.path.join(steamapps, "workshop", "content", "4000", "123")
        os.makedirs(item_dir, exist_ok=True)
        gma = os.path.join(item_dir, "addon.gma")
        with open(gma, "wb") as f:
            f.write(b"gma")

        self.assertEqual(gma, om.find_workshop_gma(gmod_path, "123"))


class RecommenderTests(unittest.TestCase):
    def test_bodygroup_options_capped_by_base_count_at_same_index(self):
        # Reachability is decided index-by-index (that's how the in-game tool works).
        # Shiroko's outfit at index 3 -> Kirumi's index-3 group (2 options) = 2 of 3.
        ov = [{"index": 3, "name": "outfit", "count": 3}]
        kirumi = {"skins": 1, "groups": [{"index": 3, "name": "neck", "count": 2},
                                         {"index": 4, "name": "tie", "count": 2}]}
        # Makoto's 3-option group is at index 1, NOT 3, so it does NOT help here.
        makoto = {"skins": 1, "groups": [{"index": 1, "name": "body", "count": 3}]}
        # A character with a 3-option group exactly at index 3 unlocks all 3.
        good = {"skins": 1, "groups": [{"index": 3, "name": "anything", "count": 3}]}
        self.assertEqual(om.match_override_to_profile(ov, 1, kirumi)["reach"], 2)
        self.assertEqual(om.match_override_to_profile(ov, 1, makoto)["reach"], 1)
        self.assertEqual(om.match_override_to_profile(ov, 1, good)["reach"], 3)

    def test_skins_uncapped_but_need_base_with_multiple_skins(self):
        # 3 override skins reach all 3 when base has >1 skin; locked to 1 when base has 1.
        r_ok = om.match_override_to_profile([], 3, {"skins": 2, "groups": []})
        r_locked = om.match_override_to_profile([], 3, {"skins": 1, "groups": []})
        self.assertEqual((r_ok["reach"], r_ok["total"]), (3, 3))
        self.assertEqual((r_locked["reach"], r_locked["total"]), (1, 3))

    def test_index_pairs_match_by_index_not_capacity(self):
        pairs = om.index_pairs(
            [{"index": 1, "name": "outfit", "count": 3}],
            [{"index": 1, "name": "x", "count": 2}, {"index": 5, "name": "y", "count": 4}],
        )
        # override idx1 pairs with target idx1 (2 options) -> 2, ignoring the bigger idx5 group
        self.assertEqual(pairs[0][2], 2)
        self.assertEqual(pairs[0][1]["index"], 1)


class ConflictResolutionTests(unittest.TestCase):
    def test_older_pack_keeps_target_newer_falls_back(self):
        packs = [{"name": "Old", "folder": "/old"}, {"name": "New", "folder": "/new"}]
        slugs = {om.pack_addon_prefix(packs[0]), om.pack_addon_prefix(packs[1])}
        orig_ct, orig_pref = om.pack_ctime, om.pack_target_preferences
        om.pack_ctime = lambda p: 1 if p["name"] == "Old" else 2
        om.pack_target_preferences = lambda cfg, p, primary: [("Ibuki Mioda", "char5"), ("Celestia Ludenberg", "char8")]
        try:
            asg = om.resolve_enabled_assignment({}, packs, slugs, lambda p: "Ibuki Mioda")
        finally:
            om.pack_ctime, om.pack_target_preferences = orig_ct, orig_pref
        self.assertEqual(asg[om.pack_addon_prefix(packs[0])], "Ibuki Mioda")        # older keeps it
        self.assertEqual(asg[om.pack_addon_prefix(packs[1])], "Celestia Ludenberg")  # newer falls back

    def test_no_conflict_keeps_both_preferred(self):
        packs = [{"name": "A", "folder": "/a"}, {"name": "B", "folder": "/b"}]
        slugs = {om.pack_addon_prefix(packs[0]), om.pack_addon_prefix(packs[1])}
        orig_ct, orig_pref = om.pack_ctime, om.pack_target_preferences
        om.pack_ctime = lambda p: 1 if p["name"] == "A" else 2
        prefs = {"A": [("X", "slotX"), ("Z", "slotZ")], "B": [("Y", "slotY"), ("Z", "slotZ")]}
        om.pack_target_preferences = lambda cfg, p, primary: prefs[p["name"]]
        try:
            asg = om.resolve_enabled_assignment({}, packs, slugs, lambda p: prefs[p["name"]][0][0])
        finally:
            om.pack_ctime, om.pack_target_preferences = orig_ct, orig_pref
        self.assertEqual(asg[om.pack_addon_prefix(packs[0])], "X")
        self.assertEqual(asg[om.pack_addon_prefix(packs[1])], "Y")



class ServerDetectTests(unittest.TestCase):
    def test_detect_current_server_from_console_log(self):
        tmp = tempfile.mkdtemp()
        try:
            log = os.path.join(tmp, "console.log")
            with open(log, "w") as f:
                f.write("map load\nConnecting to 45.67.89.10:27015...\nConnected to 45.67.89.10:27015\nplay\n")
            self.assertEqual(om.detect_current_server({"gmod_path": tmp}), "45.67.89.10:27015")
            with open(log, "a") as f:
                f.write("Disconnect: Leaving.\n")
            self.assertEqual(om.detect_current_server({"gmod_path": tmp}), "")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_ensure_console_logging_writes_autoexec_once_and_preserves_content(self):
        tmp = tempfile.mkdtemp()
        try:
            cfg = {"gmod_path": tmp}
            self.assertTrue(om.ensure_console_logging(cfg))
            autoexec = os.path.join(tmp, "cfg", "autoexec.cfg")
            self.assertIn("con_logfile", open(autoexec, encoding="utf-8").read())
            om.ensure_console_logging(cfg)  # idempotent
            self.assertEqual(open(autoexec, encoding="utf-8").read().count("con_logfile"), 1)
            with open(autoexec, "w", encoding="utf-8") as f:
                f.write("bind x say hi\n")
            om.ensure_console_logging(cfg)
            body = open(autoexec, encoding="utf-8").read()
            self.assertIn("bind x say hi", body)
            self.assertIn("con_logfile", body)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
