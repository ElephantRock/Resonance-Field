# Adaptive campaign selection rule

Experiments 004–013 use the following deterministic ordering rule.

1. Compare every candidate with the no-reputation control on the same paired seeds and environment.
2. Exclude candidates whose mean task success is more than the configured tolerance below control.
3. Exclude candidates whose early post-shift incumbent share is more than the configured tolerance above control.
4. Among remaining candidates, maximize the documented constrained utility; break ties by success, lower incumbency, structural score, then stable policy label.
5. Classify the selected policy's dominant remaining failure as quality, plasticity, structure, or calibration.
6. Use that failure classification to choose the next untested policy dimension.
7. After all local dimensions are tested, choose Experiment 012's stress environment from the remaining failure.
8. Use Experiment 012's remaining failure to choose Experiment 013's holdout shock schedule.

This rule is fixed before campaign execution. The **path through the experiments is not**: it is a deterministic function of measured results.
