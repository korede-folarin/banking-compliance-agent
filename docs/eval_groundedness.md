# Groundedness / Faithfulness Cross-Check (P8-05)

New scope, not part of Phase 8's original plan — see feature_list.json's P8-05 and ARCHITECTURE.md's "Groundedness cross-check (P8-05)" section for the design rationale (why two independent signals, why neither is trusted alone) and the class-of-project-methodology caveat (this is this project's own applied approach, not a settled technique drawn from established literature).

**Scope**: run_idx == 0 rows only, all 4 outcomes, judgments where `llm_status` is `compliant` or `potentially_non_compliant` (not `insufficient_evidence`, which has no cited evidence to check by design). See this file's generating script, `src/evaluation/groundedness.py`, for why run_idx 0 specifically, and why both signals are computed against the full retrieved source set rather than a reconstructed "cited-only" subset — both are real, structural data-availability constraints from the original eval log, not a convenience.

**Why "full retrieved context, not verified cited-only subset," specifically.** The data this check runs against (`docs/eval_raw_main_pass.jsonl`, 405 calls, Session 13) predates a logging fix made this session: `src.agent.compliance.validate_outcome` now logs, and `src.evaluation.run_eval`'s `main` subcommand now persists, each judgment's full cited-source objects (index, file name, similarity score, chunk text), not just a count. That fix is forward-looking only — it was not applied retroactively to this dataset, which recorded only `cited_source_count` (an integer) per judgment, so which specific sources were cited is not recoverable for these 51 judgments. That is the entire reason both signals here are checked against the full retrieved source set instead of the actual cited subset. A future comprehensive re-run (see ARCHITECTURE.md's "Evaluation notes" — deliberately deferred, not done incrementally per fix) would carry real per-claim citation data and could re-run this check against verified citations instead.

**Correction: what Signal 1 measures in this run.** The Signal 1 numbers below are the maximum embedding similarity between a judgment's whole reasoning text and each of the (300-character) excerpts in its *full retrieved set*, not its cited sources, because this Phase 8 data predates the citation-logging fix. That is a paragraph-level topical-closeness measure. It is **not a groundedness measure**: it shows that the reasoning is about the same topic as something it was shown, not that any statement in it is supported. It is also **a different number from the P4-02 `confidence` score**, which is the minimum retrieval similarity (question vs. chunk) among cited sources and does not involve the reasoning text at all. From P8-06 on, Signal 1 is computed per cited chunk against logged citations, with minimum and mean reported and no threshold (see ARCHITECTURE.md "Structured-claim verification (P8-06)"). The "high"/"low" buckets below use the old max-over-retrieved-set number and should be read with this in mind.

**Total in-scope judgments**: 51
**Total Signal-2 LLM calls made**: 192

## Signal agreement vs. disagreement

| Category | Count | Meaning |
|---|---|---|
| agree_grounded | 0 | Signal 1 high (>= 0.75) AND Signal 2 all claims supported — lower priority |
| agree_flagged | 13 | Signal 1 low (< 0.75) AND Signal 2 flagged/partial — lower priority, both signals independently suggest a problem |
| disagreement | 38 | Signals disagree — **flagged for human review below** |
| no_claims | 0 | Reasoning produced 0 claims after mechanical extraction (< 25 chars) — Signal 2 not computed, not counted as agreement or disagreement |

## Observed limitation: what's actually driving "flagged"

**Read this before the raw counts above.** Signal 2 returned `clean` (all
claims supported) for 0 of the 51 in-scope judgments — every judgment
landed in `flagged` or `partial`. Because of that, the agreement/
disagreement split above is not really tracking genuine two-signal
disagreement; it's mostly just re-reporting Signal 1's own high/low bucket
(38 of 51 judgments sit at Signal 1 >= 0.75, and every one of those becomes
`disagreement` almost by construction, since Signal 2 is saturated). **This
is a real limitation of this run's claim-extraction step, not evidence that
the Compliance Agent's reasoning is unsupported in 38 of 51 judgments.**

Checking the actual claim text behind the `no`/`partially` verdicts in the
disagreement cases below (142 individual claim verdicts) shows why:

| Verdict | n | Describes the document under review, or asserts an absence/negation | Share |
|---|---|---|---|
| `no` | 64 | 53 | 83% |
| `partially` | 48 | 23 | 48% |

Two claim types the mechanical sentence-splitter extracts are structurally
unable to pass a "does this claim appear in the source text" check, no
matter how accurate the reasoning is, because the check's only source pool
is the *retrieved regulatory excerpts*:

1. **Claims describing the loan agreement under review, not the
   regulation** — e.g. "The clause defines a target market (consumers
   wanting fixed-rate, fixed-term borrowing...)" or "The document also
   states the assessment is reviewed periodically." These are accurate
   restatements of the *document*, but asking whether they appear in the
   *regulatory* excerpts is a category error — they were never going to be
   found there, regardless of whether the reasoning is faithful. (This is
   also, separately, exactly what P6-01's extraction-confidence check in
   `src/agent/uncertainty.py` already validates — against the source
   *document*, not the regulation — so this isn't an uncovered risk, just
   the wrong check being applied to this sentence type here.)
2. **Negative/absence claims** — e.g. "No conflicting requirement is shown
   in the excerpts" or "No specific gap is evident from the retrieved
   excerpts." A claim that something is *absent* from the source text has
   no positive text for a claim-checker to point to, so it tends to read as
   unsupported even when the underlying observation (the excerpts don't
   contradict the document) is reasonable.

**Net effect**: this run's Signal 2, as built, is not a reliable per-claim
faithfulness signal for the ~40-80% of claims that fall into these two
categories. It remains meaningful for claims that *do* restate what the
regulation itself requires (the `yes` verdicts, and the more literal `no`/
`partially` verdicts not counted above) — those are genuine claim-level
checks. **Future work, not attempted here**: restrict mechanical claim
extraction to sentences that make an assertion about the regulatory
requirement (e.g. sentences referencing an excerpt number as their subject)
rather than every sentence in the reasoning, and either exclude negative/
absence claims from Signal 2 or check them with a differently-phrased
prompt suited to verifying an absence rather than a positive assertion. The
disagreement cases below should be read with this limitation in mind, not
as 38 independently confirmed instances of unsupported reasoning.

## Disagreement cases (for human review)

### loan_agreement_1 / price_and_value (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7986
- Signal 2 bucket: partial
- Per-claim verdicts:
  - `partially`: The retrieved excerpts establish that under the Price and Value outcome, firms must consider all costs and charges a consumer may incur (excerpt 2), must be able to demonstrate that benefits are reasonable relative to price when designing charges and charging structures (excerpt 5), and must assess fair value even for existing contracts (excerpt 4).
  - `partially`: The loan agreement only references an unspecified 'standard tariff of charges' without stating specific fee amounts, and explicitly states that fair value justification is 'Not addressed in this document.' This is a clear gap relative to the regulatory requirement that firms be able to demonstrate charges represent fair value and that benefits are reasonable relative to price — there is no fair value assessment or justification provided, and fee amounts are not disclosed, making it impossible to verify that the price charged reflects fair value as required.
- Full reasoning: The retrieved excerpts establish that under the Price and Value outcome, firms must consider all costs and charges a consumer may incur (excerpt 2), must be able to demonstrate that benefits are reasonable relative to price when designing charges and charging structures (excerpt 5), and must assess fair value even for existing contracts (excerpt 4). The loan agreement only references an unspecified 'standard tariff of charges' without stating specific fee amounts, and explicitly states that fair value justification is 'Not addressed in this document.' This is a clear gap relative to the regulatory requirement that firms be able to demonstrate charges represent fair value and that benefits are reasonable relative to price — there is no fair value assessment or justification provided, and fee amounts are not disclosed, making it impossible to verify that the price charged reflects fair value as required.

### loan_agreement_1 / consumer_support (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.8160
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: The clause demonstrates recognition that customers may be vulnerable due to a range of drivers (health, bereavement, life events, resilience, capability) consistent with the Duty's emphasis on identifying and responding to characteristics of vulnerability (excerpt 4, referencing FG21/1 guidance).
  - `partially`: It also sets out a support mechanism: encouraging disclosure in confidence, tailored responses (adjusted communication, additional time, referral to debt advice), which aligns with the requirement that firms provide effective support enabling customers to pursue their financial objectives and avoid foreseeable harm (excerpt 5).
  - `no`: The clause also monitors that contacting the Lender does not worsen obligations, addressing a key consumer support concern about not penalising customers for seeking help.
  - `partially`: While the excerpts don't detail specific monitoring/testing requirements for support channels (excerpts 2-3), the clause's core approach—proactive vulnerability recognition, confidential disclosure, tailored support options—matches the general expectations found in the retrieved guidance.
  - `no`: No clear conflict or gap is evident from the excerpts provided.
- Full reasoning: The clause demonstrates recognition that customers may be vulnerable due to a range of drivers (health, bereavement, life events, resilience, capability) consistent with the Duty's emphasis on identifying and responding to characteristics of vulnerability (excerpt 4, referencing FG21/1 guidance). It also sets out a support mechanism: encouraging disclosure in confidence, tailored responses (adjusted communication, additional time, referral to debt advice), which aligns with the requirement that firms provide effective support enabling customers to pursue their financial objectives and avoid foreseeable harm (excerpt 5). The clause also monitors that contacting the Lender does not worsen obligations, addressing a key consumer support concern about not penalising customers for seeking help. While the excerpts don't detail specific monitoring/testing requirements for support channels (excerpts 2-3), the clause's core approach—proactive vulnerability recognition, confidential disclosure, tailored support options—matches the general expectations found in the retrieved guidance. No clear conflict or gap is evident from the excerpts provided.

### loan_agreement_1 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7709
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: The excerpts establish that under the products and services outcome, firms must define a target market for their product, assess whether consumers in that target market are likely to achieve good outcomes, and monitor that distribution channels ensure the product reaches the intended target market (excerpts 2, 3).
  - `no`: The loan agreement's clause explicitly defines a target market (consumers seeking fixed-rate, fixed-term borrowing with evidenced affordability who do not need flexible/revolving credit), states the Lender's assessment that this cohort is likely to achieve good outcomes given the product's fixed cost structure, defined term, and early repayment rights, and commits to periodic review of the target market assessment considering the impact of distribution channels.
  - `yes`: This aligns with the monitoring and target market elements referenced in excerpt 2 (monitoring distribution strategies and correct distribution to target market) and the overview in excerpt 3 regarding harm from poor design or misdistribution.
  - `no`: The clause's structure and content are consistent with what these excerpts indicate is required, though the excerpts are somewhat general guidance rather than prescriptive rules.
- Full reasoning: The excerpts establish that under the products and services outcome, firms must define a target market for their product, assess whether consumers in that target market are likely to achieve good outcomes, and monitor that distribution channels ensure the product reaches the intended target market (excerpts 2, 3). The loan agreement's clause explicitly defines a target market (consumers seeking fixed-rate, fixed-term borrowing with evidenced affordability who do not need flexible/revolving credit), states the Lender's assessment that this cohort is likely to achieve good outcomes given the product's fixed cost structure, defined term, and early repayment rights, and commits to periodic review of the target market assessment considering the impact of distribution channels. This aligns with the monitoring and target market elements referenced in excerpt 2 (monitoring distribution strategies and correct distribution to target market) and the overview in excerpt 3 regarding harm from poor design or misdistribution. The clause's structure and content are consistent with what these excerpts indicate is required, though the excerpts are somewhat general guidance rather than prescriptive rules.

### loan_agreement_2 / consumer_support (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.8033
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: The retrieved excerpts establish that the Consumer Support outcome requires firms to actively ensure consumers can use their products/services effectively, including monitoring customer interactions to identify issues (excerpt 1), providing effective support through appropriate channels (excerpts 2, 3), and meeting specific rules on how support must function (excerpt 4).
  - `no`: These are substantive, affirmative obligations firms must address in their conduct and documentation.
  - `no`: The loan agreement's explicit statement that this outcome is "Not addressed in this document" represents a gap: there is no evidence the firm has considered or documented how it will provide consumer support, monitor its effectiveness, or ensure customers can act in their interests as required by the excerpts.
  - `no`: This is a real omission rather than a limitation of the regulatory text itself.
- Full reasoning: The retrieved excerpts establish that the Consumer Support outcome requires firms to actively ensure consumers can use their products/services effectively, including monitoring customer interactions to identify issues (excerpt 1), providing effective support through appropriate channels (excerpts 2, 3), and meeting specific rules on how support must function (excerpt 4). These are substantive, affirmative obligations firms must address in their conduct and documentation. The loan agreement's explicit statement that this outcome is "Not addressed in this document" represents a gap: there is no evidence the firm has considered or documented how it will provide consumer support, monitor its effectiveness, or ensure customers can act in their interests as required by the excerpts. This is a real omission rather than a limitation of the regulatory text itself.

### loan_agreement_2 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7723
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause identifies a specific target market (consumers wanting fixed-rate, fixed-term personal loans of a known amount who can evidence affordability and do not need flexible/revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to good outcomes for that target market, and states the Lender periodically reviews the target market assessment and monitors distribution channels to ensure the product reaches its intended market.
  - `yes`: This aligns with the excerpts' emphasis on defining a target market, ensuring products are distributed appropriately to that market, and monitoring distribution strategies (excerpts 2 and 3).
  - `partially`: While the excerpts are general guidance rather than granular checklists, the document's approach - target market definition, rationale for good outcomes, and ongoing distribution monitoring - matches the core requirements described (e.g., excerpt 2's questions on monitoring distribution and excerpt 3's overview on avoiding poor design/wide distribution to unsuitable customers).
- Full reasoning: The clause identifies a specific target market (consumers wanting fixed-rate, fixed-term personal loans of a known amount who can evidence affordability and do not need flexible/revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to good outcomes for that target market, and states the Lender periodically reviews the target market assessment and monitors distribution channels to ensure the product reaches its intended market. This aligns with the excerpts' emphasis on defining a target market, ensuring products are distributed appropriately to that market, and monitoring distribution strategies (excerpts 2 and 3). While the excerpts are general guidance rather than granular checklists, the document's approach - target market definition, rationale for good outcomes, and ongoing distribution monitoring - matches the core requirements described (e.g., excerpt 2's questions on monitoring distribution and excerpt 3's overview on avoiding poor design/wide distribution to unsuitable customers).

### loan_agreement_2 / consumer_understanding (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7568
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `yes`: The excerpts establish that under the Consumer Understanding outcome, firms should support informed decision-making by communicating relevant information (e.g., key product features, costs, risks) in a way that supports effective decision making, and give consumers an appropriate opportunity to review that information before proceeding (excerpts 1, 4).
  - `yes`: Excerpt 2 references firms' practice of producing summaries of products including main features, and excerpt 5 emphasizes explanations should be likely to be understood by consumers.
  - `no`: The loan agreement's "Key Facts at a Glance" section provides a clear, upfront summary of the essential terms (loan amount, APR, term, monthly repayment, total repayable, and fee) explicitly designed to help the borrower understand key terms before reading the full contract — this aligns with the requirement to communicate relevant information in a way that supports effective decision-making and gives an opportunity to review terms.
  - `no`: There is no indication of conflicting or deficient practice in the excerpts relative to this summary approach.
- Full reasoning: The excerpts establish that under the Consumer Understanding outcome, firms should support informed decision-making by communicating relevant information (e.g., key product features, costs, risks) in a way that supports effective decision making, and give consumers an appropriate opportunity to review that information before proceeding (excerpts 1, 4). Excerpt 2 references firms' practice of producing summaries of products including main features, and excerpt 5 emphasizes explanations should be likely to be understood by consumers. The loan agreement's "Key Facts at a Glance" section provides a clear, upfront summary of the essential terms (loan amount, APR, term, monthly repayment, total repayable, and fee) explicitly designed to help the borrower understand key terms before reading the full contract — this aligns with the requirement to communicate relevant information in a way that supports effective decision-making and gives an opportunity to review terms. There is no indication of conflicting or deficient practice in the excerpts relative to this summary approach.

### loan_agreement_3 / price_and_value (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7647
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `yes`: Excerpt [1] specifies that for consumer credit products firms must consider "all interest, fees and charges a consumer may incur" when assessing price and value, including charges arising from default/arrears.
  - `no`: The loan agreement's fair value assessment in clause 4.3 explicitly limits its scope to only the Arrangement Fee and interest under clause 3, and expressly excludes the default charges under clause 6 (whose amount is not even specified).
  - `no`: This is a gap: the fair value justification does not account for all costs a consumer may incur, as required by excerpt [1].
  - `partially`: Excerpt [3] similarly confirms that manufacturer firms must consider "all the costs and charges a consumer may" incur when considering price, reinforcing that omitting default charges from the fair value assessment is a shortfall.
  - `no`: While excerpt [5] notes value can be considered "in the round," this does not cure the failure to include default charges in the cost assessment.
  - `no`: Excerpt [2] and [4] address charging structures and distributor charges but do not directly resolve this issue.
  - `no`: Overall, the documented approach appears to fall short of the requirement to factor in all fees and charges, including default-related charges, into the fair value assessment.
- Full reasoning: Excerpt [1] specifies that for consumer credit products firms must consider "all interest, fees and charges a consumer may incur" when assessing price and value, including charges arising from default/arrears. The loan agreement's fair value assessment in clause 4.3 explicitly limits its scope to only the Arrangement Fee and interest under clause 3, and expressly excludes the default charges under clause 6 (whose amount is not even specified). This is a gap: the fair value justification does not account for all costs a consumer may incur, as required by excerpt [1]. Excerpt [3] similarly confirms that manufacturer firms must consider "all the costs and charges a consumer may" incur when considering price, reinforcing that omitting default charges from the fair value assessment is a shortfall. While excerpt [5] notes value can be considered "in the round," this does not cure the failure to include default charges in the cost assessment. Excerpt [2] and [4] address charging structures and distributor charges but do not directly resolve this issue. Overall, the documented approach appears to fall short of the requirement to factor in all fees and charges, including default-related charges, into the fair value assessment.

### loan_agreement_3 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7998
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause identifies a specific target market (consumers needing fixed-sum credit with defined instalments who can demonstrate affordability), describes an assessment of product features (fixed pricing, defined term, early repayment, vulnerable-customer support) against that target market's needs, and states periodic review including monitoring of distribution channels.
  - `yes`: This aligns with the Products and Services outcome expectations in the excerpts, which emphasise monitoring that distribution strategies are followed and that products are correctly distributed to the target market (Excerpt 1), and ensuring product design/coverage meets the needs of the target market (Excerpt 4).
  - `partially`: The document's approach of defining a target market, assessing features against it, and monitoring distribution matches these requirements.
- Full reasoning: The clause identifies a specific target market (consumers needing fixed-sum credit with defined instalments who can demonstrate affordability), describes an assessment of product features (fixed pricing, defined term, early repayment, vulnerable-customer support) against that target market's needs, and states periodic review including monitoring of distribution channels. This aligns with the Products and Services outcome expectations in the excerpts, which emphasise monitoring that distribution strategies are followed and that products are correctly distributed to the target market (Excerpt 1), and ensuring product design/coverage meets the needs of the target market (Excerpt 4). The document's approach of defining a target market, assessing features against it, and monitoring distribution matches these requirements.

### loan_agreement_3 / consumer_understanding (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7635
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `yes`: The retrieved excerpts establish that under the Consumer Understanding outcome, firms must communicate relevant information in a way that supports effective decision-making and provides consumers an appropriate opportunity to review information and assess their options (excerpt 3), with communications designed to be understood by consumers (excerpt 2) and to enable informed decisions (excerpt 1).
  - `no`: The loan agreement's "KEY FACTS AT A GLANCE" section, presenting loan amount, APR, term, monthly repayment, total repayable, and arrangement fee upfront before the full terms, directly supports this by giving the borrower key information in a clear, accessible format before engaging with more detailed contractual text.
  - `partially`: This practice aligns with the requirement to enable effective decision making and provide an opportunity to review key information, consistent with excerpt 3's standard.
- Full reasoning: The retrieved excerpts establish that under the Consumer Understanding outcome, firms must communicate relevant information in a way that supports effective decision-making and provides consumers an appropriate opportunity to review information and assess their options (excerpt 3), with communications designed to be understood by consumers (excerpt 2) and to enable informed decisions (excerpt 1). The loan agreement's "KEY FACTS AT A GLANCE" section, presenting loan amount, APR, term, monthly repayment, total repayable, and arrangement fee upfront before the full terms, directly supports this by giving the borrower key information in a clear, accessible format before engaging with more detailed contractual text. This practice aligns with the requirement to enable effective decision making and provide an opportunity to review key information, consistent with excerpt 3's standard.

### loan_agreement_4 / price_and_value (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7600
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: The excerpts establish that firms must be able to demonstrate that the total price paid for a product, including all interest, fees and charges (including default charges), represents fair value, and must actively assess and justify this (excerpts 2, 3, 5).
  - `partially`: The loan agreement clearly discloses the fees (arrangement fee, interest, default charges) but explicitly states that a fair value justification is "Not addressed in this document." This is a gap: the regulatory excerpts require firms to demonstrate/assess fair value of the total price, not merely disclose the fee structure.
  - `no`: Without any fair value assessment or justification, the document falls short of what the Consumer Duty price and value outcome requires.
- Full reasoning: The excerpts establish that firms must be able to demonstrate that the total price paid for a product, including all interest, fees and charges (including default charges), represents fair value, and must actively assess and justify this (excerpts 2, 3, 5). The loan agreement clearly discloses the fees (arrangement fee, interest, default charges) but explicitly states that a fair value justification is "Not addressed in this document." This is a gap: the regulatory excerpts require firms to demonstrate/assess fair value of the total price, not merely disclose the fee structure. Without any fair value assessment or justification, the document falls short of what the Consumer Duty price and value outcome requires.

### loan_agreement_4 / consumer_support (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7684
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause demonstrates the lender proactively acknowledges customers may be vulnerable (permanently or temporarily) due to a range of factors, invites disclosure in confidence, and commits to identifying appropriate support such as adjusted communication, extra time, and referral to debt advice.
  - `partially`: This aligns with the excerpts' expectations that firms address the needs of customers with characteristics of vulnerability (excerpt 4) and ensure support processes avoid foreseeable harm while enabling customers to pursue their financial objectives (excerpt 5), including offering effective support channels (excerpts 2-3).
  - `partially`: The clause's commitment to tailored support and referral to independent advice reflects the kind of proactive, harm-avoiding support processes described in the excerpts.
  - `no`: No conflicting requirement is evident in the retrieved text.
- Full reasoning: The clause demonstrates the lender proactively acknowledges customers may be vulnerable (permanently or temporarily) due to a range of factors, invites disclosure in confidence, and commits to identifying appropriate support such as adjusted communication, extra time, and referral to debt advice. This aligns with the excerpts' expectations that firms address the needs of customers with characteristics of vulnerability (excerpt 4) and ensure support processes avoid foreseeable harm while enabling customers to pursue their financial objectives (excerpt 5), including offering effective support channels (excerpts 2-3). The clause's commitment to tailored support and referral to independent advice reflects the kind of proactive, harm-avoiding support processes described in the excerpts. No conflicting requirement is evident in the retrieved text.

### loan_agreement_4 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7605
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause defines a clear target market (consumers wanting fixed-rate, fixed-term borrowing with evidenced affordability and no need for revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to likely good outcomes for that market, and states that the target market assessment is reviewed periodically with consideration of distribution channel impact.
  - `yes`: This addresses the core requirements highlighted in the excerpts: ensuring products are designed for and distributed to an appropriate target market, and monitoring that distribution strategies keep the product reaching that market (excerpts 2 and 3).
  - `partially`: While the excerpts are general guidance rather than exhaustive checklists, the clause's content aligns with the stated expectations of target market definition, review, and distribution oversight.
- Full reasoning: The clause defines a clear target market (consumers wanting fixed-rate, fixed-term borrowing with evidenced affordability and no need for revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to likely good outcomes for that market, and states that the target market assessment is reviewed periodically with consideration of distribution channel impact. This addresses the core requirements highlighted in the excerpts: ensuring products are designed for and distributed to an appropriate target market, and monitoring that distribution strategies keep the product reaching that market (excerpts 2 and 3). While the excerpts are general guidance rather than exhaustive checklists, the clause's content aligns with the stated expectations of target market definition, review, and distribution oversight.

### loan_agreement_5 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7770
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause defines a specific target market (consumers wanting fixed-rate, fixed-term borrowing of a known amount, able to evidence affordability of fixed instalments, not needing flexible/revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to likely good outcomes for that market, and states periodic review of the target market assessment plus consideration of distribution channel impact on reaching the intended market.
  - `yes`: This aligns with the products and services outcome's core requirements as reflected in the excerpts: harm arises where products are poorly designed or distributed to customers for whom they are not designed (excerpt 3), and firms should monitor distribution strategies to ensure products reach the target market (excerpt 2).
  - `partially`: The clause explicitly addresses both target market definition/rationale and distribution monitoring, matching what the guidance emphasizes.
- Full reasoning: The clause defines a specific target market (consumers wanting fixed-rate, fixed-term borrowing of a known amount, able to evidence affordability of fixed instalments, not needing flexible/revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to likely good outcomes for that market, and states periodic review of the target market assessment plus consideration of distribution channel impact on reaching the intended market. This aligns with the products and services outcome's core requirements as reflected in the excerpts: harm arises where products are poorly designed or distributed to customers for whom they are not designed (excerpt 3), and firms should monitor distribution strategies to ensure products reach the target market (excerpt 2). The clause explicitly addresses both target market definition/rationale and distribution monitoring, matching what the guidance emphasizes.

### loan_agreement_5 / consumer_understanding (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7700
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause provides an upfront "Key Facts at a Glance" summary covering the essential financial terms (loan amount, APR, term, monthly repayment, total repayable, fee), presented before the full terms and conditions.
  - `yes`: This aligns with the requirement in excerpt [2] that communications enable relevant information likely to be needed by retail customers in a way that supports effective decision making and provides an appropriate opportunity to review information before assessing options.
  - `partially`: It also matches the type of summary practice discussed in excerpt [4], where firms produce a summary of a product's main features to aid understanding.
  - `no`: There is no indication in the excerpts that such a summary is insufficient or that additional mandatory elements are missing, so on the basis of the retrieved text this approach appears consistent with the consumer understanding outcome.
- Full reasoning: The clause provides an upfront "Key Facts at a Glance" summary covering the essential financial terms (loan amount, APR, term, monthly repayment, total repayable, fee), presented before the full terms and conditions. This aligns with the requirement in excerpt [2] that communications enable relevant information likely to be needed by retail customers in a way that supports effective decision making and provides an appropriate opportunity to review information before assessing options. It also matches the type of summary practice discussed in excerpt [4], where firms produce a summary of a product's main features to aid understanding. There is no indication in the excerpts that such a summary is insufficient or that additional mandatory elements are missing, so on the basis of the retrieved text this approach appears consistent with the consumer understanding outcome.

### loan_agreement_6 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7720
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause defines a specific target market (consumers seeking fixed-rate, fixed-term personal loans of a known amount who can evidence affordability and do not need flexible/revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to the likelihood of good outcomes for that market, and states the Lender periodically reviews the target market assessment and considers the impact of distribution channels on ensuring the product reaches the intended market.
  - `partially`: This addresses the core requirements highlighted in the excerpts: avoiding harm from products distributed to customers for whom they are not designed (excerpt 3), monitoring that distribution strategies are followed and that products reach the target market (excerpt 2), and reviewing target market fit on an ongoing basis (excerpt 4 references ensuring coverage is sufficient to meet needs of the target market).
  - `partially`: While the excerpts are general guidance rather than prescriptive checklists, the clause's content aligns with what they describe as expected practice: identifying a target market, assessing outcomes for that market based on product design, and monitoring distribution to ensure alignment.
  - `no`: No conflict with the excerpts is evident.
- Full reasoning: The clause defines a specific target market (consumers seeking fixed-rate, fixed-term personal loans of a known amount who can evidence affordability and do not need flexible/revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to the likelihood of good outcomes for that market, and states the Lender periodically reviews the target market assessment and considers the impact of distribution channels on ensuring the product reaches the intended market. This addresses the core requirements highlighted in the excerpts: avoiding harm from products distributed to customers for whom they are not designed (excerpt 3), monitoring that distribution strategies are followed and that products reach the target market (excerpt 2), and reviewing target market fit on an ongoing basis (excerpt 4 references ensuring coverage is sufficient to meet needs of the target market). While the excerpts are general guidance rather than prescriptive checklists, the clause's content aligns with what they describe as expected practice: identifying a target market, assessing outcomes for that market based on product design, and monitoring distribution to ensure alignment. No conflict with the excerpts is evident.

### loan_agreement_7 / consumer_support (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.8072
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: The Consumer Duty requires firms to actively ensure the consumer support outcome — including providing effective support channels that enable customers to use their products and realise their benefits (excerpts 2, 3), and to design support processes with evidence-based review to avoid harm (excerpt 1).
  - `no`: The loan agreement does not address consumer support at all, meaning there is no evidence the firm has considered how it will support customers post-sale, handle queries, or ensure support channels are effective.
  - `partially`: This is a gap relative to the regulatory expectation that firms proactively address consumer support arrangements, rather than simply omitting the topic.
- Full reasoning: The Consumer Duty requires firms to actively ensure the consumer support outcome — including providing effective support channels that enable customers to use their products and realise their benefits (excerpts 2, 3), and to design support processes with evidence-based review to avoid harm (excerpt 1). The loan agreement does not address consumer support at all, meaning there is no evidence the firm has considered how it will support customers post-sale, handle queries, or ensure support channels are effective. This is a gap relative to the regulatory expectation that firms proactively address consumer support arrangements, rather than simply omitting the topic.

### loan_agreement_8 / consumer_support (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7825
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause merely states that customers in financial difficulty "may contact us to discuss their account" but gives no detail on how support will actually be delivered, whether the support channels are effective, or how the firm will identify and respond to signs of vulnerability or difficulty.
  - `yes`: The retrieved excerpts require firms to actively ensure that whatever support channels they offer are effective and enable customers to realise the benefits of their product and act in their interests (excerpt 1), and to monitor the support provided, take feedback into account, and watch for signs the offering is insufficient for customer needs (excerpt 3).
  - `partially`: Excerpt 2 frames consumer support as an outcome requiring firms to proactively support customers in using products/services, not just passively invite contact.
  - `partially`: The clause's generic, passive statement does not demonstrate any of the required proactive monitoring, effectiveness assurance, or tailored support for financially vulnerable customers, so it falls short of what the excerpts establish as necessary.
- Full reasoning: The clause merely states that customers in financial difficulty "may contact us to discuss their account" but gives no detail on how support will actually be delivered, whether the support channels are effective, or how the firm will identify and respond to signs of vulnerability or difficulty. The retrieved excerpts require firms to actively ensure that whatever support channels they offer are effective and enable customers to realise the benefits of their product and act in their interests (excerpt 1), and to monitor the support provided, take feedback into account, and watch for signs the offering is insufficient for customer needs (excerpt 3). Excerpt 2 frames consumer support as an outcome requiring firms to proactively support customers in using products/services, not just passively invite contact. The clause's generic, passive statement does not demonstrate any of the required proactive monitoring, effectiveness assurance, or tailored support for financially vulnerable customers, so it falls short of what the excerpts establish as necessary.

### loan_agreement_8 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7563
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause identifies a defined target market (consumers wanting a fixed-rate, fixed-term loan of known amount, able to evidence affordability, not needing flexible/revolving credit) and states the Lender has assessed that consumers with these characteristics are likely to achieve good outcomes given the product's fixed cost structure, defined term, and early repayment rights.
  - `yes`: This aligns with the products and services outcome's core requirement (excerpt 2) that firms design products for identified target markets and ensure products are not distributed to customers for whom they are not designed, avoiding harm from poor design or mis-distribution.
  - `no`: The clause's articulation of target market characteristics and a rationale for good outcomes is consistent with what the excerpts describe as the purpose of this outcome.
  - `no`: However, the excerpts do not provide granular detail on monitoring or ongoing review requirements (e.g., excerpt 3 on monitoring distribution), and the document excerpt provided does not describe monitoring - but since the specific outcome text under review only covers design/target market fit (clauses 7.1-7.2), and this matches the overview requirement in excerpt 2, it is judged compliant on the stated scope.
- Full reasoning: The clause identifies a defined target market (consumers wanting a fixed-rate, fixed-term loan of known amount, able to evidence affordability, not needing flexible/revolving credit) and states the Lender has assessed that consumers with these characteristics are likely to achieve good outcomes given the product's fixed cost structure, defined term, and early repayment rights. This aligns with the products and services outcome's core requirement (excerpt 2) that firms design products for identified target markets and ensure products are not distributed to customers for whom they are not designed, avoiding harm from poor design or mis-distribution. The clause's articulation of target market characteristics and a rationale for good outcomes is consistent with what the excerpts describe as the purpose of this outcome. However, the excerpts do not provide granular detail on monitoring or ongoing review requirements (e.g., excerpt 3 on monitoring distribution), and the document excerpt provided does not describe monitoring - but since the specific outcome text under review only covers design/target market fit (clauses 7.1-7.2), and this matches the overview requirement in excerpt 2, it is judged compliant on the stated scope.

### loan_agreement_8 / consumer_understanding (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7899
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `yes`: The excerpts require firms to communicate relevant information in a way that supports effective decision-making and enables retail customers to review information and assess options (Excerpt 4), and to help consumers understand the total price/costs of a product (Excerpt 2).
  - `no`: The "Key Facts at a Glance" section presents the core commercial terms (loan amount, APR, term, monthly repayment, total repayable, arrangement fee) upfront, before the full terms and conditions, explicitly to aid borrower understanding.
  - `yes`: This is consistent with the regulatory expectation of communications that support informed decision-making and give an appropriate opportunity to review key information before committing.
  - `partially`: While the excerpts also discuss more detailed guidance (e.g., mandatory summaries of features/risks in Excerpt 3), the clause as described aligns with the stated purpose of the consumer understanding outcome to present key terms clearly and prominently.
- Full reasoning: The excerpts require firms to communicate relevant information in a way that supports effective decision-making and enables retail customers to review information and assess options (Excerpt 4), and to help consumers understand the total price/costs of a product (Excerpt 2). The "Key Facts at a Glance" section presents the core commercial terms (loan amount, APR, term, monthly repayment, total repayable, arrangement fee) upfront, before the full terms and conditions, explicitly to aid borrower understanding. This is consistent with the regulatory expectation of communications that support informed decision-making and give an appropriate opportunity to review key information before committing. While the excerpts also discuss more detailed guidance (e.g., mandatory summaries of features/risks in Excerpt 3), the clause as described aligns with the stated purpose of the consumer understanding outcome to present key terms clearly and prominently.

### loan_agreement_9 / consumer_support (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.8226
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: Clause 9 narrowly restricts support for a revised payment arrangement to customers experiencing financial hardship due to loss of income, explicitly excluding other circumstances such as health conditions, bereavement, or reduced capability in managing financial matters.
  - `partially`: The Consumer Duty consumer support outcome requires firms to ensure support processes avoid causing foreseeable harm and enable all customers to pursue their financial objectives (excerpt 5), and to ensure support works effectively across relevant circumstances (excerpt 2, excerpt 1).
  - `partially`: By explicitly carving out customers in vulnerable circumstances (health conditions, bereavement, reduced capability) from access to a revised payment arrangement, the clause risks causing foreseeable harm to those excluded groups and fails to provide support that enables them to pursue their financial objectives, which conflicts with the overarching support obligations described in the retrieved excerpts.
  - `partially`: There is no indication in the excerpts that such a narrow, circumstance-specific exclusion is permitted; rather, the guidance suggests support should be broadly effective and harm-avoiding for customers in differing circumstances.
- Full reasoning: Clause 9 narrowly restricts support for a revised payment arrangement to customers experiencing financial hardship due to loss of income, explicitly excluding other circumstances such as health conditions, bereavement, or reduced capability in managing financial matters. The Consumer Duty consumer support outcome requires firms to ensure support processes avoid causing foreseeable harm and enable all customers to pursue their financial objectives (excerpt 5), and to ensure support works effectively across relevant circumstances (excerpt 2, excerpt 1). By explicitly carving out customers in vulnerable circumstances (health conditions, bereavement, reduced capability) from access to a revised payment arrangement, the clause risks causing foreseeable harm to those excluded groups and fails to provide support that enables them to pursue their financial objectives, which conflicts with the overarching support obligations described in the retrieved excerpts. There is no indication in the excerpts that such a narrow, circumstance-specific exclusion is permitted; rather, the guidance suggests support should be broadly effective and harm-avoiding for customers in differing circumstances.

### loan_agreement_9 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7776
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: Clause 7 identifies a defined target market (consumers wanting fixed-rate, fixed-term borrowing with evidenced affordability who do not need flexible/revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to likely good outcomes for that market, and states the Lender periodically reviews the target market assessment and considers the impact of distribution channels on reaching the intended market.
  - `yes`: This addresses the core requirements suggested by the excerpts: avoiding harm from products distributed to customers for whom they are not designed (excerpt 1), and monitoring that distribution strategies are followed so products reach the target market (excerpt 2).
  - `partially`: The clause's inclusion of periodic review and distribution channel oversight aligns with these expectations, so the stated approach is consistent with what the excerpts establish as required.
- Full reasoning: Clause 7 identifies a defined target market (consumers wanting fixed-rate, fixed-term borrowing with evidenced affordability who do not need flexible/revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to likely good outcomes for that market, and states the Lender periodically reviews the target market assessment and considers the impact of distribution channels on reaching the intended market. This addresses the core requirements suggested by the excerpts: avoiding harm from products distributed to customers for whom they are not designed (excerpt 1), and monitoring that distribution strategies are followed so products reach the target market (excerpt 2). The clause's inclusion of periodic review and distribution channel oversight aligns with these expectations, so the stated approach is consistent with what the excerpts establish as required.

### loan_agreement_9 / consumer_understanding (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7834
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `yes`: The excerpts require firms' communications to support consumer understanding by enabling communication of relevant information retail customers are likely to need in a way that supports effective decision-making, and providing an appropriate opportunity to review information and assess options (excerpt 4).
  - `no`: The "Key Facts at a Glance" section presents the essential commercial terms (loan amount, APR, term, monthly repayment, total repayable, arrangement fee) upfront before the full terms, which is designed to help the borrower grasp key information before engaging with more detailed contractual text.
  - `yes`: This aligns with the general aim in excerpt 1 that communications should support and enable consumers to make informed decisions, and the guidance in excerpts 2-3 that firms have discretion in producing summaries of products including main features, provided the explanations are likely to be understood by the target audience.
  - `no`: The clause's stated purpose - to help the borrower understand key terms before reading full terms and conditions - is consistent with this approach.
- Full reasoning: The excerpts require firms' communications to support consumer understanding by enabling communication of relevant information retail customers are likely to need in a way that supports effective decision-making, and providing an appropriate opportunity to review information and assess options (excerpt 4). The "Key Facts at a Glance" section presents the essential commercial terms (loan amount, APR, term, monthly repayment, total repayable, arrangement fee) upfront before the full terms, which is designed to help the borrower grasp key information before engaging with more detailed contractual text. This aligns with the general aim in excerpt 1 that communications should support and enable consumers to make informed decisions, and the guidance in excerpts 2-3 that firms have discretion in producing summaries of products including main features, provided the explanations are likely to be understood by the target audience. The clause's stated purpose - to help the borrower understand key terms before reading full terms and conditions - is consistent with this approach.

### loan_agreement_10 / price_and_value (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7577
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: The retrieved excerpts establish that firms must consider all costs and charges a consumer may incur (including interest, fees, and charges relating to arrears/default) when assessing price and value (excerpt 4), must consider all costs consumers may bear (excerpt 2), and should assess value "in the round," including benefits/features of the product (excerpt 3).
  - `partially`: The loan agreement's clause 4.3 fair value justification explicitly considers the total cost of credit (arrangement fee plus interest), the costs of providing the loan, the benefits and flexibility offered (early repayment right), and comparable market pricing — this aligns with the "in the round" holistic assessment required by excerpt 3, and the transparent disclosure of fees (arrangement fee, interest, default charges) matches the requirement in excerpt 4 to consider all interest, fees and charges including those from arrears/default.
  - `no`: The document also states the assessment is reviewed periodically, consistent with an ongoing fair value assessment approach.
  - `no`: No conflicting requirement is shown in the excerpts that the document fails to meet.
- Full reasoning: The retrieved excerpts establish that firms must consider all costs and charges a consumer may incur (including interest, fees, and charges relating to arrears/default) when assessing price and value (excerpt 4), must consider all costs consumers may bear (excerpt 2), and should assess value "in the round," including benefits/features of the product (excerpt 3). The loan agreement's clause 4.3 fair value justification explicitly considers the total cost of credit (arrangement fee plus interest), the costs of providing the loan, the benefits and flexibility offered (early repayment right), and comparable market pricing — this aligns with the "in the round" holistic assessment required by excerpt 3, and the transparent disclosure of fees (arrangement fee, interest, default charges) matches the requirement in excerpt 4 to consider all interest, fees and charges including those from arrears/default. The document also states the assessment is reviewed periodically, consistent with an ongoing fair value assessment approach. No conflicting requirement is shown in the excerpts that the document fails to meet.

### loan_agreement_10 / consumer_support (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7642
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: Clause 8 addresses recognition of vulnerable customers, encourages disclosure of vulnerability, and commits to identifying appropriate support (adjusted communications, extra time, referral to debt advice) — consistent with FG22/5's guidance that firms should ensure support processes avoid foreseeable harm and enable customers with characteristics of vulnerability to pursue their objectives (excerpt 5), and that firms should reference existing vulnerability guidance (excerpt 4).
  - `no`: The clause also clarifies that contacting the Lender does not affect obligations, which aligns with the intent of not penalizing customers for seeking support.
  - `no`: While the excerpts do not provide granular detail on monitoring support channel effectiveness (excerpts 2-3), the core Consumer Support expectations around vulnerability recognition and tailored assistance are met by the clause's stated approach.
- Full reasoning: Clause 8 addresses recognition of vulnerable customers, encourages disclosure of vulnerability, and commits to identifying appropriate support (adjusted communications, extra time, referral to debt advice) — consistent with FG22/5's guidance that firms should ensure support processes avoid foreseeable harm and enable customers with characteristics of vulnerability to pursue their objectives (excerpt 5), and that firms should reference existing vulnerability guidance (excerpt 4). The clause also clarifies that contacting the Lender does not affect obligations, which aligns with the intent of not penalizing customers for seeking support. While the excerpts do not provide granular detail on monitoring support channel effectiveness (excerpts 2-3), the core Consumer Support expectations around vulnerability recognition and tailored assistance are met by the clause's stated approach.

### loan_agreement_10 / products_and_services (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7824
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `yes`: The retrieved excerpts establish that firms must ensure products and services are fit for purpose, designed to meet the needs, characteristics and objectives of an identified target market, and distributed appropriately to that target market, with ongoing monitoring of distribution strategies (excerpts 2, 4, 1).
  - `partially`: This is a substantive requirement under the Products and Services outcome of the Consumer Duty.
  - `no`: The loan agreement does not address this topic at all, stating "Not addressed in this document." Since the regulatory excerpts show this is a required consideration for firms, the complete absence of any statement on target market fit, product design suitability, or distribution monitoring represents a gap against the Consumer Duty requirements, not merely a lack of retrieved evidence.
- Full reasoning: The retrieved excerpts establish that firms must ensure products and services are fit for purpose, designed to meet the needs, characteristics and objectives of an identified target market, and distributed appropriately to that target market, with ongoing monitoring of distribution strategies (excerpts 2, 4, 1). This is a substantive requirement under the Products and Services outcome of the Consumer Duty. The loan agreement does not address this topic at all, stating "Not addressed in this document." Since the regulatory excerpts show this is a required consideration for firms, the complete absence of any statement on target market fit, product design suitability, or distribution monitoring represents a gap against the Consumer Duty requirements, not merely a lack of retrieved evidence.

### loan_agreement_10 / consumer_understanding (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7712
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `yes`: The Consumer Duty's consumer understanding outcome requires firms to communicate in a way that supports effective decision-making and enables consumers to grasp key information likely needed before committing (excerpts 1, 5).
  - `yes`: PRIN 2A specifically emphasizes communications should enable understanding of relevant information and provide opportunity to review it (excerpt 5).
  - `no`: The loan agreement's "Key Facts at a Glance" section presents the essential terms (loan amount, APR, term, monthly repayment, total repayable, arrangement fee) in a clear, upfront summary explicitly designed to help the borrower understand key terms before reviewing the full agreement.
  - `partially`: This proactive, plain-language summary aligns with the outcome's goal of supporting informed decision-making and giving consumers an accessible entry point to the fuller terms, consistent with the guidance excerpts on ensuring explanations are likely to be understood and providing appropriate summaries of products' main features.
- Full reasoning: The Consumer Duty's consumer understanding outcome requires firms to communicate in a way that supports effective decision-making and enables consumers to grasp key information likely needed before committing (excerpts 1, 5). PRIN 2A specifically emphasizes communications should enable understanding of relevant information and provide opportunity to review it (excerpt 5). The loan agreement's "Key Facts at a Glance" section presents the essential terms (loan amount, APR, term, monthly repayment, total repayable, arrangement fee) in a clear, upfront summary explicitly designed to help the borrower understand key terms before reviewing the full agreement. This proactive, plain-language summary aligns with the outcome's goal of supporting informed decision-making and giving consumers an accessible entry point to the fuller terms, consistent with the guidance excerpts on ensuring explanations are likely to be understood and providing appropriate summaries of products' main features.

### loan_agreement_11 / consumer_support (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7625
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause proactively addresses vulnerability, encourages disclosure in confidence, and commits the Lender to identify appropriate support (adjusted communication, additional time, referral to debt advice).
  - `partially`: This aligns with the retrieved excerpts' emphasis on firms ensuring support processes avoid foreseeable harm and enable customers to pursue their financial objectives (excerpt 5), and the general Consumer Duty expectation of tailored treatment for vulnerable customers referenced in excerpt 4 (referencing FG21/1 guidance on vulnerable customers).
  - `partially`: While the excerpts are largely about channel support (excerpts 2-3) and representatives (excerpt 1), the clause's substance—identifying vulnerability, offering flexible support routes, and clarifying that disclosure does not waive obligations—reflects the spirit of enabling customers to realise product benefits and avoid harm as described in excerpt 5.
  - `no`: No specific contradiction is evident.
- Full reasoning: The clause proactively addresses vulnerability, encourages disclosure in confidence, and commits the Lender to identify appropriate support (adjusted communication, additional time, referral to debt advice). This aligns with the retrieved excerpts' emphasis on firms ensuring support processes avoid foreseeable harm and enable customers to pursue their financial objectives (excerpt 5), and the general Consumer Duty expectation of tailored treatment for vulnerable customers referenced in excerpt 4 (referencing FG21/1 guidance on vulnerable customers). While the excerpts are largely about channel support (excerpts 2-3) and representatives (excerpt 1), the clause's substance—identifying vulnerability, offering flexible support routes, and clarifying that disclosure does not waive obligations—reflects the spirit of enabling customers to realise product benefits and avoid harm as described in excerpt 5. No specific contradiction is evident.

### loan_agreement_11 / products_and_services (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7673
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: The excerpts require firms to ensure products are designed to meet the needs of an identified target market and that products are correctly distributed to that target market, with monitoring of distribution strategies (excerpts 2, 3).
  - `no`: Here, the document's own target market assessment describes a revolving, variable-drawdown credit product, while the Agreement itself is explicitly a fixed-sum, fixed-term loan.
  - `no`: This internal inconsistency indicates that the target market assessment does not actually correspond to the product being sold to the Borrower, meaning the firm cannot demonstrate the product was designed for, and distributed to, consumers whose needs match the actual product features.
  - `partially`: This is a clear gap in meeting the products and services outcome's requirement for accurate identification and monitoring of the target market relative to the actual product.
- Full reasoning: The excerpts require firms to ensure products are designed to meet the needs of an identified target market and that products are correctly distributed to that target market, with monitoring of distribution strategies (excerpts 2, 3). Here, the document's own target market assessment describes a revolving, variable-drawdown credit product, while the Agreement itself is explicitly a fixed-sum, fixed-term loan. This internal inconsistency indicates that the target market assessment does not actually correspond to the product being sold to the Borrower, meaning the firm cannot demonstrate the product was designed for, and distributed to, consumers whose needs match the actual product features. This is a clear gap in meeting the products and services outcome's requirement for accurate identification and monitoring of the target market relative to the actual product.

### loan_agreement_12 / consumer_support (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7732
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: The excerpts establish that firms must have processes to identify and support customers in vulnerable circumstances, ensure support channels are effective, monitor support provided, and avoid foreseeable harm in enabling customers to pursue their financial objectives (excerpts 2, 3, 5).
  - `yes`: Excerpt 4 also notes firms should refer to prior guidance (FG21/1) where Duty rules reference customers in vulnerable circumstances.
  - `no`: The loan agreement clause addresses this by explicitly recognising vulnerability (with examples consistent with regulatory framing), inviting disclosure in confidence, and committing to work with the borrower on tailored support (adjusted communication, additional time, referral to debt advice).
  - `yes`: This aligns with the excerpts' emphasis on effective, tailored support and avoiding harm.
  - `no`: The clause also clarifies that contacting the lender does not affect obligations but may affect options in payment difficulty, which is a reasonable and transparent disclosure.
  - `partially`: No specific requirement in the excerpts is contradicted or omitted here — the clause reflects a proactive, supportive approach consistent with the retrieved guidance on identifying vulnerability and providing effective support.
- Full reasoning: The excerpts establish that firms must have processes to identify and support customers in vulnerable circumstances, ensure support channels are effective, monitor support provided, and avoid foreseeable harm in enabling customers to pursue their financial objectives (excerpts 2, 3, 5). Excerpt 4 also notes firms should refer to prior guidance (FG21/1) where Duty rules reference customers in vulnerable circumstances. The loan agreement clause addresses this by explicitly recognising vulnerability (with examples consistent with regulatory framing), inviting disclosure in confidence, and committing to work with the borrower on tailored support (adjusted communication, additional time, referral to debt advice). This aligns with the excerpts' emphasis on effective, tailored support and avoiding harm. The clause also clarifies that contacting the lender does not affect obligations but may affect options in payment difficulty, which is a reasonable and transparent disclosure. No specific requirement in the excerpts is contradicted or omitted here — the clause reflects a proactive, supportive approach consistent with the retrieved guidance on identifying vulnerability and providing effective support.

### loan_agreement_12 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7710
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause defines a target market (fixed-rate, fixed-term borrowers with evidenced affordability who do not need revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to why this target market is likely to achieve good outcomes, and states that the Lender periodically reviews the target market assessment and considers the impact of distribution channels on ensuring the product reaches the intended market.
  - `yes`: This aligns with the excerpts' emphasis on the products and services outcome requiring firms to design products for identified target markets, monitor distribution strategies to ensure products reach that target market (excerpt 2), and avoid harm from products distributed to customers for whom they are not designed (excerpt 3).
  - `partially`: The clause's explicit inclusion of periodic review and distribution channel oversight addresses the monitoring expectations described in excerpt 2.
- Full reasoning: The clause defines a target market (fixed-rate, fixed-term borrowers with evidenced affordability who do not need revolving credit), links product features (fixed cost structure, defined term, early repayment rights) to why this target market is likely to achieve good outcomes, and states that the Lender periodically reviews the target market assessment and considers the impact of distribution channels on ensuring the product reaches the intended market. This aligns with the excerpts' emphasis on the products and services outcome requiring firms to design products for identified target markets, monitor distribution strategies to ensure products reach that target market (excerpt 2), and avoid harm from products distributed to customers for whom they are not designed (excerpt 3). The clause's explicit inclusion of periodic review and distribution channel oversight addresses the monitoring expectations described in excerpt 2.

### loan_agreement_12 / consumer_understanding (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7988
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `yes`: The retrieved excerpts establish that under the Consumer Understanding outcome, firms must ensure their communications support and enable consumers to make informed decisions, be understandable, and be tailored where appropriate, including one-to-one communications (excerpts 1, 2, 3, 4).
  - `no`: The loan agreement explicitly states this topic is "Not addressed in this document," meaning there is no evidence of any communication strategy, tailoring approach, or comprehension support for consumers.
  - `no`: Since the regulation requires affirmative measures to ensure consumer understanding and the document contains none, this constitutes a gap rather than a case of insufficient regulatory detail.
- Full reasoning: The retrieved excerpts establish that under the Consumer Understanding outcome, firms must ensure their communications support and enable consumers to make informed decisions, be understandable, and be tailored where appropriate, including one-to-one communications (excerpts 1, 2, 3, 4). The loan agreement explicitly states this topic is "Not addressed in this document," meaning there is no evidence of any communication strategy, tailoring approach, or comprehension support for consumers. Since the regulation requires affirmative measures to ensure consumer understanding and the document contains none, this constitutes a gap rather than a case of insufficient regulatory detail.

### loan_agreement_13 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7923
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause defines a target market (consumers wanting fixed-rate, fixed-term borrowing for a known amount, able to evidence affordability, not needing revolving credit), links product features (fixed cost, defined term, early repayment rights) to likely good outcomes for that market, and states the firm periodically reviews the target market assessment and considers distribution channel impact on reaching the intended market.
  - `yes`: This aligns with the products and services outcome's core requirements as reflected in excerpt [2], which frames harm as arising from poor product design or distribution to customers for whom products were not designed, and excerpt [3], which highlights the need for firms to monitor distribution strategies and ensure correct targeting.
  - `partially`: The clause's inclusion of periodic review and distribution channel monitoring directly addresses the type of ongoing oversight referenced in [3].
  - `no`: No conflicting requirement is evidenced in the excerpts.
- Full reasoning: The clause defines a target market (consumers wanting fixed-rate, fixed-term borrowing for a known amount, able to evidence affordability, not needing revolving credit), links product features (fixed cost, defined term, early repayment rights) to likely good outcomes for that market, and states the firm periodically reviews the target market assessment and considers distribution channel impact on reaching the intended market. This aligns with the products and services outcome's core requirements as reflected in excerpt [2], which frames harm as arising from poor product design or distribution to customers for whom products were not designed, and excerpt [3], which highlights the need for firms to monitor distribution strategies and ensure correct targeting. The clause's inclusion of periodic review and distribution channel monitoring directly addresses the type of ongoing oversight referenced in [3]. No conflicting requirement is evidenced in the excerpts.

### loan_agreement_13 / consumer_understanding (llm_status: potentially_non_compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.8152
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `yes`: The Consumer Duty's consumer understanding outcome requires firms to ensure communications support and enable consumers to make informed decisions, are tailored appropriately (including one-to-one communications), and that explanations of products/risks are likely to be understood by consumers (excerpts 1-4).
  - `no`: The loan agreement explicitly states this topic is "Not addressed in this document," meaning it fails to demonstrate any approach to ensuring consumer understanding of the loan terms, risks, or features.
  - `partially`: This is a clear gap against the regulatory requirement to design and deliver communications that support informed decision-making, as established in the excerpts.
- Full reasoning: The Consumer Duty's consumer understanding outcome requires firms to ensure communications support and enable consumers to make informed decisions, are tailored appropriately (including one-to-one communications), and that explanations of products/risks are likely to be understood by consumers (excerpts 1-4). The loan agreement explicitly states this topic is "Not addressed in this document," meaning it fails to demonstrate any approach to ensuring consumer understanding of the loan terms, risks, or features. This is a clear gap against the regulatory requirement to design and deliver communications that support informed decision-making, as established in the excerpts.

### loan_agreement_14 / consumer_support (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7595
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: The clause addresses key elements expected for consumer support around vulnerability: it commits to identifying and responding to vulnerable customers' needs (aligning with PRIN 2A guidance at excerpt 5 requiring firms to pay appropriate regard to characteristics of vulnerability), allows customers to disclose circumstances via multiple channels, treats information confidentially, offers tailored support (extended decision time, alternative formats, dedicated contact, signposting to free debt advice), and trains frontline staff to recognise vulnerability signs.
  - `yes`: This is consistent with the general direction in the excerpts that firms should monitor support channels to ensure they meet customer needs (excerpt 1) and pay attention to characteristics of vulnerability in the target market (excerpt 5).
  - `no`: No conflicting or missing element is evident from the retrieved excerpts.
- Full reasoning: The clause addresses key elements expected for consumer support around vulnerability: it commits to identifying and responding to vulnerable customers' needs (aligning with PRIN 2A guidance at excerpt 5 requiring firms to pay appropriate regard to characteristics of vulnerability), allows customers to disclose circumstances via multiple channels, treats information confidentially, offers tailored support (extended decision time, alternative formats, dedicated contact, signposting to free debt advice), and trains frontline staff to recognise vulnerability signs. This is consistent with the general direction in the excerpts that firms should monitor support channels to ensure they meet customer needs (excerpt 1) and pay attention to characteristics of vulnerability in the target market (excerpt 5). No conflicting or missing element is evident from the retrieved excerpts.

### loan_agreement_14 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7896
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `partially`: The excerpts establish that firms must define a target market, ensure product features meet that market's needs, and monitor distribution channels to confirm products reach the intended target market, including periodic review of these strategies (excerpts 1 and 4).
  - `no`: The loan agreement's clause addresses each of these elements: it defines the target market (consumers needing a fixed sum repayable by fixed instalments who can evidence affordability), states that the Lender has assessed the product's features (fixed pricing, defined term, early repayment and vulnerable-customer support) as consistent with that market's needs, and confirms periodic review including monitoring of distribution channels — directly mirroring the monitoring expectation in excerpt 1 ('How is the firm monitoring that distribution strategies are being followed and that products and services are being correctly distributed to the target market?').
  - `yes`: This aligns with the overview concern in excerpt 4 about harm from poor design or misdistribution.
  - `no`: No conflicting requirement is evident in the retrieved text.
- Full reasoning: The excerpts establish that firms must define a target market, ensure product features meet that market's needs, and monitor distribution channels to confirm products reach the intended target market, including periodic review of these strategies (excerpts 1 and 4). The loan agreement's clause addresses each of these elements: it defines the target market (consumers needing a fixed sum repayable by fixed instalments who can evidence affordability), states that the Lender has assessed the product's features (fixed pricing, defined term, early repayment and vulnerable-customer support) as consistent with that market's needs, and confirms periodic review including monitoring of distribution channels — directly mirroring the monitoring expectation in excerpt 1 ('How is the firm monitoring that distribution strategies are being followed and that products and services are being correctly distributed to the target market?'). This aligns with the overview concern in excerpt 4 about harm from poor design or misdistribution. No conflicting requirement is evident in the retrieved text.

### loan_agreement_15 / consumer_support (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.8052
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause establishes a mechanism for members to disclose vulnerability circumstances (health condition, bereavement, changed circumstances, financial shock, reduced confidence) and commits the Lender to work with the member to agree suitable support (extra time, alternative communication methods, referral to free debt advice).
  - `no`: It also clarifies that disclosure does not alter obligations but may open further support options if payment difficulty arises.
  - `partially`: This aligns with the Consumer Support outcome's focus on ensuring consumers can use products effectively and that support is tailored to consumer needs, including those in vulnerable circumstances (excerpt 1 on the overview of consumer support, and excerpt 5 referencing Duty rules on customers in vulnerable circumstances).
  - `partially`: The clause reflects a proactive, flexible support approach consistent with the guidance's emphasis on effective, needs-responsive support channels (excerpts 3 and 4 on ensuring support works effectively and monitoring for sufficiency).
  - `no`: No specific gap is evident from the retrieved excerpts relative to what the clause provides.
- Full reasoning: The clause establishes a mechanism for members to disclose vulnerability circumstances (health condition, bereavement, changed circumstances, financial shock, reduced confidence) and commits the Lender to work with the member to agree suitable support (extra time, alternative communication methods, referral to free debt advice). It also clarifies that disclosure does not alter obligations but may open further support options if payment difficulty arises. This aligns with the Consumer Support outcome's focus on ensuring consumers can use products effectively and that support is tailored to consumer needs, including those in vulnerable circumstances (excerpt 1 on the overview of consumer support, and excerpt 5 referencing Duty rules on customers in vulnerable circumstances). The clause reflects a proactive, flexible support approach consistent with the guidance's emphasis on effective, needs-responsive support channels (excerpts 3 and 4 on ensuring support works effectively and monitoring for sufficiency). No specific gap is evident from the retrieved excerpts relative to what the clause provides.

### loan_agreement_15 / products_and_services (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7575
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `no`: The clause defines a target market (borrowers wanting a fixed amount repaid in fixed instalments who can demonstrate affordability alongside other outgoings), and states the lender checks that customers taking the product match this target market, reviews that check regularly, and monitors distribution across its various channels.
  - `yes`: This aligns with the Products and Services outcome requirements described in the excerpts: firms should design products to meet the needs of an identified target market, avoid distribution to those for whom the product is not designed (excerpt 3), and monitor that distribution strategies are followed and that products reach the correct target market through ongoing data and oversight (excerpt 1).
  - `no`: The clause's combination of target-market definition, affordability-linked eligibility check, periodic review, and distribution monitoring directly mirrors these expectations.
- Full reasoning: The clause defines a target market (borrowers wanting a fixed amount repaid in fixed instalments who can demonstrate affordability alongside other outgoings), and states the lender checks that customers taking the product match this target market, reviews that check regularly, and monitors distribution across its various channels. This aligns with the Products and Services outcome requirements described in the excerpts: firms should design products to meet the needs of an identified target market, avoid distribution to those for whom the product is not designed (excerpt 3), and monitor that distribution strategies are followed and that products reach the correct target market through ongoing data and oversight (excerpt 1). The clause's combination of target-market definition, affordability-linked eligibility check, periodic review, and distribution monitoring directly mirrors these expectations.

### loan_agreement_15 / consumer_understanding (llm_status: compliant)

- Signal 1 (max embedding similarity to retrieved sources): 0.7545
- Signal 2 bucket: flagged
- Per-claim verdicts:
  - `yes`: The excerpts establish that under the Consumer Understanding outcome, firms should support consumers in making informed decisions by ensuring key information is presented clearly and is likely to be understood (excerpt 1, 5), and that firms have discretion in producing summaries of products' main features (excerpt 2).
  - `no`: The "YOUR LOAN AT A GLANCE" section provides a clear, upfront summary of the key terms (loan amount, APR, term, monthly payment, total repayable, and fees) separated from the dense numbered clauses, explicitly designed to help consumers see key terms before reading the full agreement.
  - `partially`: This approach aligns with the guidance's emphasis on clear, accessible summaries of essential product features to support informed decision-making.
  - `no`: While the excerpts don't provide granular detail on formatting requirements, the described approach reflects the spirit of the requirement for clear communication and easily digestible key terms.
- Full reasoning: The excerpts establish that under the Consumer Understanding outcome, firms should support consumers in making informed decisions by ensuring key information is presented clearly and is likely to be understood (excerpt 1, 5), and that firms have discretion in producing summaries of products' main features (excerpt 2). The "YOUR LOAN AT A GLANCE" section provides a clear, upfront summary of the key terms (loan amount, APR, term, monthly payment, total repayable, and fees) separated from the dense numbered clauses, explicitly designed to help consumers see key terms before reading the full agreement. This approach aligns with the guidance's emphasis on clear, accessible summaries of essential product features to support informed decision-making. While the excerpts don't provide granular detail on formatting requirements, the described approach reflects the spirit of the requirement for clear communication and easily digestible key terms.

## All in-scope judgments

| doc_id | outcome | llm_status | signal1 | signal2 | agreement |
|---|---|---|---|---|---|
| loan_agreement_1 | price_and_value | potentially_non_compliant | 0.7986 | partial | disagreement |
| loan_agreement_1 | consumer_support | compliant | 0.8160 | flagged | disagreement |
| loan_agreement_1 | products_and_services | compliant | 0.7709 | flagged | disagreement |
| loan_agreement_1 | consumer_understanding | compliant | 0.7228 | flagged | agree_flagged |
| loan_agreement_2 | consumer_support | potentially_non_compliant | 0.8033 | flagged | disagreement |
| loan_agreement_2 | products_and_services | compliant | 0.7723 | flagged | disagreement |
| loan_agreement_2 | consumer_understanding | compliant | 0.7568 | flagged | disagreement |
| loan_agreement_3 | price_and_value | potentially_non_compliant | 0.7647 | flagged | disagreement |
| loan_agreement_3 | consumer_support | compliant | 0.7390 | flagged | agree_flagged |
| loan_agreement_3 | products_and_services | compliant | 0.7998 | flagged | disagreement |
| loan_agreement_3 | consumer_understanding | compliant | 0.7635 | flagged | disagreement |
| loan_agreement_4 | price_and_value | potentially_non_compliant | 0.7600 | flagged | disagreement |
| loan_agreement_4 | consumer_support | compliant | 0.7684 | flagged | disagreement |
| loan_agreement_4 | products_and_services | compliant | 0.7605 | flagged | disagreement |
| loan_agreement_4 | consumer_understanding | compliant | 0.7392 | flagged | agree_flagged |
| loan_agreement_5 | consumer_support | compliant | 0.7354 | flagged | agree_flagged |
| loan_agreement_5 | products_and_services | compliant | 0.7770 | flagged | disagreement |
| loan_agreement_5 | consumer_understanding | compliant | 0.7700 | flagged | disagreement |
| loan_agreement_6 | price_and_value | potentially_non_compliant | 0.7449 | flagged | agree_flagged |
| loan_agreement_6 | products_and_services | compliant | 0.7720 | flagged | disagreement |
| loan_agreement_6 | consumer_understanding | potentially_non_compliant | 0.7391 | flagged | agree_flagged |
| loan_agreement_7 | consumer_support | potentially_non_compliant | 0.8072 | flagged | disagreement |
| loan_agreement_7 | consumer_understanding | compliant | 0.7272 | flagged | agree_flagged |
| loan_agreement_8 | consumer_support | potentially_non_compliant | 0.7825 | flagged | disagreement |
| loan_agreement_8 | products_and_services | compliant | 0.7563 | flagged | disagreement |
| loan_agreement_8 | consumer_understanding | compliant | 0.7899 | flagged | disagreement |
| loan_agreement_9 | consumer_support | potentially_non_compliant | 0.8226 | flagged | disagreement |
| loan_agreement_9 | products_and_services | compliant | 0.7776 | flagged | disagreement |
| loan_agreement_9 | consumer_understanding | compliant | 0.7834 | flagged | disagreement |
| loan_agreement_10 | price_and_value | compliant | 0.7577 | flagged | disagreement |
| loan_agreement_10 | consumer_support | compliant | 0.7642 | flagged | disagreement |
| loan_agreement_10 | products_and_services | potentially_non_compliant | 0.7824 | flagged | disagreement |
| loan_agreement_10 | consumer_understanding | compliant | 0.7712 | flagged | disagreement |
| loan_agreement_11 | price_and_value | compliant | 0.7343 | flagged | agree_flagged |
| loan_agreement_11 | consumer_support | compliant | 0.7625 | flagged | disagreement |
| loan_agreement_11 | products_and_services | potentially_non_compliant | 0.7673 | flagged | disagreement |
| loan_agreement_11 | consumer_understanding | compliant | 0.7420 | flagged | agree_flagged |
| loan_agreement_12 | consumer_support | compliant | 0.7732 | flagged | disagreement |
| loan_agreement_12 | products_and_services | compliant | 0.7710 | flagged | disagreement |
| loan_agreement_12 | consumer_understanding | potentially_non_compliant | 0.7988 | flagged | disagreement |
| loan_agreement_13 | price_and_value | compliant | 0.7325 | flagged | agree_flagged |
| loan_agreement_13 | consumer_support | compliant | 0.7383 | flagged | agree_flagged |
| loan_agreement_13 | products_and_services | compliant | 0.7923 | flagged | disagreement |
| loan_agreement_13 | consumer_understanding | potentially_non_compliant | 0.8152 | flagged | disagreement |
| loan_agreement_14 | price_and_value | compliant | 0.7287 | flagged | agree_flagged |
| loan_agreement_14 | consumer_support | compliant | 0.7595 | flagged | disagreement |
| loan_agreement_14 | products_and_services | compliant | 0.7896 | flagged | disagreement |
| loan_agreement_14 | consumer_understanding | compliant | 0.7186 | flagged | agree_flagged |
| loan_agreement_15 | consumer_support | compliant | 0.8052 | flagged | disagreement |
| loan_agreement_15 | products_and_services | compliant | 0.7575 | flagged | disagreement |
| loan_agreement_15 | consumer_understanding | compliant | 0.7545 | flagged | disagreement |
