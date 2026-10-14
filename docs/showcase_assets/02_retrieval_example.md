# Asset 2: retrieval example, loan_agreement_1 run 0, price_and_value query

All loan documents, borrowers and lenders referred to here are synthetic (data/synthetic_docs/). Regulatory text is from the FCA corpus in data/regulatory_corpus/.

Saved by `run_eval main` at run time (`_cached_price_and_value_context`). Retriever: `QueryEngine` over Chroma collection `regulatory_corpus`, embeddings `BAAI/bge-small-en-v1.5`, top k = 5 (`src/config.py` QUERY_SIMILARITY_TOP_K). Page labels looked up in the local Chroma index by node id.

## Query (built by `first_pass.build_price_and_value_question` from the extracted fields)

```text
What does the Consumer Duty's Price and Value outcome require regarding fee/charge disclosure and demonstrating that a price represents fair value? The loan agreement under review states its fees as: "Administration and arrangement charges may apply in connection with this Agreement, as set out from time to time in the Lender's standard tariff of charges (no specific amount stated in the document); the Lender may vary its tariff of charges from time to time by giving the Borrower reasonable notice." and its fair value justification as: "Not addressed in this document."
```

## Top 5 retrieved chunks

| Rank | Source file | Page | Similarity | Node id |
|---|---|---|---|---|
| 1 | fg22-5.pdf | 59 | 0.6808 | `e4cc5973-0e6c-4c54-aad1-31077ba1aee4` |
| 2 | fg22-5.pdf | 63 | 0.6775 | `d02f9051-ed13-429e-921a-3191f98bc636` |
| 3 | ps22-9.pdf | 46 | 0.6754 | `b2cb01ac-cef0-49b0-a927-0525ce3ea7d5` |
| 4 | fg22-5.pdf | 61 | 0.6750 | `9b37d595-fa31-4756-80f2-855c43b4f075` |
| 5 | fg22-5.pdf | 20 | 0.6701 | `7e3b4e48-0747-459c-a288-64450eac16a2` |

Retrieval-level confidence on this result (min similarity): 0.6701.

The QueryEngine also produced an LLM-written `answer` for this query; the judge does not use it (it receives the chunks, not the answer), so it is not reproduced here.

### [1] fg22-5.pdf, page 59

```text
This provides useful high-level 
indicators of customer experience of a product. The data can help to indicate 
whether the product provides fair value. 
The price charged to consumers
7. 25 When considering the price charged, manufacturer firms must consider all the costs 
and charges a consumer may pay for the product or service over time. For example, 
firms must consider the following points.
• The charges consumers pay at the start and end of a contract. Where different 
distribution arrangements result in different prices for consumers, manufacturers 
must consider these as well. They must ensure, where reasonable, that their 
distribution arrangements do not cause the product to become unfair value.
• All fees and charges which consumers may incur over the life of the product 
or service. These may include contingent charges, like fees as a result of late
```

### [2] fg22-5.pdf, page 63

```text
63 
FG22/5
Chapter 7
Financial Conduct Authority
FG22/5 Final non-Handbook Guidance for firms on the Consumer Duty
Guidance for distributors
7. 31 Distributors must ensure their own charges for distributing the product or service 
represent fair value. All firms in the distribution chain are responsible for the value of 
the prices that they control and are not required to re-do or challenge other firms’ 
value assessments.
7. 32 Distributors must obtain relevant information from manufacturers to understand the 
value a product or service is intended to provide and to enable them to understand 
whether their distribution arrangements (including any remuneration it or another 
person in the distribution chain receives) would result in the product or service ceasing 
to provide fair value to retail customers.
7. 33 This means that the distributor will need to consider the cumulative impact of the 
remuneration added by each person in the chain on the overall value of the product 
to the customer. This is important as fees charged by different firms along the 
distribution chain might together result in a higher overall fee that does not represent 
fair value for consumers. This is likely to be particularly relevant where there are long or 
complex distribution chains with multiple fees added by multiple parties. This risk may 
be less likely in markets with less complex and flatter distribution chains, such as in the 
mortgages sector, where there are unlikely to be multiple charges added across the 
value chain.
Example
• Mortgage lender:  The firm must be able to demonstrate that their product 
and any associated charges provide fair value for the target market. This 
includes making consideration of the overall charges that the customer might 
pay, including any that might be levied as a result of the firm’s distribution 
strategy. Firms should factor such average intermediary fees in their value 
assessments and must also ensure that distributors have the necessary 
information to carry out their own assessment of value.
• Mortgage broker: The firm must obtain information from the manufacturer 
such as a high-level summary of the benefits to the target market, information 
on overall prices or fees and confirmation that the manufacturer considers 
that total benefits are proportionate to the total costs.
```

### [3] ps22-9.pdf, page 46

```text
46
PS22/9
Chapter 7
Financial Conduct Authority
A new Consumer Duty Feedback to CP21/36 and final rules
Others asked how our rules applied to similar products under the same consolidated 
group but sold under different brands and with different prices.
Our response
The focus of the price and value rules is to ensure there is a reasonable 
relationship between the price a consumer pays for a product or service 
and the benefits they receive from it. We are clear in our Guidance that 
a product or service that meets all of the other elements of the Duty 
(for example, which is designed to meet the needs of its target market, 
is transparently sold, and for which consumers are properly supported) 
is generally much more likely to offer fair value. This is both because of 
the benefits customers get and because they have the information they 
need about the benefits and limitations of the product or service they 
are buying, and the ability to pick something else if they prefer .
We have added further examples in our Guidance of good outcomes and 
the behaviours we expect from firms under the Duty. This includes areas 
where we have seen instances of poor value and specifies how we expect 
firms to rectify these harms.
We do not necessarily expect firms to quantify non‑monetary cost 
and benefits. But we do expect firms to at least provide qualitative 
consideration of these factors, especially if these are a significant part of 
their business models.
Where the product or service does not have any financial or non‑financial 
cost to the consumer (eg debt advice funded through other sources), we 
would not expect firms to do a value assessment.
Manufacturers providing free products or services should still consider if 
their customers are paying in non‑monetary terms, and whether those 
costs are reasonable in relation to the product’s benefits. For example, 
customers may pay for their current accounts in the form of foregone 
interest, associated fees and charges or through the use of their data.
We do not believe that our approach to differential pricing increases the 
risk of consumer harm. Our work on general insurance pricing practices 
found that price walking can lead to some consumers making significant 
overpayments which do not provide fair value.
```

### [4] fg22-5.pdf, page 61

```text
61 
FG22/5
Chapter 7
Financial Conduct Authority
FG22/5 Final non-Handbook Guidance for firms on the Consumer Duty
firms must still be able to demonstrate that the benefits were reasonable relative to 
the price.
7. 27 When designing charges and charging structures, firms also need to consider how 
their target market is likely to use the product or service. As discussed below, in the 
section on different outcomes for different groups, firms must also consider the likely 
price different groups will pay through the expected term of the product relative to the 
benefits they receive.
Example
Under our Duty, firms imposing a very high charge for customers with high 
credit risk must be able to satisfy themselves that the price paid is reasonable 
compared to the benefits the customer receives. Firms have flexibility to decide 
which metrics to use to satisfy themselves that their products provide fair value.
They will also need to consider other relevant elements of the Duty. For example, 
they should consider whether customers are likely to be more at risk of accepting 
such terms due to characteristics of vulnerability or their lack of other credit 
options, and whether the high cost of repayment of the loan might increase the 
risk of customers getting into payment difficulties. The firm could consider the 
credit risk of their customer base and market rates for comparable products as 
relevant factors, but firms should consider whether high prices to mitigate losses 
from high rates of default enables lending which exposes consumers to a high 
risk of harm.
Example
Our supervisory work has highlighted practices by some mortgage firms that 
have the potential to lead to significant harm to borrowers in financial difficulty. 
This happens if the ongoing payments a borrower makes are less than the 
accruing interest, causing the outstanding balance to escalate. The effect 
can be exacerbated where firms add unpaid fees or charges to the balance 
which also accrue interest. Where the customer fails to get back on track for a 
significant period, they may ultimately lose their home if they are unable to pay 
the amount owed at the end of the mortgage.
These issues are more apparent where interest rates are higher, for example in 
parts of the second charge market, and where fees and charges are accounted 
for separately.
```

### [5] fg22-5.pdf, page 20

```text
20
FG22/5
Chapter 3
Financial Conduct Authority
FG22/5 Final non-Handbook Guidance for firms on the Consumer Duty
Assessing fair value for existing contracts made before the 
Duty comes into force
3.10 We recognise that the rules under the price and value outcome cannot be so easily 
applied as other aspects of the Duty to existing contracts made before the Duty 
comes into force. These rules are linked to the original contractual terms of products 
and services. These contractual terms may be vested rights.
3.11 While the Duty will not infringe vested rights (see the section below), we think it is 
important that firms consider our overarching expectations under the price and value 
outcome for their existing and closed products or services. For example, firms should 
be confident that:
• these products or services do not exploit consumer lack of knowledge and/or 
behavioural biases to enable unfair prices to be charged
• complex pricing and terms do not make it harder for customers to assess value
• there is and remains a reasonable relationship between the price customers pay 
and the benefits of the product or service
• they have considered whether significant changes to the benefits of a product or 
service should affect the price: for example, if a firm reduces the benefits available 
on a product, it should consider if there should be an accompanying reduction in 
charges for the product
3.12 As we set out in Chapter 7 , firms should consider value in the round. A product or 
service that meets all of the other elements of the Duty (for example, if it is designed 
to meet the needs of its target market, is transparently sold, customers are able to 
exercise choices to switch or exit, and are properly supported) is much more likely to 
offer fair value. This is both because of the benefits customers receive and because 
they have the information and support they need.
3.13 Reviews are only needed at the level of the product or service itself. There is no 
requirement to review individual existing contracts. For example, firms do not need to 
repeat their underwriting of customers for insurance or credit purposes. They should 
be looking at the product or service broadly.
```
