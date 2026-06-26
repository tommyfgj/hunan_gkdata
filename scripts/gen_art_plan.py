"""根据考生综合分，用「等位次法」生成美术与设计类平行组志愿方案。

方法（同位次百分比法 / 等效位次）：
1. 考生 2026 综合分 -> 2026 综合分一分段 -> 2026 位次 -> 全省百分比。
2. 百分比 × 2025 总人数 -> 考生「2025 等效位次」。
3. 每个 2025 美术专业组投档线 -> 2025 位次。
4. 用 (投档线位次 / 等效位次) 比值分档：冲 / 稳 / 保。
5. 仅保留 2026 仍有美术招生计划的院校（可填），附 2026 计划人数。

注意：专业组编号逐年重排，跨年只能按「院校 + 专业组类型」对应，故方案以
2025 投档线为竞争力锚点，2026 计划用于确认院校今年是否可填。
"""

import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "output" / "hunan_gkdata.db"
OUT = ROOT / "output" / "美术志愿方案_综合分305.4.csv"

# ===== 考生信息 =====
SCORE_2026 = 305.4
SUBJECT_KW = "美术"  # 专业组名称关键词
CULTURE = 479        # 高考文化成绩
PRO = 231            # 专业统考成绩
FOREIGN = 97         # 外语成绩
IS_FEMALE = False    # 性别(女生=True)

# ===== 参照控制线(2026) =====
LINE_ART_CULTURE = 320   # 美术与设计类本科文化线
LINE_PUTONG = 400        # 物理类普通本科线
LINE_TESHU = 481         # 物理类特殊类型招生控制线


def check_remark(remark: str) -> tuple[bool, str]:
    """根据考生成绩判定备注条件是否满足。返回 (是否合格, 不满足原因)。"""
    if not remark or not remark.strip():
        return True, ""
    import re
    fails: list[str] = []

    if "只招女生" in remark and not IS_FEMALE:
        fails.append("只招女生")

    # 外语成绩不低于X分
    for m in re.finditer(r"外语成绩不低于(\d+)分", remark):
        need = int(m.group(1))
        if FOREIGN < need:
            fails.append(f"外语需≥{need}(你{FOREIGN})")

    # 美术/专业统考成绩不低于X分
    for m in re.finditer(r"(?:美术类专业|专业)统考成绩不低于(\d+)分", remark):
        need = int(m.group(1))
        if PRO < need:
            fails.append(f"统考需≥{need}(你{PRO})")

    # 文化成绩要求
    if "文化成绩不低于350分" in remark and CULTURE < 350:
        fails.append("文化需≥350")
    if "文化成绩不低于400分" in remark and CULTURE < 400:
        fails.append("文化需≥400")
    # 特殊类型线上30分
    if "特殊类型招生录取控制分数线上30分" in remark:
        need = LINE_TESHU + 30
        if CULTURE < need:
            fails.append(f"文化需≥特殊线+30={need}(你{CULTURE})")
    else:
        # 特殊类型线的百分比
        mp = re.search(r"特殊类型招生录取控制分数线的(\d+)%", remark)
        if mp:
            need = round(LINE_TESHU * int(mp.group(1)) / 100)
            if CULTURE < need:
                fails.append(f"文化需≥特殊线{mp.group(1)}%={need}(你{CULTURE})")
        elif "特殊类型招生录取控制分数线" in remark:
            if CULTURE < LINE_TESHU:
                fails.append(f"文化需≥特殊线{LINE_TESHU}(你{CULTURE})")
    # 普通类本科线
    if "普通类本科录取控制分数线" in remark and CULTURE < LINE_PUTONG:
        fails.append(f"文化需≥普通本科线{LINE_PUTONG}")
    # 艺术类本科文化线140%
    mart = re.search(r"艺术类本科招生文化录取控制分数线的(\d+)%", remark)
    if mart:
        need = round(LINE_ART_CULTURE * int(mart.group(1)) / 100)
        if CULTURE < need:
            fails.append(f"文化需≥艺术线{mart.group(1)}%={need}(你{CULTURE})")

    return (len(fails) == 0), "；".join(fails)


def cumrank(cur, year: int, score: float) -> int | None:
    """该综合分在指定年份的累计位次（综合成绩<=score 的最高累计人数）。"""
    cur.execute(
        "SELECT 累计人数 FROM 一分段_美术与设计类综合成绩 "
        "WHERE 年份=? AND 综合成绩<=? ORDER BY 综合成绩 DESC LIMIT 1",
        (year, score),
    )
    r = cur.fetchone()
    return r[0] if r else None


def total(cur, year: int) -> int:
    cur.execute(
        "SELECT MAX(累计人数) FROM 一分段_美术与设计类综合成绩 WHERE 年份=?", (year,)
    )
    return cur.fetchone()[0]


def classify(ratio: float) -> str:
    """ratio = 投档线位次 / 我的等效位次。<1 表示投档线比我高(更难)。

    口径(边界)：冲 0.9 / 稳 1.1 / 保 1.3
      偏冲(风险高): ratio < 0.9
      冲:           0.9 <= ratio < 1.1
      稳:           1.1 <= ratio < 1.3
      保:           1.3 <= ratio < 1.5
      垫底(过保):    ratio >= 1.5
    """
    if ratio < 0.9:
        return "偏冲(风险高)"
    if ratio < 1.1:
        return "冲"
    if ratio < 1.3:
        return "稳"
    if ratio < 1.5:
        return "保"
    return "垫底(过保)"


def grp_type(name: str) -> str:
    if "中外合作" in name or "国际" in name:
        return "中外合作/国际"
    if "优师" in name or "公费" in name or "定向" in name:
        return "公费/优师/定向"
    return "普通"


def main() -> None:
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    rank_2026 = cumrank(cur, 2026, SCORE_2026)
    total_2026 = total(cur, 2026)
    total_2025 = total(cur, 2025)
    pct = rank_2026 / total_2026
    eq_rank_2025 = round(pct * total_2025)
    # 等位分（仅参考显示）
    cur.execute(
        "SELECT 综合成绩 FROM 一分段_美术与设计类综合成绩 "
        "WHERE 年份=2025 AND 累计人数>=? ORDER BY 累计人数 ASC LIMIT 1",
        (eq_rank_2025,),
    )
    eq_score_2025 = cur.fetchone()[0]

    print(f"考生 2026 综合分 {SCORE_2026} -> 2026 位次 {rank_2026} / {total_2026} "
          f"(前 {pct*100:.2f}%)")
    print(f"-> 2025 等效位次 ≈ {eq_rank_2025} / {total_2025}，等位分 ≈ {eq_score_2025}\n")

    # 2026 有美术计划的院校（代码 -> 计划人数合计、专业组数）
    cur.execute(
        "SELECT 院校代码, SUM(CAST(计划人数 AS INT)), COUNT(DISTINCT 院校专业组代码) "
        "FROM 招生计划2026_艺术类 "
        "WHERE 匹配类别='美术与设计类' AND 计划类别='艺术类(平行组)' "
        "GROUP BY 院校代码",
        (),
    )
    plan26 = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    # 2025 美术投档线
    cur.execute(
        "SELECT 院校代号, 院校名称, 专业组名称, 投档线, 备注 FROM 艺术类平行组投档线 "
        "WHERE 年份=2025 AND 专业组名称 LIKE ? AND 投档线 IS NOT NULL AND 投档线!=''",
        (f"%{SUBJECT_KW}%",),
    )
    rows = []
    excluded_by_remark = 0
    for code, name, grp, line, remark in cur.fetchall():
        # 剔除中外合作/国际项目专业组
        if "中外合作" in grp or "国际" in grp:
            continue
        line = float(line)
        lrank = cumrank(cur, 2025, line)
        if not lrank:
            continue
        ratio = lrank / eq_rank_2025
        cat = classify(ratio)
        if cat == "偏冲(风险高)":
            continue
        # 备注资格判定：不满足者剔除
        ok, reason = check_remark(remark or "")
        if not ok:
            excluded_by_remark += 1
            continue
        has26 = code in plan26
        plan_n, grp_n = plan26.get(code, ("", ""))
        rows.append({
            "档位": cat,
            "院校代号": code,
            "院校名称": name,
            "专业组类型": grp_type(grp),
            "2025专业组名称": grp,
            "2025投档线": line,
            "2025投档位次": lrank,
            "位次比值": round(ratio, 2),
            "2026有美术计划": "是" if has26 else "否",
            "2026计划人数": plan_n,
            "2026美术组数": grp_n,
            "2025备注要求": (remark or "").strip(),
        })

    order = {"冲": 1, "稳": 2, "保": 3, "垫底(过保)": 4}
    rows.sort(key=lambda r: (order[r["档位"]], r["2025投档位次"]))

    fields = list(rows[0].keys())
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    # 控制台汇总（仅 2026 可填的院校）
    fillable = [r for r in rows if r["2026有美术计划"] == "是"]
    print("=== 各档位院校数（仅统计 2026 可填，已剔除中外合作）===")
    for cat in ["冲", "稳", "保", "垫底(过保)"]:
        print(f"  {cat}: {sum(1 for r in fillable if r['档位']==cat)}")

    for cat in ["冲", "稳", "保"]:
        sel = [r for r in fillable if r["档位"] == cat][:10]
        print(f"\n=== {cat}（2025投档线 / 位次 / 比值）示例前10 ===")
        for r in sel:
            print(f"  {r['院校名称']:<14} {r['2025投档线']:>6} "
                  f"位次{r['2025投档位次']:>5} 比值{r['位次比值']} "
                  f"[{r['专业组类型']}] 计划{r['2026计划人数']}人")

    print(f"\n因备注条件不满足而剔除: {excluded_by_remark} 个专业组")
    print(f"完整方案已导出: {OUT}（共 {len(rows)} 个2025美术专业组，"
          f"其中2026可填 {len(fillable)} 个）")
    conn.close()


if __name__ == "__main__":
    main()
