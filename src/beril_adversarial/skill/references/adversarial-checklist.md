# Adversarial Review Checklist

A compact starting-point list for pattern recognition. The system
prompts reference this file but instruct the reviewer NOT to walk it
mechanically. Use it to catch what the project artifacts show; do not
fabricate issues to check every box.

This file grows over time. Bump `.v{N}.md` when a change is material.
Review-meta-patterns go in `state/learned-patterns.md`, not here.

## 1. Statistical rigor

- Effect sizes reported alongside p-values; for large N (> 10^3),
  p-values alone are near-uninformative.
- Multiple-comparisons correction (BH-FDR or equivalent) applied when
  N_tests > 5–10. Mandatory for enrichment, differential abundance,
  GWAS, screens.
- Test choice matches data type: non-Gaussian data not forced into
  t-tests without a robust alternative; compositional data handled
  via CLR or equivalent.
- Data leakage: train/test overlap, temporal leakage, label leakage,
  feature-derived-from-outcome. Look for train/test splits that
  respect sample groupings (same subject, same batch).
- Power: if N is small, is the analysis honest about what it can and
  cannot detect? "No difference" vs. "underpowered to detect a
  difference" are not synonyms.
- Pseudoreplication: technical replicates not pooled as biological
  replicates.
- Selection bias: filtering on an outcome-related variable before
  testing that outcome.
- Confounders and batch effects: modeled or ignored? Simpson's
  paradox risk when aggregating across strata.
- Normalization choice: CLR for compositional, DESeq2 size factors or
  TMM for RNA-seq counts, TPM only for within-sample comparison.

## 2. Bio-data

- GO / KEGG / pathway enrichment: universe defined correctly (the set
  of genes testable, not all genes); FDR applied; vague terms flagged.
  Specific failure modes worth checking:
    - **ORA validity**: over-representation analysis assumes a small
      gene set against a large universe. ORA p-values become
      anti-conservative for large gene lists.
    - **GSEA p-value calibration**: GSEA permutation p-values are
      known to be anti-conservative (especially under heavy
      compositional structure). Be skeptical of marginal GSEA
      significance.
    - **KEGG module completeness**: a module with 6 of 8 enzymes
      annotated may be a false negative on enrichment. Note
      incomplete-module risk.
- Taxonomy assignment confidence reported; placements at genus level
  vs. species level distinguished.
- Contamination checks (CheckM, BUSCO, or equivalent) for assemblies
  and MAGs.
- Reference-vs-de-novo choice justified for the organism and read
  depth.
- Annotation provenance clear: which tool, which version, which
  database snapshot. Bakta vs. eggNOG vs. RAST vs. InterProScan
  disagreements flagged rather than silently reconciled.
- Gene-family inference: sequence-identity thresholds justified;
  orthology vs. paralogy distinguished where it matters.
- Fitness data: sign convention explicit; barcodes/counts normalized
  against reference conditions; low-coverage genes excluded or flagged.

## 3. Modeling

- FBA / COBRA: gap-filling justified; biomass composition documented;
  flux constraints cited.
- ML models: train/validation/test split respects data structure;
  cross-validation folds independent; no leakage from test set into
  feature engineering.
- Calibration reported when probabilities are used downstream. A
  model with high AUC can still be poorly calibrated (predicted P=0.7
  may correspond to ~50% actual occurrence). Calibration plots,
  Brier score, or expected-calibration-error should be reported when
  the probability output is used for downstream decisions
  (annotation acceptance thresholds, prioritization).
- Effect-size heterogeneity examined when widely varying. If reported
  effect sizes range across orders of magnitude (e.g., d from 0.05
  to 1.5), the drivers of heterogeneity should be explored. High
  unexplained heterogeneity may indicate hidden confounders or
  population structure.
- Model identifiability: if multiple parameter sets give similar
  fits, flag it; don't report one fit as canonical.
- Simulation-vs-experimental-validation gap: if a model is validated
  only against simulated data, that's not validation.
- Generalization claims: if a model was trained on one organism and
  applied to another, flag the generalization assumption.

## 4. Reproducibility

- Notebooks have saved outputs (cells show results, not just code).
- Figures exist for every major claim in REPORT.
- `requirements.txt` or `pyproject.toml` with pinned versions.
- README includes `## Reproduction` with expected runtime and
  Spark-vs-local notes.
- Data provenance documented: source, snapshot date, BERDL table
  names if applicable.
- Random seeds set and recorded where stochastic methods used.
- Runtime / compute resources noted for expensive analyses.

## 5. Interpretation

- Claims match the evidence's scope. A claim about "all bacteria"
  from one genus is overreach.
- Alternative explanations addressed. Results consistent with H1 AND
  H_alt? Say so.
- Correlation vs. causation: causal language ("drives", "causes")
  reserved for evidence that supports it.
- Null results honestly reported. "No significant difference" ≠
  "equivalence".
- Novelty claims: is the novelty real, or a restatement of prior
  work? Check with WebSearch.
- Effect magnitude: statistical significance discussed alongside
  biological relevance.
- Limitations section present and substantive, not performative.

## 6. Literature and external resources

- Foundational citations present (textbook-level references for the
  methods used).
- Recent literature engaged (WebSearch for papers in the last 3
  years on the topic).
- Citations match claims: a cited paper actually supports the specific
  point it's attached to.
- For papers: every citation in the draft appears in
  bibliography.bib. Fabricated citations are a Critical issue
  regardless of where they appear.
- External tools / datasets the project could leverage:
  - Gene Annotation Predictor (Neely / O'Grady) for gene-function
    ambiguity.
  - AlphaFold for structural basis for annotation confidence.
  - PaperBLAST (in BERDL) for experimental evidence for specific genes.
  - MIBiG for biosynthetic gene cluster questions.
  - BacDive for phenotype / habitat validation.
  - KBase collections for cross-project reuse.
- Related BERIL projects: check other `projects/*/README.md` for
  overlap; cite prior work if present.

## What NOT to do with this checklist

- Do not walk every bullet. Catch what the project actually exhibits.
- Do not invent issues to check boxes. If the project does not show a
  problem, there is no issue to raise.
- Do not duplicate items from `state/learned-patterns.md` or
  `docs/pitfalls.md`. Those files capture reviewer-specific and
  BERIL-specific gotchas; this checklist is generic starting material.
