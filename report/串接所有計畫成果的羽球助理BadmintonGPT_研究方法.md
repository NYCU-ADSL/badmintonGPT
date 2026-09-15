# BadmintonGPT: A badminton assistant integrating all project outcomes

### **II. Research methods**

The core goal of this subproject is to connect the outcomes of all subprojects in the integrated project—shot-by-shot annotations, match highlights, tactical simulation, data analysis, 3D visualization, and video retrieval—into **a single conversational entry point**, enabling coaches, players, and enthusiasts to turn a complete badminton match into data they can **query, watch, and analyze** through natural language. To achieve this, we designed an end-to-end, three-layer architecture spanning **data → functional modules → presentation**, with a large language model (LLM) agent centrally **orchestrating** subproject capabilities. The three core innovations are: **(1) a hybrid agent architecture with Model Context Protocol (MCP) as the access layer and skill playbooks as the behavior layer**, **(2) one agent orchestrating five functional modules for immediate access to outcomes across subprojects**, and **(3) unified presentation across text, charts, video, and 3D, paired with same-turn polling for long asynchronous tasks**. We first explain the motivation and positioning (2.1), then describe the layers from the bottom up (2.2–2.5), followed by the key technologies supporting system operation (2.6–2.7).

#### **2.1 Introduction: motivation, features, and target users**

General-purpose LLMs such as ChatGPT can fluently answer general questions about badminton rules and player backgrounds. However, they immediately encounter limitations when asked about facts within a specific match. This subproject starts by addressing that gap.

**Motivation: addressing three gaps in general-purpose LLMs.** General models have three fundamental limitations for specific matches. First, **they cannot find "that shot"**: without shot-by-shot annotations, they cannot answer questions such as "How many points did Axelsen win with smashes in this match?" or "What was the most common reason for losing points?" that require structured match data; instead, they give vague answers from memory or fabricate them. Second, **they cannot produce highlight videos**: without match footage and shot timestamps, they cannot turn "Make me a highlight video" into a playable file. Third, **they cannot simulate matches**: without a badminton-specific simulator, they cannot reason through "How would this rally develop if the service strategy changed?" BadmintonGPT addresses these gaps with a badminton-specific agent that uses tools, verifies facts, and produces audiovisual output.

**Features: turning the whole match into data users can query, watch, and analyze.** Previously, a match's value was fragmented across video files, manual annotation tables, and analysts' knowledge. This system transforms it into three interactive forms. **Query**: ask about any shot-level fact in natural language; the system translates it into a single read-only SQL query, leading with conclusions, key numbers, and evidence. **Watch**: request a highlight video with a scoreboard and narration, play it directly through an embedded `<video>` player, and replay key rallies as 3D court trajectories. **Analyze**: after obtaining raw data, the system calculates statistics (win rates, proportions, distributions, rankings) in sandboxed Python and renders interactive charts. All three share one entry point and the same match data.

**Target users: coaches, players, and badminton enthusiasts.** Through the same natural-language interface, tool routing serves each group's needs: **coaches** focus on tactical insights and analysis (opponents' shot preferences, lost-point patterns, critical-point scenarios); **players** focus on reviewing their performance and key moments (finding a particular shot, replaying tactical rallies, examining positioning through 3D trajectories); **enthusiasts** focus on viewing and sharing (one-click publishable highlights and match-report-style summaries).

Figure ?. Three gaps in general-purpose LLMs (finding a shot / producing highlights / simulating matches) and how BadmintonGPT addresses them.

The current design starts with three gaps—data queries, highlight generation, and tactical simulation. As subproject outcomes expand, more badminton-specific capabilities, such as real-time tactical advice and personalized training prescriptions, can be added to the same agent interface.

#### **2.2 System architecture: data, functional modules, and presentation**

The greatest risk in integrating heterogeneous subproject outcomes into one assistant is ending up with disconnected features. We therefore use a clear three-layer separation: the bottom layer collects data and materials from subprojects, the middle layer converts them into callable functional modules, and the top layer presents multimodal results to users. An LLM agent spans all three, **sending user intent downward and returning results upward**, as the system's central coordinator.

![BadmintonGPT three-layer architecture](<BadmintonGPT Framework.png>)

Figure ?. BadmintonGPT's three-layer architecture (data → functional modules → presentation).

Sections 2.3–2.5 describe each layer from the bottom up and identify the source subproject for each functional module.

#### **2.3 Data layer: match materials accumulated by subprojects**

All analysis and generation require a trustworthy factual basis. The data layer gathers structured annotations, videos, and venue data produced by the subprojects, forming the system's factual foundation.

**Annotation data and video match annotations (subproject 4).** Shot-by-shot annotations from the CoachAI database include more than ten fields per shot: type, service and return, around-the-head and backhand, hit_area, landing_area, win_reason/lose_reason, and current roundscore. These provide the factual basis for querying and analysis. **Match videos (subproject 4)** are footage and pre-cut rally clips aligned with annotations, supplying materials for highlight editing and retrieval. **Smart venues (subproject 5)** provide venue-captured match data, connecting the system to the data production source.

**Data model.** Data is organized into three tables—`matches` (catalog), `rallies`, and `shots`. Both rallies and shots join matches through **`match_name`** (`matches.name`, without `.mp4`). The prototype database contains **27 official matches and approximately 24,000 shot records**, built from ShuttleSet-derived data. Integration with subproject 4's full platform can expand this to 305 matches and more than 227,000 records.

Queries currently use an offline-built SQLite snapshot. In future, smart venues (subproject 5) could stream live match data into the database automatically, enabling assistance during ongoing matches.

#### **2.4 Functional module layer: five capabilities orchestrated by the agent**

Data needs functional modules to become usable capabilities. This layer is the main meeting point for subproject outcomes: the agent routes the same match data to the most appropriate module based on user intent. The five modules and their source subprojects are:

* **Match highlight editing (subprojects 2 and 1)**: subproject 2's multi-agent match highlights, combined with subproject 1's multimodal narrative highlight generation (the sister subproject referenced by this report), produce short videos with narration and scoreboards.
* **Badminton simulator (subproject 1)**: RallyDiffuser/CoachLLM supports tactical simulations of how rallies would develop under changed strategies.
* **CoachAI data analysis (subproject 4)**: analysis dashboards and charts (scoring-method analysis, radar charts, trend charts).
* **3D visualization system (subproject 3)**: 3D court trajectories and player-pose visualization.
* **Video translation and retrieval (subprojects 2/3)**: semantic text-to-video retrieval finds corresponding clips through natural language.

Crucially, the BadmintonGPT agent **does not implement these capabilities itself**. Each module is wrapped as a callable tool, and the agent decides when to call which one (access mechanism in 2.6, routing decisions in 2.7).

Currently, the agent calls modules individually. Future cross-module workflows could let a single question coordinate multiple subproject outcomes, for example a retrieval → analysis → highlights pipeline.

#### **2.5 Presentation layer: four output modalities**

Badminton analysis produces varied results that plain text cannot fully convey. The presentation layer renders module outputs in the most suitable modality, all embedded in the same conversation: **text** (match reports, analysis, key moments, tactical advice; conclusions first, with key numbers and evidence), **charts** (scoring-method analysis, radar charts, trends; interactive rather than static), **video** (highlights with scoreboards, played directly through embedded `<video>`), and **3D visualization** (court trajectories recreating shots and positioning in key rallies).

Currently, the four modalities are presented independently. Future responses could combine textual conclusions, supporting charts, highlights, and 3D trajectories into a complete match report card.

#### **2.6 System technology (1): agent framework and MCP access layer**

For an LLM to actually use tools, it needs a framework that attaches tools, manages conversation and tool loops, and provides a web interface. The system adopts the 2026 hybrid agent architecture: **MCP as the access layer and skill playbooks as the behavior layer**, centrally orchestrated by an LLM agent.

**Agent framework: nanobot.** The system starts with `nanobot gateway`, including the agent loop and WebSocket WebUI. We use our own fork of HKUDS/nanobot v0.2.1, built with the repository. Persona, tool-routing rules, and DB query conventions are centralized in `SOUL.md`, the de facto system prompt. The **LLM model** is driven by environment variables (default gpt-5.5, openai provider), with a selectable Custom OpenAI-compatible preset. Temperature is 0.1 for stable queries and routing.

**MCP (access layer): what the agent can access.** Each external capability is wrapped as an MCP server, accessed only through standardized tool calls. Three servers are connected: **badminton-db** (local FastMCP wrapping **SQLite**) exposes only list_tables, describe_table, and query. query opens the DB in read-only mode (`mode=ro`) and **accepts only a single SELECT**, rejecting semicolon-separated multiple statements or any non-SELECT, and returning at most 200 rows. It is the agent's only DB access path, served through streamable HTTP at /mcp on port 8801. **badminton-reels** (remote MCP, subproject 2) asynchronously generates highlights with generate_reel, get_reel_status, and get_reel_result. **util** (local stdio MCP) exposes only sleep (≤60 seconds) to pace polling. Built-in **web search** retrieves recent external information absent from the DB, and an **exec Python sandbox** (bwrap, standard library only) handles statistics. Restricted MCP permissions—read-only access, single SELECT, limited tool sets—form the first security layer.

Figure ?. Hybrid agent architecture: MCP access layer + skill behavior layer.

Currently, three MCP servers serve three capability categories. New subproject outcomes can use the same interface—for example, separate MCPs for 3D visualization and simulation—allowing the access layer to expand linearly without changing the agent core.

#### **2.7 System technology (2): skill behavior layer, routing, and long asynchronous tasks**

Knowing what is accessible is insufficient; the agent must know how and when to use it. Putting all domain knowledge in the system prompt would make it bulky and hard to maintain. We therefore use **skill playbooks as the behavior layer**, loaded on demand through progressive disclosure.

**Five skills.** badminton-db (enum values, A/B↔names, query conventions such as mandatory match_name filters and WHERE has_video=1 for clips); badminton-reels (generation parameters and domain conventions); long-mcp-job (generic asynchronous polling recipe); visualise (charts rendered in WebUI-embeddable visualizer code fences); and data-analysis (fetch with MCP, calculate with exec Python, then chart). The core design pattern is: **MCP determines what can be accessed; skills determine how to behave. This access/behavior separation is the system's backbone.**

**Tool routing (in SOUL.md).** The agent chooses modules by question type: DB questions → badminton-db skill and query; highlight requests → badminton-reels skill and reels MCP; any asynchronous job → long-mcp-job; external information → web search; visualization/charts → visualise with a visualizer fence; statistics/analysis → calculate first with exec Python, then visualise.

**Long asynchronous tasks: same-turn polling.** Highlight rendering takes minutes. A silent, same-turn polling mechanism handles waiting and progress in one conversational turn: after receiving job_id, **immediately call get_reel_status once** so progress appears, then alternate util sleep (10–60 seconds, chosen according to progress) and status checks until terminal (up to about ten minutes). After succeeded, retrieve results with get_reel_result. Three strict rules apply: ① **one tool per response** (never parallelize status and sleep, which delays progress by about 30 seconds); ② **no text during polling** (text-only responses end the turn and interrupt polling; WebUI displays progress automatically); ③ **never use cron** (nanobot cron relays reminders rather than executing tasks; it reads reminders instead of polling).

Currently, polling uses a fixed upper limit and manually chosen intervals, while routing uses handwritten heuristics. Future work could replace polling with webhooks/server-push, support parallel jobs, and train a more precise intent classifier from real conversation traces.
