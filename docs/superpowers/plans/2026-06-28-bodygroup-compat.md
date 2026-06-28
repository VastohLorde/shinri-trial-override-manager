# Bodygroup Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make retargeted overrides translate server-applied target-character bodygroup indexes into the override model's bodygroup indexes.

**Architecture:** Add tested MDL bodygroup parsing and mapping helpers to `override_manager.py`. During retarget install, generate a client Lua autorun file that detects the local player's model path and remaps bodygroups every tick from the target layout to the override layout.

**Tech Stack:** Python standard library, Source `.mdl` header parsing, generated Garry's Mod Lua, `unittest`.

---

### Task 1: Bodygroup Parser And Mapping

**Files:**
- Modify: `override_manager.py`
- Modify: `tests/test_retargeting.py`

- [ ] Add tests for parsing Hoshino bodygroup names from a real `.mdl`.
- [ ] Add tests for mapping target bodygroup names to override names, including fallback by ordinal when names do not match.
- [ ] Implement `parse_mdl_bodygroups`, `bodygroup_compat_map`, and name-normalization helpers.
- [ ] Run `python -m unittest tests.test_retargeting -v`.

### Task 2: Generated Lua Compatibility Layer

**Files:**
- Modify: `override_manager.py`
- Modify: `tests/test_retargeting.py`

- [ ] Add tests that retarget install writes `lua/autorun/ovr_bodygroup_compat_<slug>.lua`.
- [ ] Implement Lua generation with target model path, override bodygroup names, and mapping table.
- [ ] Ensure the Lua only runs on the local player and only when the retargeted model path is active.
- [ ] Run `python -m unittest tests.test_retargeting -v`.

### Task 3: Full Character Coverage And Rebuild

**Files:**
- Modify: `override_manager.py`
- Modify: desktop portable app files after build

- [ ] Ensure every built-in target can produce a bodygroup map when its target model exists in the extracted addon or installed addon.
- [ ] Run `python -m unittest discover -v`.
- [ ] Run `python -m py_compile override_manager.py`.
- [ ] Rebuild the PyInstaller app and copy it to `C:\Users\user\Desktop\GMod_Override_Manager`.
