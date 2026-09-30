# Human Evaluation of BadmintonGPT

## 0. Process
1. generate the query and answer
2. generate the website to do human evaluation

## 1. generate the query and answer

Generate the 200 user query and answer by using the following pipeline:
1. input all SKILL.md to the LLM.
2. Retain the complete MCP pool and the native web_search definition separately. The primary pool has 12 capabilities: 8 analysis functions, video retrieval, reels, database-only analysis via badminton-db.query, and web research via web_search. Seeded shuffled cycles select each primary once per 12 questions (1/12 each). Draw K = Poisson(1)+1, capped by compatible capabilities: database and web primaries stand alone; other primaries can use optional supporting capabilities, including web search but excluding the dedicated database-only category. Persist raw count, eligible count, source and selected capabilities. Schema inspection, polling, waiting and health tools remain supporting steps rather than user goals.
3. For existing capabilities, cycle through six query scopes: player/year performance, player shot profile, tactical clips, cross-tournament differences, player comparison, and a single match. Give the LLM the required scope, real focus players/year, selected capabilities and recent intentions/scopes as an exclusion history. Independently select a compatible presentation requirement: text, comparison chart or interactive visualization for analysis, with court diagrams additionally eligible for lost-point zones and backcourt positioning; video for retrieval/reel primaries. Use a separate seeded uniform draw among eligible analysis formats; a short batch need not cover every format. Pass the selected presentation to both intention and bilingual-query prompts, integrating the format into the same purpose without specifying UI controls. Persist the presentation policy and per-item selection; keep visualise as a skill rather than an MCP function. Generate one short intention with a single core purpose. Secondary functions may support that purpose but cannot add tasks or metrics; do not turn every question into a match/rally lookup.
4. For local analysis questions, provide all three background categories (`match`, `rally`, `shots`) plus a catalogue of related real matches, focus players/year, available shot types and coverage limits. Keep the representative linked example (up to 12 shots); broader scopes require actual multi-match support, and cross-tournament scopes require multiple tournaments. Exclude practice, missing-player and empty-shot records. Use a concise second prompt to rewrite and translate that intention into a brief, self-contained English/zh-TW request. Add no new tasks, metrics, explanations, controls or caveats. Only the intention stage receives recent-topic history. Background is not a checklist; do not copy data-use instructions into the question. Do not fabricate annual statistics from one example, assume exhaustive coverage or refer to input absent from the query. Validate English focus names, focus year in both languages and missing-input phrasing before submission; preserve rejected question drafts and feedback, allowing up to 3 draft attempts per execution. Do not force an answer language.
For database-only questions, also provide actual table columns to both generation stages and choose only outcomes computable from those rows; do not require analysis IDs, video or external metrics. Replace tactical-clips scope with player-shot analysis. For web-primary questions, use a public_web scope with a reference date and one of news, rankings, schedules or rules; do not require any local database context, player or match. Preserve source requirements in both stages without adding tool restrictions to the query.
5. Send the unchanged English query to the existing BadmintonGPT interface with its native WebUI locale=en field, as requested for English replies, and preserve the original output. The user authorizes an English-only language rule in the gateway’s native SOUL system instruction, including chart labels and generated video narration/subtitles (`generate_reel(language="en")`); never add this rule to the user query. Other answering behavior, tool availability and anchor behavior remain unchanged. Preserve the original answer regardless of language; do not translate, rewrite or retry it because of its language. Use a new dataset ID when changing intention, data, presentation sampling rules or prompt policy / answer locale / answer system-instruction policy so existing questions, answers and ratings remain separate.

The user query should have higher diversity.

## 2. generate the website to do human evaluation

Generate the website fulfill the following requirements:
1. use cloudflare to expose the website protect it.
2. for each user query, show the following:
- user query(English)
- user query(zh-TW)
- question 1: Is this a realistic question that a user might ask BadmintonGPT?
| 選項                           | 判斷標準                      |
| ---------------------------- | ------------------------- |
| **合理（Realistic）**            | 有自然、可信的提問動機，真實使用者可能會這樣問。  |
| **有些牽強（Somewhat realistic）** | 可以想像有人會問，但情境或需求刻意、不太自然。   |
| **不合理（Unrealistic）**         | 缺乏可信的使用情境，像是為了生成問題而硬湊出來的。 |

if question 1 select Realistic or Somewhat realistic, show the BadmintonGPT’s answer and question 2:
- BadmintonGPT’s answer
- question 2: Does BadmintonGPT’s answer address the user’s question and intent? 
| 選項                            | 判斷標準                       |
| ----------------------------- | -------------------------- |
| **完全符合（Fully addresses）**     | 回答直接切題，涵蓋使用者的主要需求與明確限制。    |
| **部分符合（Partially addresses）** | 回答與問題相關，但遺漏部分需求，或部分內容偏離問題。 |
| **不符合（Does not address）**     | 誤解使用者意圖、答非所問，或沒有回應核心問題。    |

3. Should support the save(to our server), and the progress bar.
4. because the answer will have many format, so reuse the component in the BadmintonGPT to show the response.

## Notice
1. Write all the code and result in `human-evaluation/`.
2. generate 10 user query and build the website to let me check first.
