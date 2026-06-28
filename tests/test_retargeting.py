import importlib
import json
import os
import shutil
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


if __name__ == "__main__":
    unittest.main()
