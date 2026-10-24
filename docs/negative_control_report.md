# Negative control: results

Scored against `docs/negative_control_criteria.md` (criteria and addendum written before any call).

## LLM-only (the result the pass criteria apply to)

Rejected = `no`; accepted = `yes`; `partially` is neither.

| Group | Required | Met | yes | partially | no | Result |
|---|---|---|---|---|---|---|
| unrelated | no >= 10/10 | 9/10 | 0 | 1 | 9 | FAIL |
| neighbouring | no >= 7/10 | 10/10 | 0 | 0 | 10 | PASS |
| positive | yes >= 9/10 | 10/10 | 10 | 0 | 0 | PASS |

**LLM-only overall: FAIL**

## Combined gate: quote found AND LLM yes (for information)

Accepted = quote found AND `yes`; rejected = quote not found OR `no`; neither = quote found AND `partially`. Every wrong chunk was selected so that the quote is absent, so this gate rejects every negative pair by construction: its negative rows show what the quote check adds, not the LLM.

| Group | Required | Met | accepted | neither | rejected | Result |
|---|---|---|---|---|---|---|
| unrelated | rejected >= 10/10 | 10/10 | 0 | 0 | 10 | PASS |
| neighbouring | rejected >= 7/10 | 10/10 | 0 | 0 | 10 | PASS |
| positive | accepted >= 9/10 | 10/10 | 10 | 0 | 0 | PASS |

**Combined gate overall: PASS**

## Checker failures (negative pairs marked `yes`)

Annotation = the user's reading of whether the wrong chunk supports the claim in its own words. It never changes any count or result above.

None.

## Every pair

- **U01** (unrelated; loan_agreement_13 run 1 / price_and_value) -> LLM `no` | quote found: False | gate: rejected | chunk: retrieved for consumer_support in the same row
  - claim: Firms must demonstrate that the total price paid for the product, including fees and charges, represents fair value.
- **U02** (unrelated; loan_agreement_5 run 1 / consumer_support) -> LLM `partially` | quote found: False | gate: rejected | chunk: retrieved for consumer_understanding in the same row
  - claim: Firms must design and deliver support that meets the needs of customers, including those with characteristics of vulnerability.
  - supporting sentence given: '(1) the characteristics of retail customers, including any characteristics of\nvulnerability;'
- **U03** (unrelated; loan_agreement_15 run 0 / products_and_services) -> LLM `no` | quote found: False | gate: rejected | chunk: retrieved for price_and_value in the same row
  - claim: The products and services outcome does not require firms to assess suitability for individual customers, except where relevant, such as assessing affordability when arranging a loan.
- **U04** (unrelated; loan_agreement_5 run 0 / consumer_understanding) -> LLM `no` | quote found: False | gate: rejected | chunk: retrieved for consumer_support in the same row
  - claim: The consumer understanding outcome aims for customers to be given the information they need, at the right time, and presented in a way they can understand.
- **U05** (unrelated; loan_agreement_11 run 0 / price_and_value) -> LLM `no` | quote found: False | gate: rejected | chunk: retrieved for products_and_services in the same row
  - claim: Firms must consider all costs and charges a consumer may pay over time, including start/end-of-contract charges and contingent charges such as late payment fees.
- **U06** (unrelated; loan_agreement_8 run 1 / consumer_support) -> LLM `no` | quote found: False | gate: rejected | chunk: retrieved for price_and_value in the same row
  - claim: Firms should have exceptions processes, potentially including real-time human interfaces, to deal with non-standard, complex, or sensitive customer issues.
- **U07** (unrelated; loan_agreement_7 run 0 / products_and_services) -> LLM `no` | quote found: False | gate: rejected | chunk: retrieved for consumer_understanding in the same row
  - claim: Firms must monitor that distribution strategies are followed and that products reach the intended target market, and the rules under this outcome are general in nature and do not require individual suitability assessment except in specific contexts.
- **U08** (unrelated; loan_agreement_8 run 1 / consumer_understanding) -> LLM `no` | quote found: False | gate: rejected | chunk: retrieved for consumer_support in the same row
  - claim: Firms should ensure documents are reviewed as a whole and that information on a particular issue is signposted or layered so it is interlinked, rather than scattered across documents in a way that makes it hard for consumers to find and understand key information.
- **U09** (unrelated; loan_agreement_10 run 2 / price_and_value) -> LLM `no` | quote found: False | gate: rejected | chunk: retrieved for products_and_services in the same row
  - claim: Firms must consider charges consumers pay at the start and end of a contract when considering price charged.
- **U10** (unrelated; loan_agreement_15 run 0 / consumer_support) -> LLM `no` | quote found: False | gate: rejected | chunk: retrieved for products_and_services in the same row
  - claim: Vulnerability can arise temporarily or permanently for any customer, and firms should have processes to prevent harm when circumstances change.
- **N01** (neighbouring; loan_agreement_9 run 1 / price_and_value) -> LLM `no` | quote found: False | gate: rejected | chunk: next chunk of the named chunk in ps22-9.pdf
  - claim: Lenders can take account of the costs of providing credit, including financing costs, when assessing fair value.
- **N02** (neighbouring; loan_agreement_2 run 2 / consumer_support) -> LLM `no` | quote found: False | gate: rejected | chunk: previous chunk of the named chunk in fg22-5.pdf
  - claim: Firms must design and deliver support that meets the needs of customers, including those with characteristics of vulnerability, and ensure customers can use products as reasonably anticipated without unreasonable barriers.
- **N03** (neighbouring; loan_agreement_13 run 0 / products_and_services) -> LLM `no` | quote found: False | gate: rejected | chunk: next chunk of the named chunk in fg22-5.pdf
  - claim: Firms must ensure the design of the product meets the needs, characteristics and objectives of customers in the identified target market, that distribution is appropriate for the target market, and that regular reviews are carried out to ensure continued fit.
- **N04** (neighbouring; loan_agreement_4 run 2 / consumer_understanding) -> LLM `no` | quote found: False | gate: rejected | chunk: next chunk of the named chunk in fg22-5.pdf
  - claim: Good practice examples show firms simplifying and presenting key cost/rate information clearly so consumers can more easily understand the product and make effective decisions.
- **N05** (neighbouring; loan_agreement_9 run 2 / price_and_value) -> LLM `no` | quote found: False | gate: rejected | chunk: previous chunk of the named chunk in fg22-5.pdf
  - claim: Manufacturer firms must consider all the costs and charges a consumer may pay for the product over time, including contingent charges like late payment fees.
- **N06** (neighbouring; loan_agreement_9 run 1 / consumer_support) -> LLM `no` | quote found: False | gate: rejected | chunk: previous chunk of the named chunk in fg22-5.pdf
  - claim: Firms must design and deliver support that meets the needs of customers, including those with characteristics of vulnerability, and must not disadvantage particular groups of vulnerable customers.
- **N07** (neighbouring; loan_agreement_1 run 1 / products_and_services) -> LLM `no` | quote found: False | gate: rejected | chunk: next chunk of the named chunk in fg22-5.pdf
  - claim: Firms must ensure the intended distribution strategy for the product is appropriate for the target market and carry out regular reviews to ensure the product continues to meet target market needs.
- **N08** (neighbouring; loan_agreement_14 run 2 / consumer_understanding) -> LLM `no` | quote found: False | gate: rejected | chunk: next chunk of the named chunk in fg22-5.pdf
  - claim: Good practice includes simplifying product information (e.g. a summary box) so consumers can more easily understand the product and make effective decisions.
- **N09** (neighbouring; loan_agreement_8 run 0 / price_and_value) -> LLM `no` | quote found: False | gate: rejected | chunk: next chunk of the named chunk in fg22-5.pdf
  - claim: Unreasonable exit charges are not permitted; exit charges should be fair and reflective of underlying costs.
- **N10** (neighbouring; loan_agreement_9 run 2 / consumer_support) -> LLM `no` | quote found: False | gate: rejected | chunk: next chunk of the named chunk in fg22-5.pdf
  - claim: Firms must not disadvantage particular groups of customers, including those with characteristics of vulnerability.
- **P01** (positive; loan_agreement_5 run 1 / price_and_value) -> LLM `yes` | quote found: True | gate: accepted | chunk: the claim's own named chunk (as the judge saw it)
  - claim: Firms must be able to demonstrate that the total price paid for the product, including any fees and charges, represents fair value, in addition to considering the fairness of interest rates charged.
  - supporting sentence given: 'As well as considering the fairness of interest rates charged, firms will need to be able to demonstrate that the total price paid for the product, including any fees and charges that they (or others) may apply, represents fair value.'
- **P02** (positive; loan_agreement_8 run 1 / consumer_support) -> LLM `yes` | quote found: True | gate: accepted | chunk: the claim's own named chunk (as the judge saw it)
  - claim: Firms must design and deliver support that meets the needs of customers, including those with characteristics of vulnerability, and ensure customers do not face unreasonable barriers.
  - supporting sentence given: 'design and deliver support that meets the needs of customers, including those with characteristics of vulnerability'
- **P03** (positive; loan_agreement_14 run 1 / products_and_services) -> LLM `yes` | quote found: True | gate: accepted | chunk: the claim's own named chunk (as the judge saw it)
  - claim: Firms must ensure the design of the product meets the needs, characteristics and objectives of customers in the identified target market, ensure the distribution strategy is appropriate for that target market, and carry out regular reviews to ensure the product continues to meet the target market's needs.
  - supporting sentence given: 'They set out a range of requirements, including the need for relevant firms to:\n• ensure that the design of the product or service meets the needs, characteristics and objectives of customers in the identified target market\n• ensure that the intended distribution strategy for the product or service '
- **P04** (positive; loan_agreement_4 run 1 / consumer_understanding) -> LLM `yes` | quote found: True | gate: accepted | chunk: the claim's own named chunk (as the judge saw it)
  - claim: Firms must give consumers the information they need, at the right time, presented in a way they can understand.
  - supporting sentence given: 'We want customers to be given the information they need, at the right time, and presented in a way they can understand.'
- **P05** (positive; loan_agreement_6 run 1 / price_and_value) -> LLM `yes` | quote found: True | gate: accepted | chunk: the claim's own named chunk (as the judge saw it)
  - claim: Firms must be able to demonstrate that the total price paid for a product, including fees and charges, represents fair value.
  - supporting sentence given: 'As well as considering the fairness of interest rates charged, firms will need to be able to demonstrate that the total price paid for the product, including any fees and charges that they (or others) may apply, represents fair value.'
- **P06** (positive; loan_agreement_11 run 2 / consumer_support) -> LLM `yes` | quote found: True | gate: accepted | chunk: the claim's own named chunk (as the judge saw it)
  - claim: Firms should have exceptions processes to deal with non-standard issues such as security or fraud concerns or technical issues, likely requiring a real-time human interface.
  - supporting sentence given: 'Firms should also have exceptions processes in place to deal effectively with non‑standard issues that could arise in the context of their business.'
- **P07** (positive; loan_agreement_9 run 2 / products_and_services) -> LLM `yes` | quote found: True | gate: accepted | chunk: the claim's own named chunk (as the judge saw it)
  - claim: A manufacturer must ensure products, including existing ones, are designed to meet the target market's needs, characteristics and objectives, and not adversely affect groups including those with characteristics of vulnerability.
  - supporting sentence given: 'A manufacturer must ensure its products or services, including existing products and services, are designed to meet the target market’s needs, characteristics and objectives'
- **P08** (positive; loan_agreement_9 run 2 / consumer_understanding) -> LLM `yes` | quote found: True | gate: accepted | chunk: the claim's own named chunk (as the judge saw it)
  - claim: Firms should provide relevant information with an appropriate level of detail to avoid overwhelming consumers, which can prevent effective decision-making.
  - supporting sentence given: 'provide relevant information with an appropriate level of detail, to avoid providing too much information such that it may prevent retail customers from making effective decisions.'
- **P09** (positive; loan_agreement_9 run 2 / price_and_value) -> LLM `yes` | quote found: True | gate: accepted | chunk: the claim's own named chunk (as the judge saw it)
  - claim: Firms must be able to demonstrate that benefits were reasonable relative to the price, and may consider market rates for comparable products as a relevant factor.
  - supporting sentence given: 'firms must still be able to demonstrate that the benefits were reasonable relative to the price.'
- **P10** (positive; loan_agreement_14 run 0 / consumer_support) -> LLM `yes` | quote found: True | gate: accepted | chunk: the claim's own named chunk (as the judge saw it)
  - claim: Firms are expected to signpost customers to appropriate external guidance or support where relevant.
  - supporting sentence given: 'For example, in certain situations it may be appropriate to signpost customers to MoneyHelper  guidance or to provide information about specialist insurance firms.'
