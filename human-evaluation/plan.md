# Human Evaluation of BadmintonGPT

## 0. Process
1. generate the query and answer
2. generate the website to do human evaluation

## 1. generate the query and answer

Generate the 300 user query and answer by using the following pipeline:
1. input all SKILL.md to the LLM.
2. Discover and retain the full enabled MCP function pool. For intention generation, draw the function count as `K = Poisson(lambda=1) + 1` (mean 2), capped only by the available intention pool size (currently 10), not at 5. The pool contains the 8 badminton analysis functions, `start_video_retrieval`, and `generate_reel`. Choose one primary function using seeded shuffled cycles that cover all 10 functions before reuse; randomly choose the remaining `K - 1` distinct functions. Persist the raw count, selected functions and primary function. Supply names and definitions to the LLM. Database functions, status/result polling, sleep, service health and collection discovery are supporting tools and are excluded from intention sampling.
3. Cycle through six query scopes: player/year performance, player shot profile, tactical clips, cross-tournament differences, player comparison, and a single match. Give the LLM the required scope, real focus players/year, selected capabilities and recent intentions/scopes as an exclusion history. Independently select a compatible presentation requirement: text, comparison chart or interactive visualization for analysis, with court diagrams additionally eligible for lost-point zones and backcourt positioning; video for retrieval/reel primaries. Use a separate seeded uniform draw among eligible analysis formats; a short batch need not cover every format. Pass the selected presentation to both intention and bilingual-query prompts, with comparisons and controls adapted to the query scope. Persist the presentation policy and per-item selection; keep visualise as a skill rather than an MCP function. Generate one coherent user goal. Secondary functions are optional evidence; do not turn every question into a match/rally lookup.
4. Always provide all three background categories (`match`, `rally`, `shots`) plus a catalogue of related real matches, focus players/year, available shot types and coverage limits. Keep the representative linked example (up to 12 shots); broader scopes require actual multi-match support, and cross-tournament scopes require multiple tournaments. Exclude practice, missing-player and empty-shot records. Use another LLM to create a self-contained English/zh-TW query matching the scope; background is not a required checklist. Do not fabricate annual statistics from one example, assume exhaustive coverage or refer to input absent from the query. Validate English focus names, focus year in both languages and missing-input phrasing before submission; preserve rejected question drafts and feedback, allowing up to 3 draft attempts per execution. Do not force an answer language.
5. Send only the English query to the existing BadmintonGPT interface and preserve its original output. Do not modify its answering process, tool availability or anchor behavior. Preserve the original answer regardless of language; do not translate, rewrite or retry it because of its language. Use a new dataset ID when changing intention, data or presentation sampling rules so existing questions, answers and ratings remain separate.

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
