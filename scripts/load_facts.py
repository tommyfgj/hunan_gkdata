"""将 事实数据/ 下 CSV 整合并写入 output/hunan_gkdata.db。"""

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FACTS_DIR = ROOT / "事实数据"
DB = ROOT / "output" / "hunan_gkdata.db"


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8")
    return df.dropna(how="all")


def load_control_lines(conn: sqlite3.Connection) -> None:
    art = read_csv(FACTS_DIR / "录取控制分数线_艺术类_2024-2026.csv")
    art.to_sql("录取控制分数线_艺术类", conn, if_exists="replace", index=False)

    general = read_csv(FACTS_DIR / "录取控制分数线_普通类体育类_2024-2026.csv")
    general.to_sql("录取控制分数线_普通类体育类", conn, if_exists="replace", index=False)


def load_physics_yifenduan(conn: sqlite3.Connection) -> None:
    frames: list[pd.DataFrame] = []

    df_2024 = read_csv(FACTS_DIR / "2024年一分段统计表_物理类.csv")
    frames.append(
        pd.DataFrame(
            {
                "年份": 2024,
                "档分": df_2024["档分"],
                "本段人数": df_2024["本段人数(含全国性和地方性加分)"],
                "累计人数": df_2024["累计人数(含全国性和地方性加分)"],
            }
        )
    )

    for year in (2025, 2026):
        df = read_csv(FACTS_DIR / f"{year}年一分段统计表_物理类.csv")
        frames.append(
            pd.DataFrame(
                {
                    "年份": year,
                    "档分": df["档分"],
                    "本段人数": df["本段人数"],
                    "累计人数": df["累计人数(含优惠加分)"],
                }
            )
        )

    merged = pd.concat(frames, ignore_index=True)
    merged.to_sql("一分段_物理类", conn, if_exists="replace", index=False)


def load_art_yifenduan(conn: sqlite3.Connection) -> None:
    frames: list[pd.DataFrame] = []

    for year in (2024, 2025, 2026):
        df = read_csv(FACTS_DIR / f"{year}年艺术类统考成绩一分段_美术与设计类.csv")
        frames.append(
            pd.DataFrame(
                {
                    "年份": year,
                    "成绩": df["成绩"],
                    "本段人数": df["本段人数"],
                    "累计人数": df["累计人数"],
                }
            )
        )

    merged = pd.concat(frames, ignore_index=True)
    merged.to_sql("一分段_美术与设计类", conn, if_exists="replace", index=False)


def load_art_composite_yifenduan(conn: sqlite3.Connection) -> None:
    """美术与设计类本科线上综合成绩一分段（2025、2026，按年份顺序合并）。

    与 ``一分段_美术与设计类``（专业统考成绩，整数满分 300）不同，
    本表为综合成绩（文化×30% + 统考×70%，含优惠加分，小数）。
    """
    frames: list[pd.DataFrame] = []
    for year in (2025, 2026):
        df = read_csv(FACTS_DIR / f"{year}年美术与设计类本科线上综合成绩一分段.csv")
        frames.append(
            pd.DataFrame(
                {
                    "年份": year,
                    "综合成绩": df["综合成绩"],
                    "本段人数": df["本段人数"],
                    "累计人数": df["累计人数"],
                }
            )
        )

    merged = pd.concat(frames, ignore_index=True)
    merged.to_sql("一分段_美术与设计类综合成绩", conn, if_exists="replace", index=False)
    # 同时导出合并后的单文件（按年份顺序）
    merged.to_csv(
        FACTS_DIR / "美术与设计类本科线上综合成绩一分段_2025-2026.csv",
        index=False,
        encoding="utf-8-sig",
    )


def create_indexes(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    indexes = [
        ('idx_ctrl_art_年份', "录取控制分数线_艺术类", "年份"),
        ('idx_ctrl_art_类别', "录取控制分数线_艺术类", "类别"),
        ('idx_ctrl_gen_年份', "录取控制分数线_普通类体育类", "年份"),
        ('idx_ctrl_gen_批次', "录取控制分数线_普通类体育类", "批次"),
        ('idx_yfd_phy_年份', "一分段_物理类", "年份"),
        ('idx_yfd_phy_年份档分', "一分段_物理类", "年份, 档分"),
        ('idx_yfd_art_年份', "一分段_美术与设计类", "年份"),
        ('idx_yfd_art_年份成绩', "一分段_美术与设计类", "年份, 成绩"),
        ('idx_yfd_art_comp_年份', "一分段_美术与设计类综合成绩", "年份"),
        ('idx_yfd_art_comp_年份成绩', "一分段_美术与设计类综合成绩", "年份, 综合成绩"),
    ]
    for name, table, cols in indexes:
        cur.execute(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({cols})')
    conn.commit()


def verify(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    tables = [
        "录取控制分数线_艺术类",
        "录取控制分数线_普通类体育类",
        "一分段_物理类",
        "一分段_美术与设计类",
        "一分段_美术与设计类综合成绩",
    ]
    print("=== 表行数 ===")
    for table in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        count = cur.fetchone()[0]
        print(f"  {table}: {count}")

    print("\n=== 年份分布 ===")
    for table in ("一分段_物理类", "一分段_美术与设计类", "一分段_美术与设计类综合成绩"):
        cur.execute(f'SELECT 年份, COUNT(*) FROM "{table}" GROUP BY 年份 ORDER BY 年份')
        rows = cur.fetchall()
        print(f"  {table}: {dict(rows)}")

    for table, col in (
        ("录取控制分数线_艺术类", "年份"),
        ("录取控制分数线_普通类体育类", "年份"),
    ):
        cur.execute(f'SELECT {col}, COUNT(*) FROM "{table}" GROUP BY {col} ORDER BY {col}')
        rows = cur.fetchall()
        print(f"  {table}: {dict(rows)}")


def main() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    try:
        load_control_lines(conn)
        load_physics_yifenduan(conn)
        load_art_yifenduan(conn)
        load_art_composite_yifenduan(conn)
        create_indexes(conn)
        verify(conn)
    finally:
        conn.close()
    print(f"\n已写入: {DB}")


if __name__ == "__main__":
    main()
