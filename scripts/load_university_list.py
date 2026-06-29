"""解析 raw_data/闲鱼数据/全国一本二本大学清单.md，写入 output/hunan_gkdata.db。

生成一张表 ``全国一本二本院校清单``（历史/民间口径，仅供湖南考生参考）：
- 一本部分：按省份拆分，区分「双一流」与「普通一本」。
- 二本部分：区分「公办二本」「民办二本」「合作办学二本」，并提取软科/全国排名。
"""

import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / "raw_data" / "闲鱼数据" / "全国一本二本大学清单.md"
DB = ROOT / "output" / "hunan_gkdata.db"
TABLE = "全国一本二本院校清单"

# 把一行顿号/逗号分隔的院校文本拆成 (院校名称, 排名) 列表
RANK_RE = re.compile(r"^(.*?)\((\d+)\)$")


def split_names(text: str) -> list[str]:
    """按中文顿号/逗号切分，去空白。"""
    parts = re.split(r"[、,，]", text)
    cleaned = [p.replace("*", "").strip() for p in parts]
    return [p for p in cleaned if p]


def parse_name_rank(token: str) -> tuple[str, str]:
    """解析形如 ``首都医科大学(35)`` 的院校，返回 (名称, 排名字符串)。"""
    m = RANK_RE.match(token)
    if m:
        return m.group(1).strip(), m.group(2)
    return token.strip(), ""


COLUMNS = ["院校名称", "分类", "子类", "省份", "排名", "排名口径", "备注"]


def parse(md_text: str) -> list[dict]:
    rows: list[dict] = []
    lines = md_text.splitlines()

    section = None  # "一本" / "二本"
    province = None
    er_sub = None  # 二本子类

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        # 大部分切换
        if line.startswith("# 第一部分"):
            section = "一本"
            continue
        if line.startswith("# 第二部分"):
            section = "二本"
            province = None
            continue

        if section == "一本":
            # 省份标题：## 1. 北京（64所） / ## 18. 湖南（21所）★ 本省
            m = re.match(r"^##\s*\d+\.\s*([^（(]+)", line)
            if m:
                province = m.group(1).strip().rstrip("★ ").strip()
                continue
            if line.startswith("**双一流") and province:
                payload = line.split("：", 1)[1] if "：" in line else line.split(":", 1)[1]
                for name in split_names(payload):
                    nm, _ = parse_name_rank(name)
                    rows.append({
                        "院校名称": nm, "分类": "一本", "子类": "双一流",
                        "省份": province, "排名": "", "排名口径": "", "备注": "",
                    })
                continue
            if line.startswith("**普通一本") and province:
                payload = line.split("：", 1)[1]
                for name in split_names(payload):
                    nm, _ = parse_name_rank(name)
                    rows.append({
                        "院校名称": nm, "分类": "一本", "子类": "普通一本",
                        "省份": province, "排名": "", "排名口径": "", "备注": "",
                    })
                continue

        elif section == "二本":
            if line.startswith("## 一、公办二本"):
                er_sub = "公办二本"
                continue
            if line.startswith("## 二、民办二本"):
                er_sub = "民办二本"
                continue
            if line.startswith("## 三、合作办学二本"):
                er_sub = "合作办学二本"
                continue
            if line.startswith("##") or line.startswith("#") or line.startswith(">") \
                    or line.startswith("---") or line.startswith("- "):
                continue

            if er_sub == "公办二本":
                # 主排名段（含软科排名）或 职业本科/艺术类（无排名）
                if line.startswith("**职业本科/艺术类"):
                    payload = line.split("：", 1)[1]
                    for name in split_names(payload):
                        nm, _ = parse_name_rank(name)
                        rows.append({
                            "院校名称": nm, "分类": "二本", "子类": "公办二本",
                            "省份": "", "排名": "", "排名口径": "",
                            "备注": "职业本科/艺术类(无软科综合排名)",
                        })
                else:
                    for token in split_names(line):
                        nm, rk = parse_name_rank(token)
                        rows.append({
                            "院校名称": nm, "分类": "二本", "子类": "公办二本",
                            "省份": "", "排名": rk, "排名口径": "软科排名" if rk else "",
                            "备注": "",
                        })

            elif er_sub == "民办二本":
                if line.startswith("**民办（全国排名100+）"):
                    payload = line.split("：", 1)[1]
                    for name in split_names(payload):
                        nm, _ = parse_name_rank(name)
                        rows.append({
                            "院校名称": nm, "分类": "二本", "子类": "民办二本",
                            "省份": "", "排名": "", "排名口径": "",
                            "备注": "全国排名100+",
                        })
                else:
                    for token in split_names(line):
                        nm, rk = parse_name_rank(token)
                        rows.append({
                            "院校名称": nm, "分类": "二本", "子类": "民办二本",
                            "省份": "", "排名": rk, "排名口径": "民办全国排名" if rk else "",
                            "备注": "",
                        })

            elif er_sub == "合作办学二本":
                for token in split_names(line):
                    nm, _ = parse_name_rank(token)
                    rows.append({
                        "院校名称": nm, "分类": "二本", "子类": "合作办学二本",
                        "省份": "", "排名": "", "排名口径": "", "备注": "",
                    })

    return rows


def create_indexes(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    indexes = [
        ("idx_unilist_院校名称", "院校名称"),
        ("idx_unilist_分类", "分类"),
        ("idx_unilist_子类", "子类"),
        ("idx_unilist_省份", "省份"),
    ]
    for name, col in indexes:
        cur.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{TABLE}" ("{col}")')
    conn.commit()


def verify(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(f'SELECT COUNT(*) FROM "{TABLE}"')
    print(f"=== {TABLE} 总行数: {cur.fetchone()[0]} ===")
    cur.execute(f'SELECT 分类, 子类, COUNT(*) FROM "{TABLE}" GROUP BY 分类, 子类 ORDER BY 分类, 子类')
    print("\n=== 分类/子类分布 ===")
    for r in cur.fetchall():
        print(f"  {r[0]} / {r[1]}: {r[2]}")
    cur.execute(f'SELECT COUNT(DISTINCT 省份) FROM "{TABLE}" WHERE 分类="一本"')
    print(f"\n一本覆盖省份数: {cur.fetchone()[0]}")


def write_table(conn: sqlite3.Connection, rows: list[dict]) -> None:
    cur = conn.cursor()
    cur.execute(f'DROP TABLE IF EXISTS "{TABLE}"')
    cols_sql = ", ".join(f'"{c}"' for c in (["ID"] + COLUMNS))
    cur.execute(f'CREATE TABLE "{TABLE}" ({cols_sql})')
    placeholders = ", ".join(["?"] * (len(COLUMNS) + 1))
    cur.executemany(
        f'INSERT INTO "{TABLE}" ({cols_sql}) VALUES ({placeholders})',
        [tuple([i] + [r[c] for c in COLUMNS]) for i, r in enumerate(rows, start=1)],
    )
    conn.commit()


def main() -> None:
    rows = parse(MD.read_text(encoding="utf-8"))
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    try:
        write_table(conn, rows)
        create_indexes(conn)
        verify(conn)
    finally:
        conn.close()
    print(f"\n已写入: {DB}")


if __name__ == "__main__":
    main()
