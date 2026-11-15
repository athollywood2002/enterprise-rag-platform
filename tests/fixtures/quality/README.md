# Retained context regressions

`retained_cases.json` copies the synthetic questions, visible answers and retrieved excerpts for N03/N04/N11/N15/N17/N20/N22/N24 from the retained November 10 evaluation. Source identifiers are reduced to fixture filenames and internal document hashes are omitted. No screenshots, API keys, authorization headers, private reasoning or installation paths are included.

The original archive and its 82 checksummed files are unchanged. These copies test exact context/citation-ID delivery, not model answer accuracy. The separate grading addendum reports 16/24 fully passing. N11 retrieved both header [4] and data [2]; N22 is partial; N15 retains its correct result with a clarity flag. Do not label known erroneous saved answers as golden answers.

`primary_grounding_cases.json` is a separate sanitized copy of nine exposed cases from
the subsequent default/1536 primary run (18/24 combined, not the older 16/24 run).
It retains exact excerpt text/order, visible answers, generation evidence and adjudication;
source names are basenames and internal document IDs are omitted. N15 and N20 were empty
generation failures in this run, not abstentions. N12's missing cited join, N16's
target-to-obligation change, N22's omitted Security gate and N24's invented exact date
are known failures, not golden outputs. N14 is a passing exact-passage control here;
the later cap2048 run instead cited an insufficient historical example.

These fixtures contain synthetic business facts only, no installation paths, credentials,
raw private evidence or hidden held-out material. They test serialization and mechanical
diagnostics. Authored reference answers in tests are not measured model outputs.
