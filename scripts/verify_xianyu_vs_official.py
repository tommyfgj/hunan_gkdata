#!/usr/bin/env python3
"""
闲鱼数据 vs 湖南考试院官方数据核对脚本。

重要：院校专业组编号每年可能变化（如中南大学历史类 2024=105组、2025=115组、2026计划=105组）。
因此 2026 主文件中的「专业组最低分1」(2025年) 与官方 2025 投档线对比时，
不能按组号硬对齐，应按「院校 + 科类 + 分数」匹配。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OFF_DIR = ROOT / "raw_data/湖南考试院网站官方数据"
XY_DIR = ROOT / "raw_data/闲鱼数据"

COLUMNS_TOUDANG = [
    "批次", "计划类别", "科类", "院校代号", "院校名称", "专业组编号", "专业组名称",
    "投档线", "语数之和", "语数最高", "外语", "首选科目", "再选最高", "再选次高", "志愿序号", "备注",
]


def norm_group_code(x) -> str:
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if re.fullmatch(r"\d+(\.0)?", s):
        return str(int(float(s)))
    return s


def map_kl(k: str) -> str:
    return {"物理": "普通类(首选物理)", "历史": "普通类(首选历史)"}.get(str(k).strip(), str(k).strip())


def load_toudang(year: int) -> pd.DataFrame:
    path = OFF_DIR / f"{year}年本科批普通类投档线.xlsx"
    sheet = "投档线" if year == 2025 else 0
    df = pd.read_excel(path, header=2, sheet_name=sheet)
    df.columns = COLUMNS_TOUDANG
    df = df[df["院校代号"].notna() & (df["院校代号"] != "院校代号")].copy()
    df["院校代号"] = df["院校代号"].astype(str).str.replace(r"\.0$", "", regex=True)
    df["专业组编号"] = df["专业组编号"].apply(norm_group_code)
    df["投档线"] = pd.to_numeric(df["投档线"], errors="coerce")
    return df


def load_yifenduan(path: Path, rank_type: str = "default") -> dict[int, int]:
    """rank_type: default=2025表; local=2024含地方性加分列"""
    df = pd.read_csv(path)
    score_col = next(c for c in df.columns if "档分" in c or c == "分数")
    if rank_type == "local":
        rank_col = next(c for c in df.columns if "地方性" in c and "累计" in c)
    else:
        rank_col = next(c for c in df.columns if "累计" in c)
    out: dict[int, int] = {}
    for _, row in df.iterrows():
        if pd.to_numeric(row[score_col], errors="coerce") != pd.to_numeric(row[score_col], errors="coerce"):
            continue
        if pd.to_numeric(row[rank_col], errors="coerce") != pd.to_numeric(row[rank_col], errors="coerce"):
            continue
        out[int(row[score_col])] = int(row[rank_col])
    return out


def load_df26() -> pd.DataFrame:
    return pd.read_excel(XY_DIR / "湖南-2026招生计划版（不含艺术类）.xlsx", header=1)


def prepare_xy_groups(df26: pd.DataFrame, batch: str = "本科批(普通)") -> pd.DataFrame:
    xy = df26[df26["批次"] == batch].copy()
    xy["院校代码_s"] = xy["院校代码"].astype(str).str.replace(r"\.0$", "", regex=True)
    xy["专业组代码_s"] = xy["专业组代码"].apply(norm_group_code)
    xy["科类_m"] = xy["科类"].map(map_kl)
    grp = xy.groupby(
        ["院校代码_s", "院校名称", "专业组代码_s", "专业组名称", "科类", "科类_m"],
        as_index=False,
    ).agg(
        专业组最低分1=("专业组最低分1", "first"),
        专业组最低位次1=("专业组最低位次1", "first"),
        专业数=("专业代码", "count"),
    )
    grp["专业组最低分1"] = pd.to_numeric(grp["专业组最低分1"], errors="coerce")
    grp["专业组最低位次1"] = pd.to_numeric(grp["专业组最低位次1"], errors="coerce")
    return grp[grp["专业组最低分1"].notna()]


def build_off_lookup(off: pd.DataFrame) -> tuple[dict, dict]:
    """返回 (院校+科类 -> 分数集合), (院校+科类+分数 -> 官方组号列表)"""
    score_sets: dict[tuple[str, str], set[float]] = {}
    score_to_groups: dict[tuple[str, str, float], list[str]] = {}
    for _, row in off.iterrows():
        key = (row["院校代号"], row["科类"])
        score = float(row["投档线"])
        score_sets.setdefault(key, set()).add(score)
        score_to_groups.setdefault((*key, score), []).append(row["专业组编号"])
    return score_sets, score_to_groups


def verify_group_scores_by_number(grp: pd.DataFrame, off: pd.DataFrame, year: int) -> pd.DataFrame:
    """旧逻辑：按院校+组号+科类硬对齐（会低估匹配率）"""
    off = off.copy()
    m = grp.merge(
        off[["院校代号", "专业组编号", "科类", "投档线", "院校名称"]],
        left_on=["院校代码_s", "专业组代码_s", "科类_m"],
        right_on=["院校代号", "专业组编号", "科类"],
        how="inner",
        suffixes=("_xy", "_off"),
    )
    m["分差"] = m["专业组最低分1"] - m["投档线"]
    m["官方年份"] = year
    m["匹配方式"] = "组号硬对齐"
    return m


def verify_group_scores_by_score(grp: pd.DataFrame, off: pd.DataFrame, year: int) -> pd.DataFrame:
    """新逻辑：组号可变，按院校+科类+分数匹配官方投档线"""
    score_sets, score_to_groups = build_off_lookup(off)
    rows = []
    for _, row in grp.iterrows():
        key = (row["院校代码_s"], row["科类_m"])
        score = float(row["专业组最低分1"])
        official_groups = score_to_groups.get((*key, score), [])
        in_official = score in score_sets.get(key, set())
        rows.append({
            **row.to_dict(),
            "官方年份": year,
            "匹配方式": "同校同分",
            "分数命中官方": in_official,
            "官方对应组号": ",".join(official_groups) if official_groups else "",
            "组号与官方一致": row["专业组代码_s"] in official_groups if official_groups else False,
        })
    return pd.DataFrame(rows)


def verify_ranks(df26: pd.DataFrame, seg: dict[int, int], score_col: str, rank_col: str, kl: str) -> tuple[int, int]:
    sub = df26[df26["科类"] == kl].copy()
    sub[score_col] = pd.to_numeric(sub[score_col], errors="coerce")
    sub[rank_col] = pd.to_numeric(sub[rank_col], errors="coerce")
    pairs = sub[(sub[score_col].notna()) & (sub[rank_col].notna())][[score_col, rank_col]].drop_duplicates()
    ok = sum(
        1 for _, r in pairs.iterrows()
        if seg.get(int(r[score_col])) == int(r[rank_col])
    )
    return len(pairs), ok


def print_summary(df26: pd.DataFrame) -> None:
    grp = prepare_xy_groups(df26)
    off25 = load_toudang(2025)
    off24 = load_toudang(2024)

    hard = verify_group_scores_by_number(grp, off25, 2025)
    soft = verify_group_scores_by_score(grp, off25, 2025)

    print("=" * 70)
    print("2026主文件 · 2025组最低分 vs 官方2025本科投档线")
    print("=" * 70)
    print(f"有2025组分的专业组: {len(grp)}")
    print()
    print("[旧] 院校+组号+科类 硬对齐:")
    print(f"  可比对: {len(hard)}  完全一致: {(hard['分差'] == 0).sum()} ({(hard['分差'] == 0).mean() * 100:.1f}%)")
    print()
    print("[新] 院校+科类+分数 匹配（组号每年可能变化）:")
    print(f"  分数命中官方: {soft['分数命中官方'].sum()} ({soft['分数命中官方'].mean() * 100:.1f}%)")
    print(f"  其中组号也与官方相同: {soft['组号与官方一致'].sum()} ({soft['组号与官方一致'].mean() * 100:.1f}%)")
    print(f"  分数命中但组号不同: {(soft['分数命中官方'] & ~soft['组号与官方一致']).sum()}")

    # 2024 专业最低分 vs 官方2024
    xy = df26[(df26["批次"] == "本科批(普通)") & df26["最低分2"].notna()].copy()
    xy["院校代码_s"] = xy["院校代码"].astype(str).str.replace(r"\.0$", "", regex=True)
    xy["科类_m"] = xy["科类"].map(map_kl)
    xy["最低分2"] = pd.to_numeric(xy["最低分2"], errors="coerce")
    score_sets24, _ = build_off_lookup(off24)
    xy["2024分命中官方"] = xy.apply(
        lambda r: float(r["最低分2"]) in score_sets24.get((r["院校代码_s"], r["科类_m"]), set()),
        axis=1,
    )
    print()
    print("2026主文件 · 2024专业最低分 vs 官方2024（分数集合匹配）:")
    print(f"  可比对专业: {len(xy)}  分数命中: {xy['2024分命中官方'].sum()} ({xy['2024分命中官方'].mean() * 100:.1f}%)")

    print()
    print("=" * 70)
    print("位次 vs 官方一分段")
    print("=" * 70)
    seg25p = load_yifenduan(OFF_DIR / "2025年一分段统计表_物理类.csv")
    seg25h = load_yifenduan(OFF_DIR / "2025年一分段统计表_历史类.csv")
    seg24p = load_yifenduan(OFF_DIR / "2024年一分段统计表_物理类.csv", rank_type="local")
    seg24h = load_yifenduan(OFF_DIR / "2024年一分段统计表_历史类.csv", rank_type="local")

    for label, sc, rk, kl, seg in [
        ("2025组位次", "专业组最低分1", "专业组最低位次1", "物理", seg25p),
        ("2025组位次", "专业组最低分1", "专业组最低位次1", "历史", seg25h),
        ("2025专业位次", "最低分1", "最低位次1", "物理", seg25p),
        ("2025专业位次", "最低分1", "最低位次1", "历史", seg25h),
        ("2024专业位次", "最低分2", "最低位次2", "物理", seg24p),
        ("2024专业位次", "最低分2", "最低位次2", "历史", seg24h),
    ]:
        n, ok = verify_ranks(df26, seg, sc, rk, kl)
        if n:
            print(f"  {label} {kl}: {ok}/{n} ({ok / n * 100:.1f}%)")

    # 中南大学示例
    print()
    print("=" * 70)
    print("示例：中南大学 历史类（组号按年变化）")
    print("=" * 70)
    csu = soft[
        soft["院校名称"].str.contains("中南大学", na=False) & (soft["科类"] == "历史")
    ].sort_values("专业组代码_s")
    for _, r in csu.iterrows():
        flag = "组号同" if r["组号与官方一致"] else "组号异"
        off_grp = r["官方对应组号"] or "无"
        print(
            f"  闲鱼{r['专业组代码_s']}组 分{int(r['专业组最低分1'])} "
            f"→ 官方2025第{off_grp}组  [{flag}]"
        )


def export_mapping(df26: pd.DataFrame, out_path: Path) -> None:
    """导出闲鱼2026组号与官方2025组号的分数映射表"""
    grp = prepare_xy_groups(df26)
    soft = verify_group_scores_by_score(grp, load_toudang(2025), 2025)
    cols = [
        "院校代码_s", "院校名称", "科类", "科类_m",
        "专业组代码_s", "专业组名称", "专业组最低分1", "专业组最低位次1",
        "官方对应组号", "组号与官方一致", "分数命中官方", "专业数",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    soft[cols].sort_values(["院校名称", "科类", "专业组代码_s"]).to_csv(out_path, index=False)
    print(f"\n已导出映射表: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="闲鱼数据 vs 考试院官方数据核对")
    parser.add_argument(
        "--export-mapping",
        type=Path,
        default=None,
        help="导出闲鱼组号→官方2025组号映射 CSV",
    )
    args = parser.parse_args()

    df26 = load_df26()
    print_summary(df26)

    if args.export_mapping:
        export_mapping(df26, args.export_mapping)


if __name__ == "__main__":
    main()
