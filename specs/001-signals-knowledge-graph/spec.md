# Feature Specification: Signals Report — Persistent Knowledge Layer and Trend-Based Early Warning

**Feature Branch**: `001-signals-knowledge-graph`
**Created**: 2026-09-03
**Status**: Draft

## Overview

The agent is stateless. Each run summarizes newsletters in isolation and then deletes the source emails, so nothing it learns on Monday is available to it on Thursday. It can report what a newsletter said; it cannot report that four newsletters have been circling the same risk for three weeks, that a company's mention rate has tripled, or that a story the reader was tracking has gone quiet.

That limitation caps the agent's usefulness. The reader's goal is not a faster way to read newsletters — it is **advance warning of slowly developing risks and opportunities, while reading less**. Slow development is only visible over time, and time is exactly what the agent currently has no access to.

This feature gives the agent memory and a second analysis pass over that memory. As newsletters are decomposed into ideas, the agent records which concepts and entities each idea concerns and how it frames them. Those observations accumulate across runs. Every few days, a separate analysis produces a **Signals Report** — a distinct email, on its own cadence — describing what is accelerating, what is emerging, what is fading, and what opportunities or risks follow.

The feature is delivered in three independently shippable slices, and is entirely optional at every layer: switched off, the daily digest behaves exactly as it does today.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Signals Report From Newsletter History (Priority: P1)

The reader continues receiving daily digests unchanged. Behind the scenes, every idea the agent extracts is also recorded as a set of observations: which entities the idea concerns, what kind of thing each entity is, whether the idea frames it positively or negatively, which newsletter it came from, and which other entities appeared alongside it in that same idea. These observations persist across runs and accumulate into a history.

Every few days, the agent analyzes that history and emails the reader a Signals Report covering accelerating risks, investment and business opportunities, emerging themes and newly-formed connections between entities, fading stories the reader can stop tracking, and lower-confidence watch items. All counting and trend arithmetic is computed deterministically before the analysis model sees anything; the model is given movements and asked only to interpret them.

**Why this priority**: This is the irreducible slice. Nothing smaller reaches the reader's inbox, and every other part of this feature is an enrichment of this loop. It also delivers the reader's core request — advance warning from accumulated history — using nothing but newsletters the agent already processes.

**Independent Test**: Seed the observation history with a synthetic multi-week dataset, run the signals analysis on demand, and confirm a report is produced whose rising, emerging, and fading sections are populated and whose every named entity is present in the underlying history.

**Acceptance Scenarios**:

1. **Given** the knowledge layer is enabled and newsletters are processed across several runs, **When** the configured report interval elapses, **Then** the reader receives a Signals Report email that is separate from the daily digest and carries its own subject line.
2. **Given** an entity mentioned five times but all within a single newsletter source, **When** the Signals Report is generated, **Then** that entity is not reported as a trend, because it does not meet the multi-source threshold.
3. **Given** an entity mentioned five times across four distinct newsletter sources, **When** the Signals Report is generated, **Then** that entity is eligible for the rising or emerging sections.
4. **Given** the same newsletter email is processed more than once (as happens when delivery preserves the source email), **When** observations are recorded, **Then** the stored mention counts are identical to those after the first processing.
5. **Given** the observation history is missing, unreadable, or corrupt, **When** a digest run executes, **Then** the daily digest is produced and delivered normally and the failure is logged rather than raised.
6. **Given** the knowledge layer is switched off in configuration, **When** a digest run executes, **Then** the daily digest output is unchanged from its behavior before this feature existed and no observation history is created.
7. **Given** the history contains less than two full analysis windows of data, **When** a Signals Report is generated, **Then** the report explicitly states that it is in a cold-start period and that its conclusions are provisional.
8. **Given** a report was generated and the interval has not yet elapsed, **When** subsequent digest runs execute, **Then** no additional Signals Report is generated.
9. **Given** the reader wants to see a realistic report before real history exists, **When** they invoke the preview path with synthetic history, **Then** a fully populated report is rendered without waiting for weeks of accumulation.

---

### User Story 2 — Ground The Signals In External Reality (Priority: P2)

The Signals Report gains two independent forms of corroboration. First, the analysis may consult live web search to verify or extend a signal before flagging it, and cites what it checked. Second, the report opens with a macroeconomic dashboard of hard numbers — yield-curve spreads, recession trigger rules, jobless claims, credit spreads, financial conditions, broad dollar and bilateral exchange rates, inflation expectations, policy rates, oil, volatility, and mortgage rates — each shown with its latest value, its recent direction, and whether it has crossed an alarm threshold.

The most valuable output is divergence: when the newsletters' collective narrative disagrees with what the indicators actually show.

**Why this priority**: Newsletter sentiment alone is a lagging and potentially circular signal — newsletters often echo each other. Anchoring warnings about recessions, currency crashes, and economic headwinds in independent measured data is what makes the early-warning claim credible. It is P2 rather than P1 because the report is already valuable without it, and because it introduces external dependencies that must not be allowed to block delivery.

**Independent Test**: With external grounding unconfigured, confirm the report renders identically to its P1 form. With it configured and external responses simulated, confirm the macro dashboard renders every requested indicator with alarm states marked, and that a signal verified by search carries a citation.

**Acceptance Scenarios**:

1. **Given** no macroeconomic data source is configured, **When** a Signals Report is generated, **Then** the report renders exactly as it did under P1, with no error and no empty dashboard section.
2. **Given** a macroeconomic data source is configured, **When** a Signals Report is generated, **Then** the report opens with a dashboard listing each configured indicator with its latest value, as-of date, recent direction, and alarm state.
3. **Given** an indicator has crossed its alarm threshold, **When** the dashboard renders, **Then** that indicator is visually distinguished from indicators in a normal range.
4. **Given** the analysis model call fails entirely, **When** the report is assembled, **Then** the macroeconomic dashboard is still delivered, because it does not depend on that call.
5. **Given** some indicators could not be retrieved, **When** the report renders, **Then** the successfully retrieved indicators are shown and the report states that the data is partial.
6. **Given** web search is enabled, **When** the analysis flags an item at high confidence, **Then** that item cites the sources it was checked against.
7. **Given** web search is enabled, **When** a search fails or its usage ceiling is reached, **Then** the report is still delivered, without citations for the affected items.
8. **Given** web search is disabled in configuration, **When** the analysis runs, **Then** no search is performed and no search-related failure can affect the report.
9. **Given** the newsletters' narrative on a topic is optimistic while a related indicator has deteriorated, **When** the report is generated, **Then** that divergence is surfaced as its own finding rather than being averaged away.

---

### User Story 3 — Cross-Newsletter Theme Synthesis In The Daily Digest (Priority: P3)

The daily digest currently lists each newsletter separately, so a story covered by four sources is read four times. This story merges the day's ideas into deduplicated, ranked themes. Each theme cites the sources that contributed to it, states where those sources agree, and — most valuably — highlights where they disagree. Ideas absorbed into a theme are suppressed from their per-newsletter sections, so each story is read once.

**Why this priority**: This is the single largest reduction in the reader's actual reading time, but it modifies a digest that already works well, and it depends on the entity extraction delivered in P1 to cluster ideas cheaply. It is explicitly deferrable: if it never ships, the daily digest is unchanged and the rest of the feature is unaffected.

**Independent Test**: Process a batch of newsletters in which four sources cover the same story, and confirm the digest contains one merged theme citing four sources, with the four constituent ideas no longer appearing separately in their per-newsletter sections.

**Acceptance Scenarios**:

1. **Given** four newsletters in one batch cover the same story, **When** the digest is built, **Then** it contains a single merged theme that names all four sources.
2. **Given** an idea has been absorbed into a merged theme, **When** the digest renders, **Then** that idea does not also appear in its own newsletter's section.
3. **Given** an idea is covered by only one source, **When** the digest renders, **Then** it appears in its newsletter's section exactly as it does today.
4. **Given** two sources covering the same story reach opposing conclusions, **When** the theme is written, **Then** the disagreement is stated explicitly rather than being smoothed into a single narrative.
5. **Given** several ideas from the same single newsletter share entities, **When** clustering runs, **Then** they are not merged into a cross-source theme, because one author repeating a point is not corroboration.
6. **Given** theme synthesis is disabled, **When** the digest is built, **Then** the output is identical to the pre-feature digest.

---

### Edge Cases

- **What happens on the very first run, when there is no history at all?** The observation history is created empty and populated by that run. No Signals Report is generated until the history spans at least one analysis window; when the first report is generated, it is labeled as cold-start.
- **What happens if the reader runs the agent for a week and then stops for a month?** The next run resumes recording. The report's windows are defined by dates rather than by run counts, so a gap appears as a period of low activity rather than as corrupted trends.
- **What happens when no newsletters arrive on a given run?** The report cadence must still be evaluated. Quiet periods are precisely when a trend report is most useful, so an empty inbox must not prevent a due report from being generated.
- **What happens if the same entity appears under different names ("Nvidia", "NVIDIA Corp.", "NVDA")?** They are resolved to a single canonical entity before any counting occurs, otherwise a single real trend is split into three invisible ones. Resolution covers deterministic name normalization, the reader's own portfolio and watchlist names, and adjudication of near-duplicate candidates.
- **What happens if the analysis model names an entity that is not in the history?** That finding is discarded before the report is rendered. Fabricated entities are the failure mode most likely to destroy the reader's trust in the feature.
- **What happens if the analysis model asserts high confidence with no supporting evidence?** The confidence level is downgraded rather than the finding being shown as more certain than it is.
- **What happens as the history grows to tens of thousands of observations?** The analysis input is a ranked, truncated summary whose size is bounded by configuration, not by the size of the history. Report generation cost and duration stay flat as history accumulates.
- **What happens if the report generation fails repeatedly?** The cadence clock is reset on failure as well as success, so a persistently broken analysis does not retry on every digest run and consume the reader's usage budget.
- **What happens to observations that are years old?** Raw observations are pruned past a configured retention period, but a compact per-day rollup is retained so that long-horizon trend shape survives pruning.
- **What happens if an entity is mentioned once and never again?** It never meets the reporting threshold and never appears in the report. It remains in the history in case it later becomes part of an emerging pattern.

---

## Requirements *(mandatory)*

### Functional Requirements

**Entity Observation and Memory**

- **FR-001**: When decomposing a newsletter into ideas, the agent MUST also identify the concepts and entities each idea concerns, classified by kind (such as company, person, country, policy, sector, technology, asset, institution, event, or general concept).
- **FR-002**: For each identified entity, the agent MUST record whether the idea frames that entity positively, negatively, or neutrally, reflecting the idea's framing rather than the newsletter's overall tone.
- **FR-003**: The agent MUST persist each observation across runs, retaining at minimum the entity, its kind, its framing, the specific claim text it came from, the originating newsletter source, and the date observed.
- **FR-004**: The agent MUST record which entities appeared together within the same idea, so that relationships between entities can be tracked over time.
- **FR-005**: The agent MUST resolve entity name variants to a single canonical entity before any counting occurs, using at minimum deterministic name normalization and the reader's configured portfolio and watchlist names.
- **FR-006**: Recording the same newsletter email more than once MUST NOT change the stored observation counts.
- **FR-007**: Observations MUST be recorded before the source email is disposed of, so that no processed newsletter is lost to the history.
- **FR-008**: The agent MUST NOT record observations during a dry run.
- **FR-009**: The agent MUST prune raw observations older than a configured retention period while retaining a per-day summary sufficient to preserve long-horizon trend shape.

**Trend Computation**

- **FR-010**: All counting, comparison, and trend arithmetic MUST be computed deterministically. The analysis model MUST NOT be asked to count, total, or compute any figure that appears in the report.
- **FR-011**: The agent MUST compute, for each entity, its mention count in the current window, its count in the prior window, the change between them, the rate of change, how many distinct newsletter sources mentioned it, and how unusual the current level is relative to that entity's own history.
- **FR-012**: The agent MUST identify entities appearing for the first time within the current window, and entities that were previously active and have gone silent.
- **FR-013**: The agent MUST identify relationships between entities that appear in the current window and have never appeared before.
- **FR-014**: An entity MUST NOT be reported as a trend unless it meets both a configured minimum mention count and a configured minimum number of distinct newsletter sources.
- **FR-015**: The agent MUST rank and truncate the computed trends to a configured maximum before they are passed to the analysis model, so that the analysis input size is bounded by configuration rather than by the size of the accumulated history.
- **FR-016**: The agent MUST NOT present a statistical measure of unusualness when the entity's history contains too few periods for that measure to be meaningful.

**Signals Report Content**

- **FR-017**: The Signals Report MUST contain sections for accelerating risks, investment and business opportunities, emerging themes and newly-formed entity relationships, fading stories, and lower-confidence watch items.
- **FR-018**: Each reported finding MUST carry an explicit confidence level.
- **FR-019**: The agent MUST discard any finding that names an entity not present in the computed trend data.
- **FR-020**: The agent MUST downgrade the confidence of any finding presented at the highest confidence level without supporting evidence.
- **FR-021**: The report MUST state plainly that it is a reading assistant and not investment advice.
- **FR-022**: When the accumulated history spans less than two full analysis windows, the report MUST state that it is in a cold-start period and that its conclusions are provisional.
- **FR-023**: The report MUST NOT include personal-goal content such as home or vehicle purchase timing.

**Report Delivery and Cadence**

- **FR-024**: The Signals Report MUST be delivered as its own email, separate from the daily digest, with a distinct subject line.
- **FR-025**: The report MUST be generated on a configured interval measured in days, independent of how often the digest runs.
- **FR-026**: The cadence MUST be evaluated on every digest run, including runs where no newsletters were found.
- **FR-027**: The cadence state MUST survive process exit, so that the interval is honored regardless of whether the agent runs as a long-lived process or as a short-lived scheduled invocation.
- **FR-028**: The cadence clock MUST be reset after both successful and failed report generation.
- **FR-029**: A failure anywhere in the signals pipeline MUST NOT prevent the daily digest from being built or delivered.
- **FR-030**: The reader MUST be able to generate a Signals Report on demand, bypassing the cadence check, and to do so without sending an email.

**Optionality and Degradation**

- **FR-031**: The knowledge layer, the Signals Report, and each form of external grounding MUST each be independently switchable.
- **FR-032**: With the knowledge layer switched off, the daily digest output MUST be unchanged from its behavior before this feature existed, and no observation history may be created.
- **FR-033**: A missing, unreadable, or corrupt observation history MUST degrade the system to its pre-feature behavior rather than failing a run.
- **FR-034**: A corrupt observation history MUST NOT be automatically discarded or reset; recovery MUST be an explicit reader action.
- **FR-035**: Adding this feature MUST NOT introduce any new mandatory configuration for existing installations.

**External Grounding**

- **FR-036**: The report MUST be able to include a macroeconomic dashboard covering recession indicators, labor market indicators, credit and financial conditions, currency levels, inflation expectations, policy rates, commodities, and volatility.
- **FR-037**: Each dashboard indicator MUST show its latest value, the date that value is as of, its recent direction, and whether it has crossed an alarm threshold.
- **FR-038**: The macroeconomic dashboard MUST be produced without reference to the analysis model, so that it is delivered even when that call fails entirely.
- **FR-039**: When only some indicators can be retrieved, the report MUST render those that succeeded and state that the data is partial.
- **FR-040**: Indicator data MUST be cached so that repeated report generation within a short period does not re-request it.
- **FR-041**: The analysis MUST be able to consult live web search to verify or extend a candidate signal.
- **FR-042**: Findings verified by search MUST cite the sources consulted.
- **FR-043**: A web search failure, error, or usage ceiling MUST NOT prevent the report from being delivered.
- **FR-044**: The agent MUST surface disagreement between the newsletters' collective narrative and the measured indicators as a distinct finding.

**Cross-Newsletter Synthesis**

- **FR-045**: The daily digest MUST be able to merge ideas from different newsletters that concern the same story into a single theme.
- **FR-046**: Each merged theme MUST name the newsletter sources that contributed to it.
- **FR-047**: Each merged theme MUST state where its sources disagree.
- **FR-048**: Ideas absorbed into a merged theme MUST NOT also appear in their originating newsletter's section.
- **FR-049**: Ideas that originate from a single source MUST NOT be merged into a cross-source theme.
- **FR-050**: With synthesis disabled, the digest output MUST be identical to its pre-feature form.

**Cost and Scale Controls**

- **FR-051**: The reader MUST be able to bound ongoing cost through configuration of at minimum the report interval, the maximum number of trends admitted to an analysis, and the maximum number of web searches per report.
- **FR-052**: Entity identification MUST NOT require re-sending newsletter content that has already been transmitted for summarization.
- **FR-053**: The size of the analysis input MUST NOT grow as the accumulated history grows.

### Key Entities

- **Observation**: A single record that one entity was discussed in one idea, in one newsletter, on one date, with a particular framing. The atomic unit of the agent's memory. Carries the originating claim text so that any later finding can be traced back to something a newsletter actually said.
- **Entity**: A canonical real-world subject — a company, person, country, policy, sector, technology, asset, institution, event, or concept — that observations attach to. Holds the display name, the kind of thing it is, and when it was first and last seen. Name variants resolve to one entity so that a single trend is not split across spellings.
- **Relationship**: A record that two entities were discussed together within the same idea. Scoped to the idea rather than to the newsletter, because two topics sharing an inbox is not a relationship. The accumulation of these over time is what allows newly-formed connections to be detected.
- **Entity Trend**: The deterministically computed movement of one entity over the analysis window — current and prior counts, change and rate of change, how many distinct sources carried it, how unusual the level is against its own history, and whether it is newly appeared or newly silent.
- **Trend Brief**: The ranked, truncated set of entity trends and relationship changes that is handed to the analysis model. Its size is bounded by configuration, which is what keeps analysis cost flat as history grows.
- **Macro Indicator**: A single measured economic series with its latest value, as-of date, recent direction, and alarm state. Sourced independently of the newsletters, which is what makes it capable of contradicting them.
- **Signal**: One finding in the report — a headline, an explanation of the mechanism, a confidence level, the entities it concerns, and any evidence it was checked against.
- **Signals Report**: The complete periodic artifact delivered to the reader: the macro dashboard, the findings grouped into risks, opportunities, emerging themes, fading stories, and watch items, plus the cold-start and advice disclaimers.
- **Theme**: A cluster of ideas from different newsletters covering the same story, merged into one entry that names its sources and states where they disagree. Used only by the daily digest.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the feature switched off, the daily digest produced for a given set of newsletters is identical to the digest produced before this feature existed.
- **SC-002**: Processing the same newsletter email twice produces the same stored observation counts as processing it once.
- **SC-003**: Every entity named anywhere in a Signals Report can be traced to at least one stored observation from a real newsletter; the count of unverifiable entity references in a delivered report is zero.
- **SC-004**: No entity appears in the report's trend sections unless it was mentioned by at least the configured minimum number of distinct newsletter sources.
- **SC-005**: The size of the input handed to the analysis differs by less than 20% between a history of 300 observations and a history of 30,000 observations.
- **SC-006**: A Signals Report is delivered on a run where zero newsletters were fetched, provided the configured interval has elapsed.
- **SC-007**: With the observation history deleted or corrupted, a full digest run completes and delivers its digest.
- **SC-008**: With no external grounding configured, a Signals Report is delivered containing populated trend sections.
- **SC-009**: With the analysis model call failing on every attempt, the Signals Report is still delivered and still contains the macroeconomic dashboard.
- **SC-010**: Every finding in a delivered report carries a confidence level, and no finding at the highest confidence level lacks supporting evidence.
- **SC-011**: A realistic, fully populated Signals Report can be produced and inspected on a fresh installation with no real newsletter history, in a single command, without sending an email.
- **SC-012**: In a digest batch where four newsletters cover the same story, the reader encounters that story once rather than four times.
- **SC-013**: An existing installation that pulls this change and adds no new configuration continues to run without error.

---

## Assumptions

- Entity identification happens as part of the existing per-newsletter idea decomposition rather than as a separate pass over the same content, on the assumption that re-transmitting newsletter text purely to extract entities is not a cost the reader wants to bear.
- The analysis window defaults to seven days and the report interval to three days. Both are configurable; these defaults assume the reader wants a report roughly twice a week reflecting the trailing week.
- The minimum reporting thresholds default to three mentions across two distinct sources. This assumes cross-source corroboration is the primary noise filter and that a single author's repetition should never surface as a trend.
- Raw observation retention defaults to 180 days, with an indefinitely retained per-day rollup. This assumes trend shape matters longer than individual claim text does.
- The reader's existing portfolio and watchlist configuration is reused to seed entity name resolution; no new profile configuration is introduced for this.
- The Signals Report is delivered to the same address as the daily digest, using the same delivery mechanism.
- Report cadence is tracked in the persisted history rather than by a scheduler, so that the interval is honored whether the agent runs continuously or as repeated short-lived invocations.
- "Opportunity" means investment and business opportunity only. Personal-goal tracking is excluded by the reader's explicit direction.
- The daily digest and the Signals Report are separate artifacts; no part of the trend analysis is injected into the daily digest.
