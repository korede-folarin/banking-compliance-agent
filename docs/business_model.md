# Business impact model (P11-02, 2026-10-24)

**What is measured and what is assumed.** Auto-approval is off, so this system does not remove any
human reviews. Its value is **reviewer time saved per agreement**: the reviewer starts from verdicts,
quotes and the regulation passages already found, instead of from a blank page. That saving has
**not** been measured in this project. It is the main assumption below, and the first thing a pilot
should measure.

## Inputs

| Input | Conservative | Moderate | Optimistic | Source |
|---|---|---|---|---|
| Reviewer base salary | £35,000 | £45,000 | £55,000 | UK compliance analyst ranges (see Sources): about £35–45k outside London, up to £55k in London |
| Loaded hourly cost | £27.58 | £35.45 | £43.33 | Salary × 1.30 on-costs ÷ 1,650 productive hours (assumption) |
| Manual review per agreement | 20 min | 30 min | 45 min | **Assumption.** No published benchmark was found. |
| Time saved by the pre-review | 20% | 35% | 50% | **Assumption, unmeasured** |
| Extra time per false alarm | 15 min | 10 min | 10 min | **Assumption** |
| False alarms per agreement | 0.178 | 0.178 | 0.178 | **Measured:** baseline, 8 false alarms in 45 agreement-runs |
| Agreements per month | 200 | 1,000 | 5,000 | **Assumption** (a small, mid-size and large lender's book) |
| Model runs per agreement | 3 | 3 | 1 | 3 runs make run-to-run agreement usable (it flagged every baseline error) |
| AI cost per run | $0.107 | $0.107 | $0.107 | **Measured:** live agent, ~$7.70 over 72 runs (excludes claim checks, which are evaluation-only) |

## Result

Net time saved per agreement = time saved by the pre-review − extra time on false alarms.

| | Conservative | Moderate | Optimistic |
|---|---|---|---|
| Time saved by the pre-review | 4.0 min | 10.5 min | 22.5 min |
| Minus false alarms | −2.7 min | −1.8 min | −1.8 min |
| **Net per agreement** | **1.3 min** | **8.7 min** | **20.7 min** |
| Reviewer hours saved per month | 4 | 145 | 1,727 |
| Value per month | £123 | £5,154 | £74,830 |
| Full-time equivalents | 0.03 | 1.06 | 12.6 |
| Model cost per month | $64 | $321 | $535 |

## What this says

- **The case depends on one number nobody has measured:** how much reviewer time the pre-review
  saves.
  - At 20% of a 20-minute review, the gain is about equal to the model cost and the time lost to false
    alarms, so there is **no business case**.
  - At 35% or more, the saving is far larger than the model cost.
- **The model cost is never the deciding factor.** At most about $0.32 per agreement, against reviewer
  time worth £0.46–0.72 a minute.
- **False alarms are a real cost.** The baseline's 8 false alarms in 45 runs cost 1.8–2.7 minutes per
  agreement. A system that over-flags erodes the saving. This is why precision matters as much as
  catching breaches.
- **Missed breaches are not priced here.** A missed breach costs regulatory and customer harm, not
  minutes.
  - **The baseline missed none.**
  - **The agent missed 6** (consumer understanding, `docs/eval_results_v2.md`).
  - Any production use keeps a person on every case. Auto-approval stays off until calibration on far
    more documents allows it (59 or more with zero misses for a 5% bound).

## How a pilot would replace the assumptions

1. **Time a sample of reviews,** for example 30 agreements reviewed by hand and 30 with the pre-review,
   by the same reviewers. That measures "time saved" directly.
2. **Record every reviewer override in the review screen,** which logs them already. That gives the
   real false-alarm and miss rates on the lender's own documents.
3. **Use the lender's real volume and loaded cost.**

## Sources

- [FD Capital: Compliance salaries UK 2026](https://www.fdcapital.co.uk/compliance-salary-guide/). Compliance analyst (1–4 years) £35,000–£55,000; London 20–40% above regional.
- [Payscale: Compliance Analyst salary, UK](https://www.payscale.com/research/UK/Job=Compliance_Analyst/Salary). Average £32,689.
- [Payscale: Mid-career compliance analyst, financial compliance](https://www.payscale.com/research/UK/Job=Compliance_Analyst/Salary/8129879c/Mid-Career-Financial-Compliance). Average £43,888.
- [Payscale: Compliance analyst, London](https://www.payscale.com/research/UK/Job=Compliance_Analyst/Salary/3c857163/London-Financial-Compliance). Average £38,000.
- **Review time per agreement and monthly volumes:** no public benchmark was found, so they are stated as assumptions.
