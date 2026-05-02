# Changelog

## [1.5.3](https://github.com/binary-core-llc/bowerbot/compare/v1.5.2...v1.5.3) (2026-05-02)


### Bug Fixes

* pin major version upper bounds on all dependencies ([#118](https://github.com/binary-core-llc/bowerbot/issues/118)) ([ec9a12a](https://github.com/binary-core-llc/bowerbot/commit/ec9a12a5f891e507ed484d95878f142d5c1cf4ed))

## [1.5.2](https://github.com/binary-core-llc/bowerbot/compare/v1.5.1...v1.5.2) (2026-05-01)


### Bug Fixes

* replace non-ASCII output chars in CLI to fix Windows encoding crash ([#115](https://github.com/binary-core-llc/bowerbot/issues/115)) ([087d607](https://github.com/binary-core-llc/bowerbot/commit/087d607a553cadbcd57553e2eeaf4030649b8443))

## [1.5.1](https://github.com/binary-core-llc/bowerbot/compare/v1.5.0...v1.5.1) (2026-05-01)


### Documentation

* add 'Verifying a skill is installed' section ([#95](https://github.com/binary-core-llc/bowerbot/issues/95)) ([87b8cad](https://github.com/binary-core-llc/bowerbot/commit/87b8cad2f37c34f6e83f47363a46e4271aa668c1))
* restructure README flow, drop in-tree skill mode from CONTRIBUTING ([#96](https://github.com/binary-core-llc/bowerbot/issues/96)) ([50c3c46](https://github.com/binary-core-llc/bowerbot/commit/50c3c464039b4c08b1e943e3966f8d2960dc082b))
* rewrite Quick Start, add skill install walkthrough, curate Skills ([#93](https://github.com/binary-core-llc/bowerbot/issues/93)) ([e68e3f1](https://github.com/binary-core-llc/bowerbot/commit/e68e3f16c2230945453583c1aaac851525b3c664))

## [1.5.0](https://github.com/binary-core-llc/bowerbot/compare/v1.4.3...v1.5.0) (2026-05-01)


### Features

* extract sketchfab into bowerbot-skill-sketchfab + add PyPI publish ([#92](https://github.com/binary-core-llc/bowerbot/issues/92)) ([8a51488](https://github.com/binary-core-llc/bowerbot/commit/8a514888ae886dec4cf338c289d3bbefa84a313b))
* stabilize skill contract for external pip-installable packages ([#90](https://github.com/binary-core-llc/bowerbot/issues/90)) ([36e92e6](https://github.com/binary-core-llc/bowerbot/commit/36e92e6ba484cd0acb143f6f8eb5c3be2aaf726f))

## [1.4.3](https://github.com/binary-core-llc/bowerbot/compare/v1.4.2...v1.4.3) (2026-04-30)


### Bug Fixes

* plumb texture through update_light for scene and asset lights ([#88](https://github.com/binary-core-llc/bowerbot/issues/88)) ([484bd56](https://github.com/binary-core-llc/bowerbot/commit/484bd5681eb64991b80356d3baf647461c2a2310))

## [1.4.2](https://github.com/binary-core-llc/bowerbot/compare/v1.4.1...v1.4.2) (2026-04-26)


### Bug Fixes

* route cli stage calls to stage_utils after refactor ([#87](https://github.com/binary-core-llc/bowerbot/issues/87)) ([746628d](https://github.com/binary-core-llc/bowerbot/commit/746628d0ca3867da5ecb0e30ded7694baa68b1fb))


### Documentation

* drop local and textures from README config skills block ([#84](https://github.com/binary-core-llc/bowerbot/issues/84)) ([5075b6e](https://github.com/binary-core-llc/bowerbot/commit/5075b6e86029bfd7bd83817f3b6618f151f643fa))

## [1.4.1](https://github.com/binary-core-llc/bowerbot/compare/v1.4.0...v1.4.1) (2026-04-25)


### Documentation

* align README with v1.4.0 intake behavior ([#79](https://github.com/binary-core-llc/bowerbot/issues/79)) ([754350a](https://github.com/binary-core-llc/bowerbot/commit/754350a6d1928fdde46ee790987c629fd32ff188))

## [1.4.0](https://github.com/binary-core-llc/bowerbot/compare/v1.3.0...v1.4.0) (2026-04-23)


### Features

* cleanup_unused_materials tool to prune orphaned material defs ([#74](https://github.com/binary-core-llc/bowerbot/issues/74)) ([e42dc07](https://github.com/binary-core-llc/bowerbot/commit/e42dc079bd24850473b052875e330c6f9eb9e658))
* self-contained asset folder intake with localization ([#78](https://github.com/binary-core-llc/bowerbot/issues/78)) ([dcd707b](https://github.com/binary-core-llc/bowerbot/commit/dcd707b1c3a0c768c94e2a15ae1642f41f9103cc))


### Documentation

* complete Scene Builder Tools table with all 22 tools ([#77](https://github.com/binary-core-llc/bowerbot/issues/77)) ([d44ea98](https://github.com/binary-core-llc/bowerbot/commit/d44ea98e613b56924727aefcfd76809db0932fe8))

## [1.3.0](https://github.com/binary-core-llc/bowerbot/compare/v1.2.0...v1.3.0) (2026-04-16)


### Features

* place_asset_inside for nested asset references with full coordi… ([#71](https://github.com/binary-core-llc/bowerbot/issues/71)) ([c446b4b](https://github.com/binary-core-llc/bowerbot/commit/c446b4b8af8c8b2f968c03a2bc0cfa9432624b11))

## [1.2.0](https://github.com/binary-core-llc/bowerbot/compare/v1.1.1...v1.2.0) (2026-04-14)


### Features

* add bounds to list_prim_children results ([#66](https://github.com/binary-core-llc/bowerbot/issues/66)) ([30ec122](https://github.com/binary-core-llc/bowerbot/commit/30ec12284c3b65d41a3cf690372e47e169d5a18b))
* add exposure parameter to USD lights ([#70](https://github.com/binary-core-llc/bowerbot/issues/70)) ([ea6a8a1](https://github.com/binary-core-llc/bowerbot/commit/ea6a8a10ec9af607f5c1c00b03d8795ef0ab9c33))
* create procedural MaterialX materials from natural language ([#64](https://github.com/binary-core-llc/bowerbot/issues/64)) ([7cb6998](https://github.com/binary-core-llc/bowerbot/commit/7cb6998f4d1517726c4e46e8a1bd1dd76675b384))
* make max_tool_rounds configurable via LLM settings ([#63](https://github.com/binary-core-llc/bowerbot/issues/63)) ([d4cf202](https://github.com/binary-core-llc/bowerbot/commit/d4cf202ca654d2ea9e1f37296da7498e23330836))
* unified position_mode for any prim placed inside an asset ([#68](https://github.com/binary-core-llc/bowerbot/issues/68)) ([5594a72](https://github.com/binary-core-llc/bowerbot/commit/5594a729f3178a2214e945305ede19ce85c13824))


### Bug Fixes

* cli resume handles lights and any prim type in scene summary ([#67](https://github.com/binary-core-llc/bowerbot/issues/67)) ([f7eada4](https://github.com/binary-core-llc/bowerbot/commit/f7eada4db2b57a3e2a5a2a0ece87f629e2d2acc6))
* delete_project_asset supports both ASWF folders and standalone f… ([#60](https://github.com/binary-core-llc/bowerbot/issues/60)) ([c5bf1d1](https://github.com/binary-core-llc/bowerbot/commit/c5bf1d1c73adf5c150abd1e66e2f96b7d2e99f87))
* onboard wizard defaults to gpt-4.1 instead of gpt-4o ([#54](https://github.com/binary-core-llc/bowerbot/issues/54)) ([ee3c3ad](https://github.com/binary-core-llc/bowerbot/commit/ee3c3adc3eb5b0743ed50c42e32942c1ad1da87b))
* onboard wizard now asks for projects directory ([#58](https://github.com/binary-core-llc/bowerbot/issues/58)) ([6058951](https://github.com/binary-core-llc/bowerbot/commit/605895113c2899c10611bf995b1e8b833e127890))
* validate and repair ASWF compliance before asset placement ([#65](https://github.com/binary-core-llc/bowerbot/issues/65)) ([93bd388](https://github.com/binary-core-llc/bowerbot/commit/93bd3881f8c3d60939ae636d184ec132b1fc4b35))


### Documentation

* add USD variant sets to roadmap ([#56](https://github.com/binary-core-llc/bowerbot/issues/56)) ([3447dab](https://github.com/binary-core-llc/bowerbot/commit/3447dabb8ccc91ee26ecab6aff541a346d03b113))
* add YouTube tutorials playlist to README ([#59](https://github.com/binary-core-llc/bowerbot/issues/59)) ([edf06f3](https://github.com/binary-core-llc/bowerbot/commit/edf06f31d1514360303779d31f886c8be189b2ac))

## [1.1.1](https://github.com/binary-core-llc/bowerbot/compare/v1.1.0...v1.1.1) (2026-04-05)


### Bug Fixes

* cleanup stale tests and duplication ([#44](https://github.com/binary-core-llc/bowerbot/issues/44)) ([428222d](https://github.com/binary-core-llc/bowerbot/commit/428222dfba0cf5c5dc1c39a7c23c3d337ac49259))
* hardcoded mtl.usd layer name and broken e2e test ([#48](https://github.com/binary-core-llc/bowerbot/issues/48)) ([307d3dc](https://github.com/binary-core-llc/bowerbot/commit/307d3dc626bd73609159ccea8458686541c4cc8f))
* inline imports, unused imports, and pxr leaks in scene_builder ([#49](https://github.com/binary-core-llc/bowerbot/issues/49)) ([0f86da1](https://github.com/binary-core-llc/bowerbot/commit/0f86da1cbc04ccd083e9bd4f0d88549ec5aa2f4b))
* narrow exception handling in list_projects and fix stale docstring ([#52](https://github.com/binary-core-llc/bowerbot/issues/52)) ([708bd9b](https://github.com/binary-core-llc/bowerbot/commit/708bd9b8eb7b939adaed92a220fcfcf13adfd4be))
* remaining f-string logging and inline imports ([#51](https://github.com/binary-core-llc/bowerbot/issues/51)) ([c8330fe](https://github.com/binary-core-llc/bowerbot/commit/c8330fe8027eb97a865785434490908bb6448111))
* remove unused Usd import and move inline tempfile import to top ([#50](https://github.com/binary-core-llc/bowerbot/issues/50)) ([2fb0b08](https://github.com/binary-core-llc/bowerbot/commit/2fb0b08823338f2d8d9547fe866c169446e8bcec))


### Documentation

* update README and CONTRIBUTING for post-refactor architecture ([#53](https://github.com/binary-core-llc/bowerbot/issues/53)) ([936ec81](https://github.com/binary-core-llc/bowerbot/commit/936ec811972fc030f65d3b89d3bd16dd0da34fe1))

## [1.1.0](https://github.com/binary-core-llc/bowerbot/compare/v1.0.3...v1.1.0) (2026-04-05)


### Features

* add asset-level lights with inverse transform and update support ([#29](https://github.com/binary-core-llc/bowerbot/issues/29)) ([73df87d](https://github.com/binary-core-llc/bowerbot/commit/73df87d45d46b8d21d8a1685602e6ad1ed8bc7ff))
* add ASWF asset folder system with incremental assembly ([#23](https://github.com/binary-core-llc/bowerbot/issues/23)) ([27a5c36](https://github.com/binary-core-llc/bowerbot/commit/27a5c3604ebdd4e6a7102e195f0ee827969b16bc))
* add material binding, asset classification, and dependency reso… ([#21](https://github.com/binary-core-llc/bowerbot/issues/21)) ([5718707](https://github.com/binary-core-llc/bowerbot/commit/5718707e86075f2f130a3ee06197aa2feb62c3ee))
* discover skills via Python entry points instead of hardcoded im… ([#38](https://github.com/binary-core-llc/bowerbot/issues/38)) ([cd2cd24](https://github.com/binary-core-llc/bowerbot/commit/cd2cd2458bd912d49631addcd59b30c763f75e5c))
* validate ASWF compliance on asset placement ([#27](https://github.com/binary-core-llc/bowerbot/issues/27)) ([f6bd75c](https://github.com/binary-core-llc/bowerbot/commit/f6bd75c3b9dd918e614ad7e8a3f5243fbc684018))


### Bug Fixes

* add remove_light tool and prevent asset-to-scene light switching ([#30](https://github.com/binary-core-llc/bowerbot/issues/30)) ([34e170d](https://github.com/binary-core-llc/bowerbot/commit/34e170d271245383460fd5542f3eb6e2fde86251))
* enforce local asset search before answering availability ([#24](https://github.com/binary-core-llc/bowerbot/issues/24)) ([21796ff](https://github.com/binary-core-llc/bowerbot/commit/21796ff983dbd3c9d0b4c2f4c5fe30dbbb848340))
* move scene-level HDRI textures to project-level textures/ folder ([#32](https://github.com/binary-core-llc/bowerbot/issues/32)) ([f002f6f](https://github.com/binary-core-llc/bowerbot/commit/f002f6f4f8c807e5069c577489541031940bfaaa))
* recommend asset cleanup on remove ([#28](https://github.com/binary-core-llc/bowerbot/issues/28)) ([c9a1c96](https://github.com/binary-core-llc/bowerbot/commit/c9a1c9686f13a130460b3f532282949a395887f8))
* reopen existing scene instead of crashing on create_stage ([#34](https://github.com/binary-core-llc/bowerbot/issues/34)) ([03e9f0d](https://github.com/binary-core-llc/bowerbot/commit/03e9f0d6596f6d00160901ebe98f0af7bff235a0))
* scan all project USD files before deleting asset folders ([#33](https://github.com/binary-core-llc/bowerbot/issues/33)) ([d4b3065](https://github.com/binary-core-llc/bowerbot/commit/d4b30655f2393fb97567dc4714aafeda0d29ea10))
* update SKILL.md to reflect on-demand hierarchy creation ([#37](https://github.com/binary-core-llc/bowerbot/issues/37)) ([5c5225a](https://github.com/binary-core-llc/bowerbot/commit/5c5225a49b0beb76b9c997cd50a9350524834efd))

## [1.0.3](https://github.com/binary-core-llc/bowerbot/compare/v1.0.2...v1.0.3) (2026-03-24)


### Bug Fixes

* sync pyproject.toml and uv.lock version to 1.0.2 ([#18](https://github.com/binary-core-llc/bowerbot/issues/18)) ([8c7ae25](https://github.com/binary-core-llc/bowerbot/commit/8c7ae252de81a23aae4ce499d4bafc8825e3548d))

## [1.0.2](https://github.com/binary-core-llc/bowerbot/compare/v1.0.1...v1.0.2) (2026-03-24)


### Bug Fixes

* release please pyproject version ([#15](https://github.com/binary-core-llc/bowerbot/issues/15)) ([49876d6](https://github.com/binary-core-llc/bowerbot/commit/49876d62e4f3140c3e8368838da9b8af33a4b57c))

## [1.0.1](https://github.com/binary-core-llc/bowerbot/compare/v1.0.0...v1.0.1) (2026-03-24)


### Bug Fixes

* clean onboard config output and add API key validation ([#13](https://github.com/binary-core-llc/bowerbot/issues/13)) ([d8cb3a8](https://github.com/binary-core-llc/bowerbot/commit/d8cb3a8cf2be8243416ecd91bfdf9450cb984c9c))

## 1.0.0 (2026-03-22)


### Features

* add create_light tool for native USD lighting ([#2](https://github.com/binary-core-llc/bowerbot/issues/2)) ([e014dc6](https://github.com/binary-core-llc/bowerbot/commit/e014dc63224e8a312e0fa93e137128bf745c77ca))
* add textures skill for local HDRI and material map search ([#5](https://github.com/binary-core-llc/bowerbot/issues/5)) ([fe850eb](https://github.com/binary-core-llc/bowerbot/commit/fe850ebd6524737845b9d0c67b143e4b89ac8a44))


### Bug Fixes

* add dot prefix to AssetFormat enum for consistency with texture … ([#8](https://github.com/binary-core-llc/bowerbot/issues/8)) ([2c47eab](https://github.com/binary-core-llc/bowerbot/commit/2c47eabea05700a32cd03bf93ac211da3221f0e9))
* remove hardcoded download path from Sketchfab skill ([#6](https://github.com/binary-core-llc/bowerbot/issues/6)) ([0b2fb95](https://github.com/binary-core-llc/bowerbot/commit/0b2fb954f87a4e5004dedf1f3edee4ab92d191d7))
