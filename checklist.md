# 🔴 Vital (Non-Negotiable)

If you skip these, your pipeline is a liability.

### 1. Problem Type

- Regression, binary classification, multiclass, multilabel, ranking, survival, etc.
- Single-task vs multi-task.
- Static vs temporal.

If you misidentify this, nothing else matters.

---

### 2. Target Definition

- What exactly is the target?
- Is it deterministic or noisy?
- Is it aggregated over time?
- Is it leaking future information?

Most ML failures are just target definition failures wearing a GPU.

---

### 3. Data Splitting Structure

- IID vs time series vs grouped data.
- Are there duplicates?
- Are there entities that appear in both train and val?
- Is there drift over time?

Leakage here will give you 99% validation accuracy and 51% reality accuracy.

---

### 4. Sample Size vs Feature Dimension

- ( n ) vs ( d )
- Are you in low-data/high-d regime?
- Is regularization mandatory?

This determines model class viability.

---

### 5. Feature Types

- Numerical (continuous vs discrete)
- Categorical (ordinal vs nominal)
- Text
- Image
- Graph
- Sequences

Your preprocessing pipeline depends entirely on this.

---

### 6. Missingness

- MCAR, MAR, MNAR?
- Structured missingness?
- Is missingness informative?

Sometimes missingness is more predictive than the value itself.

---

### 7. Label Distribution

- Class imbalance?
- Long tail?
- Rare event prediction?

If 0.5% of samples are positive, accuracy is a useless metric.

---

### 8. Noise Level

- Measurement noise?
- Annotation noise?
- Adversarial noise?

You cannot optimize beyond the noise floor.

---

### 9. Feature Scale

- Orders of magnitude differences?
- Heavy tails?
- Log-distributed variables?

Scaling assumptions affect optimization stability.

---

### 10. Correlation Structure

- Highly collinear features?
- Redundant inputs?
- Strong interactions?

Tree vs linear vs deep nets respond very differently here.

---

### 11. Distribution Shift Risk

- Is deployment distribution different?
- Covariate shift?
- Concept drift?

If your training data is not your production data, your pipeline needs to know that.

---

### 12. Evaluation Metric

- What actually matters?
- ROC-AUC?
- PR-AUC?
- F1?
- MSE?
- Calibration?

Optimizing the wrong metric is peak self-sabotage.

---

# 🟡 Not Strictly Vital — But Makes You Elite

Now we’re talking optimization and efficiency.

---

### 13. Data Generating Process (Even Approximate)

- Is there known physics?
- Known constraints?
- Known invariances?
- Symmetry?

You, especially, should care about invariances. You’re building symmetry-aware models. Don’t pretend the data is arbitrary.

---

### 14. Intrinsic Dimensionality

- Does PCA explain 95% variance in 5 components?
- Is it manifold-like?
- Sparse?

If intrinsic dimension is low, you don’t need a transformer.

---

### 15. Computational Budget

- Memory constraints?
- Latency constraints?
- HPC availability?

AutoML without budget awareness is just irresponsible search.

---

### 16. Feature Stability

- Do features change meaning over time?
- Are they engineered or raw?
- Are they reproducible?

This matters for real-world deployment.

---

### 17. Outlier Structure

- Random outliers?
- Systematic subpopulations?
- Rare but important clusters?

Isolation forests vs robust loss vs leave them alone.

---

### 18. Redundancy / Feature Importance Pre-Screen

- Mutual information
- Variance thresholds
- Correlation pruning

Auto pipelines benefit massively from pruning before search.

---

### 19. Dependency Structure

- Graph relationships?
- Temporal lag?
- Spatial correlation?

If dependencies exist and you treat the data as IID, you're throwing away structure.

---

### 20. Calibration Needs

- Do probabilities need to be reliable?
- Or just ranking?

Calibration matters more than people think.

---

### 21. Hyperparameter Sensitivity

- Does performance vary wildly?
- Flat vs sharp optima?

Some datasets demand careful tuning. Others don’t care.

---

### 22. Feature Engineering Potential

- Can domain transforms simplify structure?
- Log transforms?
- Ratios?
- Interaction terms?

AutoML that ignores feature engineering is lazy AutoML.
