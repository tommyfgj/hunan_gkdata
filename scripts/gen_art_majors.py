"""为冲稳保院校列出 2026 美术专业组及组内专业明细（一个专业一行）。

读取已生成的 美术志愿方案_综合分305.4.csv（取冲/稳/保院校代号），
关联 招生计划2026_艺术类 的美术平行组，按专业逐行展开。
"""

import csv
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "output" / "hunan_gkdata.db"
PLAN = ROOT / "output" / "美术志愿方案_综合分305.4.csv"
OUT = ROOT / "output" / "美术志愿方案_组内专业明细.csv"

ORDER = {"冲": 1, "稳": 2, "保": 3}


def main() -> None:
    # 读取冲稳保院校（代号 -> (档位, 投档线, 比值)）
    schools: dict[str, dict] = {}
    with open(PLAN, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["档位"] in ORDER and r["2026有美术计划"] == "是":
                schools.setdefault(r["院校代号"], r)

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    rows = []
    for code, info in schools.items():
        cur.execute(
            "SELECT 院校专业组代码, 专业组名称, 专业代码, 专业名称, 专业备注, "
            "       学制, 学费, 计划人数, 最低分1, 最低位次1, "
            "       所在省, 城市, 城市水平标签, 院校标签, 院校水平, 类型, "
            "       公私性质, 保研率, 院校排名 "
            "FROM 招生计划2026_艺术类 "
            "WHERE 院校代码=? AND 匹配类别='美术与设计类' AND 计划类别='艺术类(平行组)' "
            "ORDER BY 院校专业组代码, 专业代码",
            (code,),
        )
        for (zudm, zuname, zydm, zyname, zybz, xz, xf, jh, zdf1, zdwc1,
             prov, city, citytag, schtag, schlevel, schtype,
             owner, baoyan, rank) in cur.fetchall():
            # 跳过中外合作组（与方案口径一致）
            if "中外合作" in (zuname or "") or "国际" in (zuname or ""):
                continue
            try:
                baoyan_s = f"{float(baoyan)*100:.1f}%" if baoyan not in (None, "") else ""
            except (TypeError, ValueError):
                baoyan_s = str(baoyan or "")
            rows.append({
                "档位": info["档位"],
                "院校代号": code,
                "院校名称": info["院校名称"],
                "所在省": prov,
                "城市": city,
                "城市标签": citytag,
                "院校标签": schtag,
                "院校水平": schlevel,
                "类型": schtype,
                "公私性质": owner,
                "保研率": baoyan_s,
                "院校排名": rank,
                "2025投档线": info["2025投档线"],
                "位次比值": info["位次比值"],
                "院校专业组代码": zudm,
                "专业组名称": zuname,
                "专业代码": zydm,
                "专业名称": zyname,
                "专业备注": re.sub(r"\s+", " ", (zybz or "").strip()),
                "学制": xz,
                "学费": xf,
                "计划人数": jh,
                "25专业最低分": zdf1,
                "25专业最低位次": zdwc1,
            })

    rows.sort(key=lambda r: (ORDER[r["档位"]], -float(r["位次比值"] or 0),
                             r["院校专业组代码"], r["专业代码"]))

    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    for cat in ["冲", "稳", "保"]:
        sub = [r for r in rows if r["档位"] == cat]
        groups = len({(r["院校代号"], r["院校专业组代码"]) for r in sub})
        print(f"\n{'='*70}\n【{cat}】{groups} 个专业组 / {len(sub)} 个专业\n{'='*70}")
        last_grp = None
        for r in sub:
            gkey = (r["院校名称"], r["专业组名称"])
            if gkey != last_grp:
                tags = "/".join(x for x in [r["城市"], r["类型"],
                                            r["公私性质"], r["院校标签"]] if x)
                py = f" 保研{r['保研率']}" if r["保研率"] else ""
                rk = f" 排名{r['院校排名']}" if r["院校排名"] else ""
                print(f"\n◆ {r['院校名称']} {r['专业组名称']} "
                      f"(2025投档线{r['2025投档线']}/比值{r['位次比值']})")
                print(f"   [{tags}{py}{rk}]")
                last_grp = gkey
            bz = f" [{r['专业备注']}]" if r["专业备注"] else ""
            print(f"    {r['专业代码']} {r['专业名称']:<14} "
                  f"计划{r['计划人数']}人 学费{r['学费']} "
                  f"25最低分{r['25专业最低分'] or '-'}{bz}")

    print(f"\n\n明细已导出: {OUT}（共 {len(rows)} 行，每行一个专业）")
    conn.close()


if __name__ == "__main__":
    main()
