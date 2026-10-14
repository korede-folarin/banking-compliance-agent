Confidence signals measured for one judgment: loan_agreement_1 run 1, price_and_value
Synthetic loan document (data/synthetic_docs/). Regulatory text: FCA corpus.

A. ROUTING SIGNAL (decides review; src/agent/compliance.py compute_confidence)
   Retrieval similarity of each cited source:  [1] 0.6853, [3] 0.6760, [4] 0.6753
   Confidence = minimum:  0.6753   threshold 0.65   ->  status potentially_non_compliant

B. EVALUATION SIGNALS (measured after the run; do not change routing)
   Signal 1, reasoning vs each cited chunk (embedding similarity):  [1] 0.8025, [3] 0.8131, [4] 0.7884   min 0.7884  mean 0.8014
   Per regulatory claim (quote check is deterministic; verdict is a narrow LLM check):
     claim 1: quote normalised in named_chunk, claim-to-excerpt similarity 0.8248, check verdict yes
     claim 2: quote normalised in named_chunk, claim-to-excerpt similarity 0.7307, check verdict yes
     claim 3: quote normalised in named_chunk, claim-to-excerpt similarity 0.7324, check verdict yes
     document fact 1: quote found in loan document (normalised)
     document fact 2: quote found in loan document (normalised)

C. WHAT THE ROUTING SIGNAL SEPARATES ACROSS ALL 45 RUNS (eval_raw_main_pass_v2_summary.json)
   Mean confidence, correct vs incorrect judge verdicts:
     price_and_value          correct 0.6408 (n=44)   incorrect 0.6444 (n=1)
     consumer_support         correct 0.6803 (n=42)   incorrect 0.6926 (n=3)
     products_and_services    correct 0.6796 (n=45)   incorrect none (n=0)
     consumer_understanding   correct 0.6237 (n=39)   incorrect 0.6198 (n=4)
   At threshold 0.65: 0.500 of correct verdicts overridden, 0.625 of incorrect verdicts caught.
