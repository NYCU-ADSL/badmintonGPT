"""Build a demo SQLite from locally-available HF data and compute test-bank ground truth.

Only one match is downloaded locally (Axelsen vs Lee Zii Jia); matches-table answers
use the full 32-folder listing. Stdlib only (sqlite3 + csv).
"""
import csv
import sqlite3
from pathlib import Path

DATA = Path("/mnt/ssd1/howchien/badminton-reels/data/Data")
MATCH = "Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals.mp4"

# Full 32-folder listing from HF (api.list_repo_files).
ALL_FOLDERS = [
    "AN_Se_Young_Gregoria_Mariska_TUNJUNG_Malaysia_Masters_2022_SemiFinals.mp4",
    "AN_Se_Young_TAI_Tzu_Japan_Open_2022_Semi_finals.mp4",
    "Akane_YAMAGUCHI_AN_Se_Young_BWF_World_Championships_2022_Semi_finals.mp4",
    "Akane_YAMAGUCHI_AN_Se_Young_DAIHATSU_YONEX_Japan_Open_2022_Finals.mp4",
    "Akane_YAMAGUCHI_AN_Seyoung_YONEX_All_England_Open_Badminton_Championships_2022_Finals.mp4",
    "CHEN_Yu_Fei_Ratchanok_INTANON_Denmark_Open_2022_SemiFinals.mp4",
    "CHEN_Yu_Fei_TAI_Tzu_Ying_BWF_World_Championships_2022_Semi_finals.mp4",
    "CHEN_Yu_Fei_TAI_Tzu_Ying_Malaysia_Masters_2022 _Semi_finals.mp4",
    "Carolina_MARIN_Akane_YAMAGUCHI_French_Open_2022_SemiFinals.mp4",
    "Chen_Yu_Fei_Tai_Tzu_Ying_Malaysia_Open_2022_Semi_finals.mp4",
    "HE_Bing_Jiao_CHEN_Yu_Fei_Denmark_Open_2022_Final.mp4",
    "HE_Bing_Jiao_Carolina_MARIN_French_Open_2022_Final.mp4",
    "He_Bing_Jiao_Han_Yue_Denmark_Open_2022_Semifinals.mp4",
    "Kenta_NISHIMOTO_Anders_ANTONSEN_Japan_Open_2022_SemiFinals.mp4",
    "Kento_MOMOTA_Kunlavut_VITIDSARN_Malaysia_Open_2022_ Semi_finals.mp4",
    "Lee_Zii_Jia_Loh_Kean_Yew_Denmark_Open_2022_Semifinals.mp4",
    "NYCU_Other_practice1.mp4", "NYCU_Other_practice2.mp4", "NYCU_Other_practice3.mp4",
    "NYCU_Other_practice4.mp4", "NYCU_Other_practice5.mp4",
    "Ratchanok_INTANON_CHEN_Yu_Fei_PETRONAS_Malaysia_Open_2022_Finals.mp4",
    "SHI_Yu_Qi_Kodai_NARAOKA_Denmark_Open_2022_SemiFinals.mp4",
    "SHI_Yu_Qi_LEE_Zii_Jia_Denmark_Open_2022_Final.mp4",
    "TAI_Tzu_Ying_WANG_Zhi_Yi_Indonesia_Open_2022_Final.mp4",
    "Viktor_AXELSEN_Anthony_Sinisuka_GINTING_BWF_World_Tour_Finals_2022_Finals.mp4",
    "Viktor_AXELSEN_Anthony_Sinisuka_GINTING_DAIHATSU_INDONESIA_MASTERS_2022_Semifinals.mp4",
    "Viktor_AXELSEN_CHOU_Tien_Chen_Indonesia_Masters_2022_Finals.mp4",
    "Viktor_AXELSEN_Kento_MOMOTA_PETRONAS_Malaysia_Open_2022_Finals.mp4",
    "Viktor_AXELSEN_Kodai_NARAOKA_HSBC_BWF_World_Tour_Finals_2022_Semifinals.mp4",
    "Viktor_AXELSEN_LEE_Zii_Jia_EAST_VENTURES_Indonesia_Open_2022_Semifinals.mp4",
    "Wang_Zhi_Yi_He_Bing_Jiao_Indonesia_Open_2022_Semi_finals.mp4",
]

db = sqlite3.connect(":memory:")
db.row_factory = sqlite3.Row
cur = db.cursor()

# --- matches (all 32 folders) ---
cur.execute("CREATE TABLE matches (folder TEXT, name TEXT, is_practice INT)")
for f in ALL_FOLDERS:
    name = f[:-4] if f.endswith(".mp4") else f
    cur.execute("INSERT INTO matches VALUES (?,?,?)",
                (f, name, int(name.startswith("NYCU_Other_practice"))))

# --- shots (only the one locally-available match) ---
label_dir = DATA / MATCH / "label"
cols = None
rows = []
for setfile in sorted(label_dir.glob("set*.csv")):
    setno = int(setfile.stem.replace("set", ""))
    with open(setfile, encoding="utf-8") as fh:
        r = csv.reader(fh)
        header = next(r)
        cols = header
        for row in r:
            if len(row) < len(header):
                continue
            rows.append([setno] + row)

colnames = ["set_no"] + cols
cur.execute("CREATE TABLE shots (" + ",".join(f'"{c}" TEXT' for c in colnames) + ")")
ph = ",".join("?" * len(colnames))
cur.executemany(f"INSERT INTO shots VALUES ({ph})", rows)
db.commit()

PLAYER = {"A": "Viktor AXELSEN", "B": "LEE Zii Jia"}


def show(title, sql, params=()):
    print(f"\n### {title}")
    print(f"SQL: {sql.strip()}")
    for row in cur.execute(sql, params).fetchall():
        print("   ", dict(row))


print("=" * 70)
print("Ground truth — Axelsen vs Lee (local) + 32-folder metadata")
print("=" * 70)

# Q1
show("Q1 Axelsen's matches",
     "SELECT name FROM matches WHERE name LIKE '%AXELSEN%' OR name LIKE '%Axelsen%'")

# Q2 Axelsen(A) smash points — smash by A that won the rally
show("Q2 Axelsen(A) smash points (the smash itself is the winner: nonempty win_reason)",
     "SELECT COUNT(*) AS axelsen_smash_winners FROM shots "
     "WHERE type='殺球' AND player='A' AND win_reason<>''")
show("Q2b All smashes by A (including non-winners)",
     "SELECT COUNT(*) AS total_A_smash FROM shots WHERE type='殺球' AND player='A'")

# Q3 Most common reason for losing points
show("Q3 Distribution of reasons for losing points",
     "SELECT lose_reason, COUNT(*) AS n FROM shots WHERE lose_reason<>'' "
     "GROUP BY lose_reason ORDER BY n DESC")

# Q4 Lift counts by player
show("Q4 Lift counts (by player)",
     "SELECT player, COUNT(*) AS n FROM shots WHERE type='挑球' GROUP BY player")
print("    (A=Viktor AXELSEN, B=LEE Zii Jia)")

# Q5 Scores for three games — max roundscore per set
show("Q5 Scores for three games",
     "SELECT set_no, MAX(CAST(roundscore_A AS INT)) AS final_A, "
     "MAX(CAST(roundscore_B AS INT)) AS final_B FROM shots GROUP BY set_no ORDER BY set_no")

# Q6 Lee(B) net-shot rallies (rally numbers) + video availability
rv = DATA / MATCH / "rally_video"
have = {p.stem for p in rv.glob("*.mp4")} if rv.exists() else set()
print("\n### Q6 Number of rallies featuring Lee(B) net shots")
res = cur.execute(
    "SELECT set_no, COUNT(*) AS n FROM shots WHERE type='放小球' AND player='B' "
    "GROUP BY set_no ORDER BY set_no").fetchall()
for row in res:
    print("   ", dict(row))
total_b_net = cur.execute(
    "SELECT COUNT(*) FROM shots WHERE type='放小球' AND player='B'").fetchone()[0]
print(f"    Total B net shots = {total_b_net}")
print(f"    Locally available rally_video files ({len(have)}): {sorted(have)}")

# Q9 Years / practice clip counts
show("Q9 Official match vs practice clip counts",
     "SELECT is_practice, COUNT(*) AS n FROM matches GROUP BY is_practice")
print("    (All folder names contain 2022 → all are from 2022)")

print("\nTotal shots rows =", cur.execute("SELECT COUNT(*) FROM shots").fetchone()[0])
db.close()
