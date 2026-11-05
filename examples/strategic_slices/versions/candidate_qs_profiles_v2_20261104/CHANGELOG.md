# v2实现修复

v1三题pilot在没有零质量stub的forest读取缺省Counter字段时失败；旧source及实际run保留。
本版本仅将该统计字段显式补0，不改裁剪/标签公式、输入/参数或游戏。数学方法仍见../candidate_qs_profiles_v1_20261104/DESIGN.md。
